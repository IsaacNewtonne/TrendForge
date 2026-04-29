"""TrendForge - Viral Thumbnail Generator Module

Generates 3 CTR-optimized YouTube thumbnails per video:
- Shock: Bold headline with accent, warm glow, underline
- Versus: Red vs blue split for comparisons  
- Reveal: Mystery question format with accent streak

With emotion-to-colour mapping and vignette/glow/film grain effects.
"""

import os
import re
import yaml
from pathlib import Path
from typing import Optional, Any, List, Dict
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
from loguru import logger
from datetime import datetime
import random

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

# Emotion-to-colour mapping for virality
EMOTION_PALETTES = {
    "shock": {"bg": (15, 15, 20), "accent": (255, 50, 50), "text": (255, 255, 255), "glow": (255, 100, 50)},
    "danger": {"bg": (20, 10, 10), "accent": (220, 40, 40), "text": (255, 220, 220), "glow": (200, 60, 60)},
    "money": {"bg": (10, 20, 15), "accent": (0, 200, 100), "text": (200, 255, 220), "glow": (50, 220, 150)},
    "ai": {"bg": (15, 15, 35), "accent": (100, 100, 255), "text": (220, 220, 255), "glow": (120, 120, 255)},
    "curiosity": {"bg": (20, 20, 30), "accent": (255, 180, 50), "text": (255, 250, 220), "glow": (255, 200, 100)},
    "default": {"bg": (20, 20, 30), "accent": (127, 106, 183), "text": (255, 255, 255), "glow": (150, 130, 200)},
}


def load_thumbnail_config() -> dict:
    """Load thumbnail configuration."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f).get("video", {})
    return {}


def detect_emotion(text: str) -> str:
    """Detect emotion from text to choose best palette.
    
    Args:
        text: Topic or title text
        
    Returns:
        Emotion key (shock, danger, money, ai, curiosity, default)
    """
    text_lower = text.lower()
    
    # Shock keywords
    if any(w in text_lower for w in ["exposed", "scandal", "truth", "secret", "lie", "fake", "wrong"]):
        return "shock"
    
    # Danger keywords
    if any(w in text_lower for w in ["danger", "risk", "warning", "death", "harm", "avoid", "stop"]):
        return "danger"
    
    # Money keywords
    if any(w in text_lower for w in ["money", "rich", "profit", "cost", "earn", "save", "free"]):
        return "money"
    
    # AI keywords
    if any(w in text_lower for w in ["ai", "gpt", "chatgpt", "openai", "claude", "gemini", "robot", "automation"]):
        return "ai"
    
    # Curiosity keywords
    if any(w in text_lower for w in ["why", "how", "what", "reason", "secret", "mystery", "discover"]):
        return "curiosity"
    
    return "default"


def get_palette(emotion: str = "default") -> dict:
    """Get colour palette for emotion.
    
    Args:
        emotion: Emotion key
        
    Returns:
        Palette dict with bg, accent, text, glow colours
    """
    return EMOTION_PALETTES.get(emotion, EMOTION_PALETTES["default"])


def generate_thumbnail(topic: str, frame_path: Optional[str] = None) -> str:
    """Generate main thumbnail (legacy single output).
    
    Args:
        topic: Video topic
        frame_path: Optional frame to use
        
    Returns:
        Thumbnail path
    """
    variants = generate_thumbnail_variants(topic, frame_path)
    return variants[0]["path"]


def generate_thumbnail_variants(topic: str, frame_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Generate 3 viral thumbnail variants.
    
    Args:
        topic: Video topic
        frame_path: Optional frame for base
        
    Returns:
        List of variant dicts with 'type', 'path', 'score'
    """
    cfg = load_thumbnail_config()
    width = 1280
    height = 720
    
    output_dir = Path("./output/")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_topic = sanitize_topic(topic)
    
    # Detect emotion
    emotion = detect_emotion(topic)
    palette = get_palette(emotion)
    
    # Clean topic text for display
    display_topic = clean_topic_for_thumbnail(topic)
    
    variants = []
    
    # 1. SHOCK variant
    shock_path = output_dir / f"{timestamp}_{safe_topic}_thumb_shock.jpg"
    create_shock_variant(display_topic, palette, width, height, str(shock_path))
    score = score_thumbnail_ctr_estimate("shock", topic)
    variants.append({"type": "shock", "path": str(shock_path), "score": score})
    
    # 2. VERSUS variant  
    versus_path = output_dir / f"{timestamp}_{safe_topic}_thumb_versus.jpg"
    create_versus_variant(display_topic, palette, width, height, str(versus_path))
    score = score_thumbnail_ctr_estimate("versus", topic)
    variants.append({"type": "versus", "path": str(versus_path), "score": score})
    
    # 3. REVEAL variant
    reveal_path = output_dir / f"{timestamp}_{safe_topic}_thumb_reveal.jpg"
    create_reveal_variant(display_topic, palette, width, height, str(reveal_path))
    score = score_thumbnail_ctr_estimate("reveal", topic)
    variants.append({"type": "reveal", "path": str(reveal_path), "score": score})
    
    # Sort by score (best first)
    variants.sort(key=lambda x: x["score"], reverse=True)
    
    logger.info(f"Generated {len(variants)} thumbnail variants")
    return variants


def create_shock_variant(text: str, palette: dict, width: int, height: int, output: str):
    """Create SHOCK variant - bold headline with warning accent.
    
    Args:
        text: Topic text
        palette: Colour palette
        width: Image width
        height: Image height
        output: Output path
    """
    from PIL import ImageOps
    
    # Create base with gradient
    img = create_gradient_base(width, height, palette["bg"], (30, 30, 45))
    draw = ImageDraw.Draw(img)
    
    # Add vignette
    add_vignette(img, strength=0.4)
    
    # Top accent bar
    bar_height = 8
    draw.rectangle([(0, 0), (width, bar_height)], fill=palette["accent"])
    
    # Warning badge
    badge = "⚠ EXPOSED"
    try:
        font_badge = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
    except:
        font_badge = ImageFont.load_default()
    
    badge_w = draw.textlength(badge, font_badge)
    draw.text(((width - badge_w) // 2, 30), badge, fill=palette["accent"], font=font_badge)
    
    # Main text - big and bold
    lines = wrap_text(text, width - 100, font_size=56)
    y_offset = height // 2 - (len(lines) * 50)
    
    try:
        font_main = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 56)
    except:
        font_main = ImageFont.load_default()
    
    for line in lines:
        text_w = draw.textlength(line, font_main)
        x = (width - text_w) // 2
        # Outline
        for adj in [(-3, -3), (-3, 3), (3, -3), (3, 3)]:
            draw.text((x + adj[0], y_offset + adj[1]), line, fill=(0, 0, 0), font=font_main)
        draw.text((x, y_offset), line, fill=palette["text"], font=font_main)
        
        # Accent underline
        underline_y = y_offset + 65
        draw.line([(x - 20, underline_y), (x + text_w + 20, underline_y)], 
                 fill=palette["accent"], width=4)
        
        y_offset += 70
    
    # Glow effect
    add_glow(img, palette["glow"])
    
    # Film grain
    add_film_grain(img, strength=15)
    
    img.save(output, "JPEG", quality=92)


def create_versus_variant(text: str, palette: dict, width: int, height: int, output: str):
    """Create VERSUS variant - red vs blue split.

    Args:
        text: Topic text
        palette: Colour palette  
        width: Image width
        height: Image height
        output: Output path
    """
    img = Image.new("RGB", (width, height), palette["bg"])
    draw = ImageDraw.Draw(img)
    
    # Split line at 60% from left
    split_x = int(width * 0.6)
    
    # Left side - warm (red tinted)
    left_color = (180, 40, 40)
    draw.rectangle([(0, 0), (split_x, height)], fill=left_color)
    
    # Right side - cool (blue tinted)
    right_color = (40, 60, 120)
    draw.rectangle([(split_x, 0), (width, height)], fill=right_color)
    
    # VS in middle
    vs_text = "VS"
    try:
        font_vs = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80)
    except:
        font_vs = ImageFont.load_default()
    
    vs_w = draw.textlength(vs_text, font_vs)
    vs_x = split_x - vs_w // 2
    vs_y = height // 2 - 40
    
    # VS outline
    for adj in [(-4, -4), (-4, 4), (4, -4), (4, 4)]:
        draw.text((vs_x + adj[0], vs_y + adj[1]), vs_text, fill=(255, 255, 255), font=font_vs)
    draw.text((vs_x, vs_y), vs_text, fill=(255, 255, 255), font=font_vs)
    
    # Split line
    draw.line([(split_x, 0), (split_x, height)], fill=(255, 255, 255), width=6)
    
    # Topic on left side (abbreviated)
    short_text = text[:30] + "..." if len(text) > 30 else text
    try:
        font_topic = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
    except:
        font_topic = ImageFont.load_default()
    
    topic_w = draw.textlength(short_text, font_topic)
    draw.text(((split_x - topic_w) // 2, height - 100), short_text, fill=(255, 255, 255), font=font_topic)
    
    add_vignette(img, strength=0.3)
    add_film_grain(img, strength=12)
    
    img.save(output, "JPEG", quality=92)


def create_reveal_variant(text: str, palette: dict, width: int, height: int, output: str):
    """Create REVEAL variant - mystery question with accent streak.
    
    Args:
        text: Topic text
        palette: Colour palette
        width: Image width
        height: Image height
        output: Output path
    """
    img = create_gradient_base(width, height, palette["bg"], (25, 25, 40))
    draw = ImageDraw.Draw(img)
    
    add_vignette(img, strength=0.35)
    
    # Top accent streak
    streak_height = 12
    draw.rectangle([(0, 0), (width, streak_height)], fill=palette["accent"])
    
    # Question mark watermark
    qm = "?"
    try:
        font_qm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 200)
    except:
        font_qm = ImageFont.load_default()
    
    qm_w = draw.textlength(qm, font_qm)
    draw.text(((width - qm_w) // 2, height // 2 - 80), qm, fill=(255, 255, 255, 30), font=font_qm)
    
    # Question headline
    question = f"What's the truth about {text}?"
    lines = wrap_text(question, width - 120, font_size=44)
    y_offset = 60
    
    try:
        font_q = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 44)
    except:
        font_q = ImageFont.load_default()
    
    for line in lines:
        text_w = draw.textlength(line, font_q)
        x = (width - text_w) // 2
        # Outline
        for adj in [(-2, -2), (-2, 2), (2, -2), (2, 2)]:
            draw.text((x + adj[0], y_offset + adj[1]), line, fill=(0, 0, 0), font=font_q)
        draw.text((x, y_offset), line, fill=palette["accent"], font=font_q)
        y_offset += 55
    
    # Bottom accent bar
    bar_y = height - 60
    bar_width = 300
    bar_x = (width - bar_width) // 2
    draw.rectangle([(bar_x, bar_y), (bar_x + bar_width, bar_y + 4)], fill=palette["accent"])
    
    add_glow(img, palette["glow"])
    add_film_grain(img, strength=10)
    
    img.save(output, "JPEG", quality=92)


def create_gradient_base(width: int, height: int, color1: tuple, color2: tuple) -> Image.Image:
    """Create gradient background.
    
    Args:
        width: Image width
        height: Image height
        color1: Top/left colour
        color2: Bottom/right colour
        
    Returns:
        PIL Image
    """
    base = Image.new("RGB", (width, height), color1)
    
    # Simple horizontal gradient
    for y in range(height):
        ratio = y / height
        r = int(color1[0] * (1 - ratio) + color2[0] * ratio)
        g = int(color1[1] * (1 - ratio) + color2[1] * ratio)
        b = int(color1[2] * (1 - ratio) + color2[2] * ratio)
        
        for x in range(width):
            base.putpixel((x, y), (r, g, b))
    
    return base


def add_vignette(img: Image.Image, strength: float = 0.4):
    """Add vignette effect.
    
    Args:
        img: PIL Image
        strength: Vignette strength 0-1
    """
    width, height = img.size
    mask = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(mask)
    
    # Draw darkening ellipse
    for y in range(height):
        for x in range(width):
            # Distance from center
            dx = (x - width/2) / (width/2)
            dy = (y - height/2) / (height/2)
            dist = (dx**2 + dy**2) ** 0.5
            
            if dist > 0.5:
                # Darken towards edges
                factor = min(1.0, (dist - 0.5) * 2 * strength)
                v = int(255 * (1 - factor))
                if mask.getpixel((x, y)) > v:
                    mask.putpixel((x, y), v)
    
    # Apply as darkened overlay
    img.putalpha(255)


def add_glow(img: Image.Image, color: tuple):
    """Add subtle glow effect (placeholder - basic implementation).
    
    Args:
        img: PIL Image
        color: Glow colour RGB
    """
    # Add simple blur for glow feel
    try:
        img = img.filter(ImageFilter.GaussianBlur(radius=2))
    except:
        pass


def add_film_grain(img: Image.Image, strength: int = 12):
    """Add film grain effect.
    
    Args:
        img: PIL Image
        strength: Grain intensity (0-100)
    """
    import random
    
    # Convert to RGB if needed (handles both RGB and RGBA)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    
    # Make a copy to avoid modifying original
    img = img.convert("RGBA")
    
    width, height = img.size
    pixels = img.load()
    
    for y in range(height):
        for x in range(width):
            if random.randint(0, 100) < strength:
                r, g, b, a = pixels[x, y]  # Handle RGBA
                noise = random.randint(-strength, strength)
                r = max(0, min(255, r + noise))
                g = max(0, min(255, g + noise))
                b = max(0, min(255, b + noise))
                pixels[x, y] = (r, g, b, a)


def wrap_text(text: str, max_width: int, font_size: int = 56) -> List[str]:
    """Wrap text to fit within max width.
    
    Args:
        text: Text to wrap
        max_width: Max pixel width
        font_size: Font size for estimation
        
    Returns:
        List of text lines
    """
    # Simple word wrap
    words = text.split()
    lines = []
    current_line = ""
    
    # Approximate char width
    char_width = font_size * 0.6
    
    for word in words:
        test_line = current_line + " " + word if current_line else word
        if len(test_line) * char_width < max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    
    if current_line:
        lines.append(current_line)
    
    # Limit to 3 lines max
    return lines[:3]


def sanitize_topic(topic: str) -> str:
    """Sanitize topic for filename.
    
    Args:
        topic: Original topic
        
    Returns:
        Sanitized topic
    """
    topic = re.sub(r"\s+", "_", topic)
    topic = re.sub(r"[^a-zA-Z0-9_\-]", "", topic)
    return topic[:30]


def clean_topic_for_thumbnail(text: str) -> str:
    """Clean topic text for thumbnail display.
    
    Args:
        text: Raw topic text
        
    Returns:
        Cleaned text
    """
    # Capitalize words
    text = " ".join(w.capitalize() for w in text.split())
    
    # Limit length
    if len(text) > 45:
        text = text[:42] + "..."
    
    return text


def score_thumbnail_ctr_estimate(variant_type: str, topic: str) -> int:
    """Estimate CTR score for thumbnail variant.
    
    Args:
        variant_type: shock, versus, reveal
        topic: Topic text
        
    Returns:
        Score 0-100
    """
    base_scores = {"shock": 85, "versus": 80, "reveal": 75}
    base = base_scores.get(variant_type, 70)
    
    # Boost for emotion keywords
    emotion = detect_emotion(topic)
    boosts = {"shock": 10, "danger": 8, "money": 12, "ai": 5, "curiosity": 7}
    boost = boosts.get(emotion, 0)
    
    return min(100, base + boost)


def generate_thumbnail_options(topic: str, frame_paths: list) -> list:
    """Generate multiple thumbnail options (legacy wrapper).
    
    Args:
        topic: Video topic
        frame_paths: List of frame paths (ignored now)
        
    Returns:
        List of thumbnail paths
    """
    variants = generate_thumbnail_variants(topic)
    return [v["path"] for v in variants]


def apply_branding(img: Image.Image, brand_color: tuple = (83, 74, 183)) -> Image.Image:
    """Apply TrendForge branding to image.
    
    Args:
        img: Input image
        brand_color: Brand RGB color
        
    Returns:
        Branded image
    """
    draw = ImageDraw.Draw(img)
    width, height = img.size
    
    # Brand bar on left
    draw.rectangle([(0, 0), (8, height)], fill=brand_color)
    
    return img