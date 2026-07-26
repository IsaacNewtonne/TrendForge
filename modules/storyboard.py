"""Storyboard planning and validation for TrendForge videos.

The storyboard is the contract between narration, evidence, visuals, and
rendering. It prevents the pipeline from drifting into loosely matched images.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import yaml
from loguru import logger

from modules.claim_confirmation import (
    enforce_claim_confirmation,
    score_visual_confirmation,
    source_match_confidence_floor,
)
from modules.manual_images import ai_image_style_prompt, default_negative_prompt
from modules.visual_matcher import enrich_storyboard_matches
from modules.visual_planner import generate_visual_plan, visual_planner_enabled


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
    r"\bpaper\b",
    r"\bfiling\b",
    r"\bpress release\b",
    r"\bblog post\b",
    r"\bwhite paper\b",
    r"\bgithub\b",
    r"\barxiv\b",
    r"\bpubmed\b",
    r"\bsec\b",
    r"\bftc\b",
    r"\bregulator",
]

CLAIM_TYPES = {"fact", "source_claim"}
CONCEPT_TYPES = {"opinion", "transition", "verdict"}
SOURCE_VISUAL_INTENTS = {
    "source_card",
    "source_screenshot",
    "chart_visual",
    "product_visual",
    "social_post_visual",
    "article_visual",
}
ARTICLE_SOCIAL_VISUAL_INTENTS = {
    "chart_visual",
    "product_visual",
    "social_post_visual",
    "article_visual",
}
ART_VISUAL_INTENTS = {"analogy_art", "concept_art", "brand_or_concept", "comparison_visual"}
MAX_CONSECUTIVE_SOURCE_VISUALS = 4
MAX_CONSECUTIVE_ART_VISUALS = 3
MAX_VISUAL_HOLD_SECONDS = 8.0
MAX_REFRESH_VISUALS_PER_SEGMENT = 3
MIN_REFRESH_SEGMENT_SECONDS = 10.0
MAX_WEAK_EVIDENCE_PER_DOMAIN = 2

HIGH_TRUST_EVIDENCE_DOMAINS = [
    ".gov",
    ".edu",
    "sec.gov",
    "nist.gov",
    "who.int",
    "oecd.org",
    "pubmed.ncbi.nlm.nih.gov",
]

PREFERRED_EVIDENCE_DOMAINS = [
    "arxiv.org",
    "github.com",
    "wikipedia.org",
    "openai.com",
    "microsoft.com",
    "googleblog.com",
    "anthropic.com",
]

WEAK_SCREENSHOT_DOMAINS = [
    "news.google.com",
    "google.com",
    "reddit.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
]

HARD_EVIDENCE_PATTERNS = [
    r"\b\d+(?:\.\d+)?\s?(?:%|percent|million|billion|trillion)\b",
    r"\$\s?\d+",
    r"\b20\d{2}\b",
    r"\b(?:survey|poll|filing|lawsuit|earnings|revenue|users|downloads)\b",
    r"\b(?:researchers|analysts|regulators|company said|officials said)\b",
    r"\b(?:announced|launched|released|reported|filed|warned|approved|investigated|sued|acquired|invested|partnered|disclosed)\b",
]

NAMED_EVIDENCE_PATTERNS = [
    r"\b(?:OpenAI|Microsoft|Google|Alphabet|Meta|Facebook|Apple|Amazon|Anthropic|Nvidia|Tesla|Netflix|Adobe|Oracle|IBM|Intel|AMD|GitHub|Reddit|TikTok|ByteDance|YouTube)\b",
    r"\b(?:SEC|FTC|DOJ|FDA|WHO|EU|European Union|White House|Congress|Senate|Supreme Court)\b",
    r"\b[A-Z][A-Za-z0-9&.-]{2,}(?:\s+[A-Z][A-Za-z0-9&.-]{2,}){0,3}\s+(?:said|announced|launched|released|reported|filed|warned|approved|investigated|sued|acquired|invested|partnered|disclosed)\b",
]

CHART_VISUAL_PATTERNS = [
    r"\b\d+(?:\.\d+)?\s?(?:%|percent|million|billion|trillion)\b",
    r"\bchart\b",
    r"\bgraph\b",
    r"\bdata\b",
    r"\bstatistics?\b",
    r"\bstat\b",
    r"\bsurvey\b",
    r"\bpoll\b",
    r"\bearnings\b",
    r"\brevenue\b",
    r"\bgrowth\b",
    r"\bincrease\b",
    r"\bdecrease\b",
]

PRODUCT_VISUAL_PATTERNS = [
    r"\biPhone\b",
    r"\bGalaxy\b",
    r"\bPixel\b",
    r"\bMacBook\b",
    r"\biPad\b",
    r"\bApple Watch\b",
    r"\bAirPods\b",
    r"\bTesla\b",
    r"\bSurface\b",
    r"\bThinkPad\b",
    r"\bGalaxy S\d+\b",
    r"\biPhone \d+\b",
]

SOCIAL_POST_PATTERNS = [
    r"\btweet\b",
    r"\btweeted\b",
    r"\bpost on\b",
    r"\bReddit post\b",
    r"\bshared on\b",
    r"\bgoing viral\b",
    r"\bviral post\b",
    r"\bpost said\b",
    r"\buser wrote\b",
]

ARTICLE_PATTERNS = [
    r"\barticle\b",
    r"\bheadline\b",
    r"\bnewspaper\b",
    r"\bpress release\b",
    r"\bblog post\b",
    r"\beditorial\b",
    r"\bop-ed\b",
]

COMPARISON_VISUAL_PATTERNS = [
    r"\bcompared to\b",
    r"\bversus\b",
    r"\bvs\b",
    r"\bbetter than\b",
    r"\bworse than\b",
    r"\bopposite of\b",
    r"\bin contrast\b",
    r"\bwhere-as\b",
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


def load_sentence_level_config() -> Dict[str, Any]:
    """Load sentence-level visual configuration."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
            return cfg.get("visuals", {}).get("sentence_level", {})
    return {}


def split_into_sentences(text: str) -> List[str]:
    """Split text into individual sentences."""
    text = normalize_text(text)
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if s.strip() and len(s.strip().split()) >= 3]


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
    visual_plan_source = "rules"
    llm_plan = None
    
    sentence_level_cfg = load_sentence_level_config()
    sentence_level_enabled = sentence_level_cfg.get("enabled", False)

    if visual_planner_enabled(analysis):
        llm_plan = generate_visual_plan(script, evidence, analysis)
    
    if llm_plan:
        storyboard_segments = build_llm_visual_plan_storyboard_segments(llm_plan, segments, script, bool(evidence))
        visual_plan_source = "llm"
    elif sentence_level_enabled:
        storyboard_segments = build_sentence_level_storyboard(
            segments, evidence, script, source_cursor
        )
    else:
        planned_segments = plan_visual_sequence(build_visual_plan_items(segments), bool(evidence))
        storyboard_segments = build_standard_storyboard_segments(
            planned_segments, evidence, script, source_cursor
        )

    storyboard = {
        "topic": script.get("topic", ""),
        "title": script.get("title", ""),
        "style_profile": build_style_profile(script),
        "evidence": evidence,
        "segments": storyboard_segments,
        "analysis_confidence": (analysis or {}).get("confidence"),
        "visual_plan_source": visual_plan_source,
    }

    storyboard = enforce_claim_confirmation(storyboard)
    storyboard = enrich_storyboard_matches(storyboard)
    storyboard = demote_weak_source_matches(storyboard)
    storyboard = repair_unmatched_source_visuals(storyboard)
    storyboard["visual_confirmation"] = score_visual_confirmation(storyboard)
    issues = validate_storyboard(storyboard)
    storyboard["validation"] = [issue.as_dict() for issue in issues]
    log_storyboard_summary(storyboard, issues)
    return storyboard


def build_llm_visual_plan_storyboard_segments(
    plan_beats: List[Dict[str, Any]],
    script_segments: List[Dict[str, Any]],
    script: Dict[str, Any],
    has_evidence: bool,
) -> List[Dict[str, Any]]:
    """Convert an LLM visual plan into the normal storyboard segment contract."""
    storyboard_segments: List[Dict[str, Any]] = []
    covered_parents = set()

    for beat_index, beat in enumerate(plan_beats):
        parent_index = int(beat.get("parent_segment_index", 0))
        if parent_index < 0 or parent_index >= len(script_segments):
            continue
        segment = script_segments[parent_index]
        visual_intent = normalize_planned_visual_intent(beat.get("visual_intent"))
        warnings: List[str] = []
        if visual_intent in SOURCE_VISUAL_INTENTS and not has_evidence:
            visual_intent = art_intent_for_segment(
                {
                    "text": beat.get("narration", ""),
                    "segment_type": segment.get("type", "fact"),
                    "visual_role_hint": beat.get("visual_role", ""),
                }
            )
            warnings.append("LLM requested evidence visual but no evidence sources were available; using art.")

        narration = normalize_text(beat.get("narration", "") or segment.get("text", ""))
        visual_prompt = normalize_text(beat.get("visual_prompt", "")) or planned_visual_prompt(script, beat, segment, visual_intent)
        image_prompt = normalize_text(beat.get("image_prompt", "")) or planned_image_prompt(script, beat, segment, visual_intent)
        visual_role = normalize_text(beat.get("visual_role", ""))

        storyboard_segments.append(
            {
                "id": f"llm_{beat_index:04d}",
                "index": beat_index,
                "segment_type": segment.get("type", "fact"),
                "narration": narration,
                "visual_intent": visual_intent,
                "required_visual": required_visual_for_intent(visual_intent),
                "visual_prompt": visual_prompt,
                "source_id": None,
                "source_url": None,
                "source_title": None,
                "source_name": None,
                "source_published": None,
                "source_excerpt": None,
                "source_image": None,
                "claim": narration if visual_intent in SOURCE_VISUAL_INTENTS else None,
                "evidence_need": normalize_text(beat.get("evidence_need", "")),
                "source_query": normalize_text(beat.get("source_query", "")),
                "image_prompt": image_prompt,
                "payoff_min_seconds": segment.get("payoff_min_seconds", 0),
                "beat_type": segment.get("beat_type", "evidence"),
                "beat_purpose": segment.get("beat_purpose", ""),
                "visual_role_hint": visual_role or segment.get("visual_role_hint", ""),
                "visual_plan_reason": f"LLM visual plan: {normalize_text(beat.get('reason', 'planned visual beat'))}",
                "delivery": segment.get("delivery", {}),
                "parent_segment_index": parent_index,
                "sentence_index": int(beat.get("sentence_index", 0) or 0),
                "audio_path": None,
                "duration": None,
                "visual_path": None,
                "visual_paths": [],
                "visual_refresh_specs": [],
                "warnings": warnings,
            }
        )
        covered_parents.add(parent_index)

    if len(covered_parents) < len(script_segments):
        missing = sorted(set(range(len(script_segments))) - covered_parents)
        raise RuntimeError(
            f"LLM visual plan omitted script parent indices {missing}. "
            "No rule-based gap segments were created."
        )

    storyboard_segments.sort(key=lambda item: (item.get("parent_segment_index", 0), item.get("sentence_index", 0), item.get("index", 0)))
    for index, segment in enumerate(storyboard_segments):
        segment["index"] = index
    return storyboard_segments


def normalize_planned_visual_intent(value: Any) -> str:
    intent = normalize_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "source": "source_screenshot",
        "screenshot": "source_screenshot",
        "evidence": "source_screenshot",
        "evidence_screenshot": "source_screenshot",
        "card": "source_card",
        "sourcecard": "source_card",
        "ai_art": "concept_art",
        "art": "concept_art",
        "metaphor": "analogy_art",
        "analogy": "analogy_art",
        "brand": "brand_or_concept",
    }
    intent = aliases.get(intent, intent)
    if intent == "source_card":
        intent = "source_screenshot"
    if intent in SOURCE_VISUAL_INTENTS or intent in {"concept_art", "analogy_art", "brand_or_concept"}:
        return intent
    return "concept_art"


def planned_visual_prompt(script: Dict[str, Any], beat: Dict[str, Any], segment: Dict[str, Any], visual_intent: str) -> str:
    if visual_intent in SOURCE_VISUAL_INTENTS:
        return normalize_text(beat.get("evidence_need") or beat.get("source_query") or beat.get("narration", ""))[:180]
    return build_visual_prompt(script, segment, visual_intent, None)


def planned_image_prompt(script: Dict[str, Any], beat: Dict[str, Any], segment: Dict[str, Any], visual_intent: str) -> str:
    if visual_intent in SOURCE_VISUAL_INTENTS:
        return normalize_text(beat.get("source_query") or beat.get("evidence_need") or beat.get("narration", ""))[:140]
    return normalize_text(beat.get("image_prompt") or build_visual_prompt(script, segment, visual_intent, None))


def fallback_llm_gap_segment(
    script: Dict[str, Any],
    segment: Dict[str, Any],
    parent_index: int,
    index: int,
    has_evidence: bool,
) -> Dict[str, Any]:
    text = normalize_text(segment.get("text", ""))
    visual_intent = classify_sentence_visual_intent(text, segment.get("type", "fact"), segment.get("visual_role_hint", ""))
    if visual_intent in SOURCE_VISUAL_INTENTS and not has_evidence:
        visual_intent = art_intent_for_segment(
            {
                "text": text,
                "segment_type": segment.get("type", "fact"),
                "visual_role_hint": segment.get("visual_role_hint", ""),
            }
        )
    return {
        "id": f"llm_gap_{index:04d}",
        "index": index,
        "segment_type": segment.get("type", "fact"),
        "narration": text,
        "visual_intent": visual_intent,
        "required_visual": required_visual_for_intent(visual_intent),
        "visual_prompt": build_visual_prompt(script, segment, visual_intent, None),
        "source_id": None,
        "source_url": None,
        "source_title": None,
        "source_name": None,
        "source_published": None,
        "source_excerpt": None,
        "source_image": None,
        "claim": text if visual_intent in SOURCE_VISUAL_INTENTS else None,
        "evidence_need": text if visual_intent in SOURCE_VISUAL_INTENTS else None,
        "source_query": text if visual_intent in SOURCE_VISUAL_INTENTS else "",
        "image_prompt": build_visual_prompt(script, segment, visual_intent, None),
        "payoff_min_seconds": segment.get("payoff_min_seconds", 0),
        "beat_type": segment.get("beat_type", "evidence"),
        "beat_purpose": segment.get("beat_purpose", ""),
        "visual_role_hint": segment.get("visual_role_hint", ""),
        "visual_plan_reason": "Rule fallback filled a script segment missing from the LLM visual plan.",
        "delivery": segment.get("delivery", {}),
        "parent_segment_index": parent_index,
        "sentence_index": 0,
        "audio_path": None,
        "duration": None,
        "visual_path": None,
        "visual_paths": [],
        "visual_refresh_specs": [],
        "warnings": ["LLM visual plan omitted this script segment; rule fallback filled it."],
    }


def build_standard_storyboard_segments(
    planned_segments: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    script: Dict[str, Any],
    source_cursor: int,
) -> List[Dict[str, Any]]:
    """Build storyboard segments using the standard (non-sentence-level) approach."""
    storyboard_segments: List[Dict[str, Any]] = []
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
                "evidence_need": item.get("evidence_need"),
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
    return storyboard_segments


def build_sentence_level_storyboard(
    segments: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    script: Dict[str, Any],
    source_cursor: int,
) -> List[Dict[str, Any]]:
    """Build storyboard with each sentence as its own segment with its own visual."""
    storyboard_segments: List[Dict[str, Any]] = []
    sentence_idx = 0
    evidence_count = len(evidence) if evidence else 0
    
    for seg_idx, segment in enumerate(segments):
        original_text = normalize_text(segment.get("text", ""))
        sentences = split_into_sentences(original_text)
        
        if not sentences:
            sentences = [original_text]
        
        for sent_idx, sentence in enumerate(sentences):
            segment_id = f"sent_{sentence_idx:04d}"
            segment_type = segment.get("type", "fact")
            
            visual_intent = classify_sentence_visual_intent(
                sentence, 
                segment_type,
                segment.get("visual_role_hint", ""),
            )
            
            evidence_item = None
            if visual_intent in SOURCE_VISUAL_INTENTS and evidence:
                evidence_item = evidence[source_cursor % evidence_count]
                source_cursor += 1
            elif visual_intent in SOURCE_VISUAL_INTENTS:
                visual_intent = "concept_art"
            
            storyboard_segments.append(
                {
                    "id": segment_id,
                    "index": sentence_idx,
                    "segment_type": segment_type,
                    "narration": sentence,
                    "visual_intent": visual_intent,
                    "required_visual": required_visual_for_intent(visual_intent),
                    "visual_prompt": build_sentence_visual_prompt(
                        script, segment, sentence, visual_intent, evidence_item
                    ),
                    "source_id": evidence_item.get("id") if evidence_item else None,
                    "source_url": evidence_item.get("url") if evidence_item else None,
                    "source_title": evidence_item.get("title") if evidence_item else None,
                    "source_name": evidence_item.get("source_name") if evidence_item else None,
                    "source_published": evidence_item.get("published") if evidence_item else None,
                    "source_excerpt": evidence_item.get("text_excerpt") if evidence_item else None,
                    "source_image": evidence_item.get("image_url") if evidence_item else None,
                    "claim": sentence if visual_intent in SOURCE_VISUAL_INTENTS else None,
                    "evidence_need": None,
                    "image_prompt": build_sentence_image_prompt(sentence, segment, visual_intent),
                    "payoff_min_seconds": segment.get("payoff_min_seconds", 0),
                    "beat_type": segment.get("beat_type", "evidence"),
                    "beat_purpose": segment.get("beat_purpose", ""),
                    "visual_role_hint": segment.get("visual_role_hint", ""),
                    "visual_plan_reason": f"Sentence-level visual: {explain_sentence_intent(visual_intent, sentence)}",
                    "delivery": segment.get("delivery", {}),
                    "parent_segment_index": seg_idx,
                    "sentence_index": sent_idx,
                    "audio_path": None,
                    "duration": None,
                    "visual_path": None,
                    "visual_paths": [],
                    "visual_refresh_specs": [],
                    "warnings": [],
                }
            )
            sentence_idx += 1
    
    return storyboard_segments


def classify_sentence_visual_intent(
    sentence: str, 
    segment_type: str, 
    visual_role_hint: str = "",
) -> str:
    """Classify visual intent for a single sentence."""
    lower = sentence.lower()
    visual_role = visual_role_hint.lower()
    
    if segment_type == "hook" or segment_type == "verdict":
        return "brand_or_concept"
    
    if is_analogy(lower):
        return "analogy_art"
    
    if visual_role in {"contrast", "synthesis"} or has_comparison_marker(lower):
        return "comparison_visual"
    
    if visual_role == "evidence" or is_evidence_worthy(sentence, segment_type):
        return _evidence_intent_for_text(sentence, segment_type)
    
    if references_source(lower):
        return _evidence_intent_for_text(sentence, segment_type)
    
    if has_hard_evidence_marker(lower) or has_named_evidence_marker(sentence):
        return _evidence_intent_for_text(sentence, segment_type)
    
    return "concept_art"


def explain_sentence_intent(visual_intent: str, sentence: str) -> str:
    """Explain why a particular visual intent was assigned to a sentence."""
    if visual_intent == "brand_or_concept":
        return "Opening/closing segment uses branded concept art"
    if visual_intent == "analogy_art":
        return "Analogy or metaphor uses generated visual metaphor"
    if visual_intent in SOURCE_VISUAL_INTENTS:
        if references_source(sentence.lower()):
            return "Sentence references a source, uses source visual"
        if has_hard_evidence_marker(sentence.lower()):
            return "Sentence contains specific data, uses source visual"
        if has_named_evidence_marker(sentence):
            return "Sentence mentions specific entities, uses source visual"
        return "Factual claim uses source visual"
    return "Concept or context uses generated art"


def build_sentence_visual_prompt(
    script: Dict[str, Any],
    segment: Dict[str, Any],
    sentence: str,
    visual_intent: str,
    evidence_item: Optional[Dict[str, Any]],
) -> str:
    """Build visual prompt for a sentence-level segment."""
    topic = script.get("topic", "")
    
    if visual_intent in SOURCE_VISUAL_INTENTS and evidence_item:
        return evidence_item.get("title") or sentence[:120]
    
    if visual_intent == "analogy_art":
        return (
            f"Visual metaphor for: {sentence[:150]}. "
            "Clear symbolic composition, no text, documentary editorial style."
        )
    
    if visual_intent == "brand_or_concept":
        return f"Strong visual for {topic}, premium documentary style, no text."
    
    return f"Editorial visual for: {sentence[:150]}, no text, documentary style."


def build_sentence_image_prompt(sentence: str, segment: Dict[str, Any], visual_intent: str) -> str:
    """Build image prompt for sentence-level generation."""
    base_prompt = segment.get("image_prompt", "")
    if base_prompt:
        return base_prompt
    
    if visual_intent == "analogy_art":
        return f"Visual metaphor: {sentence[:100]}, symbolic, no text"
    if visual_intent == "brand_or_concept":
        return "Concept art, editorial style, no text, premium documentary"
    if visual_intent in SOURCE_VISUAL_INTENTS:
        return f"Source reference: {sentence[:80]}, documentary style"
    return f"Editorial visual: {sentence[:100]}, no text"


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

    source_policy = load_source_visual_policy()
    if source_policy.get("source_first", True):
        return enforce_source_first_visuals(planned, source_policy)

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
                item["visual_intent"] = "source_screenshot"
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
            candidate["visual_intent"] = "source_screenshot"
            candidate["visual_plan_reason"] = "First evidence-backed beat promoted to a source visual."

    return planned


def load_source_visual_policy() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
            source_cfg = cfg.get("source_visuals", {}) or {}
            return {
                "source_first": bool(source_cfg.get("source_first", True)),
                "target_source_ratio": float(source_cfg.get("target_source_ratio", 0.9)),
                "max_ai_art_segments": int(source_cfg.get("max_ai_art_segments", 0)),
                "allow_analogy_art": bool(source_cfg.get("allow_analogy_art", False)),
                "allow_context_art_refreshes": bool(source_cfg.get("allow_context_art_refreshes", True)),
            }
    return {
        "source_first": True,
        "target_source_ratio": 0.9,
        "max_ai_art_segments": 0,
        "allow_analogy_art": False,
        "allow_context_art_refreshes": True,
    }


def enforce_source_first_visuals(items: List[Dict[str, Any]], policy: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Promote source visuals selectively while preserving viral pacing breaks."""
    planned = [dict(item) for item in items]
    target_ratio = min(1.0, max(0.0, float(policy.get("target_source_ratio", 0.9))))
    target_source_count = int(round(len(planned) * target_ratio))
    max_ai_art = max(0, int(policy.get("max_ai_art_segments", 0)))
    allow_analogy_art = bool(policy.get("allow_analogy_art", False))
    source_count = sum(1 for item in planned if item.get("visual_intent") in SOURCE_VISUAL_INTENTS)
    kept_art = sum(1 for item in planned if item.get("visual_intent") in ART_VISUAL_INTENTS)

    for item in planned:
        intent = item.get("visual_intent")
        if intent in SOURCE_VISUAL_INTENTS:
            continue

        can_keep_art = kept_art < max_ai_art or source_count >= target_source_count
        if intent == "analogy_art" and allow_analogy_art:
            kept_art += 1
            continue
        if intent == "brand_or_concept" and can_keep_art:
            kept_art += 1
            continue
        if intent == "concept_art" and can_keep_art:
            kept_art += 1
            continue
        if source_count >= target_source_count:
            kept_art += 1
            continue

        item["visual_intent"] = "source_screenshot"
        item["visual_plan_reason"] = (
            "Source-first mode promoted this beat to evidence-backed screenshot/card visual."
        )
        source_count += 1

    for item in reversed(planned):
        if source_count <= target_source_count:
            break
        if item.get("visual_intent") not in SOURCE_VISUAL_INTENTS:
            continue
        if not can_demote_source_for_pacing(item):
            continue
        item["visual_intent"] = art_intent_for_segment(item)
        item["visual_plan_reason"] = "Demoted to art so source proof beats do not dominate pacing."
        source_count -= 1

    source_run = 0
    for item in planned:
        if item.get("visual_intent") in SOURCE_VISUAL_INTENTS:
            source_run += 1
            if source_run > 2 and can_demote_source_for_pacing(item) and kept_art < max_ai_art:
                item["visual_intent"] = art_intent_for_segment(item)
                item["visual_plan_reason"] = "Pacing break after repeated source visuals."
                source_run = 0
                kept_art += 1
            continue
        source_run = 0

    return planned


def can_demote_source_for_pacing(item: Dict[str, Any]) -> bool:
    """Keep hard proof beats as sources, but let soft/context beats become art."""
    if item.get("visual_role_hint") == "evidence":
        return False
    text = str(item.get("text", ""))
    if has_hard_evidence_marker(text.lower()):
        return False
    reason = str(item.get("visual_plan_reason", "")).lower()
    return "source-first mode promoted" in reason or not is_evidence_worthy(text, item.get("segment_type", ""))


def demote_weak_source_matches(storyboard: Dict[str, Any]) -> Dict[str, Any]:
    """Avoid showing unrelated pages as proof when the matcher only found a weak source."""
    min_confidence = source_match_confidence_floor()
    for segment in storyboard.get("segments", []):
        if segment.get("visual_intent") not in SOURCE_VISUAL_INTENTS:
            continue
        try:
            confidence = float(segment.get("evidence_match_confidence"))
        except (TypeError, ValueError):
            continue
        if confidence >= min_confidence:
            continue
        if not can_replace_weak_source_with_art(segment):
            continue

        segment["visual_intent"] = art_intent_for_segment(
            {
                "text": segment.get("narration", ""),
                "segment_type": segment.get("segment_type", ""),
                "visual_role_hint": segment.get("visual_role_hint", ""),
            }
        )
        segment["required_visual"] = required_visual_for_intent(segment["visual_intent"])
        segment["visual_plan_reason"] = "Weak source match demoted to explanatory art to avoid misleading proof."
        segment["claim"] = None
        segment.setdefault("warnings", []).append("Weak source match; using explanatory art instead of a source visual.")

    return storyboard


def repair_unmatched_source_visuals(storyboard: Dict[str, Any]) -> Dict[str, Any]:
    """Replace impossible source visuals with honest generated art.

    A planner may request a screenshot even when none of the scraped evidence
    has a usable URL. Keeping that intent guarantees a blocking validation
    error and cannot produce truthful proof, so retain the narration while
    switching only the visual treatment.
    """
    for segment in storyboard.get("segments", []):
        if segment.get("visual_intent") not in SOURCE_VISUAL_INTENTS:
            continue
        if segment.get("source_url"):
            continue

        segment["visual_intent"] = art_intent_for_segment(
            {
                "text": segment.get("narration", ""),
                "segment_type": segment.get("segment_type", ""),
                "visual_role_hint": segment.get("visual_role_hint", ""),
            }
        )
        segment["required_visual"] = required_visual_for_intent(segment["visual_intent"])
        segment["visual_plan_reason"] = (
            "No usable source URL matched this beat; using explanatory art "
            "instead of inventing or displaying unsupported proof."
        )
        segment["claim"] = None
        segment["visual_role"] = "context"
        segment["motion_hint"] = "slow_push_in"
        segment.setdefault("warnings", []).append(
            "No usable source URL matched this claim; using explanatory art."
        )

    return storyboard


def can_replace_weak_source_with_art(segment: Dict[str, Any]) -> bool:
    text = str(segment.get("narration", ""))
    if references_source(text.lower()):
        return False
    reason = str(segment.get("visual_plan_reason", "")).lower()
    if "source-first mode promoted" in reason:
        return True
    if segment.get("segment_type") not in CLAIM_TYPES:
        return True
    return not has_hard_evidence_marker(text.lower()) and not has_named_evidence_marker(text)


def attach_audio_to_storyboard(storyboard: Dict[str, Any], audio_files: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Attach rendered audio paths and durations to storyboard segments."""
    refresh_cfg = load_visual_refresh_config()
    segments = storyboard.get("segments", [])
    by_text = audio_files_by_text(audio_files)
    by_parent = audio_files_by_parent_index(audio_files)

    if any("parent_segment_index" in segment for segment in segments):
        grouped: Dict[int, List[Dict[str, Any]]] = {}
        for segment in segments:
            parent_index = segment.get("parent_segment_index")
            if parent_index is not None:
                grouped.setdefault(int(parent_index), []).append(segment)

        for parent_index, child_segments in grouped.items():
            audio = by_parent.get(parent_index) or find_parent_audio_by_text(child_segments, by_text)
            if not audio:
                continue
            durations = distribute_duration_by_narration(
                float(audio.get("duration") or 0.0),
                [segment.get("narration", "") for segment in child_segments],
            )
            for segment, duration in zip(child_segments, durations):
                segment["audio_path"] = audio.get("path")
                segment["parent_audio_path"] = audio.get("path")
                segment["duration"] = duration
                segment["visual_refresh_specs"] = plan_visual_refresh_specs(segment, refresh_cfg)
    else:
        for segment in segments:
            audio = by_text.get(segment.get("narration", ""))
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

    storyboard["visual_confirmation"] = score_visual_confirmation(storyboard)
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
    segments = storyboard.get("segments", [])
    if any("parent_segment_index" in segment for segment in segments):
        return sentence_level_audio_files(storyboard, audio_files)

    by_text = audio_files_by_text(audio_files)
    ordered = []
    for segment in segments:
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


def sentence_level_audio_files(storyboard: Dict[str, Any], audio_files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return parent narration clips with all sentence-level visuals attached."""
    by_parent = audio_files_by_parent_index(audio_files)
    by_text = audio_files_by_text(audio_files)
    grouped: Dict[int, List[Dict[str, Any]]] = {}

    for segment in storyboard.get("segments", []):
        parent_index = segment.get("parent_segment_index")
        if parent_index is not None:
            grouped.setdefault(int(parent_index), []).append(segment)

    ordered: List[Dict[str, Any]] = []
    for parent_index in sorted(grouped):
        child_segments = grouped[parent_index]
        item = by_parent.get(parent_index) or find_parent_audio_by_text(child_segments, by_text)
        if not item:
            continue

        first_segment = child_segments[0]
        item = dict(item)
        item["storyboard_id"] = first_segment.get("id")
        item["storyboard_ids"] = [segment.get("id") for segment in child_segments]
        item["visual_intent"] = first_segment.get("visual_intent")
        item["visual_role"] = first_segment.get("visual_role")
        item["motion_hint"] = first_segment.get("motion_hint")
        item["beat_type"] = first_segment.get("beat_type")
        item["delivery"] = item.get("delivery") or first_segment.get("delivery", {})
        item["visual_paths"] = collect_visual_paths(child_segments)
        ordered.append(item)

    return ordered


def audio_files_by_text(audio_files: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {
        normalize_text(item.get("segment", {}).get("text", "")): item
        for item in audio_files
        if item.get("segment", {}).get("text")
    }


def audio_files_by_parent_index(audio_files: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    by_parent: Dict[int, Dict[str, Any]] = {}
    for fallback_index, item in enumerate(audio_files):
        raw_index = item.get("script_index", fallback_index)
        if raw_index is None:
            continue
        by_parent[int(raw_index)] = item
    return by_parent


def find_parent_audio_by_text(
    child_segments: List[Dict[str, Any]],
    by_text: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    joined = normalize_text(" ".join(segment.get("narration", "") for segment in child_segments))
    return by_text.get(joined)


def distribute_duration_by_narration(duration: float, narrations: List[str]) -> List[float]:
    if not narrations:
        return []
    if duration <= 0:
        return [0.0 for _ in narrations]

    weights = [max(1, len(normalize_text(text).split())) for text in narrations]
    total_weight = sum(weights) or len(narrations)
    durations = [duration * (weight / total_weight) for weight in weights]
    durations[-1] += duration - sum(durations)
    return durations


def collect_visual_paths(segments: List[Dict[str, Any]]) -> List[str]:
    paths: List[str] = []
    seen = set()
    for segment in segments:
        segment_paths = segment.get("visual_paths") or ([segment["visual_path"]] if segment.get("visual_path") else [])
        for path in segment_paths:
            if path and path not in seen:
                seen.add(path)
                paths.append(path)
    return paths


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

    if segment.get("visual_intent") in SOURCE_VISUAL_INTENTS:
        max_hold_seconds = float(refresh_cfg.get("evidence_max_hold_seconds", max_hold_seconds))
        max_refresh_visuals = int(
            refresh_cfg.get(
                "evidence_max_extra_visuals_per_segment",
                max(2, max_refresh_visuals),
            )
        )
        if max_hold_seconds <= 0 or max_refresh_visuals <= 0:
            return []

    refresh_count = min(
        max_refresh_visuals,
        max(0, int(duration // max_hold_seconds)),
    )
    if refresh_count <= 0:
        return []

    ideas = extract_visual_ideas(segment.get("narration", ""), refresh_count)
    if refresh_cfg.get("skip_redundant_refreshes", True):
        parent_words = set(normalize_text(segment.get("visual_prompt") or "").lower().split())
        ideas = [
            idea
            for idea in ideas
            if text_overlap_ratio(parent_words, set(normalize_text(idea).lower().split())) < 0.75
        ]
    specs: List[Dict[str, Any]] = []
    for index, idea in enumerate(ideas, start=1):
        intent = refresh_intent_for_segment(segment, idea)
        source_refresh = intent in SOURCE_VISUAL_INTENTS
        source_context = source_refresh_context(segment) if source_refresh else {}
        specs.append(
            {
                "id": f"{segment.get('id', 'segment')}_refresh_{index:02d}",
                "parent_id": segment.get("id"),
                "visual_intent": intent,
                "required_visual": "screenshot" if source_refresh else "generated_art",
                "visual_prompt": refresh_visual_prompt(segment, idea, intent),
                "image_prompt": refresh_visual_prompt(segment, idea, intent),
                "narration": idea,
                "segment_type": segment.get("segment_type", "transition"),
                "visual_role": "evidence" if source_refresh else ("metaphor" if intent == "analogy_art" else "context"),
                "motion_hint": "source_push_in" if source_refresh else ("slow_drift" if intent == "analogy_art" else "slow_push_in"),
                "claim": idea if source_refresh else None,
                **source_context,
            }
        )
    return specs


def text_overlap_ratio(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, min(len(left), len(right)))


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
    policy = load_source_visual_policy()
    if policy.get("source_first") and segment.get("source_url"):
        if policy.get("allow_analogy_art") and (is_analogy(idea.lower()) or segment.get("visual_intent") == "analogy_art"):
            return "analogy_art"
        if policy.get("allow_context_art_refreshes", True) and not is_evidence_worthy(
            idea,
            segment.get("segment_type", ""),
        ):
            return "concept_art"
        return "source_screenshot"
    if is_analogy(idea.lower()) or segment.get("visual_intent") == "analogy_art":
        return "analogy_art"
    if segment.get("visual_intent") in SOURCE_VISUAL_INTENTS and is_evidence_worthy(idea, segment.get("segment_type", "")):
        return "source_screenshot"
    return "concept_art"


def refresh_visual_prompt(segment: Dict[str, Any], idea: str, visual_intent: str) -> str:
    topic = normalize_text(segment.get("visual_prompt") or segment.get("source_title") or "")
    if visual_intent == "analogy_art":
        return (
            f"Visual metaphor for this idea: {idea}. "
            "Clear symbolic composition, no text, documentary editorial style."
        )
    if visual_intent in SOURCE_VISUAL_INTENTS:
        return normalize_text(segment.get("source_title") or segment.get("visual_prompt") or idea[:120])
    return (
        f"Cutaway visual for {topic}: {idea}. "
        "Fresh composition, no text, documentary editorial style."
    )


def source_refresh_context(segment: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source_id": segment.get("source_id"),
        "source_url": segment.get("source_url"),
        "source_title": segment.get("source_title"),
        "source_name": segment.get("source_name"),
        "source_published": segment.get("source_published"),
        "source_excerpt": segment.get("source_excerpt"),
        "source_image": segment.get("source_image"),
        "source_type": segment.get("source_type"),
        "source_domain": segment.get("source_domain"),
    }


def build_evidence_ledger(raw_content: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize scraped content into reusable source evidence."""
    evidence = []
    for index, item in enumerate(raw_content):
        url = item.get("url", "")
        if not url or not url.startswith("http"):
            continue
        domain = normalize_domain(item.get("domain") or urlparse(url).netloc)

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
                "domain": domain,
                "citation_score": item.get("citation_score"),
                "evidence_tags": item.get("evidence_tags", []),
                "source_quality_score": evidence_source_score(url, domain, item),
            }
        )

    usable = [item for item in evidence if not is_hard_reject_source(item)]
    balanced = interleave_evidence_by_domain(usable or evidence)
    return cap_weak_evidence_domains(balanced)


def normalize_domain(value: Any) -> str:
    return str(value or "").lower().replace("www.", "").strip()


def evidence_source_score(url: str, domain: str, item: Dict[str, Any]) -> float:
    """Score how likely a source is to produce a useful evidence screenshot."""
    lower_url = str(url or "").lower()
    domain = normalize_domain(domain)
    score = 50.0

    if any(domain.endswith(preferred) or preferred in domain for preferred in HIGH_TRUST_EVIDENCE_DOMAINS):
        score += 24
    elif any(domain.endswith(preferred) or preferred in domain for preferred in PREFERRED_EVIDENCE_DOMAINS):
        score += 12
    if item.get("source_type") == "specialist":
        score += 6
    if item.get("citation_score") is not None:
        try:
            score += min(10, float(item.get("citation_score")) / 12)
        except (TypeError, ValueError):
            pass
    if any(weak in domain for weak in WEAK_SCREENSHOT_DOMAINS):
        score -= 18
    if "news.google.com/rss/articles" in lower_url:
        score -= 45
    if lower_url.endswith(".pdf"):
        score -= 12
    if not item.get("text"):
        score -= 8

    return max(0.0, min(100.0, score))


def is_hard_reject_source(item: Dict[str, Any]) -> bool:
    url = str(item.get("url", "")).lower()
    return "news.google.com/rss/articles" in url


def is_unreliable_screenshot_source(item: Dict[str, Any]) -> bool:
    """Return soft-risk domains that can still be used if quality-gated screenshots pass."""
    domain = normalize_domain(item.get("domain", ""))
    return any(weak in domain for weak in WEAK_SCREENSHOT_DOMAINS)


def cap_weak_evidence_domains(evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep social/search sources as texture without letting them dominate proof beats."""
    if not any(not is_unreliable_screenshot_source(item) for item in evidence):
        return evidence

    kept: List[Dict[str, Any]] = []
    weak_counts: Dict[str, int] = {}
    for item in evidence:
        if not is_unreliable_screenshot_source(item):
            kept.append(item)
            continue

        domain = normalize_domain(item.get("domain", "")) or "unknown"
        count = weak_counts.get(domain, 0)
        if count >= MAX_WEAK_EVIDENCE_PER_DOMAIN:
            continue
        weak_counts[domain] = count + 1
        kept.append(item)

    return kept or evidence


def interleave_evidence_by_domain(evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Balance the evidence pool so one clean domain cannot dominate the whole video."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in sorted(evidence, key=lambda row: row.get("source_quality_score", 0), reverse=True):
        grouped.setdefault(normalize_domain(item.get("domain", "")) or "unknown", []).append(item)

    ordered: List[Dict[str, Any]] = []
    while grouped:
        domains = sorted(
            grouped,
            key=lambda domain: grouped[domain][0].get("source_quality_score", 0),
            reverse=True,
        )
        for domain in domains:
            bucket = grouped.get(domain, [])
            if not bucket:
                grouped.pop(domain, None)
                continue
            ordered.append(bucket.pop(0))
            if not bucket:
                grouped.pop(domain, None)
    return ordered


def classify_visual_intent(segment_type: str, text: str, visual_role_hint: str = "") -> str:
    """Decide which kind of visual a segment requires."""
    lower = text.lower()
    visual_role = visual_role_hint.lower()
    if segment_type == "hook":
        return "brand_or_concept"
    if visual_role == "metaphor" or (is_analogy(lower) and not is_evidence_worthy(text, segment_type)):
        return "analogy_art"
    if visual_role in {"contrast", "synthesis"} or has_comparison_marker(lower):
        return "comparison_visual"
    if visual_role == "evidence":
        return _evidence_intent_for_text(text, segment_type)
    if is_evidence_worthy(text, segment_type):
        return _evidence_intent_for_text(text, segment_type)
    if segment_type in CONCEPT_TYPES:
        return "concept_art"
    return "concept_art"


def _evidence_intent_for_text(text: str, segment_type: str) -> str:
    """Choose the best source-backed visual type based on text content."""
    lower = text.lower()
    if has_chart_marker(lower):
        return "chart_visual"
    if has_product_marker(lower):
        return "product_visual"
    if has_social_post_marker(lower):
        return "social_post_visual"
    if has_article_marker(lower):
        return "article_visual"
    return "source_screenshot"


def has_chart_marker(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in CHART_VISUAL_PATTERNS)


def has_product_marker(text: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in PRODUCT_VISUAL_PATTERNS)


def has_social_post_marker(text: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in SOCIAL_POST_PATTERNS)


def has_article_marker(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in ARTICLE_PATTERNS)


def has_comparison_marker(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in COMPARISON_VISUAL_PATTERNS)


def explain_visual_intent(visual_intent: str, segment_type: str, text: str, visual_role_hint: str = "") -> str:
    lower = text.lower()
    visual_role = visual_role_hint.lower()
    if visual_intent == "brand_or_concept":
        return "Opening or branded context uses generated concept art."
    if visual_intent == "analogy_art":
        return "Analogy or metaphor beat uses generated visual metaphor art."
    if visual_intent == "comparison_visual":
        return "Comparison beat uses two-panel generated art to show contrast."
    if visual_intent == "chart_visual":
        return "Data or statistic claim uses chart or infographic source visual."
    if visual_intent == "product_visual":
        return "Specific product mention uses product showcase visual."
    if visual_intent == "social_post_visual":
        return "Social media post reference uses stylized social post visual."
    if visual_intent == "article_visual":
        return "Article or publication reference uses editorial article visual."
    if visual_intent in SOURCE_VISUAL_INTENTS:
        if references_source(lower):
            return "Source-referencing beat uses a source visual."
        if visual_role == "evidence":
            return "Narrative plan marked this beat as evidence."
        if has_hard_evidence_marker(lower):
            return "Specific data or dated claim uses a source visual."
        if has_named_evidence_marker(text):
            return "Named company, institution, or official action uses a source visual."
        if segment_type in CLAIM_TYPES:
            return "Factual claim uses a source visual."
    return "Concept, contrast, implication, or synthesis beat uses generated art."


def has_hard_evidence_marker(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in HARD_EVIDENCE_PATTERNS)


def has_named_evidence_marker(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in NAMED_EVIDENCE_PATTERNS)


def is_evidence_worthy(text: str, segment_type: str = "") -> bool:
    lower = text.lower()
    return (
        references_source(lower)
        or has_hard_evidence_marker(lower)
        or has_named_evidence_marker(text)
        or segment_type in CLAIM_TYPES
    )


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
    if has_named_evidence_marker(str(item.get("text", ""))):
        score += 2
    if visual_role == "evidence":
        score += 2
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
    if visual_intent in {"analogy_art", "concept_art", "brand_or_concept", "comparison_visual", "chart_visual", "product_visual", "social_post_visual", "article_visual"}:
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

    if visual_intent == "comparison_visual":
        return (
            f"Two-panel comparison visual: {text}. "
            "Show contrast between two options side by side, clear compositional split, "
            "no text, documentary editorial style, balanced panels."
        )

    if visual_intent == "chart_visual":
        return (
            f"Data visualization for {topic}: {text}. "
            "Clean infographic aesthetic, no text labels, editorial diagram style, no numbers."
        )

    if visual_intent == "product_visual":
        return (
            f"Product showcase illustration: {text}. "
            "One clean device or object rendered as precise Signal-Ink editorial art, no text."
        )

    if visual_intent == "social_post_visual":
        return (
            f"Stylized social media post illustration: {text}. "
            "Editorial reinterpretation using flat ink contours and symbolic shapes, no interface or text."
        )

    if visual_intent == "article_visual":
        return (
            f"Editorial article illustration: {text}. "
            "Grounded Signal-Ink editorial metaphor, no publication page, headline, frame, or text."
        )

    return base_prompt or f"Conceptual editorial visual for {topic}: {text[:160]}, no text."


def build_style_profile(script: Dict[str, Any]) -> Dict[str, Any]:
    topic = script.get("topic", "")
    return {
        "style_id": "trendforge_signal_ink",
        "topic": topic,
        "palette": "warm bone, midnight navy, mineral teal, electric coral focal accent, restrained amber",
        "camera": "graphic editorial framing with varied scale, one clear subject, no product-view perspective",
        "lighting": "layered gouache value structure with controlled graphite shadows and tactile paper texture",
        "composition": "edge-to-edge 16:9 artwork, asymmetrical balance, bold negative space, central crop-safe subject, no frame or mockup",
        "style_prompt": ai_image_style_prompt(),
        "negative": default_negative_prompt(),
        "seed_strategy": "stable seed per video topic and segment index",
    }


def validate_storyboard(storyboard: Dict[str, Any]) -> List[StoryboardIssue]:
    """Validate coverage and alignment rules."""
    issues: List[StoryboardIssue] = []
    seen_visuals: Dict[str, List[str]] = {}
    source_policy = load_source_visual_policy()
    min_confidence = source_match_confidence_floor()

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
        if visual_intent in SOURCE_VISUAL_INTENTS and confidence is not None and confidence < min_confidence:
            issues.append(StoryboardIssue("warning", segment_id, "Source match confidence is low."))

        if (
            is_analogy(narration.lower())
            and visual_intent != "analogy_art"
            and not source_policy.get("source_first")
            and not is_evidence_worthy(narration, segment.get("segment_type", ""))
        ):
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
    confirmation = storyboard.get("visual_confirmation", {})
    logger.info(f"Storyboard: {len(storyboard.get('segments', []))} segments, intents={counts}")
    if confirmation:
        logger.info(
            "Visual confirmation: "
            f"{confirmation.get('confirmed_count', 0)}/{confirmation.get('required_count', 0)} "
            f"claims confirmed ({confirmation.get('confirmation_ratio', 1.0)})"
        )
    logger.info(f"Storyboard validation: {errors} errors, {warnings} warnings")
