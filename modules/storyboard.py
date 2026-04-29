"""Storyboard planning and validation for TrendForge videos.

The storyboard is the contract between narration, evidence, visuals, and
rendering. It prevents the pipeline from drifting into loosely matched images.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger

from modules.visual_matcher import enrich_storyboard_matches


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

    for index, segment in enumerate(segments):
        text = normalize_text(segment.get("text", ""))
        segment_type = segment.get("type", "fact")
        segment_id = f"seg_{index:03d}"
        visual_intent = classify_visual_intent(segment_type, text)
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
                "delivery": segment.get("delivery", {}),
                "audio_path": None,
                "duration": None,
                "visual_path": None,
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


def attach_audio_to_storyboard(storyboard: Dict[str, Any], audio_files: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Attach rendered audio paths and durations to storyboard segments."""
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

    storyboard["validation"] = [issue.as_dict() for issue in validate_storyboard(storyboard)]
    return storyboard


def attach_visuals_to_storyboard(
    storyboard: Dict[str, Any],
    visual_paths: Dict[str, str],
) -> Dict[str, Any]:
    """Attach generated/captured visual paths to storyboard segments."""
    for segment in storyboard.get("segments", []):
        segment_id = segment.get("id")
        if segment_id in visual_paths:
            segment["visual_path"] = visual_paths[segment_id]

    storyboard["validation"] = [issue.as_dict() for issue in validate_storyboard(storyboard)]
    return storyboard


def storyboard_visual_files(storyboard: Dict[str, Any]) -> List[str]:
    """Return visual files in segment order for the editor."""
    return [
        segment["visual_path"]
        for segment in storyboard.get("segments", [])
        if segment.get("visual_path")
    ]


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
            ordered.append(item)

    return ordered


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


def classify_visual_intent(segment_type: str, text: str) -> str:
    """Decide which kind of visual a segment requires."""
    lower = text.lower()
    if segment_type == "hook":
        return "brand_or_concept"
    if is_analogy(lower):
        return "analogy_art"
    if segment_type in CLAIM_TYPES or references_source(lower):
        return "source_card"
    if segment_type in CONCEPT_TYPES:
        return "concept_art"
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
        "style_id": "trendforge_documentary",
        "topic": topic,
        "palette": "dark editorial, deep neutral background, muted purple, warm amber accents",
        "camera": "wide documentary framing, centered subject, readable negative space",
        "lighting": "controlled studio lighting, high contrast, realistic shadows",
        "composition": "16:9, clean foreground, no embedded text, no logos",
        "negative": "watermark, text, logo, blurry, distorted UI, extra fingers, low quality",
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

        if segment.get("visual_path"):
            seen_visuals.setdefault(segment["visual_path"], []).append(segment_id)
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
