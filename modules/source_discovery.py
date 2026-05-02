"""Topic-aware source planning for TrendForge research."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

import openai
import yaml
from loguru import logger


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


SYSTEM_PROMPT = """You plan open-web research for short documentary videos.
Return only valid JSON. Do not include markdown.

Schema:
{
  "topic_angle": "one sentence angle",
  "source_categories": ["news", "reddit", "wiki", "specialist"],
  "search_queries": ["query 1", "query 2"],
  "preferred_domains": ["domain.com"],
  "avoid_domains": ["domain.com"],
  "controversy_axes": ["axis 1"],
  "specialist_sources": ["arxiv", "pubmed", "github", "government", "sec", "who"]
}

Choose specialist sources only when they fit the topic. Prefer primary,
official, academic, open data, and public discussion sources."""


def load_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


def get_openai_client() -> openai.OpenAI:
    cfg = load_config().get("opencode", {})
    return openai.OpenAI(
        base_url=cfg.get("base_url", "http://localhost:11434/v1"),
        api_key=cfg.get("api_key", "ollama"),
    )


def build_source_plan(topic: str) -> Dict[str, Any]:
    """Ask the local model for a source plan, with deterministic fallback."""
    cfg = load_config()
    opencode_cfg = cfg.get("opencode", {})
    research_cfg = cfg.get("research", {})

    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model=opencode_cfg.get("model", "opencode"),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Build a research source plan for this video topic: {topic}\n"
                        f"Target source count: {research_cfg.get('target_source_count', 40)}"
                    ),
                },
            ],
            temperature=0.25,
        )
        text = response.choices[0].message.content or ""
        plan = parse_plan_json(text)
        plan = validate_source_plan(plan, topic)
        logger.info(
            "Source plan: "
            f"{len(plan.get('search_queries', []))} queries, "
            f"specialist={plan.get('specialist_sources', [])}"
        )
        return plan
    except Exception as exc:
        logger.warning(f"Source planning failed: {exc}")
        logger.info("Using deterministic fallback source plan")
        return fallback_source_plan(topic)


def parse_plan_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        text = text.replace("json", "", 1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        first = text.find("{")
        last = text.rfind("}")
        if first >= 0 and last > first:
            return json.loads(text[first : last + 1])
        raise


def validate_source_plan(plan: Dict[str, Any], topic: str) -> Dict[str, Any]:
    fallback = fallback_source_plan(topic)
    result = dict(fallback)
    if isinstance(plan, dict):
        result.update({k: v for k, v in plan.items() if v})

    for key in (
        "source_categories",
        "search_queries",
        "preferred_domains",
        "avoid_domains",
        "controversy_axes",
        "specialist_sources",
    ):
        value = result.get(key)
        if not isinstance(value, list):
            value = [str(value)] if value else []
        result[key] = [clean_item(item) for item in value if clean_item(item)]

    if not result["search_queries"]:
        result["search_queries"] = fallback["search_queries"]
    if not result["source_categories"]:
        result["source_categories"] = fallback["source_categories"]

    result["specialist_sources"] = [
        source
        for source in result["specialist_sources"]
        if specialist_source_fits_topic(source, topic)
    ]

    return result


def specialist_source_fits_topic(source: str, topic: str) -> bool:
    """Keep model-planned specialist sources inside their natural domain."""
    source = clean_item(source).lower()
    topic_lower = topic.lower()

    health_terms = [
        "health",
        "healthcare",
        "medical",
        "medicine",
        "clinical",
        "patient",
        "hospital",
        "disease",
        "cancer",
        "drug",
        "therapy",
        "diagnosis",
        "biotech",
        "pharma",
        "sleep",
        "diet",
        "longevity",
    ]
    tech_terms = ["ai", "artificial intelligence", "machine learning", "robot", "software", "model"]
    finance_terms = ["stock", "company", "crypto", "market", "money", "housing", "earnings", "revenue"]
    public_policy_terms = ["policy", "regulation", "government", "law", "climate", "energy", "environment"]

    if source in {"pubmed", "who"}:
        return any(term in topic_lower for term in health_terms)
    if source in {"arxiv", "github"}:
        return any(term in topic_lower for term in tech_terms + health_terms + ["science", "research"])
    if source == "sec":
        return any(term in topic_lower for term in finance_terms)
    if source == "government":
        return any(term in topic_lower for term in public_policy_terms + health_terms + finance_terms)
    return True


def fallback_source_plan(topic: str) -> Dict[str, Any]:
    topic_lower = topic.lower()
    specialist = []
    preferred_domains = []

    if any(word in topic_lower for word in ["ai", "artificial intelligence", "machine learning", "robot"]):
        specialist.extend(["arxiv", "github"])
        preferred_domains.extend(["arxiv.org", "github.com", "openai.com"])
    if any(word in topic_lower for word in ["health", "medical", "disease", "sleep", "diet", "longevity"]):
        specialist.extend(["pubmed", "who", "government"])
        preferred_domains.extend(["nih.gov", "who.int", "cdc.gov"])
    if any(word in topic_lower for word in ["climate", "energy", "weather", "environment"]):
        specialist.extend(["government"])
        preferred_domains.extend(["noaa.gov", "nasa.gov", "epa.gov"])
    if any(word in topic_lower for word in ["stock", "company", "crypto", "market", "money", "housing"]):
        specialist.extend(["sec", "government"])
        preferred_domains.extend(["sec.gov", "bls.gov", "fred.stlouisfed.org"])

    specialist = list(dict.fromkeys(specialist))
    preferred_domains = list(dict.fromkeys(preferred_domains))

    return {
        "topic_angle": f"What is changing around {topic}, and why people disagree about it.",
        "source_categories": ["news", "reddit", "wiki", "specialist"],
        "search_queries": [
            topic,
            f"{topic} latest evidence",
            f"{topic} controversy",
            f"{topic} expert analysis",
            f"{topic} public reaction",
        ],
        "preferred_domains": preferred_domains,
        "avoid_domains": [],
        "controversy_axes": [
            "what supporters believe",
            "what critics worry about",
            "what evidence is still uncertain",
        ],
        "specialist_sources": specialist,
    }


def clean_item(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
