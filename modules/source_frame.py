"""Polished evidence frames for accepted source screenshots."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFilter

from modules.source_card import (
    COLORS,
    HEIGHT,
    WIDTH,
    clean_text,
    clean_url,
    fit_text,
    font,
    load_brand_logo,
    source_palette,
    text_width,
    wrap_text,
)


def create_evidence_frame(screenshot_path: Path, output_path: Path, segment: Dict[str, Any]) -> str:
    """Wrap a raw source screenshot in a video-ready evidence composition."""
    with Image.open(screenshot_path) as source_image:
        screenshot = source_image.convert("RGB")
    title = clean_text(segment.get("source_title") or segment.get("visual_prompt") or segment.get("claim") or "Source evidence")
    raw_url = clean_text(segment.get("source_url") or "")
    domain = clean_text(urlparse(raw_url).netloc.replace("www.", ""))
    source = clean_text(segment.get("source_name") or domain or "Source")
    palette = source_palette(source or domain or title)

    canvas = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background"])
    draw_evidence_background(canvas, screenshot, palette)

    draw = ImageDraw.Draw(canvas, "RGBA")
    layout = layout_for_segment(segment)
    if layout == "left_text":
        text_box = (104, 150, 620, 780)
        shot_box = (660, 138, 1812, 920)
    else:
        text_box = (1160, 150, 1815, 820)
        shot_box = (108, 138, 1110, 920)

    draw_text_stack(draw, text_box, title, source, domain, raw_url, palette)
    draw_screenshot_panel(canvas, screenshot, shot_box, palette)
    draw_brand_mark(canvas)
    draw_footer(draw, clean_url(raw_url), palette)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return str(output_path)


def draw_brand_mark(canvas: Image.Image) -> None:
    logo = load_brand_logo(118, opacity=0.9)
    if logo is None:
        return

    x = WIDTH - logo.width - 118
    y = 58
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    glow = Image.new("RGBA", logo.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow, "RGBA")
    glow_draw.ellipse((6, 6, logo.width - 6, logo.height - 6), fill=(30, 151, 255, 36))
    overlay.alpha_composite(glow.filter(ImageFilter.GaussianBlur(14)), (x, y))
    overlay.alpha_composite(logo, (x, y))
    canvas.paste(Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB"))


def draw_evidence_background(
    canvas: Image.Image,
    screenshot: Image.Image,
    palette: Dict[str, tuple[int, int, int]],
) -> None:
    bg = cover_image(screenshot, WIDTH, HEIGHT).filter(ImageFilter.GaussianBlur(26))
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (5, 7, 13, 218))
    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow, "RGBA")
    glow_draw.ellipse((-260, -160, 760, 620), fill=(*palette["primary"], 60))
    glow_draw.ellipse((1180, 420, 2220, 1260), fill=(*palette["cyan"], 44))
    glow_draw.ellipse((640, 820, 1360, 1200), fill=(*palette["accent"], 28))
    composed = Image.alpha_composite(bg.convert("RGBA"), overlay)
    composed = Image.alpha_composite(composed, glow.filter(ImageFilter.GaussianBlur(34)))
    canvas.paste(composed.convert("RGB"))

    draw = ImageDraw.Draw(canvas, "RGBA")
    for y in range(HEIGHT):
        ratio = y / max(1, HEIGHT - 1)
        draw.line((0, y, WIDTH, y), fill=(0, 18, 42, int(22 * ratio)))
    for x in range(-200, WIDTH, 86):
        draw.line((x, 0, x + 520, HEIGHT), fill=(255, 255, 255, 10), width=1)


def draw_screenshot_panel(
    canvas: Image.Image,
    screenshot: Image.Image,
    box: tuple[int, int, int, int],
    palette: Dict[str, tuple[int, int, int]],
) -> None:
    x1, y1, x2, y2 = box
    panel_w = x2 - x1
    panel_h = y2 - y1
    shot = contain_image(screenshot, panel_w, panel_h)

    panel = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow, "RGBA")
    shadow_draw.rounded_rectangle((x1 + 14, y1 + 22, x2 + 14, y2 + 22), radius=30, fill=(0, 0, 0, 170))
    panel.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(22)))

    draw = ImageDraw.Draw(panel, "RGBA")
    draw.rounded_rectangle((x1, y1, x2, y2), radius=30, fill=(8, 10, 16, 245), outline=(*palette["cyan"], 180), width=2)
    draw.rounded_rectangle((x1 + 12, y1 + 12, x2 - 12, y2 - 12), radius=22, fill=(255, 255, 255, 255))

    shot_x = x1 + 12 + (panel_w - 24 - shot.width) // 2
    shot_y = y1 + 12 + (panel_h - 24 - shot.height) // 2
    panel.alpha_composite(shot.convert("RGBA"), (shot_x, shot_y))
    draw.rounded_rectangle((x1, y1, x2, y2), radius=30, outline=(255, 255, 255, 42), width=1)
    canvas.paste(Image.alpha_composite(canvas.convert("RGBA"), panel).convert("RGB"))


def draw_text_stack(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    source: str,
    domain: str,
    raw_url: str,
    palette: Dict[str, tuple[int, int, int]],
) -> None:
    x1, y1, x2, _ = box
    label_font = font(28, bold=True)
    source_font = font(38, bold=True)
    title_font = font(62, bold=True)
    meta_font = font(30)

    badge_text = "SOURCE RECEIPT"
    badge_w = text_width(draw, badge_text, label_font) + 34
    draw.rounded_rectangle((x1, y1, x1 + badge_w, y1 + 42), radius=18, fill=(*palette["cyan"], 50), outline=(*palette["cyan"], 180), width=1)
    draw.text((x1 + 17, y1 + 7), badge_text, font=label_font, fill=palette["cyan"])

    source_y = y1 + 76
    draw.text((x1, source_y), fit_text(draw, source, source_font, x2 - x1), font=source_font, fill=COLORS["text"])
    if domain:
        draw.text((x1, source_y + 50), fit_text(draw, domain, meta_font, x2 - x1), font=meta_font, fill=COLORS["muted"])

    title_y = source_y + 116
    title_lines = wrap_text(draw, title, title_font, x2 - x1, 5)
    for line in title_lines:
        draw.text((x1, title_y), line, font=title_font, fill=COLORS["text"])
        title_y += 72

    draw.line((x1, title_y + 18, min(x2, x1 + 420), title_y + 18), fill=(*palette["accent"], 210), width=4)
    url = clean_url(raw_url)
    if url:
        draw.text((x1, title_y + 48), fit_text(draw, url, meta_font, x2 - x1), font=meta_font, fill=COLORS["muted"])


def draw_footer(draw: ImageDraw.ImageDraw, url: str, palette: Dict[str, tuple[int, int, int]]) -> None:
    small = font(24, bold=True)
    value_font = font(26)
    draw.rounded_rectangle((106, 974, 1814, 1030), radius=18, fill=(9, 12, 22, 170), outline=(255, 255, 255, 22), width=1)
    draw.text((134, 990), "VERIFIED VISUAL EVIDENCE", font=small, fill=palette["cyan"])
    if url:
        draw.text((520, 990), fit_text(draw, url, value_font, 1230), font=value_font, fill=COLORS["muted"])


def layout_for_segment(segment: Dict[str, Any]) -> str:
    key = str(segment.get("id") or segment.get("source_url") or segment.get("source_title") or "")
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return "left_text" if digest[0] % 2 == 0 else "right_text"


def cover_image(image: Image.Image, width: int, height: int) -> Image.Image:
    scale = max(width / image.width, height / image.height)
    resized = image.resize((int(image.width * scale), int(image.height * scale)), Image.Resampling.LANCZOS)
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def contain_image(image: Image.Image, width: int, height: int) -> Image.Image:
    scale = min(width / image.width, height / image.height)
    return image.resize((int(image.width * scale), int(image.height * scale)), Image.Resampling.LANCZOS)
