"""Semantic matching between narration segments, evidence, and visual roles."""

from __future__ import annotations

import re
from typing import Any, Dict, List


SOURCE_INTENTS = {"source_card", "source_screenshot"}


def enrich_storyboard_matches(storyboard: Dict[str, Any]) -> Dict[str, Any]:
    """Attach best evidence and motion metadata to every storyboard segment."""
    evidence = storyboard.get("evidence", [])
    used: set[str] = set()
    used_domains: dict[str, int] = {}

    for segment in storyboard.get("segments", []):
        visual_intent = segment.get("visual_intent")
        narration = segment.get("narration", "")
        visual_role = infer_visual_role(segment)
        segment["visual_role"] = visual_role
        segment["motion_hint"] = infer_motion_hint(segment)

        if visual_intent in SOURCE_INTENTS and evidence:
            match = best_evidence_match(narration, evidence, used, used_domains)
            if match:
                item, confidence, reason = match
                used.add(item.get("id", ""))
                domain = normalize_domain(item.get("domain", ""))
                used_domains[domain] = used_domains.get(domain, 0) + 1
                attach_evidence(segment, item, confidence, reason)
            else:
                segment["evidence_match_confidence"] = 0.0
                segment["match_reason"] = "No usable evidence candidate found."
        else:
            segment["evidence_match_confidence"] = None
            segment["match_reason"] = f"{visual_role} visual does not require source evidence."

    return storyboard


def best_evidence_match(
    narration: str,
    evidence: List[Dict[str, Any]],
    used: set[str],
    used_domains: Dict[str, int] | None = None,
) -> tuple[Dict[str, Any], float, str] | None:
    scored = []
    narration_tokens = tokenize(narration)
    unused_evidence = [item for item in evidence if item.get("id", "") not in used]
    candidates = unused_evidence or evidence
    used_domains = used_domains or {}

    for item in candidates:
        haystack = " ".join(
            str(item.get(key, ""))
            for key in ("title", "source_name", "source", "text_excerpt", "domain", "source_type")
        )
        item_tokens = tokenize(haystack)
        if not item_tokens:
            continue

        overlap = narration_tokens & item_tokens
        union = narration_tokens | item_tokens
        jaccard = len(overlap) / max(1, len(union))
        title_overlap = len(narration_tokens & tokenize(item.get("title", ""))) * 0.035
        domain = normalize_domain(item.get("domain", ""))
        reuse_penalty = 0.45 if item.get("id") in used else 0.0
        domain_reuse_penalty = min(0.72, used_domains.get(domain, 0) * 0.18)
        source_bonus = 0.05 if item.get("source_type") == "specialist" else 0.0
        quality_bonus = evidence_quality_bonus(item)
        score = min(
            1.0,
            jaccard * 2.8
            + title_overlap
            + source_bonus
            + quality_bonus
            - reuse_penalty
            - domain_reuse_penalty,
        )
        scored.append((score, item, overlap))

    if not scored:
        return None

    scored.sort(key=lambda row: row[0], reverse=True)
    score, item, overlap = scored[0]
    reason = (
        f"Matched {len(overlap)} shared terms"
        if overlap
        else "Best available source fallback; low lexical overlap"
    )
    if item.get("id", "") in used:
        reason += "; source evidence pool exhausted, reuse required"
    domain = normalize_domain(item.get("domain", ""))
    if used_domains.get(domain, 0):
        reason += f"; domain reuse penalty applied ({domain})"
    return item, round(max(0.0, score), 3), reason


def evidence_quality_bonus(item: Dict[str, Any]) -> float:
    try:
        source_quality = float(item.get("source_quality_score", 50))
    except (TypeError, ValueError):
        source_quality = 50
    domain = str(item.get("domain", "")).lower()
    url = str(item.get("url", "")).lower()
    bonus = (source_quality - 50) / 200
    if "news.google.com/rss/articles" in url or "news.google.com" in domain:
        bonus -= 0.35
    return max(-0.35, min(0.25, bonus))


def normalize_domain(value: Any) -> str:
    return str(value or "").lower().replace("www.", "").strip()


def attach_evidence(segment: Dict[str, Any], item: Dict[str, Any], confidence: float, reason: str):
    segment["source_id"] = item.get("id")
    segment["source_url"] = item.get("url")
    segment["source_title"] = item.get("title")
    segment["source_name"] = item.get("source_name")
    segment["source_published"] = item.get("published")
    segment["source_excerpt"] = item.get("text_excerpt")
    segment["source_image"] = item.get("image_url")
    segment["source_type"] = item.get("source_type")
    segment["source_domain"] = item.get("domain")
    segment["evidence_match_confidence"] = confidence
    segment["match_reason"] = reason
    if item.get("title"):
        segment["visual_prompt"] = item.get("title")


def infer_visual_role(segment: Dict[str, Any]) -> str:
    if segment.get("visual_role_hint"):
        return str(segment.get("visual_role_hint"))

    visual_intent = segment.get("visual_intent")
    seg_type = segment.get("segment_type")
    narration = str(segment.get("narration", "")).lower()

    if visual_intent in SOURCE_INTENTS:
        return "evidence"
    if "imagine" in narration or "it's like" in narration or "think of" in narration:
        return "metaphor"
    if seg_type == "opinion":
        return "contrast"
    if seg_type == "verdict":
        return "synthesis"
    if seg_type == "hook":
        return "context"
    return "context"


def infer_motion_hint(segment: Dict[str, Any]) -> str:
    role = infer_visual_role(segment)
    intent = segment.get("visual_intent")
    if intent in SOURCE_INTENTS:
        return "source_push_in"
    if role == "metaphor":
        return "slow_drift"
    if role == "contrast":
        return "pan_left"
    if role == "synthesis":
        return "slow_pull_back"
    return "slow_push_in"


def tokenize(value: Any) -> set[str]:
    stop = {
        "the", "and", "that", "this", "with", "from", "into", "about", "what",
        "when", "where", "which", "would", "could", "should", "there", "their",
        "because", "while", "have", "has", "had", "for", "are", "was", "were",
    }
    return {
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", str(value).lower())
        if token not in stop
    }
