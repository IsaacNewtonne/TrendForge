"""Deterministic proof policy for storyboard visuals.

The LLM can propose a good visual rhythm, but source-backed claims still need a
hard gate. This module marks concrete claims that should be visually confirmed,
promotes them to source visuals when evidence exists, and scores the final plan.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

import yaml


SOURCE_VISUAL_INTENTS = {"source_card", "source_screenshot"}
ART_VISUAL_INTENTS = {"analogy_art", "concept_art", "brand_or_concept"}
DEFAULT_MIN_SOURCE_MATCH_CONFIDENCE = 0.33
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
    r"\baccording to\b",
    r"\bdata from\b",
    r"\breport\b",
    r"\bstudy\b",
    r"\bsurvey\b",
    r"\bpoll\b",
    r"\bfiling\b",
    r"\bpress release\b",
    r"\bpaper\b",
    r"\bsource\b",
    r"\bheadline\b",
    r"\barticle\b",
]

METRIC_PATTERNS = [
    r"\b\d+(?:\.\d+)?\s?(?:%|percent|million|billion|trillion|x)\b",
    r"\$\s?\d+",
    r"\b20\d{2}\b",
]

OFFICIAL_ACTION_PATTERNS = [
    r"\b(?:announced|launched|released|reported|filed|warned|approved|investigated|sued|acquired|invested|partnered|disclosed|published|banned|ordered|charged|settled|raised|expanded)\b",
    r"\b(?:company said|officials said|researchers said|analysts said|regulators said)\b",
]

KNOWN_ENTITY_PATTERNS = [
    r"\b(?:OpenAI|Microsoft|Google|Alphabet|Meta|Facebook|Apple|Amazon|Anthropic|Nvidia|Tesla|Netflix|Adobe|Oracle|IBM|Intel|AMD|GitHub|Reddit|TikTok|ByteDance|YouTube)\b",
    r"\b(?:SEC|FTC|DOJ|FDA|WHO|NIST|EU|European Union|White House|Congress|Senate|Supreme Court|United States|United Kingdom)\b",
]

NAMED_ACTION_PATTERN = re.compile(
    r"\b[A-Z][A-Za-z0-9&.-]{2,}(?:\s+[A-Z][A-Za-z0-9&.-]{2,}){0,3}\s+"
    r"(?:said|announced|launched|released|reported|filed|warned|approved|investigated|sued|acquired|invested|partnered|disclosed|published|raised|expanded)\b"
)


def enforce_claim_confirmation(storyboard: Dict[str, Any]) -> Dict[str, Any]:
    """Promote visually unconfirmed concrete claims to source visuals."""
    evidence_available = bool(storyboard.get("evidence"))
    for segment in storyboard.get("segments", []):
        required = confirmation_required(segment)
        segment["confirmation_required"] = required
        segment["confirmation_signals"] = detect_confirmation_signals(segment.get("narration", ""))

        if not required:
            continue

        if segment.get("visual_intent") in SOURCE_VISUAL_INTENTS:
            ensure_claim_fields(segment)
            continue

        if not evidence_available:
            segment.setdefault("warnings", []).append(
                "Concrete claim needs visual proof, but no evidence sources are available."
            )
            continue

        previous_intent = segment.get("visual_intent")
        segment["visual_intent"] = "source_screenshot"
        segment["required_visual"] = "screenshot"
        ensure_claim_fields(segment)
        segment["visual_plan_reason"] = confirmation_reason(segment, previous_intent)

    return storyboard


def score_visual_confirmation(storyboard: Dict[str, Any]) -> Dict[str, Any]:
    """Score how many proof-required beats are backed by screenshot visuals."""
    required_segments = [
        segment for segment in storyboard.get("segments", [])
        if segment.get("confirmation_required") and segment_requires_screenshot_scoring(segment)
    ]
    match_floor = source_match_confidence_floor()
    confirmed_segments = [
        segment for segment in required_segments if segment_confirmed(segment, min_confidence=match_floor)
    ]
    unsupported_segments = [
        segment for segment in required_segments
        if segment.get("id") not in {item.get("id") for item in confirmed_segments}
    ]

    for segment in unsupported_segments:
        segment.setdefault("warnings", []).append(
            "Needs stronger visual proof for this narrated claim."
        )

    required_count = len(required_segments)
    confirmed_count = len(confirmed_segments)
    return {
        "required_count": required_count,
        "confirmed_count": confirmed_count,
        "unsupported_count": len(unsupported_segments),
        "confirmation_ratio": round(confirmed_count / required_count, 3) if required_count else 1.0,
        "unsupported_segments": [
            {
                "id": segment.get("id"),
                "narration": segment.get("narration", ""),
                "visual_intent": segment.get("visual_intent", ""),
                "source_url": segment.get("source_url"),
                "evidence_match_confidence": segment.get("evidence_match_confidence"),
            }
            for segment in unsupported_segments
        ],
    }


def confirmation_required(segment: Dict[str, Any]) -> bool:
    """Return true when a narration beat should be backed by visible evidence."""
    text = normalize_text(segment.get("narration", ""))
    if not text:
        return False

    lower = text.lower()
    signals = detect_confirmation_signals(text)
    analogy_only = is_analogy(lower) and not any(
        signal in signals
        for signal in {"source_reference", "metric_or_date", "official_action", "known_entity", "named_action"}
    )
    if analogy_only:
        return False

    if signals:
        return True

    if str(segment.get("visual_role_hint", "")).lower() == "evidence":
        return True

    if segment.get("segment_type") == "source_claim":
        return True

    return False


def detect_confirmation_signals(text: Any) -> List[str]:
    """Return deterministic reasons a narration beat needs visual proof."""
    value = normalize_text(text)
    lower = value.lower()
    signals: List[str] = []

    if any(re.search(pattern, lower) for pattern in SOURCE_REFERENCE_PATTERNS):
        signals.append("source_reference")
    if any(re.search(pattern, lower) for pattern in METRIC_PATTERNS):
        signals.append("metric_or_date")
    if any(re.search(pattern, lower) for pattern in OFFICIAL_ACTION_PATTERNS):
        signals.append("official_action")
    if any(re.search(pattern, value) for pattern in KNOWN_ENTITY_PATTERNS):
        signals.append("known_entity")
    if NAMED_ACTION_PATTERN.search(value):
        signals.append("named_action")

    return signals


def segment_confirmed(
    segment: Dict[str, Any],
    min_confidence: float = DEFAULT_MIN_SOURCE_MATCH_CONFIDENCE,
) -> bool:
    if not segment_requires_screenshot_scoring(segment):
        return False
    if not segment.get("source_url"):
        return False
    try:
        confidence = float(segment.get("evidence_match_confidence"))
    except (TypeError, ValueError):
        return False
    return confidence >= min_confidence


def segment_requires_screenshot_scoring(segment: Dict[str, Any]) -> bool:
    """Only score proof for beats that ended up with an actual screenshot visual."""
    evidence = segment.get("source_visual_evidence") or {}
    visual_kind = str(evidence.get("visual_kind") or "").strip().lower()
    if visual_kind:
        return visual_kind == "source_screenshot"
    return segment.get("visual_intent") == "source_screenshot"


def source_match_confidence_floor() -> float:
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            value = (cfg.get("source_visuals") or {}).get(
                "min_source_match_confidence",
                DEFAULT_MIN_SOURCE_MATCH_CONFIDENCE,
            )
            return max(0.0, min(1.0, float(value)))
    except Exception:
        pass
    return DEFAULT_MIN_SOURCE_MATCH_CONFIDENCE


def ensure_claim_fields(segment: Dict[str, Any]) -> None:
    narration = normalize_text(segment.get("narration", ""))
    if not segment.get("claim"):
        segment["claim"] = narration
    if not segment.get("evidence_need"):
        segment["evidence_need"] = narration
    if not segment.get("source_query"):
        segment["source_query"] = source_query_for_claim(narration)


def source_query_for_claim(text: str) -> str:
    words = normalize_text(text).split()
    return " ".join(words[:18])


def confirmation_reason(segment: Dict[str, Any], previous_intent: Any) -> str:
    signals = ", ".join(segment.get("confirmation_signals") or ["claim"])
    return (
        f"Proof gate promoted {previous_intent or 'art'} to source screenshot "
        f"because this beat needs visual confirmation: {signals}."
    )


def is_analogy(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in ANALOGY_PATTERNS)


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
