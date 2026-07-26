"""Image quality diagnostics for generated TrendForge visuals."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict


def analyze_image(path: str | Path) -> Dict[str, Any]:
    from PIL import Image, ImageChops, ImageFilter, ImageStat

    image = Image.open(path).convert("RGB")
    small = image.resize((240, 135))
    stat = ImageStat.Stat(small)
    mean = sum(stat.mean) / 3
    pixels = list(small.getdata())
    luminance = sorted((0.2126 * r) + (0.7152 * g) + (0.0722 * b) for r, g, b in pixels)
    low_index = int((len(luminance) - 1) * 0.05)
    high_index = int((len(luminance) - 1) * 0.95)
    min_value = luminance[low_index]
    max_value = luminance[high_index]
    contrast = max_value - min_value
    dark = sum(1 for r, g, b in pixels if max(r, g, b) < 12)
    bright = sum(1 for r, g, b in pixels if min(r, g, b) > 242)
    low_contrast = sum(1 for r, g, b in pixels if max(r, g, b) - min(r, g, b) < 5)
    total = max(1, len(pixels))
    # High-pass energy catches soft, smeared generations that can have acceptable
    # global contrast but still look poor at 1080p. Crop the filter border so it
    # does not artificially inflate the score.
    gray = small.convert("L")
    high_pass = ImageChops.difference(gray, gray.filter(ImageFilter.GaussianBlur(radius=1.2)))
    high_pass = high_pass.crop((2, 2, high_pass.width - 2, high_pass.height - 2))
    detail_energy = ImageStat.Stat(high_pass).mean[0]
    megapixels = (image.width * image.height) / 1_000_000

    return {
        "path": str(path),
        "width": image.width,
        "height": image.height,
        "mean_brightness": round(mean, 2),
        "contrast": round(contrast, 2),
        "contrast_metric": "p95_minus_p05_luminance",
        "dark_ratio": round(dark / total, 4),
        "bright_ratio": round(bright / total, 4),
        "low_contrast_ratio": round(low_contrast / total, 4),
        "detail_energy": round(detail_energy, 2),
        "megapixels": round(megapixels, 2),
        "is_black": mean < 6 and max_value < 18,
        "is_blank": (dark + bright) / total > 0.82 and contrast < 24,
        "is_low_contrast": contrast < 18 or low_contrast / total > 0.92,
        "is_soft": detail_energy < 1.35,
        "is_undersized": image.width < 1280 or image.height < 720,
    }


def is_video_ready_image(path: str | Path) -> bool:
    result = analyze_image(path)
    return not any(
        result[key]
        for key in ("is_black", "is_blank", "is_low_contrast", "is_soft", "is_undersized")
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()
    print(analyze_image(args.path))


if __name__ == "__main__":
    main()
