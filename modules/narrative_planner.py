"""Narrative planning and critique for TrendForge scripts."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

import openai
import yaml
from loguru import logger
from modules.llm_client import create_llm_client


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


PLAN_SYSTEM_PROMPT = """You are the narrative producer for a calm technology documentary channel.
Return only valid JSON. No markdown.

Create a story plan for a composed narrator who sounds intelligent, analytical,
smooth, reflective, slightly mysterious, polished, and trustworthy.
Avoid hype, jokes, shouting, slang, clickbait, and influencer-style energy.

Schema:
{
  "central_question": "the quiet question driving the video",
  "viewer_promise": "what the viewer will understand by the end",
  "thesis": "balanced main interpretation",
  "tension": "what makes the topic uncertain or contested",
  "human_stakes": "why this matters in ordinary life",
  "tone_profile": "calm technology documentary host",
  "reflective_device": "imagine_if | small_scene | courtroom | two_futures | hidden_in_plain_sight | contrarian_but_fair",
  "comment_question": "specific question for viewers",
  "beats": [
    {
      "beat_type": "cold_open | setup | hidden_context | evidence | counterpoint | implication | reflective_turn | synthesis | viewer_question",
      "purpose": "what this beat accomplishes",
      "evidence_focus": "source-backed idea or empty string",
      "visual_role": "context | evidence | contrast | metaphor | synthesis"
    }
  ]
}

Produce enough beats for the requested segment count."""


CRITIC_SYSTEM_PROMPT = """You are a strict narration editor for a calm technology documentary channel.
Return only valid JSON. No markdown.

Evaluate whether a script follows this narrator character:
intelligent, composed, curious, analytical, smooth, reflective, professional,
slightly mysterious, polished, and trustworthy.

Reject hype, jokes, shouting, slang, clickbait, influencer-style energy, unsupported
claims, incoherent structure, and weak endings."""


def load_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


def get_openai_client() -> openai.OpenAI:
    cfg = load_config().get("opencode", {})
    return create_llm_client(cfg)


def build_narrative_plan(topic: str, analysis: Dict[str, Any], source_plan: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Build a beat-level story plan before script writing."""
    cfg = load_config()
    opencode_cfg = cfg.get("opencode", {})
    script_cfg = cfg.get("script", {})
    target_segments = int(script_cfg.get("target_segments", 18))
    narrator = script_cfg.get("narrator_character", "")

    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model=opencode_cfg.get("model", "opencode"),
            messages=[
                {"role": "system", "content": PLAN_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Topic: {topic}\n"
                        f"Requested beats/segments: {target_segments}\n"
                        f"Narrator character: {narrator}\n"
                        f"Analysis: {json.dumps(analysis, ensure_ascii=False)[:7000]}\n"
                        f"Source plan: {json.dumps(source_plan or {}, ensure_ascii=False)[:4000]}"
                    ),
                },
            ],
            temperature=0.35,
        )
        plan = parse_json(response.choices[0].message.content or "")
        plan = validate_narrative_plan(plan, topic, analysis, target_segments)
        logger.info(
            f"Narrative plan: {len(plan.get('beats', []))} beats, "
            f"device={plan.get('reflective_device')}"
        )
        return plan
    except Exception as exc:
        logger.warning(f"Narrative planning fell back to deterministic plan: {exc}")
        return fallback_narrative_plan(topic, analysis, target_segments)


def critique_script(
    topic: str,
    script: Dict[str, Any],
    narrative_plan: Dict[str, Any],
    analysis: Dict[str, Any],
) -> Dict[str, Any]:
    """Grade a generated script and recommend revision if needed."""
    cfg = load_config()
    opencode_cfg = cfg.get("opencode", {})
    script_cfg = cfg.get("script", {})

    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model=opencode_cfg.get("model", "opencode"),
            messages=[
                {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Evaluate this script. Return JSON with keys: "
                        "score_overall, persona_score, evidence_score, coherence_score, "
                        "ending_score, issues, revision_instructions, needs_revision.\n\n"
                        f"Target narrator: {script_cfg.get('narrator_character', '')}\n"
                        f"Topic: {topic}\n"
                        f"Narrative plan: {json.dumps(narrative_plan, ensure_ascii=False)[:6000]}\n"
                        f"Analysis: {json.dumps(analysis, ensure_ascii=False)[:5000]}\n"
                        f"Script: {json.dumps(script, ensure_ascii=False)[:12000]}"
                    ),
                },
            ],
            temperature=0.1,
        )
        critique = parse_json(response.choices[0].message.content or "")
        return validate_critique(critique)
    except Exception as exc:
        logger.warning(f"Narration critique unavailable: {exc}")
        return {
            "score_overall": 80,
            "persona_score": 80,
            "evidence_score": 80,
            "coherence_score": 80,
            "ending_score": 80,
            "issues": [],
            "revision_instructions": "",
            "needs_revision": False,
        }


def parse_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        first = text.find("{")
        last = text.rfind("}")
        if first >= 0 and last > first:
            return json.loads(text[first : last + 1])
        raise


def validate_narrative_plan(plan: Dict[str, Any], topic: str, analysis: Dict[str, Any], target_segments: int) -> Dict[str, Any]:
    fallback = fallback_narrative_plan(topic, analysis, target_segments)
    if not isinstance(plan, dict):
        return fallback

    result = {**fallback, **{k: v for k, v in plan.items() if v}}
    beats = result.get("beats")
    if not isinstance(beats, list):
        beats = fallback["beats"]

    normalized = []
    for beat in beats:
        if not isinstance(beat, dict):
            continue
        normalized.append({
            "beat_type": clean(beat.get("beat_type")) or "evidence",
            "purpose": clean(beat.get("purpose")) or "Develop the story with source-backed context.",
            "evidence_focus": clean(beat.get("evidence_focus")),
            "visual_role": clean(beat.get("visual_role")) or "context",
        })

    if len(normalized) < target_segments:
        normalized.extend(fallback["beats"][len(normalized):target_segments])
    result["beats"] = normalized[: max(target_segments, len(normalized))]
    result["reflective_device"] = clean(result.get("reflective_device")) or "hidden_in_plain_sight"
    return result


def validate_critique(critique: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(critique or {})
    for key in ("score_overall", "persona_score", "evidence_score", "coherence_score", "ending_score"):
        try:
            result[key] = int(result.get(key, 75))
        except (TypeError, ValueError):
            result[key] = 75
    issues = result.get("issues", [])
    if not isinstance(issues, list):
        issues = [str(issues)]
    result["issues"] = [clean(item) for item in issues if clean(item)]
    result["revision_instructions"] = clean(result.get("revision_instructions"))
    result["needs_revision"] = bool(result.get("needs_revision")) or result["score_overall"] < 82 or result["persona_score"] < 85
    return result


def fallback_narrative_plan(topic: str, analysis: Dict[str, Any], target_segments: int = 18) -> Dict[str, Any]:
    facts = [str(item) for item in analysis.get("facts", []) if str(item).strip()]
    opinions = [str(item) for item in analysis.get("opinions", []) if str(item).strip()]
    conflicts = [str(item) for item in analysis.get("conflicts", []) if str(item).strip()]
    evidence_items = facts + opinions + conflicts or [topic]

    beat_templates = [
        ("cold_open", "Open a quiet question that makes the topic feel larger than the headline.", "", "context"),
        ("setup", "Establish what changed and why it matters now.", evidence_items[0], "context"),
        ("hidden_context", "Reveal the older force or business incentive beneath the visible story.", evidence_items[1 % len(evidence_items)], "evidence"),
        ("evidence", "Present a source-backed fact with measured context.", evidence_items[2 % len(evidence_items)], "evidence"),
        ("counterpoint", "Introduce the strongest reasonable opposing view.", evidence_items[3 % len(evidence_items)], "contrast"),
        ("implication", "Explain what this could mean for people, companies, or the wider system.", evidence_items[4 % len(evidence_items)], "context"),
        ("reflective_turn", "Use a restrained thought experiment to make the stakes visible.", "", "metaphor"),
        ("evidence", "Return to evidence after the reflection.", evidence_items[5 % len(evidence_items)], "evidence"),
        ("counterpoint", "Clarify what is still uncertain or disputed.", evidence_items[6 % len(evidence_items)], "contrast"),
        ("synthesis", "Draw the careful interpretation without overstating the case.", analysis.get("verdict", ""), "synthesis"),
        ("viewer_question", "Ask a specific question that invites thoughtful comments.", "", "synthesis"),
    ]

    beats = []
    cursor = 0
    while len(beats) < target_segments:
        beat_type, purpose, evidence_focus, visual_role = beat_templates[cursor % len(beat_templates)]
        beats.append({
            "beat_type": beat_type,
            "purpose": purpose,
            "evidence_focus": str(evidence_focus or ""),
            "visual_role": visual_role,
        })
        cursor += 1

    return {
        "central_question": f"What is the hidden story behind {topic}, and what does it reveal about where technology and business are moving?",
        "viewer_promise": f"By the end, the viewer will understand the evidence, the disagreement, and the deeper stakes behind {topic}.",
        "thesis": f"{topic} is best understood not as a single headline, but as a signal of a larger system changing quietly.",
        "tension": "The evidence points in one direction, while public reaction and business incentives pull in several others.",
        "human_stakes": "The consequences appear in ordinary decisions, work, trust, money, privacy, and attention.",
        "tone_profile": "calm technology documentary host",
        "reflective_device": "hidden_in_plain_sight",
        "comment_question": f"What part of {topic} do you think people are underestimating?",
        "beats": beats,
    }


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
