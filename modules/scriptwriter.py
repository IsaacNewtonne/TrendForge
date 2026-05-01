"""TrendForge - Script Generation Module

Generates structured video scripts from analysis data using AI with viral hook patterns.
"""

import json
import yaml
import random
import re
from pathlib import Path
from typing import Dict, List, Any
from loguru import logger

import openai

from modules.narrative_planner import build_narrative_plan, critique_script

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
    base_url = cfg.get("base_url", "http://localhost:11434/v1")
    api_key = cfg.get("api_key", "local")
    client = openai.OpenAI(base_url=base_url, api_key=api_key)
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
    if not max_tokens or int(max_tokens) <= 0:
        return {}
    return {"max_tokens": int(max_tokens)}


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


def load_opencode_config() -> dict:
    """Load OpenCode/API configuration."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f)
            return cfg.get("opencode", {})
    return {}


def get_openai_client() -> openai.OpenAI:
    """Create OpenAI client configured for OpenCode."""
    cfg = load_opencode_config()
    
    base_url = cfg.get("base_url", "http://localhost:11434/v1")
    api_key = cfg.get("api_key", "local")
    
    client = openai.OpenAI(
        base_url=base_url,
        api_key=api_key
    )
    
    return client


def generate_script(topic: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a video script from topic and analysis.
    
    Requires OpenCode to be running. Will FAIL if OpenCode unavailable.
    
    Args:
        topic: The video topic
        analysis: Fact/opinion analysis dictionary
        
    Returns:
        Script dictionary with segments
        
    Raises:
        RuntimeError: If OpenCode is not available
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
    
    # Try OpenCode - FAIL if unavailable
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
        
        result_text = response.choices[0].message.content
        
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
                # Last resort: create minimal valid script
                logger.warning("Creating fallback script due to parse failure")
                script = {
                    "title": topic,
                    "segments": [
                        {"type": "hook", "text": f"Here are {len(topic.split())} key things about {topic}", "duration": 5},
                        {"type": "fact", "text": topic, "duration": 10}
                    ],
                    " conclusion": f"Stay tuned for more about {topic}"
                }
        
        script = validate_script(script, topic, narrative_plan=narrative_plan)
        
        # Keep explicit intro/outro narration so silent clips can carry audio.
        script = force_custom_intro_outro(script, full_cfg.get("intro_outro", {}))
        script = enforce_script_length(script, topic, analysis, min_words, max_words, target_segments, cfg)
        script = apply_narrative_metadata(script, narrative_plan)
        script = revise_script_if_needed(script, topic, analysis, narrative_plan, cfg)
        
        logger.info(
            f"Script generated: {len(script.get('segments', []))} segments, "
            f"{count_script_words(script)} words, estimated {estimate_duration(script):.1f}s"
        )
        return script
            
    except Exception as e:
        logger.error(f"OpenCode unavailable: {e}")
        raise RuntimeError(
            f"OpenCode is required but unavailable. Ensure 'opencode serve' is running.\n"
            f"Error: {e}"
        )


def generate_fallback_script(topic: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a fallback script when API is unavailable.
    
    Args:
        topic: The video topic
        analysis: Fact/opinion analysis
        
    Returns:
        Fallback script dictionary
    """
    facts = analysis.get("facts", [])
    opinions = analysis.get("opinions", [])
    verdict = analysis.get("verdict", f"Learn more about {topic} to form your own opinion.")
    
    segments = []
    
    # Hook - using provided intro text
    segments.append({
        "type": "hook",
        "text": "Welcome to Trend Forge — where the latest trends, viral moments, and what’s next are forged into quick, clear updates.\n\nLet’s get into it.",
        "image_prompt": f"{topic} concept, cinematic, dramatic lighting, 4K"
    })
    
    # Facts
    for fact in facts[:3]:
        if fact and len(fact) > 10:
            segments.append({
                "type": "fact",
                "text": str(fact),
                "image_prompt": f"{topic} {fact[:30]}, cinematic, informative, 4K"
            })
    
    # Transition
    segments.append({
        "type": "transition",
        "text": "But not everyone sees it the same way.",
        "image_prompt": f"Split view, {topic}, contrasting perspectives, 4K"
    })
    
    # Opinions
    for opinion in opinions[:3]:
        if opinion and len(opinion) > 10:
            segments.append({
                "type": "opinion",
                "text": str(opinion),
                "image_prompt": f"Expert opinion, {opinion[:30]}, interview style, 4K"
            })
    
    # Verdict - using provided outro text
    segments.append({
        "type": "verdict",
        "text": "That’s it for today from Trend Forge.\n\nSubscribe for the latest trends, viral moments, and what’s next.\n\nSee you in the next one.",
        "image_prompt": f"Conclusion, balanced view, {topic}, thoughtful, 4K"
    })
    
    narrative_plan = analysis.get("narrative_plan") if isinstance(analysis.get("narrative_plan"), dict) else build_narrative_plan(topic, analysis, analysis.get("source_plan"))
    script = {
        "topic": topic,
        "title": f"The Truth About {topic.title()}",
        "hook": segments[0]["text"],
        "segments": segments,
        "outro": "That’s it for today from Trend Forge.\n\nSubscribe for the latest trends, viral moments, and what’s next.\n\nSee you in the next one.",
        "confidence": analysis.get("confidence", 50)
    }
    
    logger.info(f"Fallback script generated: {len(segments)} segments")
    return apply_narrative_metadata(script, narrative_plan)


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
    words = count_script_words(script)
    if words >= min_words and len(script.get("segments", [])) >= max(10, target_segments - 4):
        return trim_overlong_segments(script, max_words)

    logger.info(f"Script below target ({words}/{min_words} words); expanding")
    expanded = expand_script_with_model(script, topic, analysis, min_words, max_words, target_segments, cfg)
    if count_script_words(expanded) >= min_words:
        return trim_overlong_segments(expanded, max_words)

    logger.warning("Model expansion did not meet target; using deterministic expansion")
    return trim_overlong_segments(
        deterministic_expand_script(expanded, topic, analysis, min_words, target_segments),
        max_words,
    )


def expand_script_with_model(
    script: Dict[str, Any],
    topic: str,
    analysis: Dict[str, Any],
    min_words: int,
    max_words: int,
    target_segments: int,
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        script_cfg = load_full_config().get("script", {})
        narrator_character = script_cfg.get(
            "narrator_character",
            "A calm technology documentary host: intelligent, composed, curious, analytical, smooth, reflective, professional, slightly mysterious, polished, and trustworthy. Avoid hype, jokes, shouting, slang, clickbait, and influencer-style energy.",
        )
        client = get_openai_client()
        response = client.chat.completions.create(
            model=cfg.get("model", "opencode"),
            messages=[
                {"role": "system", "content": SCRIPT_TEMPLATE},
                {
                    "role": "user",
                    "content": (
                        "Expand this JSON script into a coherent five-minute narration. "
                        f"Keep valid JSON. Use {target_segments} segments and {min_words}-{max_words} words. "
                        "Add evidence context, counterpoints, a reflective turn, synthesis, and a comment prompt. "
                        f"Maintain this narrator character throughout: {narrator_character}\n\n"
                        f"TOPIC: {topic}\nANALYSIS: {json.dumps(analysis)[:6000]}\n"
                        f"SCRIPT: {json.dumps(script)[:8000]}"
                    ),
                },
            ],
            temperature=cfg.get("temperature", 0.7),
            **completion_options(cfg),
        )
        text = response.choices[0].message.content or ""
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()
        expanded = json.loads(text[text.find("{") : text.rfind("}") + 1])
        expanded = validate_script(expanded, topic)
        return force_custom_intro_outro(expanded, load_full_config().get("intro_outro", {}))
    except Exception as exc:
        logger.warning(f"Script expansion failed: {exc}")
        return script


def deterministic_expand_script(
    script: Dict[str, Any],
    topic: str,
    analysis: Dict[str, Any],
    min_words: int,
    target_segments: int,
) -> Dict[str, Any]:
    """Build extra grounded segments from analysis when the model under-writes."""
    segments = list(script.get("segments", []))
    if not segments:
        segments = [{"type": "hook", "text": CUSTOM_INTRO_TEXT, "image_prompt": topic, "payoff_min_seconds": 0}]

    facts = [str(item) for item in analysis.get("facts", []) if str(item).strip()]
    opinions = [str(item) for item in analysis.get("opinions", []) if str(item).strip()]
    conflicts = [str(item) for item in analysis.get("conflicts", []) if str(item).strip()]
    verdict = str(analysis.get("verdict", "")).strip()
    source_items = facts + opinions + conflicts

    insert_at = max(1, len(segments) - 1)
    cursor = 0
    while count_script_words({"segments": segments}) < min_words or len(segments) < target_segments:
        item = source_items[cursor % len(source_items)] if source_items else topic
        if cursor % 4 == 0:
            text = (
                f"This is the part of {topic} that deserves a slower look. {item} "
                "By itself, it may seem like another isolated signal. But placed beside the rest of the evidence, it begins to reveal the deeper structure of the story."
            )
            seg_type = "fact"
        elif cursor % 4 == 1:
            text = (
                f"Imagine this playing out quietly in an ordinary day. A decision that once felt abstract becomes a tool, a cost, a habit, a career question, or a private concern. "
                f"That is where {topic} stops being a surface-level trend and becomes part of the machinery of modern life."
            )
            seg_type = "transition"
        elif cursor % 4 == 2:
            text = (
                f"The careful counterpoint is this: not every concern around {topic} is proven, and not every optimistic claim should be dismissed. "
                f"{item} The honest answer sits in the space between what is documented and what people believe may happen next."
            )
            seg_type = "opinion"
        else:
            text = (
                f"So the useful question is not simply whether {topic} is good or bad. It is who benefits, who absorbs the risk, and what evidence would change a reasonable mind. "
                f"{verdict or item}"
            )
            seg_type = "verdict"

        segments.insert(insert_at, {
            "type": seg_type,
            "text": text,
            "image_prompt": f"{topic}, {seg_type}, documentary editorial visual, no text",
            "payoff_min_seconds": 120,
        })
        insert_at += 1
        cursor += 1
        if cursor > 40:
            break

    script["segments"] = segments
    return script


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
