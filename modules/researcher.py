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
    if not max_tokens or int(max_tokens) <= 0:
        return {}
    return {"max_tokens": int(max_tokens)}


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
    
    # Create client - FAIL if unavailable
    try:
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
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            **completion_options(cfg)
        )
        
        result_text = response.choices[0].message.content
        
        # Strip markdown code blocks if present
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0].strip()
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0].strip()
        
        try:
            analysis = json.loads(result_text)
        except json.JSONDecodeError as e:
            # Try fixing single quotes if model returns invalid JSON
            try:
                fixed = result_text.replace("'", '"')
                analysis = json.loads(fixed)
            except:
                logger.error(f"Invalid JSON from OpenCode: {e}")
                raise RuntimeError("OpenCode returned invalid analysis.")
        
        analysis = validate_analysis(analysis)
        logger.info(f"Analysis complete: {len(analysis.get('facts', []))} facts, {len(analysis.get('opinions', []))} opinions")
        return analysis
            
    except Exception as e:
        logger.error(f"OpenCode unavailable: {e}")
        raise RuntimeError(
            f"OpenCode is required but unavailable. Ensure 'opencode serve' is running.\n"
            f"Error: {e}"
        )
    
    logger.info(f"Analyzing {len(raw_content)} sources...")
    
    # Create client
    try:
        client = get_openai_client()
        
        # Build messages
        messages = [
            {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
            {"role": "user", "content": f"""Analyze the following web content about the topic. 
Focus on separating what's FACT from OPINION. Identify where sources disagree.

CONTENT:
{combined_text}

Return your analysis as JSON."""}
        ]
        
        # Make API call
        model = cfg.get("model", "opencode")
        temperature = cfg.get("temperature", 0.7)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            **completion_options(cfg)
        )
        
        result_text = response.choices[0].message.content
        
        # Strip markdown code blocks if present
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0].strip()
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0].strip()
        
        try:
            analysis = json.loads(result_text)
        except json.JSONDecodeError:
            try:
                fixed = result_text.replace("'", '"')
                analysis = json.loads(fixed)
            except:
                logger.error(f"Invalid JSON: {result_text[:200]}")
                analysis = get_fallback_analysis()
        except json.JSONDecodeError:
            # Try to extract valid JSON from incomplete response
            try:
                import re
                first_brace = result_text.find('{')
                last_brace = result_text.rfind('}')
                if first_brace >= 0 and last_brace > first_brace:
                    result_text = result_text[first_brace:last_brace+1]
                analysis = json.loads(result_text)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse JSON from API: {e}")
                return parse_fallback_analysis(result_text)
        
        # Validate required keys
            required_keys = ["facts", "opinions", "conflicts", "verdict"]
            for key in required_keys:
                if key not in analysis:
                    analysis[key] = []
            
            # Ensure lists
            if not isinstance(analysis.get("facts"), list):
                analysis["facts"] = []
            if not isinstance(analysis.get("opinions"), list):
                analysis["opinions"] = []
            if not isinstance(analysis.get("conflicts"), list):
                analysis["conflicts"] = []
                
            logger.info(f"Analysis complete: {len(analysis.get('facts', []))} facts, {len(analysis.get('opinions', []))} opinions")
            return analysis
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON from API: {e}")
            return parse_fallback_analysis(result_text)
            
    except Exception as e:
        logger.error(f"OpenAI API call failed: {e}")
        logger.info("Using fallback analysis")
        return get_fallback_analysis()


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
