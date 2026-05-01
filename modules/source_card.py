"""Branded source-card visuals for evidence-backed video segments."""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFilter, ImageFont


WIDTH = 1920
HEIGHT = 1080
BRAND_LOGO_PATH = Path("./Assets/Logo.png")

COLORS = {
    "background": (8, 9, 15),
    "background_2": (15, 16, 26),
    "surface": (18, 19, 30),
    "surface_2": (28, 30, 45),
    "primary": (83, 74, 183),
    "cyan": (30, 151, 255),
    "accent": (239, 159, 39),
    "text": (255, 255, 255),
    "muted": (178, 181, 198),
    "dim": (112, 118, 138),
    "border": (111, 139, 255),
}


def create_source_card(segment: Dict[str, Any], output_path: Path) -> str:
    """Render a modern video-ready fallback card from extracted source metadata."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    source = clean_text(segment.get("source_name") or "Source")
    title = clean_text(segment.get("source_title") or segment.get("visual_prompt") or segment.get("claim") or "Source update")
    summary = clean_text(segment.get("source_summary") or segment.get("source_excerpt") or segment.get("claim") or "")
    date = clean_text(segment.get("source_published") or segment.get("published") or "")
    raw_url = clean_text(segment.get("source_url") or "")
    url = clean_url(raw_url)
    domain = clean_text(urlparse(raw_url).netloc.replace("www.", ""))
    source_label = source if source.lower() != "source" and source else (domain or "Verified source")

    image = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background"])
    draw = ImageDraw.Draw(image, "RGBA")

    palette = source_palette(source_label or domain or title)
    draw_background(image, palette)
    draw_motion_field(image, palette)

    card = (118, 104, WIDTH - 118, HEIGHT - 104)
    draw_glass_panel(image, card, palette)
    draw = ImageDraw.Draw(image, "RGBA")

    draw_source_header(draw, card, source_label, domain, date, palette)
    draw_content(draw, card, title, summary)
    draw_signal_art(draw, card, palette)
    draw_brand_logo(image, card)
    draw = ImageDraw.Draw(image, "RGBA")
    draw_footer(draw, card, url or domain, palette)

    image.save(output_path)
    return str(output_path)


def draw_background(image: Image.Image, palette: Dict[str, tuple[int, int, int]]) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    top = COLORS["background"]
    bottom = COLORS["background_2"]
    for y in range(HEIGHT):
        ratio = y / max(1, HEIGHT - 1)
        r = int(top[0] * (1 - ratio) + bottom[0] * ratio)
        g = int(top[1] * (1 - ratio) + bottom[1] * ratio)
        b = int(top[2] * (1 - ratio) + bottom[2] * ratio)
        draw.line((0, y, WIDTH, y), fill=(r, g, b, 255))

    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow, "RGBA")
    glow_draw.ellipse((WIDTH - 720, -280, WIDTH + 240, 560), fill=(*palette["primary"], 42))
    glow_draw.ellipse((-280, HEIGHT - 480, 590, HEIGHT + 220), fill=(*palette["accent"], 30))
    glow_draw.ellipse((540, 290, 1430, 1160), fill=(*palette["cyan"], 24))
    composite = Image.alpha_composite(image.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(45)))
    image.paste(composite.convert("RGB"))


def draw_motion_field(image: Image.Image, palette: Dict[str, tuple[int, int, int]]) -> None:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")

    origin_x = 745
    origin_y = 860
    for index in range(34):
        angle = -0.36 + index * 0.024
        length = 1250 + (index % 7) * 65
        end_x = origin_x + int(math.cos(angle) * length)
        end_y = origin_y + int(math.sin(angle) * length)
        alpha = 18 + (index % 4) * 9
        width = 1 + (index % 5 == 0)
        draw.line((origin_x, origin_y, end_x, end_y), fill=(*palette["cyan"], alpha), width=width)

    for x in range(0, WIDTH, 160):
        draw.line((x, 0, x + 620, HEIGHT), fill=(255, 255, 255, 8), width=1)

    for x in range(1320, 1760, 42):
        h = 60 + ((x // 42) % 8) * 22
        draw.rounded_rectangle((x, 735 - h, x + 18, 735), radius=5, fill=(*palette["cyan"], 40))

    image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"))


def draw_glass_panel(image: Image.Image, card: tuple[int, int, int, int], palette: Dict[str, tuple[int, int, int]]) -> None:
    panel = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(panel, "RGBA")
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow, "RGBA")
    shadow_draw.rounded_rectangle((card[0], card[1] + 28, card[2], card[3] + 28), radius=38, fill=(0, 0, 0, 145))
    panel.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(26)))

    draw.rounded_rectangle(card, radius=38, fill=(13, 17, 29, 218), outline=(*COLORS["border"], 210), width=2)
    draw.rounded_rectangle((card[0] + 2, card[1] + 2, card[2] - 2, card[3] - 2), radius=36, outline=(*palette["cyan"], 70), width=2)
    draw.line((card[0] + 890, card[3] - 154, card[2] - 72, card[3] - 154), fill=(126, 154, 255, 90), width=2)
    image.paste(Image.alpha_composite(image.convert("RGBA"), panel).convert("RGB"))


def draw_source_header(
    draw: ImageDraw.ImageDraw,
    card: tuple[int, int, int, int],
    source: str,
    domain: str,
    date: str,
    palette: Dict[str, tuple[int, int, int]],
) -> None:
    badge = (card[0] + 82, card[1] + 66, card[0] + 266, card[1] + 250)
    draw.rounded_rectangle(badge, radius=28, fill=(9, 21, 43, 230), outline=(*palette["cyan"], 205), width=2)
    draw_source_mark(draw, badge, palette)

    font_source = font(45, bold=True)
    font_meta = font(32)
    source_x = badge[2] + 60
    source_y = card[1] + 96
    display_source = fit_text(draw, source, font_source, 470)
    draw.text((source_x, source_y), display_source, font=font_source, fill=COLORS["text"])
    draw_verified_badge(draw, source_x + min(500, text_width(draw, display_source, font_source)) + 22, source_y + 15, palette)

    meta_parts = [part for part in [domain, date] if part]
    meta = " | ".join(meta_parts)
    if meta:
        draw.text((source_x, source_y + 70), fit_text(draw, meta, font_meta, 650), font=font_meta, fill=COLORS["muted"])


def draw_source_mark(draw: ImageDraw.ImageDraw, badge: tuple[int, int, int, int], palette: Dict[str, tuple[int, int, int]]) -> None:
    cx = (badge[0] + badge[2]) // 2
    cy = (badge[1] + badge[3]) // 2
    radius = 60
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(*palette["cyan"], 235))
    draw.pieslice((cx - radius, cy - radius, cx + radius, cy + radius), 205, 342, fill=(*palette["primary"], 245))
    draw.line((cx - 56, cy + 28, cx + 56, cy - 22), fill=(5, 10, 25, 190), width=8)
    draw.ellipse((cx - radius + 7, cy - radius + 7, cx + radius - 7, cy + radius - 7), outline=(255, 255, 255, 48), width=2)


def draw_verified_badge(draw: ImageDraw.ImageDraw, x: int, y: int, palette: Dict[str, tuple[int, int, int]]) -> None:
    draw.ellipse((x, y, x + 38, y + 38), fill=(*palette["cyan"], 255))
    draw.line((x + 10, y + 20, x + 17, y + 27, x + 29, y + 12), fill=(255, 255, 255, 255), width=4, joint="curve")


def draw_content(draw: ImageDraw.ImageDraw, card: tuple[int, int, int, int], title: str, summary: str) -> None:
    title_width = card[2] - card[0] - 760
    title_font = best_font_for_box(draw, title, 86, 58, title_width, 285, max_lines=3)
    summary_font = font(38)
    title_box = (card[0] + 82, card[1] + 315, card[0] + 1045, card[1] + 600)
    title_lines = wrap_text(draw, title, title_font, title_width, 3)
    title_line_height = int(getattr(title_font, "size", 66) * 1.12)
    y = title_box[1]
    for line in title_lines:
        draw.text((title_box[0], y), line, font=title_font, fill=COLORS["text"])
        y += title_line_height

    underline_y = min(card[1] + 610, y + 18)
    draw.line((card[0] + 78, underline_y, card[0] + 900, underline_y), fill=(30, 151, 255, 175), width=4)
    draw.ellipse((card[0] + 72, underline_y - 6, card[0] + 88, underline_y + 10), fill=(30, 151, 255, 255))

    summary_text = summary or "Evidence-backed claim with verified source context and concise key takeaway."
    summary_y = max(card[1] + 570, underline_y + 34)
    max_summary_lines = 2 if len(title_lines) >= 3 or summary_y > card[1] + 630 else 3
    summary_box = (card[0] + 86, summary_y, card[0] + 760, card[1] + 760)
    draw_wrapped_text(draw, summary_text, summary_box, summary_font, COLORS["muted"], max_lines=max_summary_lines)


def draw_signal_art(draw: ImageDraw.ImageDraw, card: tuple[int, int, int, int], palette: Dict[str, tuple[int, int, int]]) -> None:
    base_x = card[0] + 1030
    base_y = card[1] + 590
    points = [
        (base_x, base_y + 56),
        (base_x + 170, base_y + 56),
        (base_x + 230, base_y),
        (base_x + 410, base_y),
        (base_x + 332, base_y + 92),
        (base_x + 185, base_y + 92),
        (base_x + 128, base_y + 148),
        (base_x - 40, base_y + 148),
    ]
    draw.polygon(points, fill=(*palette["primary"], 160), outline=(*palette["cyan"], 210))
    draw.line((base_x + 110, base_y + 170, base_x + 520, base_y - 280), fill=(*palette["cyan"], 235), width=8)
    draw.line((base_x + 118, base_y + 180, base_x + 528, base_y - 270), fill=(255, 255, 255, 110), width=2)
    arrow = [
        (base_x + 520, base_y - 280),
        (base_x + 460, base_y - 258),
        (base_x + 582, base_y - 356),
        (base_x + 556, base_y - 202),
    ]
    draw.polygon(arrow, fill=(*palette["cyan"], 225), outline=(255, 255, 255, 180))

    for index, x in enumerate(range(base_x + 395, card[2] - 105, 34)):
        h = 58 + index * 18
        draw.rounded_rectangle((x, card[1] + 645 - h, x + 17, card[1] + 645), radius=5, fill=(*palette["cyan"], 62))
    for index in range(10):
        x = base_x + 265 + index * 57
        y = card[1] + 590 - int(math.sin(index * 0.8) * 55) - index * 14
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=(*palette["cyan"], 180))
        if index:
            px = base_x + 265 + (index - 1) * 57
            py = card[1] + 590 - int(math.sin((index - 1) * 0.8) * 55) - (index - 1) * 14
            draw.line((px, py, x, y), fill=(*palette["cyan"], 95), width=2)


def draw_brand_logo(image: Image.Image, card: tuple[int, int, int, int]) -> None:
    logo = load_brand_logo(150, opacity=0.92)
    if logo is None:
        return

    x = card[2] - logo.width - 70
    y = card[1] + 48

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    glow = Image.new("RGBA", logo.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow, "RGBA")
    glow_draw.ellipse((8, 8, logo.width - 8, logo.height - 8), fill=(30, 151, 255, 44))
    overlay.alpha_composite(glow.filter(ImageFilter.GaussianBlur(16)), (x, y))
    overlay.alpha_composite(logo, (x, y))
    image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"))


def load_brand_logo(target_width: int, opacity: float = 1.0) -> Image.Image | None:
    if not BRAND_LOGO_PATH.exists():
        return None
    try:
        logo = Image.open(BRAND_LOGO_PATH).convert("RGBA")
    except OSError:
        return None

    pixels = logo.load()
    for y in range(logo.height):
        for x in range(logo.width):
            r, g, b, a = pixels[x, y]
            if r > 238 and g > 238 and b > 238:
                pixels[x, y] = (r, g, b, 0)
            else:
                pixels[x, y] = (r, g, b, int(a * opacity))

    alpha = logo.getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        return None
    logo = logo.crop(bbox)
    target_height = max(1, int(logo.height * (target_width / max(1, logo.width))))
    return logo.resize((target_width, target_height), Image.Resampling.LANCZOS)


def draw_footer(
    draw: ImageDraw.ImageDraw,
    card: tuple[int, int, int, int],
    url: str,
    palette: Dict[str, tuple[int, int, int]],
) -> None:
    footer_y = card[3] - 104
    icon = (card[0] + 82, footer_y - 20, card[0] + 166, footer_y + 64)
    draw.regular_polygon(((icon[0] + icon[2]) // 2, (icon[1] + icon[3]) // 2, 48), n_sides=6, rotation=math.pi / 6, outline=(*palette["cyan"], 210), width=2)
    draw.ellipse((icon[0] + 25, icon[1] + 23, icon[2] - 25, icon[3] - 23), outline=(*palette["cyan"], 210), width=3)
    draw.line((icon[0] + 42, icon[1] + 24, icon[0] + 42, icon[3] - 24), fill=(*palette["cyan"], 180), width=2)
    draw.line((icon[0] + 24, icon[1] + 42, icon[2] - 24, icon[1] + 42), fill=(*palette["cyan"], 180), width=2)

    font_label = font(34, bold=True)
    font_url = font(34)
    x = card[0] + 216
    draw.text((x, footer_y), "SOURCE", font=font_label, fill=palette["cyan"])
    draw.line((x + 214, footer_y - 8, x + 214, footer_y + 48), fill=(*COLORS["dim"], 170), width=2)
    draw.text((x + 268, footer_y), fit_text(draw, url, font_url, 700), font=font_url, fill=COLORS["text"])
    arrow_x = x + 268 + min(760, text_width(draw, url, font_url)) + 34
    draw.line((arrow_x, footer_y + 30, arrow_x + 30, footer_y), fill=palette["cyan"], width=4)
    draw.line((arrow_x + 30, footer_y, arrow_x + 30, footer_y + 24), fill=palette["cyan"], width=4)
    draw.line((arrow_x + 30, footer_y, arrow_x + 6, footer_y), fill=palette["cyan"], width=4)


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


def best_font_for_box(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_size: int,
    min_size: int,
    max_width: int,
    max_height: int,
    max_lines: int,
) -> ImageFont.ImageFont:
    for size in range(max_size, min_size - 1, -4):
        candidate = font(size, bold=True)
        lines = wrap_text(draw, text, candidate, max_width, max_lines)
        line_height = int(size * 1.14)
        if lines and len(lines) * line_height <= max_height:
            return candidate
    return font(min_size, bold=True)


def draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    font_obj: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    max_lines: int,
) -> None:
    lines = wrap_text(draw, text, font_obj, box[2] - box[0], max_lines)
    size = getattr(font_obj, "size", 34)
    line_height = int(size * 1.18)
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


def fit_text(draw: ImageDraw.ImageDraw, text: str, font_obj: ImageFont.ImageFont, max_width: int) -> str:
    if text_width(draw, text, font_obj) <= max_width:
        return text
    ellipsis = "..."
    trimmed = text
    while trimmed and text_width(draw, trimmed + ellipsis, font_obj) > max_width:
        trimmed = trimmed[:-1]
    return trimmed.rstrip() + ellipsis


def text_width(draw: ImageDraw.ImageDraw, text: str, font_obj: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font_obj)
    return bbox[2] - bbox[0]


def source_palette(value: str) -> Dict[str, tuple[int, int, int]]:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return {
        "primary": mix(COLORS["primary"], (digest[0], digest[1], digest[2]), 0.22),
        "cyan": mix(COLORS["cyan"], (digest[3], digest[4], digest[5]), 0.14),
        "accent": mix(COLORS["accent"], (digest[6], digest[7], digest[8]), 0.18),
    }


def mix(a: tuple[int, int, int], b: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
    return (
        int(a[0] * (1 - ratio) + b[0] * ratio),
        int(a[1] * (1 - ratio) + b[1] * ratio),
        int(a[2] * (1 - ratio) + b[2] * ratio),
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
