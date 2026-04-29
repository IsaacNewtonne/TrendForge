"""Storyboard visual asset generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import yaml

from loguru import logger

from modules.imagegen import generate_storyboard_art
from modules.screenshot import capture_clean_source_screenshot, setup_driver
from modules.source_card import create_source_card


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def load_source_visual_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
            return cfg.get("source_visuals", {})
    return {}


def create_storyboard_visuals(
    storyboard: Dict[str, Any],
    output_dir: Path = Path("./temp/storyboard_visuals"),
    allow_ai_art: bool = True,
) -> Dict[str, str]:
    """Create visual assets for every storyboard segment.

    Source-backed claims get screenshots. Analogies and concepts get generated
    art using the video style profile. If a screenshot fails, the segment gets a
    warning and receives fallback art so the render can still proceed.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    source_card_dir = output_dir / "source_cards"
    screenshot_dir = output_dir / "screenshots"
    art_dir = output_dir / "art"
    source_card_dir.mkdir(exist_ok=True)
    screenshot_dir.mkdir(exist_ok=True)
    art_dir.mkdir(exist_ok=True)
    source_cfg = load_source_visual_config()
    source_mode = source_cfg.get("mode", "cards")
    quality_threshold = int(source_cfg.get("screenshot_quality_threshold", 70))
    screenshot_retries = int(source_cfg.get("screenshot_retries", 3))
    delay_between_sources = float(source_cfg.get("delay_between_sources", 3))

    visual_paths: Dict[str, str] = {}
    driver = None

    try:
        source_segments = [
            segment
            for segment in storyboard.get("segments", [])
            if segment.get("visual_intent") in {"source_card", "source_screenshot"} and segment.get("source_url")
        ]

        if source_segments and source_mode in {"screenshots", "auto"}:
            driver = setup_driver()
            if not driver:
                logger.warning("Screenshot driver unavailable; source visuals will use source cards")

        segments = storyboard.get("segments", [])
        for index, segment in enumerate(segments, start=1):
            segment_id = segment.get("id", "segment")
            visual_intent = segment.get("visual_intent")
            logger.info(f"Visual {index}/{len(segments)}: {segment_id} -> {visual_intent}")

            if visual_intent in {"source_card", "source_screenshot"}:
                path = create_source_visual(
                    segment,
                    source_card_dir,
                    screenshot_dir,
                    driver,
                    source_mode,
                    quality_threshold,
                    screenshot_retries,
                    delay_between_sources,
                )
                if path:
                    visual_paths[segment_id] = path
                    continue

                segment.setdefault("warnings", []).append("Source visual failed; fallback art used.")

            visual_paths[segment_id] = generate_storyboard_art(
                segment,
                storyboard.get("style_profile", {}),
                output_dir=art_dir,
                allow_ai=allow_ai_art,
            )

    finally:
        if driver:
            driver.quit()

    duplicate_paths = find_duplicate_visual_paths(visual_paths)
    if duplicate_paths:
        detail = "; ".join(
            f"{path} -> {', '.join(segment_ids)}"
            for path, segment_ids in duplicate_paths.items()
        )
        raise RuntimeError(f"Duplicate visual assets are not allowed: {detail}")

    logger.info(f"Storyboard visuals ready: {len(visual_paths)} assets")
    return visual_paths


def find_duplicate_visual_paths(visual_paths: Dict[str, str]) -> Dict[str, list[str]]:
    seen: Dict[str, list[str]] = {}
    for segment_id, path in visual_paths.items():
        seen.setdefault(path, []).append(segment_id)
    return {path: ids for path, ids in seen.items() if len(ids) > 1}


def create_source_visual(
    segment: Dict[str, Any],
    card_dir: Path,
    screenshot_dir: Path,
    driver,
    source_mode: str,
    quality_threshold: int,
    screenshot_retries: int,
    delay_between_sources: float,
) -> str | None:
    """Create a source-backed visual, preferring branded cards by default."""
    segment_id = segment.get("id", "segment")

    if source_mode == "cards" or not driver:
        output_path = card_dir / f"{segment_id}_source_card.png"
        logger.info(f"Creating source card for {segment_id}")
        return create_source_card(segment, output_path)

    screenshot_path = create_source_screenshot(
        segment,
        screenshot_dir,
        driver,
        quality_threshold,
        screenshot_retries,
        delay_between_sources,
    )
    if screenshot_path:
        return screenshot_path

    output_path = card_dir / f"{segment_id}_source_card.png"
    logger.info(f"Using source card for {segment_id} after screenshot quality failure")
    return create_source_card(segment, output_path)


def create_source_screenshot(
    segment: Dict[str, Any],
    output_dir: Path,
    driver,
    quality_threshold: int,
    screenshot_retries: int,
    delay_between_sources: float,
) -> str | None:
    """Capture one source screenshot and reject pages that are not video-ready."""
    if not driver:
        return None

    source_url = segment.get("source_url")
    if not source_url:
        return None

    output_path = output_dir / f"{segment.get('id', 'segment')}_source.png"
    logger.info(f"Capturing source visual for {segment.get('id')}: {source_url}")

    try:
        result = capture_clean_source_screenshot(
            driver,
            source_url,
            output_path,
            expected_source=segment.get("source_name") or "",
            expected_headline=segment.get("source_title") or "",
            min_score=quality_threshold,
            max_attempts=screenshot_retries,
            delay_between_attempts=delay_between_sources,
            vision_config=load_source_visual_config(),
        )
        if result.get("ok") and result.get("path"):
            logger.info(
                f"Clean screenshot accepted for {segment.get('id')}: "
                f"score={result.get('score')}/100"
            )
            return str(output_path)
        logger.warning(
            f"Screenshot rejected by quality gate: {source_url} "
            f"(best_score={result.get('score', 0)}/100, reason={result.get('reason')})"
        )
    except Exception as e:
        logger.warning(f"Source screenshot failed for {source_url}: {e}")

    return None
