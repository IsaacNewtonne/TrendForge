"""Storyboard planning and validation for TrendForge videos.

The storyboard is the contract between narration, evidence, visuals, and
rendering. It prevents the pipeline from drifting into loosely matched images.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from loguru import logger

from modules.manual_images import ai_image_style_prompt, default_negative_prompt
from modules.visual_matcher import enrich_storyboard_matches


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

ANALOGY_PATTERNS = [
    r"\bit'?s like\b",
    r"\bthink of (it|this|them) as\b",
    r"\bthink of (it|this|them) like\b",
    r"\bimagine\b",
    r"\bas if\b",
    r"\bsimilar to\b",
    r"\bworks like\b",
    r"\bkind of like\b",
]

SOURCE_REFERENCE_PATTERNS = [
    r"\bpost\b",
    r"\breddit\b",
    r"\barticle\b",
    r"\breport\b",
    r"\bstudy\b",
    r"\baccording to\b",
    r"\bdata from\b",
    r"\bsource\b",
    r"\bheadline\b",
    r"\bnews\b",
]

CLAIM_TYPES = {"fact", "source_claim"}
CONCEPT_TYPES = {"opinion", "transition", "verdict"}
SOURCE_VISUAL_INTENTS = {"source_card", "source_screenshot"}
ART_VISUAL_INTENTS = {"analogy_art", "concept_art", "brand_or_concept"}
MAX_CONSECUTIVE_SOURCE_VISUALS = 2
MAX_CONSECUTIVE_ART_VISUALS = 3
MAX_VISUAL_HOLD_SECONDS = 8.0
MAX_REFRESH_VISUALS_PER_SEGMENT = 3
MIN_REFRESH_SEGMENT_SECONDS = 10.0

HARD_EVIDENCE_PATTERNS = [
    r"\b\d+(?:\.\d+)?\s?(?:%|percent|million|billion|trillion)\b",
    r"\$\s?\d+",
    r"\b20\d{2}\b",
    r"\b(?:survey|poll|filing|lawsuit|earnings|revenue|users|downloads)\b",
    r"\b(?:researchers|analysts|regulators|company said|officials said)\b",
]


@dataclass(frozen=True)
class StoryboardIssue:
    severity: str
    segment_id: str
    message: str

    def as_dict(self) -> Dict[str, str]:
        return {
            "severity": self.severity,
            "segment_id": self.segment_id,
            "message": self.message,
        }


def build_storyboard(
    script: Dict[str, Any],
    raw_content: List[Dict[str, Any]],
    analysis: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a storyboard from script segments and scraped evidence."""
    segments = script.get("segments", [])
    evidence = build_evidence_ledger(raw_content)
    source_cursor = 0
    storyboard_segments: List[Dict[str, Any]] = []
    planned_segments = plan_visual_sequence(build_visual_plan_items(segments), bool(evidence))

    for item in planned_segments:
        index = item["index"]
        segment = item["segment"]
        text = item["text"]
        segment_type = item["segment_type"]
        segment_id = item["id"]
        visual_intent = item["visual_intent"]
        evidence_item = None

        if visual_intent in SOURCE_VISUAL_INTENTS and evidence:
            evidence_item = evidence[source_cursor % len(evidence)]
            source_cursor += 1

        storyboard_segments.append(
            {
                "id": segment_id,
                "index": index,
                "segment_type": segment_type,
                "narration": text,
                "visual_intent": visual_intent,
                "required_visual": required_visual_for_intent(visual_intent),
                "visual_prompt": build_visual_prompt(script, segment, visual_intent, evidence_item),
                "source_id": evidence_item.get("id") if evidence_item else None,
                "source_url": evidence_item.get("url") if evidence_item else None,
                "source_title": evidence_item.get("title") if evidence_item else None,
                "source_name": evidence_item.get("source_name") if evidence_item else None,
                "source_published": evidence_item.get("published") if evidence_item else None,
                "source_excerpt": evidence_item.get("text_excerpt") if evidence_item else None,
                "source_image": evidence_item.get("image_url") if evidence_item else None,
                "claim": text if visual_intent in SOURCE_VISUAL_INTENTS else None,
                "image_prompt": segment.get("image_prompt", ""),
                "payoff_min_seconds": segment.get("payoff_min_seconds", 0),
                "beat_type": segment.get("beat_type"),
                "beat_purpose": segment.get("beat_purpose"),
                "visual_role_hint": item.get("visual_role_hint", ""),
                "visual_plan_reason": item.get("visual_plan_reason", ""),
                "delivery": segment.get("delivery", {}),
                "audio_path": None,
                "duration": None,
                "visual_path": None,
                "visual_paths": [],
                "visual_refresh_specs": [],
                "warnings": [],
            }
        )

    storyboard = {
        "topic": script.get("topic", ""),
        "title": script.get("title", ""),
        "style_profile": build_style_profile(script),
        "evidence": evidence,
        "segments": storyboard_segments,
        "analysis_confidence": (analysis or {}).get("confidence"),
    }

    storyboard = enrich_storyboard_matches(storyboard)
    issues = validate_storyboard(storyboard)
    storyboard["validation"] = [issue.as_dict() for issue in issues]
    log_storyboard_summary(storyboard, issues)
    return storyboard


def build_visual_plan_items(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Create first-pass visual assignments before pacing is applied."""
    items: List[Dict[str, Any]] = []
    for index, segment in enumerate(segments):
        text = normalize_text(segment.get("text", ""))
        segment_type = segment.get("type", "fact")
        visual_role_hint = normalize_text(segment.get("visual_role_hint", ""))
        visual_intent = classify_visual_intent(segment_type, text, visual_role_hint)
        items.append(
            {
                "id": f"seg_{index:03d}",
                "index": index,
                "segment": segment,
                "segment_type": segment_type,
                "text": text,
                "visual_role_hint": visual_role_hint,
                "visual_intent": visual_intent,
                "visual_plan_reason": explain_visual_intent(
                    visual_intent,
                    segment_type,
                    text,
                    visual_role_hint,
                ),
            }
        )
    return items


def plan_visual_sequence(items: List[Dict[str, Any]], evidence_available: bool) -> List[Dict[str, Any]]:
    """Balance visual intent so the final timeline feels deliberately mixed.

    The classifier decides what each beat wants. This pacing pass prevents long
    runs of source pages or long runs of generated art while keeping explicit
    source references and analogies protected.
    """
    planned = [dict(item) for item in items]

    if not evidence_available:
        for item in planned:
            if item.get("visual_intent") in SOURCE_VISUAL_INTENTS:
                item["visual_intent"] = art_intent_for_segment(item)
                item["visual_plan_reason"] = "No source evidence was available, so this beat uses explanatory art."
        return planned

    source_run = 0
    art_run = 0
    source_count = 0

    for item in planned:
        intent = item.get("visual_intent")

        if intent in SOURCE_VISUAL_INTENTS:
            if source_run >= MAX_CONSECUTIVE_SOURCE_VISUALS and can_use_art_for_pacing(item):
                item["visual_intent"] = art_intent_for_segment(item)
                item["visual_plan_reason"] = (
                    "Pacing break after source visuals; this beat is better as explanatory art."
                )
                intent = item["visual_intent"]
            else:
                source_run += 1
                art_run = 0
                source_count += 1
                continue

        if intent in ART_VISUAL_INTENTS:
            if art_run >= MAX_CONSECUTIVE_ART_VISUALS and can_promote_to_source(item):
                item["visual_intent"] = "source_card"
                item["visual_plan_reason"] = (
                    "Evidence beat inserted after generated visuals to re-anchor the story."
                )
                source_run = 1
                art_run = 0
                source_count += 1
            else:
                art_run += 1
                source_run = 0

    if source_count == 0:
        candidate = first_source_candidate(planned)
        if candidate:
            candidate["visual_intent"] = "source_card"
            candidate["visual_plan_reason"] = "First evidence-backed beat promoted to a source visual."

    return planned


def attach_audio_to_storyboard(storyboard: Dict[str, Any], audio_files: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Attach rendered audio paths and durations to storyboard segments."""
    refresh_cfg = load_visual_refresh_config()
    by_index = {
        item.get("segment", {}).get("text", ""): item
        for item in audio_files
        if item.get("segment", {}).get("text")
    }

    for segment in storyboard.get("segments", []):
        audio = by_index.get(segment.get("narration", ""))
        if audio:
            segment["audio_path"] = audio.get("path")
            segment["duration"] = audio.get("duration")
            segment["visual_refresh_specs"] = plan_visual_refresh_specs(segment, refresh_cfg)

    storyboard["validation"] = [issue.as_dict() for issue in validate_storyboard(storyboard)]
    return storyboard


def attach_visuals_to_storyboard(
    storyboard: Dict[str, Any],
    visual_paths: Dict[str, Any],
) -> Dict[str, Any]:
    """Attach generated/captured visual paths to storyboard segments."""
    for segment in storyboard.get("segments", []):
        segment_id = segment.get("id")
        if segment_id in visual_paths:
            paths = normalize_visual_paths(visual_paths[segment_id])
            if paths:
                segment["visual_path"] = paths[0]
                segment["visual_paths"] = paths

    storyboard["validation"] = [issue.as_dict() for issue in validate_storyboard(storyboard)]
    return storyboard


def storyboard_visual_files(storyboard: Dict[str, Any]) -> List[str]:
    """Return visual files in segment order for the editor."""
    files: List[str] = []
    for segment in storyboard.get("segments", []):
        paths = segment.get("visual_paths") or ([segment["visual_path"]] if segment.get("visual_path") else [])
        files.extend(path for path in paths if path)
    return files


def storyboard_audio_files(storyboard: Dict[str, Any], audio_files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return audio files in storyboard order, preserving existing editor shape."""
    by_text = {
        item.get("segment", {}).get("text", ""): item
        for item in audio_files
        if item.get("segment", {}).get("text")
    }

    ordered = []
    for segment in storyboard.get("segments", []):
        item = by_text.get(segment.get("narration", ""))
        if item:
            item = dict(item)
            item["storyboard_id"] = segment.get("id")
            item["visual_intent"] = segment.get("visual_intent")
            item["visual_role"] = segment.get("visual_role")
            item["motion_hint"] = segment.get("motion_hint")
            item["beat_type"] = segment.get("beat_type")
            item["delivery"] = segment.get("delivery", {})
            item["visual_paths"] = segment.get("visual_paths") or ([segment["visual_path"]] if segment.get("visual_path") else [])
            ordered.append(item)

    return ordered


def normalize_visual_paths(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, dict):
        primary = value.get("primary")
        extras = value.get("extras", [])
        paths = [primary] if primary else []
        if isinstance(extras, list):
            paths.extend(str(item) for item in extras if item)
        return paths
    return []


def load_visual_refresh_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
            return cfg.get("visuals", {}).get("refresh", {})
    return {}


def plan_visual_refresh_specs(segment: Dict[str, Any], refresh_cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Plan extra cutaway visuals for long narration segments."""
    refresh_cfg = refresh_cfg or {}
    max_hold_seconds = float(refresh_cfg.get("max_hold_seconds", MAX_VISUAL_HOLD_SECONDS))
    max_refresh_visuals = int(refresh_cfg.get("max_extra_visuals_per_segment", MAX_REFRESH_VISUALS_PER_SEGMENT))
    min_segment_seconds = float(refresh_cfg.get("min_segment_seconds", MIN_REFRESH_SEGMENT_SECONDS))
    if max_hold_seconds <= 0 or max_refresh_visuals <= 0:
        return []
    try:
        duration = float(segment.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    if duration < min_segment_seconds:
        return []

    refresh_count = min(
        max_refresh_visuals,
        max(0, int(duration // max_hold_seconds)),
    )
    if refresh_count <= 0:
        return []

    ideas = extract_visual_ideas(segment.get("narration", ""), refresh_count)
    specs: List[Dict[str, Any]] = []
    for index, idea in enumerate(ideas, start=1):
        intent = refresh_intent_for_segment(segment, idea)
        specs.append(
            {
                "id": f"{segment.get('id', 'segment')}_refresh_{index:02d}",
                "parent_id": segment.get("id"),
                "visual_intent": intent,
                "required_visual": "generated_art",
                "visual_prompt": refresh_visual_prompt(segment, idea, intent),
                "image_prompt": refresh_visual_prompt(segment, idea, intent),
                "narration": idea,
                "segment_type": segment.get("segment_type", "transition"),
                "visual_role": "metaphor" if intent == "analogy_art" else "context",
                "motion_hint": "slow_drift" if intent == "analogy_art" else "slow_push_in",
            }
        )
    return specs


def extract_visual_ideas(narration: str, limit: int) -> List[str]:
    sentences = [
        normalize_text(part)
        for part in re.split(r"(?<=[.!?])\s+", str(narration or ""))
        if len(normalize_text(part).split()) >= 5
    ]
    if not sentences:
        sentences = [normalize_text(narration)]
    return sentences[1 : limit + 1] or sentences[:limit]


def refresh_intent_for_segment(segment: Dict[str, Any], idea: str) -> str:
    if is_analogy(idea.lower()) or segment.get("visual_intent") == "analogy_art":
        return "analogy_art"
    return "concept_art"


def refresh_visual_prompt(segment: Dict[str, Any], idea: str, visual_intent: str) -> str:
    topic = normalize_text(segment.get("visual_prompt") or segment.get("source_title") or "")
    if visual_intent == "analogy_art":
        return (
            f"Visual metaphor for this idea: {idea}. "
            "Clear symbolic composition, no text, documentary editorial style."
        )
    return (
        f"Cutaway visual for {topic}: {idea}. "
        "Fresh composition, no text, documentary editorial style."
    )


def build_evidence_ledger(raw_content: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize scraped content into reusable source evidence."""
    evidence = []
    for index, item in enumerate(raw_content):
        url = item.get("url", "")
        if not url or not url.startswith("http"):
            continue

        evidence.append(
            {
                "id": f"src_{index:03d}",
                "source": item.get("source", "unknown"),
                "source_name": item.get("source_name", ""),
                "title": normalize_text(item.get("title", "")),
                "url": url,
                "published": item.get("published", ""),
                "image_url": item.get("image_url", ""),
                "text_excerpt": normalize_text(item.get("text", ""))[:500],
                "source_type": item.get("source_type", "web"),
                "domain": item.get("domain", ""),
                "citation_score": item.get("citation_score"),
                "evidence_tags": item.get("evidence_tags", []),
            }
        )

    return evidence


def classify_visual_intent(segment_type: str, text: str, visual_role_hint: str = "") -> str:
    """Decide which kind of visual a segment requires."""
    lower = text.lower()
    visual_role = visual_role_hint.lower()
    if segment_type == "hook":
        return "brand_or_concept"
    if is_analogy(lower) or visual_role == "metaphor":
        return "analogy_art"
    if visual_role in {"contrast", "synthesis"}:
        return "concept_art"
    if visual_role == "context" and not has_hard_evidence_marker(lower) and not references_source(lower):
        return "concept_art"
    if visual_role == "evidence":
        return "source_card"
    if has_hard_evidence_marker(lower):
        return "source_card"
    if segment_type in CLAIM_TYPES or references_source(lower):
        return "source_card"
    if segment_type in CONCEPT_TYPES:
        return "concept_art"
    return "concept_art"


def explain_visual_intent(visual_intent: str, segment_type: str, text: str, visual_role_hint: str = "") -> str:
    lower = text.lower()
    visual_role = visual_role_hint.lower()
    if visual_intent == "brand_or_concept":
        return "Opening or branded context uses generated concept art."
    if visual_intent == "analogy_art":
        return "Analogy or metaphor beat uses generated visual metaphor art."
    if visual_intent in SOURCE_VISUAL_INTENTS:
        if references_source(lower):
            return "Source-referencing beat uses a source visual."
        if visual_role == "evidence":
            return "Narrative plan marked this beat as evidence."
        if has_hard_evidence_marker(lower):
            return "Specific data or dated claim uses a source visual."
        if segment_type in CLAIM_TYPES:
            return "Factual claim uses a source visual."
    return "Concept, contrast, implication, or synthesis beat uses generated art."


def has_hard_evidence_marker(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in HARD_EVIDENCE_PATTERNS)


def visual_lock_score(item: Dict[str, Any]) -> int:
    """Score how strongly a segment should stay source-backed."""
    text = str(item.get("text", "")).lower()
    visual_role = str(item.get("visual_role_hint", "")).lower()
    segment_type = item.get("segment_type")
    score = 0
    if references_source(text):
        score += 3
    if has_hard_evidence_marker(text):
        score += 2
    if visual_role == "evidence":
        score += 1
    if segment_type in CLAIM_TYPES:
        score += 1
    return score


def can_use_art_for_pacing(item: Dict[str, Any]) -> bool:
    """Return true when a source-looking beat can become explanatory art."""
    text = str(item.get("text", "")).lower()
    if item.get("segment_type") in {"hook", "verdict"}:
        return True
    if is_analogy(text):
        return True
    return visual_lock_score(item) < 3


def can_promote_to_source(item: Dict[str, Any]) -> bool:
    """Return true when an art beat can carry a source visual for pacing."""
    text = str(item.get("text", "")).lower()
    if item.get("segment_type") in {"hook", "verdict"}:
        return False
    if is_analogy(text) or item.get("visual_intent") == "analogy_art":
        return False
    return visual_lock_score(item) > 0 or item.get("segment_type") == "fact"


def first_source_candidate(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    candidates = [
        item
        for item in items
        if can_promote_to_source(item)
    ]
    if not candidates:
        return None
    candidates.sort(key=visual_lock_score, reverse=True)
    return candidates[0]


def art_intent_for_segment(item: Dict[str, Any]) -> str:
    text = str(item.get("text", "")).lower()
    visual_role = str(item.get("visual_role_hint", "")).lower()
    if item.get("segment_type") == "hook":
        return "brand_or_concept"
    if is_analogy(text) or visual_role == "metaphor":
        return "analogy_art"
    return "concept_art"


def required_visual_for_intent(visual_intent: str) -> str:
    if visual_intent == "source_card":
        return "source_card"
    if visual_intent == "source_screenshot":
        return "screenshot"
    if visual_intent in {"analogy_art", "concept_art", "brand_or_concept"}:
        return "generated_art"
    return "visual"


def build_visual_prompt(
    script: Dict[str, Any],
    segment: Dict[str, Any],
    visual_intent: str,
    evidence_item: Optional[Dict[str, Any]],
) -> str:
    topic = script.get("topic", "")
    text = normalize_text(segment.get("text", ""))
    base_prompt = normalize_text(segment.get("image_prompt", ""))

    if visual_intent in SOURCE_VISUAL_INTENTS and evidence_item:
        return evidence_item.get("title") or text[:120]

    if visual_intent == "analogy_art":
        return (
            f"Visual metaphor for {topic}: {text}. "
            "Clear symbolic composition, no text, documentary editorial style."
        )

    if visual_intent == "brand_or_concept":
        return base_prompt or f"Strong opening visual for {topic}, premium documentary style, no text."

    return base_prompt or f"Conceptual editorial visual for {topic}: {text[:160]}, no text."


def build_style_profile(script: Dict[str, Any]) -> Dict[str, Any]:
    topic = script.get("topic", "")
    return {
        "style_id": "trendforge_manual_editorial",
        "topic": topic,
        "palette": "warm off-white background, flat pastel colors, dusty blue, sage green, pale gold, soft black",
        "camera": "slightly above isometric view, centered symbolic subject, balanced whitespace",
        "lighting": "soft muted shading, subtle airbrushed focal glow, light print texture",
        "composition": "16:9 finished editorial poster frame, clean foreground, no readable text, no UI panels",
        "style_prompt": ai_image_style_prompt(),
        "negative": default_negative_prompt(),
        "seed_strategy": "stable seed per video topic and segment index",
    }


def validate_storyboard(storyboard: Dict[str, Any]) -> List[StoryboardIssue]:
    """Validate coverage and alignment rules."""
    issues: List[StoryboardIssue] = []
    seen_visuals: Dict[str, List[str]] = {}

    for segment in storyboard.get("segments", []):
        segment_id = segment.get("id", "unknown")
        narration = segment.get("narration", "")
        visual_intent = segment.get("visual_intent")
        required_visual = segment.get("required_visual")

        if not narration:
            issues.append(StoryboardIssue("error", segment_id, "Segment has no narration."))

        if visual_intent in SOURCE_VISUAL_INTENTS and not segment.get("source_url"):
            issues.append(StoryboardIssue("error", segment_id, "Source claim has no source URL."))

        confidence = segment.get("evidence_match_confidence")
        if visual_intent in SOURCE_VISUAL_INTENTS and confidence is not None and confidence < 0.18:
            issues.append(StoryboardIssue("warning", segment_id, "Source match confidence is low."))

        if is_analogy(narration.lower()) and visual_intent != "analogy_art":
            issues.append(StoryboardIssue("error", segment_id, "Analogy was not assigned generated art."))

        if required_visual and not segment.get("visual_prompt"):
            issues.append(StoryboardIssue("warning", segment_id, "Required visual has no prompt."))

        if segment.get("audio_path") and not segment.get("duration"):
            issues.append(StoryboardIssue("warning", segment_id, "Audio path exists but duration is missing."))

        segment_visual_paths = segment.get("visual_paths") or ([segment["visual_path"]] if segment.get("visual_path") else [])
        if segment_visual_paths:
            for path in segment_visual_paths:
                seen_visuals.setdefault(path, []).append(segment_id)
        elif segment.get("audio_path"):
            issues.append(StoryboardIssue("warning", segment_id, "Audio segment has no attached visual yet."))

    for path, segment_ids in seen_visuals.items():
        if len(segment_ids) > 1:
            issues.append(
                StoryboardIssue(
                    "error",
                    "global",
                    f"Visual reused by segments {', '.join(segment_ids)}: {path}",
                )
            )

    return issues


def has_blocking_issues(storyboard: Dict[str, Any]) -> bool:
    return any(issue.get("severity") == "error" for issue in storyboard.get("validation", []))


def normalize_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def is_analogy(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in ANALOGY_PATTERNS)


def references_source(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in SOURCE_REFERENCE_PATTERNS)


def log_storyboard_summary(storyboard: Dict[str, Any], issues: List[StoryboardIssue]):
    counts: Dict[str, int] = {}
    for segment in storyboard.get("segments", []):
        intent = segment.get("visual_intent", "unknown")
        counts[intent] = counts.get(intent, 0) + 1

    errors = sum(1 for issue in issues if issue.severity == "error")
    warnings = sum(1 for issue in issues if issue.severity == "warning")
    logger.info(f"Storyboard: {len(storyboard.get('segments', []))} segments, intents={counts}")
    logger.info(f"Storyboard validation: {errors} errors, {warnings} warnings")
