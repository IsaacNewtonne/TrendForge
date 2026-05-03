"""Semantic matching between narration segments, evidence, and visual roles."""

from __future__ import annotations

import re
from typing import Any, Dict, List


SOURCE_INTENTS = {"source_card", "source_screenshot", "chart_visual", "product_visual", "social_post_visual", "article_visual"}
MAX_SOURCE_CANDIDATES = 4
CONFIDENT_ALIGNMENT_FLOOR = 0.26
VISUAL_EVIDENCE_MIN_TOKENS = 5
VISUAL_EVIDENCE_CONFIRMATION_THRESHOLD = 0.35
TOKEN_NORMALIZATIONS = {
    "artificial": "ai",
    "intelligence": "ai",
    "machine": "ml",
    "learning": "ml",
    "u.s.": "us",
    "u.s": "us",
    "usa": "us",
    "american": "us",
    "europe": "eu",
    "european": "eu",
    "union": "eu",
    "regulatory": "regulation",
    "regulator": "regulation",
    "regulators": "regulation",
    "announces": "announce",
    "announced": "announce",
    "announcing": "announce",
    "launches": "launch",
    "launched": "launch",
    "launching": "launch",
    "releases": "release",
    "released": "release",
    "releasing": "release",
    "reports": "report",
    "reported": "report",
    "reporting": "report",
}


def enrich_storyboard_matches(storyboard: Dict[str, Any]) -> Dict[str, Any]:
    """Attach best evidence and motion metadata to every storyboard segment."""
    evidence = storyboard.get("evidence", [])
    used: set[str] = set()
    used_domains: dict[str, int] = {}

    for segment in storyboard.get("segments", []):
        visual_intent = segment.get("visual_intent")
        narration = segment_match_text(segment)
        visual_role = infer_visual_role(segment)
        segment["visual_role"] = visual_role
        segment["motion_hint"] = infer_motion_hint(segment)

        if visual_intent in SOURCE_INTENTS and evidence:
            matches = ranked_evidence_matches(narration, evidence, used, used_domains)
            if matches:
                item, confidence, reason = matches[0]
                used.add(item.get("id", ""))
                domain = normalize_domain(item.get("domain", ""))
                used_domains[domain] = used_domains.get(domain, 0) + 1
                attach_evidence(segment, item, confidence, reason)
                segment["source_candidates"] = [
                    evidence_candidate(item, score, match_reason)
                    for item, score, match_reason in matches[:MAX_SOURCE_CANDIDATES]
                ]
            else:
                segment["evidence_match_confidence"] = 0.0
                segment["match_reason"] = "No usable evidence candidate found."
                segment["source_candidates"] = []
        else:
            segment["evidence_match_confidence"] = None
            segment["match_reason"] = f"{visual_role} visual does not require source evidence."

    return storyboard


def segment_match_text(segment: Dict[str, Any]) -> str:
    """Build source-matching text from narration plus planner evidence hints."""
    return " ".join(
        str(segment.get(key, ""))
        for key in ("narration", "claim", "evidence_need", "source_query")
        if segment.get(key)
    )


def best_evidence_match(
    narration: str,
    evidence: List[Dict[str, Any]],
    used: set[str],
    used_domains: Dict[str, int] | None = None,
) -> tuple[Dict[str, Any], float, str] | None:
    matches = ranked_evidence_matches(narration, evidence, used, used_domains)
    return matches[0] if matches else None


def ranked_evidence_matches(
    narration: str,
    evidence: List[Dict[str, Any]],
    used: set[str],
    used_domains: Dict[str, int] | None = None,
) -> List[tuple[Dict[str, Any], float, str]]:
    """Return ranked source candidates so screenshot capture can try backups."""
    scored = []
    narration_tokens = tokenize(narration)
    narration_entities = extract_named_entities(narration)
    narration_years = extract_years(narration)
    narration_numbers = extract_significant_numbers(narration)
    unused_evidence = [item for item in evidence if item.get("id", "") not in used]
    candidates = unused_evidence or evidence
    used_domains = used_domains or {}

    for item in candidates:
        haystack = " ".join(
            str(item.get(key, ""))
            for key in ("title", "source_name", "source", "text_excerpt", "domain", "source_type")
        )
        item_tokens = tokenize(haystack)
        item_entities = extract_named_entities(haystack)
        item_years = extract_years(haystack)
        item_numbers = extract_significant_numbers(haystack)
        if not item_tokens:
            continue
        if not evidence_context_fits_narration(item, narration_tokens):
            continue

        overlap = narration_tokens & item_tokens
        entity_overlap = narration_entities & item_entities
        year_overlap = narration_years & item_years
        number_overlap = narration_numbers & item_numbers
        union = narration_tokens | item_tokens
        jaccard = len(overlap) / max(1, len(union))
        recall = len(overlap) / max(1, len(narration_tokens))
        precision = len(overlap) / max(1, len(item_tokens))
        title_overlap = len(narration_tokens & tokenize(item.get("title", ""))) * 0.035
        domain = normalize_domain(item.get("domain", ""))
        reuse_penalty = 0.45 if item.get("id") in used else 0.0
        domain_reuse_penalty = min(0.72, used_domains.get(domain, 0) * 0.18)
        source_bonus = 0.05 if item.get("source_type") == "specialist" else 0.0
        quality_bonus = evidence_quality_bonus(item)
        entity_bonus = min(0.24, len(entity_overlap) * 0.12)
        year_bonus = min(0.18, len(year_overlap) * 0.09)
        number_bonus = min(0.12, len(number_overlap) * 0.06)
        if not overlap and not entity_overlap and not year_overlap:
            score = 0.0
        else:
            score = min(
                1.0,
                jaccard * 1.7
                + recall * 0.95
                + precision * 0.35
                + title_overlap
                + source_bonus
                + quality_bonus
                + entity_bonus
                + year_bonus
                + number_bonus
                - reuse_penalty
                - domain_reuse_penalty,
            )
            if len(overlap) >= 3 and (entity_overlap or year_overlap or number_overlap):
                score = max(score, CONFIDENT_ALIGNMENT_FLOOR)
        scored.append((score, item, overlap))

    if not scored:
        return []

    scored.sort(key=lambda row: row[0], reverse=True)
    ranked: List[tuple[Dict[str, Any], float, str]] = []
    for score, item, overlap in scored[:MAX_SOURCE_CANDIDATES]:
        reason_bits = []
        if overlap:
            reason_bits.append(f"Matched {len(overlap)} shared terms")
        else:
            reason_bits.append("Best available source fallback; low lexical overlap")
        entity_overlap = extract_named_entities(narration) & extract_named_entities(
            " ".join(
                str(item.get(key, ""))
                for key in ("title", "source_name", "source", "text_excerpt", "domain", "source_type")
            )
        )
        if entity_overlap:
            reason_bits.append(f"{len(entity_overlap)} named-entity matches")
        year_overlap = extract_years(narration) & extract_years(
            " ".join(
                str(item.get(key, ""))
                for key in ("title", "source_name", "source", "text_excerpt", "domain", "source_type")
            )
        )
        if year_overlap:
            reason_bits.append(f"{len(year_overlap)} year matches")
        reason = "; ".join(reason_bits)
        if item.get("id", "") in used:
            reason += "; source evidence pool exhausted, reuse required"
        domain = normalize_domain(item.get("domain", ""))
        if used_domains.get(domain, 0):
            reason += f"; domain reuse penalty applied ({domain})"
        ranked.append((item, round(max(0.0, score), 3), reason))
    return ranked


def evidence_context_fits_narration(item: Dict[str, Any], narration_tokens: set[str]) -> bool:
    """Reject high-quality specialist pages that are from the wrong subject area."""
    domain = normalize_domain(item.get("domain", ""))
    if domain == "pubmed.ncbi.nlm.nih.gov" or domain.endswith(".pubmed.ncbi.nlm.nih.gov"):
        health_context = {
            "health",
            "healthcare",
            "medical",
            "medicine",
            "clinical",
            "patient",
            "patients",
            "hospital",
            "disease",
            "cancer",
            "oncology",
            "drug",
            "therapy",
            "diagnosis",
            "biotech",
            "pharma",
            "tuberculosis",
            "covid",
            "sleep",
            "diet",
            "longevity",
        }
        return bool(narration_tokens & health_context)
    return True


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


def evidence_candidate(item: Dict[str, Any], confidence: float, reason: str) -> Dict[str, Any]:
    return {
        "source_id": item.get("id"),
        "source_url": item.get("url"),
        "source_title": item.get("title"),
        "source_name": item.get("source_name"),
        "source_published": item.get("published"),
        "source_excerpt": item.get("text_excerpt"),
        "source_image": item.get("image_url"),
        "source_type": item.get("source_type"),
        "source_domain": item.get("domain"),
        "evidence_match_confidence": confidence,
        "match_reason": reason,
    }


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
    tokens = set()
    for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_.-]{2,}", str(value).lower()):
        if token in stop:
            continue
        canonical = normalize_token(token)
        if canonical and canonical not in stop:
            tokens.add(canonical)
    return tokens


def normalize_token(token: str) -> str:
    value = token.strip().lower()
    if not value:
        return ""
    value = TOKEN_NORMALIZATIONS.get(value, value)
    value = value.replace(".", "").replace("_", "").replace("-", "")
    if value.endswith("ies") and len(value) > 5:
        value = value[:-3] + "y"
    elif value.endswith("ing") and len(value) > 6:
        value = value[:-3]
    elif value.endswith("ed") and len(value) > 5:
        value = value[:-2]
    elif value.endswith("es") and len(value) > 5:
        value = value[:-2]
    elif value.endswith("s") and len(value) > 5 and not value.endswith("ss"):
        value = value[:-1]
    return TOKEN_NORMALIZATIONS.get(value, value)


def extract_named_entities(value: Any) -> set[str]:
    text = str(value or "")
    entities = set()
    for match in re.findall(r"\b[A-Z]{2,}\b", text):
        entities.add(normalize_token(match))
    for match in re.findall(r"\b[A-Z][A-Za-z0-9&.-]{2,}(?:\s+[A-Z][A-Za-z0-9&.-]{2,}){0,3}\b", text):
        compact = " ".join(part for part in match.split() if part)
        if compact:
            entities.add(compact.lower())
    return {entity for entity in entities if entity}


def extract_years(value: Any) -> set[str]:
    return set(re.findall(r"\b(?:19|20)\d{2}\b", str(value or "")))


def extract_significant_numbers(value: Any) -> set[str]:
    numbers = set(re.findall(r"\b\d{2,}(?:\.\d+)?\b", str(value or "")))
    return numbers


def check_visual_evidence_support(segment: Dict[str, Any], item: Dict[str, Any]) -> tuple[bool, float]:
    """Verify that matched evidence actually contains visual support for the claim.

    Returns (has_support, support_score) where support_score is 0.0-1.0.
    A score below VISUAL_EVIDENCE_CONFIRMATION_THRESHOLD means the match is
    text-relevant but lacks visual/evidential support for the claim.
    """
    claim = segment.get("narration", "") or segment.get("claim", "") or ""
    excerpt = str(item.get("text_excerpt", "") or "").lower()
    title = str(item.get("title", "") or "").lower()

    if not excerpt or len(excerpt) < 20:
        return False, 0.0

    claim_entities = extract_named_entities(claim)
    claim_numbers = extract_significant_numbers(claim)
    excerpt_entities = extract_named_entities(excerpt + " " + title)
    excerpt_tokens = tokenize(excerpt + " " + title)

    entity_match_count = len(claim_entities & excerpt_entities)
    number_match_count = len(extract_significant_numbers(claim) & extract_significant_numbers(excerpt + " " + title))
    claim_tokens = tokenize(claim)

    if not claim_tokens:
        return True, 1.0

    token_overlap = len(claim_tokens & excerpt_tokens)
    overlap_ratio = token_overlap / max(len(claim_tokens), 1)

    entity_ratio = entity_match_count / max(len(claim_entities), 1) if claim_entities else 0
    number_ratio = number_match_count / max(len(claim_numbers), 1) if claim_numbers else 0

    support_score = min(
        1.0,
        overlap_ratio * 0.4
        + entity_ratio * 0.35
        + number_ratio * 0.25,
    )

    has_entities = bool(claim_entities)
    has_numbers = bool(claim_numbers)
    if has_entities and entity_match_count == 0:
        return False, support_score
    if has_numbers and number_match_count == 0:
        return False, support_score

    return support_score >= VISUAL_EVIDENCE_CONFIRMATION_THRESHOLD, support_score


def enrich_storyboard_matches(storyboard: Dict[str, Any]) -> Dict[str, Any]:
    """Attach best evidence and motion metadata to every storyboard segment."""
    evidence = storyboard.get("evidence", [])
    used: set[str] = set()
    used_domains: dict[str, int] = {}

    for segment in storyboard.get("segments", []):
        visual_intent = segment.get("visual_intent")
        narration = segment_match_text(segment)
        visual_role = infer_visual_role(segment)
        segment["visual_role"] = visual_role
        segment["motion_hint"] = infer_motion_hint(segment)

        if visual_intent in SOURCE_INTENTS and evidence:
            matches = ranked_evidence_matches(narration, evidence, used, used_domains)
            if matches:
                item, confidence, reason = matches[0]
                has_visual_support, support_score = check_visual_evidence_support(segment, item)

                if has_visual_support:
                    adjusted_confidence = confidence
                    visual_support_note = "visual evidence confirmed"
                else:
                    adjusted_confidence = confidence * 0.65
                    visual_support_note = f"weak visual support (score={support_score:.2f}); text match only"

                used.add(item.get("id", ""))
                domain = normalize_domain(item.get("domain", ""))
                used_domains[domain] = used_domains.get(domain, 0) + 1

                attach_evidence(segment, item, round(adjusted_confidence, 3), reason)
                segment["visual_support_score"] = round(support_score, 3)
                segment["visual_support_verified"] = has_visual_support
                segment["match_reason"] = f"{reason}; {visual_support_note}"
                segment["source_candidates"] = [
                    evidence_candidate(item, score, match_reason)
                    for item, score, match_reason in matches[:MAX_SOURCE_CANDIDATES]
                ]
            else:
                segment["evidence_match_confidence"] = 0.0
                segment["match_reason"] = "No usable evidence candidate found."
                segment["visual_support_score"] = 0.0
                segment["visual_support_verified"] = False
                segment["source_candidates"] = []
        else:
            segment["evidence_match_confidence"] = None
            segment["match_reason"] = f"{visual_role} visual does not require source evidence."

    return storyboard
