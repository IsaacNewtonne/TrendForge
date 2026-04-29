"""Branded source-card visuals for evidence-backed video segments."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1920
HEIGHT = 1080

COLORS = {
    "background": (13, 13, 18),
    "surface": (22, 22, 29),
    "surface_2": (31, 31, 42),
    "primary": (83, 74, 183),
    "accent": (239, 159, 39),
    "text": (255, 255, 255),
    "muted": (160, 160, 176),
    "border": (42, 42, 53),
}


def create_source_card(segment: Dict[str, Any], output_path: Path) -> str:
    """Render a clean video-ready card from extracted article metadata."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    source = clean_text(segment.get("source_name") or "Source")
    title = clean_text(segment.get("source_title") or segment.get("visual_prompt") or segment.get("claim") or "Source update")
    summary = clean_text(segment.get("source_summary") or segment.get("source_excerpt") or segment.get("claim") or "")
    date = clean_text(segment.get("source_published") or segment.get("published") or "")
    url = clean_url(segment.get("source_url") or "")
    domain = clean_text(urlparse(segment.get("source_url") or "").netloc.replace("www.", ""))

    image = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background"])
    draw = ImageDraw.Draw(image, "RGBA")
    draw_background(draw)

    margin = 118
    card = (margin, 112, WIDTH - margin, HEIGHT - 112)
    draw.rounded_rectangle(card, radius=18, fill=COLORS["surface"], outline=COLORS["border"], width=2)

    # Accent rail and source mark.
    draw.rounded_rectangle((card[0], card[1], card[0] + 12, card[3]), radius=8, fill=COLORS["accent"])
    badge = (card[0] + 58, card[1] + 58, card[0] + 190, card[1] + 190)
    badge_color = source_color(source or domain or title)
    draw.rounded_rectangle(badge, radius=18, fill=badge_color)

    font_source = font(38, bold=True)
    font_badge = font(48, bold=True)
    font_title = font(70, bold=True)
    font_summary = font(34)
    font_meta = font(28)
    font_url = font(24)

    initials = source_initials(source or domain)
    center_text(draw, initials, badge, font_badge, COLORS["text"])

    source_x = badge[2] + 34
    draw.text((source_x, card[1] + 66), source, font=font_source, fill=COLORS["text"])
    meta = " • ".join(part for part in [date, domain] if part)
    if meta:
        draw.text((source_x, card[1] + 120), meta, font=font_meta, fill=COLORS["muted"])

    title_box = (card[0] + 58, card[1] + 245, card[2] - 58, card[1] + 520)
    draw_wrapped_text(draw, title, title_box, font_title, COLORS["text"], max_lines=4)

    summary_box = (card[0] + 62, card[1] + 575, card[2] - 62, card[1] + 760)
    draw_wrapped_text(draw, summary, summary_box, font_summary, COLORS["muted"], max_lines=4)

    footer_y = card[3] - 92
    draw.line((card[0] + 58, footer_y - 28, card[2] - 58, footer_y - 28), fill=(*COLORS["border"], 255), width=2)
    draw.text((card[0] + 62, footer_y), "SOURCE", font=font_url, fill=COLORS["accent"])
    draw.text((card[0] + 185, footer_y), url or domain, font=font_url, fill=COLORS["muted"])

    image.save(output_path)
    return str(output_path)


def draw_background(draw: ImageDraw.ImageDraw):
    for y in range(HEIGHT):
        ratio = y / max(1, HEIGHT - 1)
        r = int(COLORS["background"][0] * (1 - ratio) + 18 * ratio)
        g = int(COLORS["background"][1] * (1 - ratio) + 18 * ratio)
        b = int(COLORS["background"][2] * (1 - ratio) + 25 * ratio)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))

    for x in range(0, WIDTH, 160):
        draw.line((x, 0, x, HEIGHT), fill=(255, 255, 255, 10), width=1)
    for y in range(0, HEIGHT, 120):
        draw.line((0, y, WIDTH, y), fill=(255, 255, 255, 8), width=1)

    draw.ellipse((WIDTH - 430, -180, WIDTH + 180, 430), fill=(*COLORS["primary"], 58))
    draw.ellipse((-170, HEIGHT - 340, 420, HEIGHT + 170), fill=(*COLORS["accent"], 36))


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    font_obj: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    max_lines: int,
):
    lines = wrap_text(draw, text, font_obj, box[2] - box[0], max_lines)
    line_height = int(font_obj.size * 1.18) if hasattr(font_obj, "size") else 34
    y = box[1]
    for line in lines:
        draw.text((box[0], y), line, font=font_obj, fill=fill)
        y += line_height


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_obj: ImageFont.ImageFont,
    max_width: int,
    max_lines: int,
) -> List[str]:
    words = text.split()
    lines: List[str] = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip()
        if text_width(draw, candidate, font_obj) <= max_width:
            current = candidate
            continue

        if current:
            lines.append(current)
        current = word
        if len(lines) >= max_lines:
            break

    if current and len(lines) < max_lines:
        lines.append(current)

    if len(lines) == max_lines and len(" ".join(words)) > len(" ".join(lines)):
        lines[-1] = lines[-1].rstrip(" .") + "..."

    return lines


def center_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    font_obj: ImageFont.ImageFont,
    fill: tuple[int, int, int],
):
    bbox = draw.textbbox((0, 0), text, font=font_obj)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = box[0] + ((box[2] - box[0]) - w) / 2
    y = box[1] + ((box[3] - box[1]) - h) / 2 - 4
    draw.text((x, y), text, font=font_obj, fill=fill)


def text_width(draw: ImageDraw.ImageDraw, text: str, font_obj: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font_obj)
    return bbox[2] - bbox[0]


def source_initials(source: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", source.upper())
    if not words:
        return "TF"
    if len(words) == 1:
        return words[0][:2]
    return "".join(word[0] for word in words[:2])


def source_color(value: str) -> tuple[int, int, int]:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    base = COLORS["primary"]
    return (
        min(255, int(base[0] * 0.55 + digest[0] * 0.45)),
        min(255, int(base[1] * 0.55 + digest[1] * 0.35)),
        min(255, int(base[2] * 0.55 + digest[2] * 0.35)),
    )


def clean_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text.replace("\u2014", "-").replace("\u2013", "-")


def clean_url(value: Any) -> str:
    text = clean_text(value)
    parsed = urlparse(text)
    if not parsed.netloc:
        return text[:90]
    path = parsed.path.rstrip("/")
    display = f"{parsed.netloc.replace('www.', '')}{path}"
    return display[:110]
