"""TrendForge - Script Generation Module

Generates structured video scripts from analysis data using AI with viral hook patterns.
"""

import json
import math
import os
import yaml
import random
import re
from pathlib import Path
from typing import Dict, List, Any
from loguru import logger

import openai

from modules.llm_client import create_llm_client
from modules.narrative_planner import build_narrative_plan, critique_script
from modules.hook_optimizer import optimize_hooks, predict_retention, summarize_hook_report

# Configuration
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

# Custom branding - used unless config overrides it
CUSTOM_INTRO_TEXT = "Trend Forge. Clear evidence, sharp context, and the story behind what is changing."
CUSTOM_OUTRO_TEXT = "That was Trend Forge. Subscribe for clearer context on what comes next."
APPROX_CHARS_PER_TOKEN = 4

# Viral hook templates - categorized by type
QUESTION_HOOKS = [
    "Why are {count} million people suddenly {action}?",
    "What if I told you {reveal}?",
    "Have you heard about {topic}? Here's what nobody is telling you.",
    "What's the {topic} industry not want you to know?",
    "How does {topic} actually work? (Most people get this wrong)",
    "What happens when you {action}? You'll never guess.",
]

CONTROVERSY_HOOKS = [
    "Everyone got this wrong. Here's why...",
    "The truth about {topic} that the mainstream won't tell you.",
    "I've investigated {topic} for months. Here's what I found.",
    "This is the most {adjective} thing about {topic}.",
    "The {topic} scandal nobody is talking about.",
    "Stop {action} - do this instead.",
]

NUMBER_HOOKS = [
    "{count} things your [expert] never told you about {topic}.",
    "The {count} biggest {topic} myths, debunked.",
    "{count} reasons to {action} (number {one} will surprise you)",
    "I've seen {count} {topic} predictions this year. Only {one} came true.",
    "{count} hidden {topic} secrets the industry doesn't want you to know.",
]

# Hook type detection keywords
HOOK_KEYWORDS = {
    "question": ["why", "what", "how", "what if", "have you", "does", "can"],
    "controversy": ["wrong", "truth", "scandal", "nobody", "won't tell", "exposed", "secret"],
    "number": ["thing", "reason", "secret", "way", "myth", "tips", "rules", "facts"],
}


def load_opencode_config() -> dict:
    """Load OpenCode/API configuration."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f)
            return cfg.get("opencode", {})
    return {}


def load_full_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


def get_openai_client() -> openai.OpenAI:
    """Create OpenAI client configured for OpenCode."""
    cfg = load_opencode_config()
    return create_llm_client(cfg)


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


def trim_item(text: Any, char_budget: int) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if not char_budget or int(char_budget) <= 0:
        return normalized

    char_budget = int(char_budget)
    if len(normalized) <= char_budget:
        return normalized
    return normalized[:char_budget].rsplit(" ", 1)[0].rstrip(" .,") + "."


def format_limited_items(items: List[Any], limit: int, char_budget: int) -> str:
    limited = [trim_item(item, char_budget) for item in items[:limit] if str(item).strip()]
    return chr(10).join(f"- {item}" for item in limited) or "- None"


def completion_options(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Build optional completion parameters without forcing local token caps."""
    max_tokens = cfg.get("max_tokens")
    options = {}
    if max_tokens and int(max_tokens) > 0:
        options["max_tokens"] = int(max_tokens)
    if cfg.get("json_response_format", True):
        options["response_format"] = {"type": "json_object"}
    return options


def detect_hook_type(topic: str) -> str:
    """Detect which hook type fits the topic best.
    
    Args:
        topic: Video topic
        
    Returns:
        Hook type: question, controversy, or number
    """
    topic_lower = topic.lower()
    
    for keyword in HOOK_KEYWORDS["controversy"]:
        if keyword in topic_lower:
            return "controversy"
    
    for keyword in HOOK_KEYWORDS["number"]:
        if keyword in topic_lower:
            return "number"
    
    for keyword in HOOK_KEYWORDS["question"]:
        if keyword in topic_lower:
            return "question"
    
    # Default - alternate between question and controversy
    return random.choice(["question", "controversy"])


def generate_viral_hooks(topic: str, count: int = 3) -> List[str]:
    """Generate multiple viral hook variants.
    
    Args:
        topic: Video topic
        count: Number of hooks to generate
        
    Returns:
        List of hook strings
    """
    hook_type = detect_hook_type(topic)
    
    if hook_type == "question":
        templates = QUESTION_HOOKS
    elif hook_type == "controversy":
        templates = CONTROVERSY_HOOKS
    else:
        templates = NUMBER_HOOKS
    
    hooks = []
    for template in templates[:count]:
        hook = template.format(
            topic=topic,
            action=topic.split()[0] if topic else "care",
            reveal=f"{topic} is changing",
            adjective="controversial",
            count=random.choice([3, 5, 7]),
            one=random.choice(["one", "this"])
        )
        hooks.append(hook)
    
    return hooks[:count]


# Viral script template - enforces payoff delay
SCRIPT_TEMPLATE = """Create a calm, cinematic technology-documentary script optimized for thoughtful YouTube retention.

CRITICAL RULES:
1. The HOOK must create a question in viewer's mind in the first 3 seconds
2. The ANSWER to the hook question must come after setup and evidence, not immediately
3. Build a human, grounded story from the facts gathered and evidence collected
4. Include one appropriate reflective device: "imagine if", everyday scene, two futures, courtroom evidence, hidden-in-plain-sight, or a fair contrarian turn
5. Creative parts must remain clearly framed as metaphor, possibility, or opinion, not invented facts
6. End with a topic-specific comment question that invites viewers to share their view
7. Narrator character: intelligent, composed, curious, analytical, smooth, reflective, professional, slightly mysterious, polished, and trustworthy
8. Avoid hype, jokes, shouting, slang, clickbait, and influencer-style energy

Structure:
- INTRO: short TrendForge welcome
- HOOK: question or controversy that creates curiosity
- CONTEXT: what happened and why people care
- EVIDENCE: verified facts with context
- COUNTERPOINTS: different viewpoints, balanced
- REFLECTIVE TURN: a thought experiment or grounded analogy that fits the topic
- SYNTHESIS: what this means
- COMMENT PROMPT: a fair, specific question for viewers
- OUTRO: farewell CTA

Return JSON with exact keys:
- title: "The Truth About [Topic]" or "Why [Topic] is [Adjective]"
- hook: Your best hook (question-creating)
- hooks_variants: 2-3 alternative hooks (for testing)
- segments: List with:
  - Produce the requested number of total segments
  - type: "hook" | "fact" | "opinion" | "verdict" | "transition"
  - text: Conversational spoken text with enough detail for a five-minute video
  - image_prompt: STYLE_ANCHORED prompt under 30 words (cinematic, NO generic "cinematic")
  - payoff_min_seconds: Minimum seconds before revealing answer
- outro: Subscribe CTA
- payoff_delay_enforced: true"""


def generate_script(topic: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a video script from topic and analysis.

    Uses the configured LLM provider chain, including the local fallback.
    
    Args:
        topic: The video topic
        analysis: Fact/opinion analysis dictionary
        
    Returns:
        Script dictionary with segments
        
    Raises:
        RuntimeError: If generation fails on the available provider
    """
    full_cfg = load_full_config()
    cfg = full_cfg.get("opencode", {})
    script_cfg = full_cfg.get("script", {})
    
    # Build context from analysis
    facts = analysis.get("facts", [])
    opinions = analysis.get("opinions", [])
    conflicts = analysis.get("conflicts", [])
    verdict = analysis.get("verdict", "")
    confidence = analysis.get("confidence", 0)
    
    item_chars = cfg.get("script_item_chars")
    analysis_summary = f"""Topic: {trim_item(topic, 160)}
    
Key Facts ({len(facts)}):
{format_limited_items(facts, 5, item_chars)}

Key Opinions ({len(opinions)}):
{format_limited_items(opinions, 5, item_chars)}

Conflicting Views:
{format_limited_items(conflicts, 3, item_chars)}

Verdict: {trim_item(verdict, item_chars)}

Analysis Confidence: {confidence}%"""
    analysis_summary = trim_to_token_budget(
        analysis_summary,
        cfg.get("input_token_budget"),
        "Script context",
    )
    
    logger.info(f"Generating script for: {topic}")
    target_segments = int(script_cfg.get("target_segments", 18))
    min_words = int(script_cfg.get("min_words", 760))
    max_words = int(script_cfg.get("max_words", 980))
    target_duration = int(script_cfg.get("target_duration_seconds", 330))
    creative_devices = ", ".join(script_cfg.get("creative_devices", []))
    narrator_character = script_cfg.get(
        "narrator_character",
        "A calm technology documentary host: intelligent, composed, curious, analytical, smooth, reflective, professional, slightly mysterious, polished, and trustworthy. Avoid hype, jokes, shouting, slang, clickbait, and influencer-style energy.",
    )
    narrative_plan = analysis.get("narrative_plan")
    if not isinstance(narrative_plan, dict):
        narrative_plan = build_narrative_plan(topic, analysis, analysis.get("source_plan"))
    
    try:
        client = get_openai_client()
        
        messages = [
            {"role": "system", "content": SCRIPT_TEMPLATE},
            {"role": "user", "content": f"""Generate a HIGHLY ENGAGING documentary video script.

Targets:
- Total spoken duration: about {target_duration} seconds
- Total words: {min_words}-{max_words}
- Total segments: {target_segments}
- Creative device options: {creative_devices}
- Narrator character: {narrator_character}
- Tone: calm, cinematic, analytical, reflective, evidence-grounded
- Comment strategy: invite viewers to share their view on the real tension in the topic without provoking outrage
- Narrative plan: {json.dumps(narrative_plan, ensure_ascii=False)[:6000]}

{analysis_summary}

Return the script as JSON that can be parsed by json.loads()"""}
        ]
        
        model = cfg.get("model", "opencode")
        temperature = cfg.get("temperature", 0.7)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            **completion_options(cfg)
        )
        
        result_text = response.choices[0].message.content or ""
        finish_reason = getattr(response.choices[0], "finish_reason", None)
        if finish_reason == "length":
            raise RuntimeError(
                "Script generation reached the model output limit. "
                "No fallback script was created; reduce input context or increase model capacity."
            )
        
        # Strip markdown code blocks if present
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0].strip()
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0].strip()
        
        # Try to extract JSON, even if incomplete
        try:
            script = json.loads(result_text)
        except json.JSONDecodeError:
            # Try to find and fix truncated JSON
            import re
            # Find first { and last } to extract potential JSON
            first_brace = result_text.find('{')
            last_brace = result_text.rfind('}')
            if first_brace >= 0 and last_brace > first_brace:
                result_text = result_text[first_brace:last_brace+1]
            
            # Try to fix unterminated strings by completing the JSON
            try:
                script = json.loads(result_text)
            except json.JSONDecodeError:
                raise RuntimeError(
                    "Script model returned invalid JSON. No fallback script was created."
                )
        
        script = validate_script(script, topic, narrative_plan=narrative_plan)

        # Hook optimizer: score variants locally and promote the strongest opener.
        try:
            hook_opt = optimize_hooks(
                topic,
                analysis,
                count=int(script_cfg.get("hook_variants", 5)),
            )
            if hook_opt.get("selected_hook"):
                script["hook"] = hook_opt["selected_hook"]
                # A stronger hook should also open the first segment.
                if script.get("segments"):
                    script["segments"][0]["text"] = hook_opt["selected_hook"]
            script["hook_optimization"] = hook_opt
            logger.info(summarize_hook_report(hook_opt))
            try:
                from modules.hook_optimizer import write_hook_report

                write_hook_report(hook_opt, script.get("retention_report", {}), topic)
            except Exception:
                pass
        except Exception as exc:
            logger.warning(f"Hook optimization skipped: {exc}")
            script["hook_optimization"] = {}

        # Keep explicit intro/outro narration so silent clips can carry audio.
        script = force_custom_intro_outro(script, full_cfg.get("intro_outro", {}))
        script = enforce_script_length(script, topic, analysis, min_words, max_words, target_segments, cfg)
        script = apply_narrative_metadata(script, narrative_plan)
        if script_cfg.get("narration_critic_enabled", True):
            script = revise_script_if_needed(script, topic, analysis, narrative_plan, cfg)
            # A rewrite must not invalidate the duration and segment-count contract.
            script = enforce_script_length(
                script, topic, analysis, min_words, max_words, target_segments, cfg
            )
            script = apply_narrative_metadata(script, narrative_plan)
        else:
            logger.info("Narration critic disabled; keeping the validated script")

        # Retention predictor: flag weak segments so the editor/UI can surface fixes.
        try:
            script["retention_report"] = predict_retention(script)
            if (
                script_cfg.get("retention_rewrite_enabled", True)
                and str(script["retention_report"].get("overall_grade", "")).upper() in {"C", "D", "F"}
                and script["retention_report"].get("weak_indices")
            ):
                logger.warning(
                    "Retention grade is below target; running one focused narration rewrite"
                )
                script = revise_script_if_needed(
                    script, topic, analysis, narrative_plan, cfg
                )
                script = enforce_script_length(
                    script, topic, analysis, min_words, max_words, target_segments, cfg
                )
                script = apply_narrative_metadata(script, narrative_plan)
                script["retention_report"] = predict_retention(script)
        except Exception as exc:
            logger.warning(f"Retention prediction skipped: {exc}")
            script["retention_report"] = {}

        logger.info(
            f"Script generated: {len(script.get('segments', []))} segments, "
            f"{count_script_words(script)} words, estimated {estimate_duration(script):.1f}s"
        )
        return script
            
    except Exception as e:
        logger.error(f"Script generation failed: {e}")
        raise RuntimeError(f"Script generation failed: {e}") from e


def validate_script(script: Dict[str, Any], topic: str, narrative_plan: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Validate and normalize script output.
    
    Args:
        script: Raw script dictionary
        topic: Topic for fallback
        
    Returns:
        Validated script
    """
    result = {
        "topic": script.get("topic") or topic,
        "title": script.get("title") or f"The Truth About {topic.title()}",
        "hook": script.get("hook") or f"Today we're exploring {topic}.",
        "hooks_variants": script.get("hooks_variants", []) or [],
        "segments": [],
        "outro": script.get("outro") or "Subscribe for more daily content!",
        "confidence": script.get("confidence", 50),
        "payoff_delay_enforced": script.get("payoff_delay_enforced", True)
    }
    
    # Validate segments
    segments = script.get("segments", [])
    if not isinstance(segments, list):
        segments = []
    
    beats = (narrative_plan or {}).get("beats", [])
    for index, seg in enumerate(segments):
        if isinstance(seg, dict) and seg.get("text"):
            beat = beats[index] if index < len(beats) and isinstance(beats[index], dict) else {}
            validated_seg = {
                "type": seg.get("type", "fact"),
                "text": str(seg.get("text", "")),
                "image_prompt": seg.get("image_prompt", f"{topic}, cinematic, 4K"),
                "payoff_min_seconds": seg.get("payoff_min_seconds", 60),
                "beat_type": seg.get("beat_type") or beat.get("beat_type") or infer_beat_type(seg.get("type", "fact")),
                "beat_purpose": seg.get("beat_purpose") or beat.get("purpose", ""),
                "delivery": normalize_delivery(seg.get("delivery"), seg.get("type", "fact")),
            }
            result["segments"].append(validated_seg)
    
    # Ensure at least one segment
    if not result["segments"]:
        result["segments"] = [
            {"type": "hook", "text": f"Today we're exploring {topic}.", "image_prompt": f"{topic}, documentary style, 4K", "payoff_min_seconds": 0, "beat_type": "cold_open", "beat_purpose": "Open the topic calmly.", "delivery": normalize_delivery(None, "hook")},
            {"type": "verdict", "text": "Stay tuned for more information.", "image_prompt": f"Conclusion, {topic}, thoughtful, 4K", "payoff_min_seconds": 90, "beat_type": "synthesis", "beat_purpose": "Close with reflection.", "delivery": normalize_delivery(None, "verdict")}
        ]
    
    return result


def force_custom_intro_outro(script: Dict[str, Any], intro_outro_cfg: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Force explicit intro/outro narration on first/last segments.
    
    Args:
        script: Script dictionary
        
    Returns:
        Script with forced intro/outro
    """
    segments = script.get("segments", [])
    if not segments:
        return script
    
    intro_outro_cfg = intro_outro_cfg or {}
    intro_text = intro_outro_cfg.get("intro_text") or CUSTOM_INTRO_TEXT
    outro_text = intro_outro_cfg.get("outro_text") or CUSTOM_OUTRO_TEXT

    # Force intro on first segment. The editor can place this audio over a silent intro clip.
    segments[0]["text"] = intro_text
    segments[0]["type"] = "hook"
    segments[0]["timing_role"] = "intro"
    segments[0]["image_prompt"] = script.get("title") or script.get("topic", "")
    
    # Force outro on last segment. The editor can place this audio over a silent outro clip.
    segments[-1]["text"] = outro_text
    segments[-1]["type"] = "verdict"
    segments[-1]["timing_role"] = "outro"
    segments[-1]["image_prompt"] = f"Closing visual for {script.get('topic', '')}, reflective editorial style"
    
    script["segments"] = segments
    script["intro"] = intro_text
    script["outro"] = outro_text
    
    return script


def count_script_words(script: Dict[str, Any]) -> int:
    return sum(len(str(segment.get("text", "")).split()) for segment in script.get("segments", []))


def enforce_script_length(
    script: Dict[str, Any],
    topic: str,
    analysis: Dict[str, Any],
    min_words: int,
    max_words: int,
    target_segments: int,
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Expand or trim script into the configured five-minute range."""
    script_cfg = load_full_config().get("script", {})
    acceptance_ratio = max(
        0.5,
        min(1.0, float(script_cfg.get("min_word_acceptance_ratio", 0.95))),
    )
    accepted_words = math.ceil(min_words * acceptance_ratio)
    accepted_segments = max(10, target_segments - 4)

    def meets_quality_floor(candidate: Dict[str, Any]) -> bool:
        return (
            count_script_words(candidate) >= accepted_words
            and len(candidate.get("segments", [])) >= accepted_segments
        )

    def finalize(candidate: Dict[str, Any]) -> Dict[str, Any]:
        candidate = trim_overlong_segments(candidate, max_words)
        return consolidate_script_segments(candidate, target_segments)

    words = count_script_words(script)
    if meets_quality_floor(script):
        if words < min_words:
            logger.warning(
                f"Script is slightly below target ({words}/{min_words} words) "
                f"but meets the {acceptance_ratio:.0%} quality floor"
            )
        return finalize(script)

    logger.info(f"Script below target ({words}/{min_words} words); expanding")
    if not script_cfg.get("model_expansion_enabled", True):
        raise RuntimeError(
            "Script is below its duration target and model expansion is disabled. "
            "No deterministic filler was added."
        )
    expanded = script
    max_attempts = max(1, int(script_cfg.get("model_expansion_attempts", 3)))
    for attempt in range(1, max_attempts + 1):
        previous_words = count_script_words(expanded)
        expanded = expand_script_with_model(
            expanded,
            topic,
            analysis,
            min_words,
            max_words,
            target_segments,
            cfg,
        )
        expanded_words = count_script_words(expanded)
        logger.info(
            f"Script expansion {attempt}/{max_attempts}: "
            f"{previous_words} -> {expanded_words} words"
        )
        if meets_quality_floor(expanded):
            if expanded_words < min_words:
                logger.warning(
                    f"Expanded script is slightly below target ({expanded_words}/{min_words} words) "
                    f"but meets the {acceptance_ratio:.0%} quality floor"
                )
            return finalize(expanded)
        if expanded_words <= previous_words:
            logger.warning("Script expansion made no progress; stopping retries")
            break

    raise RuntimeError(
        f"Script continuation failed quality validation: {count_script_words(expanded)}/{min_words} "
        f"words and {len(expanded.get('segments', []))}/{target_segments} segments. "
        "No fallback content was added."
    )


def consolidate_script_segments(
    script: Dict[str, Any],
    target_segments: int,
) -> Dict[str, Any]:
    """Merge adjacent micro-segments while retaining every narration word."""
    segments = list(script.get("segments") or [])
    target = max(1, int(target_segments))
    if len(segments) <= target:
        return script

    consolidated = []
    total = len(segments)
    for group_index in range(target):
        start = round(group_index * total / target)
        end = round((group_index + 1) * total / target)
        group = segments[start:end]
        if not group:
            continue
        merged = dict(group[0])
        merged["text"] = " ".join(
            str(item.get("text") or "").strip()
            for item in group
            if str(item.get("text") or "").strip()
        )
        consolidated.append(merged)

    result = dict(script)
    result["segments"] = consolidated
    logger.info(
        f"Consolidated narration structure: {len(segments)} -> "
        f"{len(consolidated)} segments without dropping words"
    )
    return result


def expand_script_with_model(
    script: Dict[str, Any],
    topic: str,
    analysis: Dict[str, Any],
    min_words: int,
    max_words: int,
    target_segments: int,
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    current_words = count_script_words(script)
    missing_words = max(0, min_words - current_words)
    missing_segments = max(
        1,
        target_segments - len(script.get("segments", [])),
        math.ceil(missing_words / 35),
    )
    client = get_openai_client()
    response = client.chat.completions.create(
        model=cfg.get("model", "opencode"),
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a documentary script continuation editor. Return only valid JSON with "
                    "one key, segments. Do not rewrite existing narration and do not invent facts."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Add {missing_segments} concise segments totaling {missing_words + 40}-"
                    f"{min(missing_words + 140, max_words - current_words)} words to this script. "
                    "Use only the supplied analysis. Add missing evidence context, counterpoint, implication, "
                    "or synthesis; avoid repetition and filler words. Each segment needs type, text, "
                    "image_prompt, and payoff_min_seconds.\n"
                    f"TOPIC: {topic}\nANALYSIS: {json.dumps(analysis, ensure_ascii=False)[:6000]}\n"
                    f"EXISTING SCRIPT: {json.dumps(script, ensure_ascii=False)[:10000]}"
                ),
            },
        ],
        temperature=0.25,
        **completion_options(cfg),
    )
    if getattr(response.choices[0], "finish_reason", None) == "length":
        raise RuntimeError("Script continuation reached the output limit; no fallback content was added.")
    text = response.choices[0].message.content or ""
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    payload = json.loads(text[text.find("{") : text.rfind("}") + 1])
    additions = payload.get("segments")
    if not isinstance(additions, list) or not additions:
        raise RuntimeError("Script continuation returned no usable segments; no fallback content was added.")
    validated = validate_script({"segments": additions}, topic).get("segments", [])
    if not validated:
        raise RuntimeError("Script continuation segments failed validation; no fallback content was added.")
    result = dict(script)
    existing = list(result.get("segments", []))
    insert_at = max(1, len(existing) - 1)
    result["segments"] = existing[:insert_at] + validated + existing[insert_at:]
    return force_custom_intro_outro(result, load_full_config().get("intro_outro", {}))


def trim_overlong_segments(script: Dict[str, Any], max_words: int) -> Dict[str, Any]:
    """Keep runaway scripts bounded without destroying the outline."""
    if count_script_words(script) <= max_words:
        return script

    segments = script.get("segments", [])
    for segment in segments:
        words = str(segment.get("text", "")).split()
        if len(words) > 75:
            segment["text"] = " ".join(words[:75]).rstrip(" .,") + "."
        if count_script_words(script) <= max_words:
            break
    return script


def apply_narrative_metadata(script: Dict[str, Any], narrative_plan: Dict[str, Any]) -> Dict[str, Any]:
    """Align generated segments with planner beat and delivery metadata."""
    beats = narrative_plan.get("beats", []) if isinstance(narrative_plan, dict) else []
    for index, segment in enumerate(script.get("segments", [])):
        beat = beats[index] if index < len(beats) and isinstance(beats[index], dict) else {}
        segment.setdefault("beat_type", beat.get("beat_type") or infer_beat_type(segment.get("type", "fact")))
        segment.setdefault("beat_purpose", beat.get("purpose", ""))
        segment.setdefault("visual_role_hint", beat.get("visual_role", ""))
        segment["delivery"] = normalize_delivery(segment.get("delivery"), segment.get("type", "fact"), segment.get("beat_type"))

    script["narrative_plan"] = narrative_plan
    if narrative_plan.get("central_question"):
        script["central_question"] = narrative_plan.get("central_question")
    if narrative_plan.get("comment_question"):
        script["comment_question"] = narrative_plan.get("comment_question")
    return script


def revise_script_if_needed(
    script: Dict[str, Any],
    topic: str,
    analysis: Dict[str, Any],
    narrative_plan: Dict[str, Any],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Run a narration critic and revise once if the script misses the voice."""
    critique = critique_script(topic, script, narrative_plan, analysis)
    script["narration_critique"] = critique
    logger.info(
        "Narration critique: "
        f"overall={critique.get('score_overall')}, "
        f"persona={critique.get('persona_score')}, "
        f"revision={critique.get('needs_revision')}"
    )
    if not critique.get("needs_revision"):
        return script

    try:
        client = get_openai_client()
        full_cfg = load_full_config()
        script_cfg = full_cfg.get("script", {})
        response = client.chat.completions.create(
            model=cfg.get("model", "opencode"),
            messages=[
                {"role": "system", "content": SCRIPT_TEMPLATE},
                {
                    "role": "user",
                    "content": (
                        "Revise this script once. Keep the same JSON schema and segment count. "
                        "Preserve source-backed meaning, remove hype, and strengthen the calm technology-documentary narrator. "
                        f"Narrator character: {script_cfg.get('narrator_character', '')}\n"
                        f"Revision instructions: {critique.get('revision_instructions', '')}\n"
                        f"Issues: {json.dumps(critique.get('issues', []), ensure_ascii=False)}\n"
                        f"Narrative plan: {json.dumps(narrative_plan, ensure_ascii=False)[:6000]}\n"
                        f"Script: {json.dumps(script, ensure_ascii=False)[:12000]}"
                    ),
                },
            ],
            temperature=0.35,
            **completion_options(cfg),
        )
        text = response.choices[0].message.content or ""
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()
        revised = json.loads(text[text.find("{") : text.rfind("}") + 1])
        revised = validate_script(revised, topic, narrative_plan=narrative_plan)
        revised = force_custom_intro_outro(revised, load_full_config().get("intro_outro", {}))
        revised = apply_narrative_metadata(revised, narrative_plan)
        revised["narration_critique"] = critique
        logger.info("Narration revised after critic pass")
        return revised
    except Exception as exc:
        logger.warning(f"Narration revision skipped: {exc}")
        return script


def infer_beat_type(segment_type: str) -> str:
    mapping = {
        "hook": "cold_open",
        "fact": "evidence",
        "opinion": "counterpoint",
        "transition": "implication",
        "verdict": "synthesis",
    }
    return mapping.get(segment_type, "evidence")


def normalize_delivery(delivery: Any, segment_type: str = "fact", beat_type: str | None = None) -> Dict[str, Any]:
    """Normalize future-proof delivery metadata for TTS pacing."""
    if not isinstance(delivery, dict):
        delivery = {}

    pause_after = delivery.get("pause_after")
    if pause_after is None:
        if beat_type in {"cold_open", "reflective_turn", "synthesis"} or segment_type in {"hook", "verdict"}:
            pause_after = 0.65
        elif segment_type == "transition":
            pause_after = 0.45
        else:
            pause_after = 0.3

    pace = delivery.get("pace")
    if not pace:
        pace = "measured" if segment_type in {"hook", "verdict", "transition"} else "steady"

    tone = delivery.get("tone") or "calm analytical"
    emphasis = delivery.get("emphasis", [])
    if not isinstance(emphasis, list):
        emphasis = [str(emphasis)]

    return {
        "pace": str(pace),
        "tone": str(tone),
        "pause_after": max(0.0, min(1.5, float(pause_after))),
        "emphasis": [str(item) for item in emphasis[:5]],
    }


def estimate_duration(script: Dict[str, Any]) -> float:
    """Estimate video duration from script.
    
    Args:
        script: Script dictionary
        
    Returns:
        Estimated duration in seconds
    """
    total_words = 0
    
    for segment in script.get("segments", []):
        text = segment.get("text", "")
        words = len(text.split())
        total_words += words
    
    # Average speaking pace: ~150 words/minute = 2.5 words/second
    words_per_second = 2.5
    
    return total_words / words_per_second


def get_segment_image_prompts(script: Dict[str, Any]) -> List[str]:
    """Extract all image prompts from script.
    
    Args:
        script: Script dictionary
        
    Returns:
        List of image prompts
    """
    prompts = []
    
    for segment in script.get("segments", []):
        prompt = segment.get("image_prompt", "")
        if prompt:
            prompts.append(prompt)
    
    return prompts
