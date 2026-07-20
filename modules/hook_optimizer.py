"""TrendForge - Hook Optimizer and Retention Predictor

Generates multiple hook variants for a faceless video, scores them with a local
OpenAI-compatible model on the dimensions that drive watch-time (curiosity gap,
clarity, clickability, persona fit), and selects the strongest opener. Also
estimates a per-segment retention/drop-off risk so weak beats can be rewritten.

All scoring runs locally through the same failover LLM chain used elsewhere in
TrendForge, so there is no external API bill.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from loguru import logger

from modules.llm_client import create_llm_client

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

HOOK_SCORE_SYSTEM = """You are a retention strategist for a calm technology documentary channel.
Return only valid JSON. No markdown.

Score each candidate hook for a faceless YouTube/Reels video. The ideal hook creates a
genuine curiosity gap in the first 3 seconds, stays clear and specific, and never feels
like spammy clickbait. It must fit a calm, analytical, trustworthy narrator (no hype,
shouting, or influencer energy) while still making someone want to keep watching.

For each hook return an object with:
  id: the integer index you were given
  curiosity_gap: 0-100 (how strongly it makes the viewer ask "what happens next?")
  clarity: 0-100 (is it concrete and easy to understand instantly?)
  clickability: 0-100 (would a scrolling viewer stop and watch?)
  persona_fit: 0-100 (does it suit a calm, trustworthy documentary host?)
  risk: 0-100 (chance a viewer bounces in the first 5 seconds: lower is better)
  reasoning: one short sentence

Then return:
  selected_id: the id of the best overall hook
  selected_hook: the exact text of that hook

Schema:
{
  "scores": [ {"id": 0, "curiosity_gap": 0, "clarity": 0, "clickability": 0, "persona_fit": 0, "risk": 0, "reasoning": ""} ],
  "selected_id": 0,
  "selected_hook": ""
}"""

RETENTION_SYSTEM = """You are a retention analyst for a calm technology documentary channel.
Return only valid JSON. No markdown.

Given a video script (title, hook, and segment texts in order), estimate where viewers
are most likely to drop off. A strong faceless video keeps tension rising, pays off the
hook late, and avoids slow or redundant middle beats.

For each segment return an object:
  index: integer segment position (0-based)
  retention_risk: 0-100 (higher = more likely to lose viewers)
  reason: one short sentence explaining the risk
  fix: one short, concrete rewrite suggestion (keep the calm documentary voice)

Also return:
  weak_indices: list of indices with retention_risk >= 60
  overall_grade: "A" | "B" | "C" | "D"

Schema:
{
  "segments": [ {"index": 0, "retention_risk": 0, "reason": "", "fix": ""} ],
  "weak_indices": [],
  "overall_grade": "B"
}"""


def load_script_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


def _openai_client():
    cfg = load_script_config().get("opencode", {})
    # Bound the optimizer so a slow/unreachable provider degrades gracefully
    # instead of stalling the whole pipeline.
    timeout = cfg.get("hook_optimizer_timeout", 25)
    try:
        timeout = float(timeout)
    except (TypeError, ValueError):
        timeout = 25.0
    return create_llm_client(cfg, timeout=timeout)


def _parse_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        first, last = text.find("{"), text.rfind("}")
        if first >= 0 and last > first:
            return json.loads(text[first : last + 1])
        raise


def optimize_hooks(
    topic: str,
    analysis: Dict[str, Any],
    count: int = 5,
    base_hooks: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Generate and score hook variants, returning a ranked selection.

    Args:
        topic: Video topic.
        analysis: Fact/opinion analysis used to ground hooks in evidence.
        count: Number of hook variants to produce/score.
        base_hooks: Optional pre-generated hooks; if omitted, they are generated.

    Returns:
        {
          "hooks": [ {"text": str, "scores": {...}, "reasoning": str} ],
          "selected_hook": str,
          "selected_index": int,
          "alternates": [str]
        }
    """
    if base_hooks:
        hooks = list(base_hooks)[:count]
    else:
        from modules.scriptwriter import generate_viral_hooks

        hooks = generate_viral_hooks(topic, count=count)

    if not hooks:
        hooks = [f"Today we're exploring {topic}."]

    verdict = analysis.get("verdict", "")
    facts = analysis.get("facts", [])[:3]

    try:
        client = _openai_client()
        items = "\n".join(f"{i}: {h}" for i, h in enumerate(hooks))
        response = client.chat.completions.create(
            model=load_script_config().get("opencode", {}).get("model", "opencode"),
            messages=[
                {"role": "system", "content": HOOK_SCORE_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Topic: {topic}\n"
                        f"Key verdict: {verdict}\n"
                        f"Top facts: {'; '.join(str(f) for f in facts)}\n\n"
                        f"Score these hook candidates:\n{items}"
                    ),
                },
            ],
            temperature=0.2,
        )
        result = _parse_json(response.choices[0].message.content or "")
    except Exception as exc:
        logger.warning(f"Hook scoring unavailable, using first hook: {exc}")
        return {
            "hooks": [{"text": h, "scores": {}, "reasoning": ""} for h in hooks],
            "selected_hook": hooks[0],
            "selected_index": 0,
            "alternates": hooks[1:],
        }

    scored = result.get("scores", []) or []
    by_id = {int(s.get("id", -1)): s for s in scored if isinstance(s, dict)}
    ranked: List[Dict[str, Any]] = []
    for i, hook in enumerate(hooks):
        meta = by_id.get(i, {})
        ranked.append(
            {
                "text": hook,
                "scores": {
                    "curiosity_gap": int(meta.get("curiosity_gap", 0)),
                    "clarity": int(meta.get("clarity", 0)),
                    "clickability": int(meta.get("clickability", 0)),
                    "persona_fit": int(meta.get("persona_fit", 0)),
                    "risk": int(meta.get("risk", 0)),
                },
                "composite": _composite(meta),
                "reasoning": str(meta.get("reasoning", "")),
            }
        )

    ranked.sort(key=lambda r: r.get("composite", 0), reverse=True)

    selected_index = int(result.get("selected_id", 0))
    selected_hook = result.get("selected_hook") or (ranked[0]["text"] if ranked else hooks[0])
    if selected_hook not in hooks and ranked:
        selected_hook = ranked[0]["text"]
        selected_index = hooks.index(selected_hook)

    logger.info(
        f"Hook optimizer: picked '{selected_hook[:60]}...' "
        f"(composite {max((r.get('composite', 0) for r in ranked), default=0)})"
    )

    return {
        "hooks": ranked,
        "selected_hook": selected_hook,
        "selected_index": selected_index,
        "alternates": [r["text"] for r in ranked[1:]],
    }


def _composite(meta: Dict[str, Any]) -> int:
    """Weight curiosity + clickability, penalize bounce risk."""
    curiosity = int(meta.get("curiosity_gap", 0))
    clarity = int(meta.get("clarity", 0))
    click = int(meta.get("clickability", 0))
    persona = int(meta.get("persona_fit", 0))
    risk = int(meta.get("risk", 0))
    return int(
        curiosity * 0.30
        + click * 0.30
        + clarity * 0.15
        + persona * 0.15
        - risk * 0.10
    )


def predict_retention(script: Dict[str, Any]) -> Dict[str, Any]:
    """Estimate per-segment drop-off risk and suggest fixes for weak beats.

    Args:
        script: Validated script dict with title, hook, and segments.

    Returns:
        {
          "segments": [ {"index", "retention_risk", "reason", "fix"} ],
          "weak_indices": [int],
          "overall_grade": str
        }
    """
    segments = script.get("segments", [])
    if not segments:
        return {"segments": [], "weak_indices": [], "overall_grade": "C"}

    lines = []
    for i, seg in enumerate(segments):
        lines.append(f"{i}: {str(seg.get('text', '')).strip()}")
    script_text = "\n".join(lines)

    try:
        client = _openai_client()
        response = client.chat.completions.create(
            model=load_script_config().get("opencode", {}).get("model", "opencode"),
            messages=[
                {"role": "system", "content": RETENTION_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Title: {script.get('title', '')}\n"
                        f"Hook: {script.get('hook', '')}\n\n"
                        f"Script segments:\n{script_text}"
                    ),
                },
            ],
            temperature=0.2,
        )
        result = _parse_json(response.choices[0].message.content or "")
    except Exception as exc:
        logger.warning(f"Retention prediction unavailable: {exc}")
        return {
            "segments": [
                {"index": i, "retention_risk": 0, "reason": "", "fix": ""}
                for i in range(len(segments))
            ],
            "weak_indices": [],
            "overall_grade": "B",
        }

    seg_meta = result.get("segments", []) or []
    normalized = []
    for item in seg_meta:
        if not isinstance(item, dict):
            continue
        idx = int(item.get("index", -1))
        if idx < 0 or idx >= len(segments):
            continue
        normalized.append(
            {
                "index": idx,
                "retention_risk": int(item.get("retention_risk", 0)),
                "reason": str(item.get("reason", "")),
                "fix": str(item.get("fix", "")),
            }
        )
    normalized.sort(key=lambda r: r["index"])

    weak = [r["index"] for r in normalized if r["retention_risk"] >= 60]
    grade = str(result.get("overall_grade", "B")).upper() or "B"

    logger.info(f"Retention predictor: {len(weak)} weak segment(s), grade {grade}")
    return {"segments": normalized, "weak_indices": weak, "overall_grade": grade}


def summarize_hook_report(optimization: Dict[str, Any]) -> str:
    """Compact human-readable log/report line for the UI."""
    hooks = optimization.get("hooks", [])
    if not hooks:
        return "No hook scored."
    top = hooks[0]
    parts = [
        f"Best hook ({top.get('composite', 0)}): {top['text']}",
    ]
    for h in hooks[1:4]:
        parts.append(f"  alt {h.get('composite', 0)}: {h['text']}")
    return "\n".join(parts)


HOOK_REPORT_PATH = Path("./temp/hook_report.json")


def write_hook_report(optimization: Dict[str, Any], retention: Dict[str, Any], topic: str) -> None:
    """Persist the hook + retention analysis so the UI can render it live."""
    try:
        HOOK_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "topic": topic,
            "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "selected_hook": optimization.get("selected_hook", ""),
            "selected_index": optimization.get("selected_index", 0),
            "alternates": optimization.get("alternates", []),
            "hooks": [
                {
                    "text": h.get("text", ""),
                    "composite": h.get("composite", 0),
                    "scores": h.get("scores", {}),
                    "reasoning": h.get("reasoning", ""),
                }
                for h in optimization.get("hooks", [])
            ],
            "retention": {
                "overall_grade": (retention or {}).get("overall_grade", ""),
                "weak_indices": (retention or {}).get("weak_indices", []),
                "segments": (retention or {}).get("segments", []),
            },
        }
        with open(HOOK_REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.debug(f"Hook report write skipped: {exc}")


def read_hook_report() -> Optional[Dict[str, Any]]:
    """Load the latest persisted hook + retention report, if present."""
    try:
        if HOOK_REPORT_PATH.exists():
            with open(HOOK_REPORT_PATH, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


if __name__ == "__main__":
    import sys

    sample_topic = sys.argv[1] if len(sys.argv) > 1 else "quantum computing"
    sample_analysis = {
        "verdict": "Quantum advantage is arriving in narrow domains first.",
        "facts": [
            "A 2024 experiment demonstrated error correction below the threshold.",
            "Cloud quantum access expanded to three new regions.",
        ],
    }
    opt = optimize_hooks(sample_topic, sample_analysis)
    print(summarize_hook_report(opt))
    print("\nAlternates:", opt["alternates"])
