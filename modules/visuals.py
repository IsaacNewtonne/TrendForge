"""Storyboard visual asset generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
import yaml

from loguru import logger

from modules.imagegen import generate_storyboard_art
from modules.screenshot import capture_clean_source_screenshot_any, setup_source_capture_browser
from modules.source_card import create_source_card


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
SOURCE_VISUAL_INTENTS = {"source_card", "source_screenshot"}
SCREENSHOT_MODES = {"auto", "screenshots"}


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
) -> Dict[str, List[str]]:
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

    visual_paths: Dict[str, List[str]] = {}
    driver = None

    try:
        source_segments = [
            segment
            for segment in storyboard.get("segments", [])
            if segment.get("visual_intent") in SOURCE_VISUAL_INTENTS and segment.get("source_url")
        ]

        if source_segments and source_mode in SCREENSHOT_MODES:
            driver = setup_source_capture_browser()
            if not driver:
                logger.warning("Screenshot driver unavailable; source visuals will use source cards")
            elif source_mode == "auto":
                logger.info("Source visual mode auto: trying source screenshots before source cards")

        segments = storyboard.get("segments", [])
        for index, segment in enumerate(segments, start=1):
            segment_id = segment.get("id", "segment")
            visual_intent = segment.get("visual_intent")
            logger.info(f"Visual {index}/{len(segments)}: {segment_id} -> {visual_intent}")

            if visual_intent in SOURCE_VISUAL_INTENTS:
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
                    visual_paths[segment_id] = [path]
                    visual_paths[segment_id].extend(
                        create_refresh_visuals(segment, storyboard.get("style_profile", {}), art_dir, allow_ai_art)
                    )
                    continue

                segment.setdefault("warnings", []).append("Source visual failed; fallback art used.")

            primary_path = generate_storyboard_art(
                segment,
                storyboard.get("style_profile", {}),
                output_dir=art_dir,
                allow_ai=allow_ai_art,
            )
            visual_paths[segment_id] = [primary_path]
            visual_paths[segment_id].extend(
                create_refresh_visuals(segment, storyboard.get("style_profile", {}), art_dir, allow_ai_art)
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

    total_assets = sum(len(paths) for paths in visual_paths.values())
    save_evidence_manifest(storyboard, output_dir / "evidence_manifest.json")
    logger.info(f"Storyboard visuals ready: {total_assets} assets across {len(visual_paths)} segments")
    return visual_paths


def create_storyboard_source_visuals(
    storyboard: Dict[str, Any],
    output_dir: Path = Path("./temp/storyboard_visuals"),
) -> Dict[str, List[str]]:
    """Create only source-backed primary visuals, preserving screenshot capture in manual mode."""
    output_dir.mkdir(parents=True, exist_ok=True)
    source_card_dir = output_dir / "source_cards"
    screenshot_dir = output_dir / "screenshots"
    source_card_dir.mkdir(exist_ok=True)
    screenshot_dir.mkdir(exist_ok=True)

    source_cfg = load_source_visual_config()
    source_mode = source_cfg.get("mode", "cards")
    quality_threshold = int(source_cfg.get("screenshot_quality_threshold", 70))
    screenshot_retries = int(source_cfg.get("screenshot_retries", 3))
    delay_between_sources = float(source_cfg.get("delay_between_sources", 3))

    source_segments = [
        segment
        for segment in storyboard.get("segments", [])
        if segment.get("visual_intent") in SOURCE_VISUAL_INTENTS and segment.get("source_url")
    ]
    visual_paths: Dict[str, List[str]] = {}
    driver = None

    try:
        if source_segments and source_mode in SCREENSHOT_MODES:
            driver = setup_source_capture_browser()
            if not driver:
                logger.warning("Screenshot driver unavailable; source visuals will use source cards")
            elif source_mode == "auto":
                logger.info("Source visual mode auto: trying source screenshots before source cards")

        for index, segment in enumerate(source_segments, start=1):
            logger.info(
                f"Source visual {index}/{len(source_segments)}: "
                f"{segment.get('id', 'segment')} -> {segment.get('visual_intent')}"
            )
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
                visual_paths[segment.get("id", "segment")] = [path]
            else:
                segment.setdefault("warnings", []).append("Source visual failed in manual mode.")
    finally:
        if driver:
            driver.quit()

    save_evidence_manifest(storyboard, output_dir / "evidence_manifest.json")
    logger.info(f"Source visuals ready: {len(visual_paths)} assets")
    return visual_paths


def create_refresh_visuals(
    segment: Dict[str, Any],
    style_profile: Dict[str, Any],
    art_dir: Path,
    allow_ai_art: bool,
) -> List[str]:
    paths: List[str] = []
    for refresh in segment.get("visual_refresh_specs", []):
        refresh_segment = {**segment, **refresh}
        logger.info(
            f"Visual refresh for {segment.get('id')}: "
            f"{refresh.get('id')} -> {refresh.get('visual_intent')}"
        )
        paths.append(
            generate_storyboard_art(
                refresh_segment,
                style_profile,
                output_dir=art_dir,
                allow_ai=allow_ai_art,
            )
        )
    return paths


def find_duplicate_visual_paths(visual_paths: Dict[str, List[str]]) -> Dict[str, list[str]]:
    seen: Dict[str, list[str]] = {}
    for segment_id, paths in visual_paths.items():
        for path in paths:
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
    """Create a source-backed visual, preferring real screenshots outside card-only mode."""
    segment_id = segment.get("id", "segment")

    if source_mode == "cards":
        output_path = card_dir / f"{segment_id}_source_card.png"
        logger.info(f"Creating source card for {segment_id}")
        path = create_source_card(segment, output_path)
        attach_source_visual_metadata(segment, path, "source_card", {"reason": "card mode selected"})
        return path

    if not driver:
        output_path = card_dir / f"{segment_id}_source_card.png"
        logger.info(f"Creating source card for {segment_id}; screenshot driver unavailable")
        path = create_source_card(segment, output_path)
        attach_source_visual_metadata(segment, path, "source_card", {"reason": "screenshot driver unavailable"})
        return path

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
    path = create_source_card(segment, output_path)
    attach_source_visual_metadata(segment, path, "source_card", {"reason": "screenshot quality gate failed"})
    return path


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
        result = capture_clean_source_screenshot_any(
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
            attach_source_visual_metadata(segment, str(output_path), "source_screenshot", result)
            return str(output_path)
        attach_source_visual_metadata(segment, "", "source_screenshot_rejected", result)
        logger.warning(
            f"Screenshot rejected by quality gate: {source_url} "
            f"(best_score={result.get('score', 0)}/100, reason={result.get('reason')})"
        )
    except Exception as e:
        logger.warning(f"Source screenshot failed for {source_url}: {e}")

    return None


def attach_source_visual_metadata(
    segment: Dict[str, Any],
    path: str,
    visual_kind: str,
    result: Dict[str, Any],
) -> None:
    """Attach capture context so generated videos can be audited later."""
    metadata = dict(result.get("metadata") or {})
    segment["source_visual_evidence"] = {
        "segment_id": segment.get("id", "segment"),
        "visual_kind": visual_kind,
        "path": path,
        "source_url": segment.get("source_url", ""),
        "source_name": segment.get("source_name", ""),
        "source_title": segment.get("source_title", ""),
        "score": int(result.get("score", 0) or 0),
        "ok": bool(result.get("ok", visual_kind == "source_card")),
        "reason": result.get("reason", ""),
        "metadata": metadata,
    }


def save_evidence_manifest(storyboard: Dict[str, Any], output_path: Path) -> None:
    """Persist source visual evidence decisions next to generated assets."""
    entries = [
        segment.get("source_visual_evidence")
        for segment in storyboard.get("segments", [])
        if segment.get("source_visual_evidence")
    ]
    if not entries:
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"entries": entries}, f, indent=2, ensure_ascii=False)
    logger.info(f"Evidence manifest saved: {output_path}")
