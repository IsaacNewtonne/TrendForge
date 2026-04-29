"""Vision quality gate for source screenshots.

Uses a local Ollama vision model to judge whether a captured source screenshot
is clean enough for video use. This is intentionally separate from the
research/script/narration model configuration.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path
from typing import Any, Dict

import requests
from loguru import logger


DEFAULT_PROMPT = """You are a strict visual quality inspector for a documentary video pipeline.
Judge whether this screenshot is usable as a clean source visual in a 16:9 YouTube video.

Score only what is visible in the image. Penalize:
- cookie banners, popups, modals, paywalls, login walls, bot checks, newsletter prompts
- mostly blank pages, loading pages, error pages, huge ads, cropped/illegible content
- missing headline/source context when a news/article screenshot is expected
- screenshots unrelated to the expected source or headline

Return ONLY compact JSON with these keys:
{
  "ok": true,
  "score": 0,
  "problems": [],
  "recommended_action": "accept",
  "reason": "short explanation"
}

Use recommended_action "accept", "retry", "crop_or_clean", or "fallback_card".
"""


def evaluate_source_screenshot(
    screenshot_path: str | Path,
    config: Dict[str, Any],
    expected_source: str = "",
    expected_headline: str = "",
    source_url: str = "",
) -> Dict[str, Any]:
    """Return a vision-based quality report for a screenshot."""
    path = Path(screenshot_path)
    if not path.exists():
        return {
            "ok": False,
            "score": 0,
            "problems": ["screenshot file missing"],
            "recommended_action": "retry",
            "reason": f"Screenshot not found: {path}",
        }

    if not config.get("vision_quality_gate", False):
        return {
            "ok": True,
            "score": 100,
            "problems": [],
            "recommended_action": "accept",
            "reason": "vision quality gate disabled",
        }

    base_url = str(config.get("vision_base_url", "http://localhost:11434")).rstrip("/")
    model = config.get("vision_model", "qwen3.5:4b")
    timeout = float(config.get("vision_timeout", 120))
    min_score = int(config.get("vision_min_score", 75))
    fail_open = bool(config.get("vision_fail_open", True))

    try:
        image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        payload = {
                "model": model,
                "stream": False,
                "think": bool(config.get("vision_think", False)),
                "options": {
                    "temperature": float(config.get("vision_temperature", 0.0)),
                    "num_predict": int(config.get("vision_num_predict", 220)),
                },
                "messages": [
                    {
                        "role": "user",
                        "content": build_prompt(expected_source, expected_headline, source_url),
                        "images": [image_b64],
                    }
                ],
        }
        if config.get("vision_force_json", False):
            payload["format"] = "json"

        response = requests.post(
            f"{base_url}/api/chat",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        content = ((payload.get("message") or {}).get("content") or "").strip()
        report = normalize_report(parse_json_object(content), min_score)
        report["model"] = model
        return report
    except Exception as e:
        logger.warning(f"Vision screenshot gate unavailable: {e}")
        return {
            "ok": fail_open,
            "score": 100 if fail_open else 0,
            "problems": [str(e)],
            "recommended_action": "accept" if fail_open else "fallback_card",
            "reason": "vision gate unavailable; existing DOM/image quality gate used"
            if fail_open
            else "vision gate unavailable",
            "model": model,
        }


def build_prompt(expected_source: str, expected_headline: str, source_url: str) -> str:
    context = []
    if expected_source:
        context.append(f"Expected source: {expected_source}")
    if expected_headline:
        context.append(f"Expected headline/title: {expected_headline}")
    if source_url:
        context.append(f"Expected URL/domain: {source_url}")

    if context:
        return DEFAULT_PROMPT + "\n\nContext:\n" + "\n".join(context)
    return DEFAULT_PROMPT


def parse_json_object(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def normalize_report(report: Dict[str, Any], min_score: int) -> Dict[str, Any]:
    try:
        score = int(float(report.get("score", 0)))
    except (TypeError, ValueError):
        score = 0

    problems = report.get("problems", [])
    if isinstance(problems, str):
        problems = [problems]
    if not isinstance(problems, list):
        problems = [str(problems)]

    action = str(report.get("recommended_action") or "").strip().lower()
    if action not in {"accept", "retry", "crop_or_clean", "fallback_card"}:
        action = "accept" if score >= min_score else "retry"

    ok = bool(report.get("ok", score >= min_score)) and score >= min_score and action == "accept"
    return {
        "ok": ok,
        "score": max(0, min(score, 100)),
        "problems": [str(item) for item in problems if str(item).strip()],
        "recommended_action": action,
        "reason": str(report.get("reason") or ("accepted" if ok else "vision score too low")),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--min-score", type=int, default=75)
    args = parser.parse_args()

    print(
        evaluate_source_screenshot(
            args.path,
            {
                "vision_quality_gate": True,
                "vision_model": args.model,
                "vision_base_url": args.base_url,
                "vision_min_score": args.min_score,
                "vision_fail_open": False,
            },
        )
    )


if __name__ == "__main__":
    main()
