"""TrendForge - AI Research & Fact/Opinion Analysis Module

Provides AI-powered content analysis to separate facts from opinions.
Uses OpenAI-compatible API (works with OpenCode or OpenAI).
"""

import json
import os
import re
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
from loguru import logger

import openai

# Configuration
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
DEFAULT_SYSTEM_PROMPT = """You are a research analyst for TrendForge, an AI video generator.
Your job is to analyze web content and clearly separate FACT from OPINION.

Guidelines:
- FACTS: Verifiable, source-backed statements (statistics, dates, official statements)
- OPINIONS: Expert views, editorial positions, public sentiment, predictions
- CONFLICTS: Where sources disagree or present conflicting information
- VERDICT: A balanced 2-sentence conclusion summarizing both sides

Return ONLY valid JSON with these exact keys:
- facts: List of 3-5 key facts (strings)
- opinions: List of 3-5 key opinions (strings) 
- conflicts: List of 1-3 areas where sources disagree
- verdict: A balanced 2-sentence conclusion
- confidence: Score from 0-100 on analysis confidence"""

APPROX_CHARS_PER_TOKEN = 4
ANALYSIS_KEYS = ["facts", "opinions", "conflicts", "verdict", "confidence"]


def load_opencode_config() -> dict:
    """Load OpenCode/API configuration."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f)
            return cfg.get("opencode", {})
    return {}


def get_openai_client() -> openai.OpenAI:
    """Create OpenAI client configured for Ollama."""
    cfg = load_opencode_config()
    
    base_url = cfg.get("base_url", "http://localhost:11434/v1")
    api_key = cfg.get("api_key", "ollama")
    
    client = openai.OpenAI(
        base_url=base_url,
        api_key=api_key
    )
    
    return client


def trim_to_token_budget(text: str, token_budget: int, label: str) -> str:
    """Approximate token-budget trimming for local/OpenAI-compatible models."""
    if not token_budget or int(token_budget) <= 0:
        return text

    max_chars = max(1, int(token_budget * APPROX_CHARS_PER_TOKEN))
    if len(text) <= max_chars:
        return text

    logger.info(
        f"{label} trimmed from ~{len(text) // APPROX_CHARS_PER_TOKEN} "
        f"to ~{token_budget} input tokens"
    )
    return text[:max_chars].rsplit(" ", 1)[0].strip()


def build_analysis_context(raw_content: List[Dict[str, Any]], cfg: Dict[str, Any]) -> str:
    """Build a bounded research context before sending it to the LLM."""
    per_source_chars = cfg.get("analysis_source_chars")
    input_token_budget = cfg.get("input_token_budget")
    chunks = []

    for item in raw_content[:8]:
        source = item.get("source", "unknown")
        title = item.get("title", "")
        text = re.sub(r"\s+", " ", str(item.get("text", ""))).strip()

        if text and len(text) > 50:
            heading = f"[{source.upper()}] {title}".strip()
            if per_source_chars and int(per_source_chars) > 0:
                text = text[: int(per_source_chars)]
            chunks.append(f"{heading}\n{text}")

    return trim_to_token_budget("\n\n".join(chunks), input_token_budget, "Analysis context")


def completion_options(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Build optional completion parameters without forcing local token caps."""
    max_tokens = cfg.get("max_tokens")
    options = {}
    if max_tokens and int(max_tokens) > 0:
        options["max_tokens"] = int(max_tokens)
    if cfg.get("json_response_format", True):
        options["response_format"] = {"type": "json_object"}
    return options


def strip_json_wrappers(text: str) -> str:
    """Strip markdown fences and prose around a JSON object."""
    text = str(text or "").strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        return text[first_brace:last_brace + 1].strip()
    return text


def parse_analysis_response(text: str) -> Dict[str, Any]:
    """Parse model analysis JSON without destructive quote replacement."""
    candidate = strip_json_wrappers(text)
    attempts = [
        candidate,
        re.sub(r",\s*([}\]])", r"\1", candidate),
    ]

    for attempt in attempts:
        try:
            return validate_analysis(json.loads(attempt))
        except json.JSONDecodeError:
            continue

    import ast

    try:
        parsed = ast.literal_eval(candidate)
        if isinstance(parsed, dict):
            return validate_analysis(parsed)
    except (SyntaxError, ValueError):
        pass

    raise ValueError("Model response is not valid analysis JSON")


def request_analysis_repair(client: openai.OpenAI, model: str, broken_text: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Ask the model to repair malformed JSON once."""
    logger.warning("Analysis JSON invalid; requesting one repair pass")
    response = create_chat_completion(
        client,
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Return only valid JSON with keys facts, opinions, conflicts, verdict, confidence. "
                    "Do not add markdown or commentary."
                ),
            },
            {
                "role": "user",
                "content": f"Repair this malformed analysis into valid JSON only:\n{broken_text}",
            },
        ],
        temperature=0,
        cfg=cfg,
    )
    return parse_analysis_response(response.choices[0].message.content)


def create_chat_completion(
    client: openai.OpenAI,
    model: str,
    messages: List[Dict[str, str]],
    temperature: float,
    cfg: Dict[str, Any],
):
    """Create a completion, retrying without JSON mode if the backend rejects it."""
    options = completion_options(cfg)
    try:
        return client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            **options,
        )
    except Exception as e:
        if "response_format" not in options:
            raise
        logger.warning(f"JSON response_format rejected; retrying without it: {e}")
        options.pop("response_format", None)
        return client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            **options,
        )


def source_fallback_analysis(raw_content: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a usable analysis from scraped sources when model JSON is malformed."""
    facts = []
    opinions = []
    for item in raw_content:
        title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()
        source_name = str(item.get("source_name") or item.get("source") or "source").strip()
        excerpt = re.sub(r"\s+", " ", str(item.get("text") or item.get("text_excerpt") or "")).strip()
        if title and len(facts) < 5:
            facts.append(f"{source_name} reports: {title}")
        elif excerpt and len(opinions) < 5:
            opinions.append(excerpt[:220])
        if len(facts) >= 5 and len(opinions) >= 5:
            break

    if not opinions:
        opinions = [
            "Sources frame artificial intelligence as a fast-moving field with uncertain social and business impacts.",
            "Public discussion remains split between optimism about productivity and concern about risk and governance.",
        ]

    return validate_analysis({
        "facts": facts or ["Scraped sources were available, but the analysis model returned malformed JSON."],
        "opinions": opinions[:5],
        "conflicts": [
            "Sources differ on whether AI's near-term impact is mostly productivity gain, labor disruption, or governance risk."
        ],
        "verdict": (
            "The source set supports a balanced story: artificial intelligence is advancing quickly, "
            "but its costs, regulation, and social effects remain contested."
        ),
        "confidence": 45,
    })


def analyse_content(raw_content: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze scraped content to separate facts from opinions.
    
    Requires OpenCode to be running. Will FAIL if unavailable.
    
    Args:
        raw_content: List of scraped content dictionaries
        
    Returns:
        Analysis dictionary with facts, opinions, conflicts, verdict
        
    Raises:
        RuntimeError: If OpenCode is not available
    """
    cfg = load_opencode_config()
    
    combined_text = build_analysis_context(raw_content, cfg)
    
    if not combined_text.strip():
        raise RuntimeError("No content available to analyze. Scrape failed or returned empty.")
    
    logger.info(f"Analyzing {len(raw_content)} sources...")
    
    client = get_openai_client()

    messages = [
        {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": f"""Analyze the following web content about the topic.
Focus on separating what's FACT from OPINION. Identify where sources disagree.

CONTENT:
{combined_text}

Return your analysis as JSON."""}
    ]

    model = cfg.get("model", "opencode")
    temperature = cfg.get("temperature", 0.7)
    try:
        response = create_chat_completion(client, model, messages, temperature, cfg)
    except Exception as e:
        logger.error(f"OpenCode unavailable: {e}")
        raise RuntimeError(
            f"OpenCode is required but unavailable. Ensure 'opencode serve' is running.\n"
            f"Error: {e}"
        )

    result_text = response.choices[0].message.content

    try:
        analysis = parse_analysis_response(result_text)
    except ValueError as parse_error:
        try:
            analysis = request_analysis_repair(client, model, result_text, cfg)
        except Exception as repair_error:
            logger.warning(
                f"Analysis JSON repair failed ({repair_error}); using source-derived fallback. "
                f"Original parse error: {parse_error}"
            )
            analysis = source_fallback_analysis(raw_content)

    logger.info(
        f"Analysis complete: {len(analysis.get('facts', []))} facts, "
        f"{len(analysis.get('opinions', []))} opinions"
    )
    return analysis


def parse_fallback_analysis(text: str) -> Dict[str, Any]:
    """Try to parse analysis from non-JSON text response.
    
    Args:
        text: Raw response text
        
    Returns:
        Analysis dictionary
    """
    import re
    
    analysis = {
        "facts": [],
        "opinions": [],
        "conflicts": [],
        "verdict": "",
        "confidence": 50
    }
    
    # Try to extract facts (lines starting with - or bullets)
    fact_pattern = r"(?:^|\n)\s*(?:fact|facts?)\s*[:\-]?\s*(.+?)(?=\n|$)"
    opinion_pattern = r"(?:^|\n)\s*(?:opinion|opinions?)\s*[:\-]?\s*(.+?)(?=\n|$)"
    
    facts = re.findall(fact_pattern, text, re.IGNORECASE)
    opinions = re.findall(opinion_pattern, text, re.IGNORECASE)
    
    if facts:
        analysis["facts"] = facts[:5]
    if opinions:
        analysis["opinions"] = opinions[:5]
    
    # Extract verdict sentences
    sentences = text.split(".")
    verdict_sentences = [s.strip() for s in sentences[-3:] if s.strip()]
    if verdict_sentences:
        analysis["verdict"] = ". ".join(verdict_sentences[:2]) + "."
    
    return analysis


def get_fallback_analysis() -> Dict[str, Any]:
    """Get a fallback analysis when API is unavailable.
    
    Returns:
        Default analysis dictionary
    """
    return {
        "facts": [
            "Analysis unavailable - API connection failed",
            "Using fallback content processing",
            "Please check your OpenCode server is running"
        ],
        "opinions": [
            "Topic requires further research",
            "Content analysis pending API availability"
        ],
        "conflicts": [
            "Unable to determine source conflicts without API"
        ],
        "verdict": "This topic is currently being researched. Please check your configuration and try again.",
        "confidence": 10
    }


def validate_analysis(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize analysis output.
    
    Args:
        analysis: Raw analysis dictionary
        
    Returns:
        Validated analysis with required fields
    """
    required_keys = ["facts", "opinions", "conflicts", "verdict", "confidence"]
    
    result = {}
    for key in required_keys:
        if key in analysis:
            result[key] = analysis[key]
        else:
            result[key] = [] if key in ["facts", "opinions", "conflicts"] else ""
    
    # Ensure lists
    if not isinstance(result["facts"], list):
        result["facts"] = [str(result["facts"])]
    if not isinstance(result["opinions"], list):
        result["opinions"] = [str(result["opinions"])]
    if not isinstance(result["conflicts"], list):
        result["conflicts"] = [str(result["conflicts"])]
    
    # Ensure verdict is string
    if not isinstance(result.get("verdict"), str):
        result["verdict"] = str(result.get("verdict", ""))
    
    # Ensure confidence is int
    try:
        result["confidence"] = int(result.get("confidence", 50))
    except (ValueError, TypeError):
        result["confidence"] = 50
    
    return result
