"""LLM-backed visual planning for TrendForge storyboards."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import openai
import yaml
from loguru import logger


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
APPROX_CHARS_PER_TOKEN = 4
VALID_VISUAL_INTENTS = {"source_screenshot", "source_card", "concept_art", "analogy_art", "brand_or_concept"}


def load_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def load_planner_config() -> Dict[str, Any]:
    return load_config().get("visuals", {}).get("visual_planner", {})


def visual_planner_enabled(analysis: Optional[Dict[str, Any]] = None) -> bool:
    cfg = load_planner_config()
    if os.environ.get("TRENDFORGE_DISABLE_LLM_VISUAL_PLANNER") == "1":
        return False
    if not cfg.get("enabled", False):
        return False
    if cfg.get("require_analysis", True) and not analysis:
        return False
    return True


def generate_visual_plan(
    script: Dict[str, Any],
    evidence: List[Dict[str, Any]],
    analysis: Optional[Dict[str, Any]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Ask the configured local LLM for a structured visual beat plan."""
    cfg = load_config()
    planner_cfg = cfg.get("visuals", {}).get("visual_planner", {})
    opencode_cfg = cfg.get("opencode", {})
    model = planner_cfg.get("model") or opencode_cfg.get("model")
    if not model:
        logger.warning("LLM visual planner skipped: no model configured")
        return None

    prompt = build_visual_plan_prompt(script, evidence, analysis, planner_cfg)
    client = openai.OpenAI(
        base_url=opencode_cfg.get("base_url", "http://localhost:11434/v1"),
        api_key=opencode_cfg.get("api_key", "local"),
        timeout=float(planner_cfg.get("timeout", 90)),
    )

    options: Dict[str, Any] = {}
    max_tokens = planner_cfg.get("max_tokens") or opencode_cfg.get("max_tokens")
    if max_tokens and int(max_tokens) > 0:
        options["max_tokens"] = int(max_tokens)
    if planner_cfg.get("json_response_format", True):
        options["response_format"] = {"type": "json_object"}

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": visual_planner_system_prompt(),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=float(planner_cfg.get("temperature", 0.15)),
            **options,
        )
    except Exception as exc:
        if "response_format" not in options or not json_mode_rejected(exc):
            logger.warning(f"LLM visual planner failed; using rule-based plan: {exc}")
            return None
        logger.warning(f"LLM visual planner JSON mode rejected; retrying without response_format: {exc}")
        options.pop("response_format", None)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": visual_planner_system_prompt()},
                    {"role": "user", "content": prompt},
                ],
                temperature=float(planner_cfg.get("temperature", 0.15)),
                **options,
            )
        except Exception as retry_exc:
            logger.warning(f"LLM visual planner failed; using rule-based plan: {retry_exc}")
            return None

    text = response.choices[0].message.content or ""
    try:
        beats = parse_visual_plan_response(text)
    except ValueError as exc:
        logger.warning(f"LLM visual planner returned invalid JSON; using rule-based plan: {exc}")
        return None

    beats = validate_visual_plan(beats, script, planner_cfg)
    if not beats:
        logger.warning("LLM visual planner returned no usable beats; using rule-based plan")
        return None

    logger.info(f"LLM visual planner produced {len(beats)} visual beats")
    return beats


def json_mode_rejected(exc: Exception) -> bool:
    """Only retry errors that specifically reject response_format/JSON mode."""
    message = str(exc).lower()
    return any(
        marker in message
        for marker in ("response_format", "json mode", "json_object", "unsupported parameter")
    )


def visual_planner_system_prompt() -> str:
    return (
        "You are TrendForge's visual director. Create a convincing documentary visual plan. "
        "Use evidence screenshots/source cards for facts, named entities, dates, statistics, "
        "official claims, reports, studies, and concrete business actions. Use AI art for ideas, "
        "context, synthesis, mood, analogies, and metaphors. Every new concrete claim needs a "
        "specific evidence_need and source_query. Never invent sources. Return only JSON."
    )


def build_visual_plan_prompt(
    script: Dict[str, Any],
    evidence: List[Dict[str, Any]],
    analysis: Optional[Dict[str, Any]],
    planner_cfg: Dict[str, Any],
) -> str:
    max_narration_chars = int(planner_cfg.get("max_narration_chars", 18000))
    max_evidence_items = int(planner_cfg.get("max_evidence_items", 24))

    script_context = format_script_for_planner(script)
    script_context = trim_to_chars(script_context, max_narration_chars)
    evidence_context = format_evidence_for_planner(evidence[:max_evidence_items])
    analysis_context = json.dumps(analysis or {}, ensure_ascii=False)[:5000]

    return f"""TOPIC: {script.get('topic', '')}
TITLE: {script.get('title', '')}

NARRATION SEGMENTS
{script_context}

AVAILABLE EVIDENCE SOURCES
{evidence_context}

ANALYSIS CONTEXT
{analysis_context}

Return valid JSON with this exact shape:
{{
  "beats": [
    {{
      "parent_segment_index": 0,
      "sentence_index": 0,
      "narration": "exact sentence or short narration span this visual supports",
      "visual_intent": "source_screenshot | source_card | concept_art | analogy_art | brand_or_concept",
      "visual_role": "evidence | context | metaphor | contrast | synthesis",
      "evidence_need": "what must be proven if this is an evidence visual",
      "source_query": "keywords that should match the best source, or empty",
      "visual_prompt": "source title target or concise visual objective",
      "image_prompt": "AI art prompt when visual_intent is art, no text in image",
      "reason": "short reason for this visual choice"
    }}
  ]
}}

Planning rules:
- Create a new beat for each new concrete claim, named entity, statistic, date, report, study, policy, product, company, or quote-like claim.
- Use source_screenshot for verifiable proof beats when a source should be shown.
- Use source_card when a source is important but screenshot quality may be poor.
- Use analogy_art for analogies and metaphorical explanations.
- Use concept_art for abstract ideas, transitions, context, and synthesis.
- Use brand_or_concept for opening and closing brand moments.
- Keep narration copied from the script, not rewritten.
- Split dense narration into multiple beats when it introduces multiple claims, names, statistics, products, policies, studies, or actions.
- Prefer visible confirmation over decoration: the viewer should see proof shortly after each factual claim is spoken.
- Do not use concept_art for a concrete factual claim just because the claim is broad; use source_screenshot/source_card when evidence exists.
- Prefer fewer high-value visuals over a visual for every filler phrase.
- Do not choose an evidence visual unless the available evidence list plausibly supports it."""


def format_script_for_planner(script: Dict[str, Any]) -> str:
    lines: List[str] = []
    for index, segment in enumerate(script.get("segments", [])):
        text = normalize_text(segment.get("text", ""))
        segment_type = segment.get("type", "fact")
        role = segment.get("visual_role_hint", "")
        lines.append(f"[segment {index}] type={segment_type} role={role}")
        for sentence_index, sentence in enumerate(split_into_sentences(text) or [text]):
            lines.append(f"  ({sentence_index}) {sentence}")
    return "\n".join(lines)


def format_evidence_for_planner(evidence: List[Dict[str, Any]]) -> str:
    if not evidence:
        return "No evidence sources are available. Use art unless a source card can be validated later."

    lines = []
    for item in evidence:
        lines.append(
            "\n".join(
                [
                    f"- id: {item.get('id', '')}",
                    f"  title: {trim_to_chars(item.get('title', ''), 180)}",
                    f"  source: {item.get('source_name') or item.get('source', '')}",
                    f"  domain: {item.get('domain', '')}",
                    f"  type: {item.get('source_type', '')}",
                    f"  excerpt: {trim_to_chars(item.get('text_excerpt', ''), 320)}",
                ]
            )
        )
    return "\n".join(lines)


def parse_visual_plan_response(text: str) -> List[Dict[str, Any]]:
    candidate = strip_json_wrappers(text)
    attempts = [candidate, re.sub(r",\s*([}\]])", r"\1", candidate)]
    for attempt in attempts:
        try:
            parsed = json.loads(attempt)
            if isinstance(parsed, dict):
                beats = parsed.get("beats", [])
            else:
                beats = parsed
            if isinstance(beats, list):
                return [beat for beat in beats if isinstance(beat, dict)]
        except json.JSONDecodeError:
            continue
    raise ValueError("response does not contain a JSON beats array")


def validate_visual_plan(
    beats: List[Dict[str, Any]],
    script: Dict[str, Any],
    planner_cfg: Dict[str, Any],
) -> List[Dict[str, Any]]:
    segments = script.get("segments", [])
    if not segments:
        return []
    max_beats = int(planner_cfg.get("max_beats", 90))
    valid: List[Dict[str, Any]] = []

    for raw in beats[:max_beats]:
        try:
            parent_index = int(raw.get("parent_segment_index", raw.get("segment_index", 0)))
        except (TypeError, ValueError):
            continue
        if parent_index < 0 or parent_index >= len(segments):
            continue

        narration = normalize_text(raw.get("narration", ""))
        if not narration:
            narration = normalize_text(segments[parent_index].get("text", ""))
        if not narration:
            continue

        beat = dict(raw)
        beat["parent_segment_index"] = parent_index
        try:
            beat["sentence_index"] = int(beat.get("sentence_index", 0))
        except (TypeError, ValueError):
            beat["sentence_index"] = 0
        beat["narration"] = narration
        beat["visual_intent"] = normalize_visual_intent(beat.get("visual_intent"))
        beat["visual_role"] = normalize_text(beat.get("visual_role", "")) or role_for_intent(beat["visual_intent"])
        beat["evidence_need"] = normalize_text(beat.get("evidence_need", ""))
        beat["source_query"] = normalize_text(beat.get("source_query", ""))
        beat["visual_prompt"] = normalize_text(beat.get("visual_prompt", "")) or narration[:160]
        beat["image_prompt"] = normalize_text(beat.get("image_prompt", ""))
        beat["reason"] = normalize_text(beat.get("reason", "")) or "LLM visual plan"
        valid.append(beat)

    return valid


def normalize_visual_intent(value: Any) -> str:
    intent = normalize_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "screenshot": "source_screenshot",
        "source": "source_screenshot",
        "evidence": "source_screenshot",
        "evidence_screenshot": "source_screenshot",
        "card": "source_card",
        "sourcecard": "source_card",
        "ai_art": "concept_art",
        "art": "concept_art",
        "idea_art": "concept_art",
        "metaphor": "analogy_art",
        "analogy": "analogy_art",
        "brand": "brand_or_concept",
        "opening": "brand_or_concept",
        "closing": "brand_or_concept",
    }
    intent = aliases.get(intent, intent)
    if intent not in VALID_VISUAL_INTENTS:
        return "concept_art"
    return intent


def role_for_intent(intent: str) -> str:
    if intent in {"source_screenshot", "source_card"}:
        return "evidence"
    if intent == "analogy_art":
        return "metaphor"
    if intent == "brand_or_concept":
        return "context"
    return "context"


def split_into_sentences(text: str) -> List[str]:
    text = normalize_text(text)
    if not text:
        return []
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", text)
        if sentence.strip() and len(sentence.strip().split()) >= 3
    ]


def strip_json_wrappers(text: str) -> str:
    text = str(text or "").strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        return text[first:last + 1]
    return text


def trim_to_chars(value: Any, limit: int) -> str:
    text = normalize_text(value)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" .,") + "."


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
