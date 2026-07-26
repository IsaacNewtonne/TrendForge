"""Manual image handoff for externally generated storyboard visuals."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import yaml
from loguru import logger


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
INPUT_DIR = ROOT / "input_images"
MANUAL_DIR = ROOT / "temp" / "manual_images"
MANIFEST_PATH = MANUAL_DIR / "manifest.json"
SUPPORTED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
SOURCE_VISUAL_INTENTS = {"source_card", "source_screenshot"}
MANUAL_IMAGE_STYLE = (
    "TrendForge Signal-Ink editorial illustration: precise graphite and ink contours over translucent gouache "
    "color fields, tactile uncoated-paper grain, and selective crisp technical detail. Palette: warm bone, "
    "midnight navy, mineral teal, electric coral, and a restrained amber highlight. Build one concrete, "
    "human-scale scene with a dominant subject, asymmetrical depth, believable perspective, and a recurring "
    "coral signal thread or pulse used sparingly as the channel signature. Favor observed environments, "
    "machinery, hands, architecture, and topic-specific objects over generic symbolism. Keep quiet space around "
    "the focal subject while still filling the frame with purposeful detail. This is edge-to-edge editorial art, "
    "never Japanese pastiche, anime, a framed print, canvas, triptych, product listing, room mockup, gallery wall, "
    "UI, labeled diagram, or literal infographic."
)
AI_IMAGE_STYLE = (
    "TrendForge Signal-Ink editorial illustration, precise graphite contours, translucent gouache color fields, "
    "tactile uncoated-paper grain, crisp selective detail"
)
ANCHOR_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "about",
    "what",
    "when",
    "where",
    "which",
    "would",
    "could",
    "should",
    "their",
    "there",
    "while",
    "because",
    "through",
    "around",
    "under",
    "over",
    "after",
    "before",
    "between",
    "across",
    "being",
    "been",
    "also",
    "more",
    "most",
    "less",
    "than",
    "very",
    "just",
    "like",
}


def confirmation_file(run_id: str) -> Path:
    return MANUAL_DIR / f"confirmed_{run_id}.json"


def create_manual_image_manifest(
    storyboard: Dict[str, Any],
    run_id: str | None = None,
    include_source_primary: bool = True,
    skip_source_primary_ids: set[str] | None = None,
    include_source_refresh: bool = True,
) -> Dict[str, Any]:
    """Write the numbered prompt manifest used by the UI manual-image modal."""
    run_id = run_id or os.environ.get("TRENDFORGE_RUN_ID") or datetime.now().strftime("%Y%m%d%H%M%S")
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    MANUAL_DIR.mkdir(parents=True, exist_ok=True)

    confirmation_path = confirmation_file(run_id)
    if confirmation_path.exists():
        confirmation_path.unlink()

    video_spec = load_video_spec()
    style_profile = storyboard.get("style_profile", {})
    entries = build_manual_entries(
        storyboard,
        video_spec=video_spec,
        style_profile=style_profile,
        include_source_primary=include_source_primary,
        skip_source_primary_ids=skip_source_primary_ids,
        include_source_refresh=include_source_refresh,
    )
    manifest = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "input_dir": str(INPUT_DIR),
        "confirmation_path": str(confirmation_path),
        "supported_extensions": list(SUPPORTED_EXTENSIONS),
        "video_spec": video_spec,
        "style_guide": manual_style_guide(style_profile, video_spec),
        "entries": entries,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info(f"Manual image manifest ready: {MANIFEST_PATH}")
    logger.info(f"MANUAL_IMAGE_COUNT {len(entries)}")
    if entries:
        logger.info(f"MANUAL_IMAGE_MANIFEST_READY {MANIFEST_PATH}")
        logger.info(f"Save numbered images in: {INPUT_DIR}")
    else:
        logger.info("Manual image manifest has no prompt entries; prompt window will stay closed.")
    return manifest


def build_manual_entries(
    storyboard: Dict[str, Any],
    video_spec: Dict[str, Any] | None = None,
    style_profile: Dict[str, Any] | None = None,
    include_source_primary: bool = True,
    skip_source_primary_ids: set[str] | None = None,
    include_source_refresh: bool = True,
) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    number = 1
    video_spec = video_spec or load_video_spec()
    style_profile = style_profile or storyboard.get("style_profile", {})
    skip_source_primary_ids = skip_source_primary_ids or set()
    for segment in storyboard.get("segments", []):
        segment_id = segment.get("id", "segment")
        should_skip_source_primary = is_source_visual(segment) and (
            not include_source_primary or segment_id in skip_source_primary_ids
        )
        if not should_skip_source_primary:
            entries.append(manual_entry(number, segment, slot_type="primary", video_spec=video_spec, style_profile=style_profile))
            number += 1
        for refresh in segment.get("visual_refresh_specs", []):
            if not include_source_refresh and is_source_visual(refresh):
                continue
            entries.append(
                manual_entry(
                    number,
                    {**segment, **refresh},
                    slot_type="refresh",
                    parent=segment,
                    video_spec=video_spec,
                    style_profile=style_profile,
                )
            )
            number += 1
    return entries


def is_source_visual(item: Dict[str, Any]) -> bool:
    return item.get("visual_intent") in SOURCE_VISUAL_INTENTS


def manual_entry(
    number: int,
    item: Dict[str, Any],
    slot_type: str,
    parent: Dict[str, Any] | None = None,
    video_spec: Dict[str, Any] | None = None,
    style_profile: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    raw_prompt = str(item.get("visual_prompt") or item.get("image_prompt") or item.get("narration") or "").strip()
    segment_id = (parent or item).get("id", "segment")
    video_spec = video_spec or load_video_spec()
    style_profile = style_profile or {}
    prompt = compose_manual_prompt(item, raw_prompt, slot_type, video_spec, style_profile, parent=parent, number=number)
    return {
        "number": number,
        "file_prefix": f"{number:03d}",
        "suggested_filename": f"{number:03d}.png",
        "segment_id": segment_id,
        "slot_id": item.get("id", segment_id),
        "slot_type": slot_type,
        "visual_intent": item.get("visual_intent", "concept_art"),
        "visual_role": item.get("visual_role") or item.get("visual_role_hint") or "",
        "video_size": f"{video_spec['width']}x{video_spec['height']}",
        "aspect_ratio": video_spec["aspect_ratio"],
        "style_guide": manual_style_guide(style_profile, video_spec),
        "raw_prompt": raw_prompt,
        "prompt": prompt,
        "negative_prompt": default_negative_prompt(),
        "source_title": item.get("source_title") or "",
        "source_url": item.get("source_url") or "",
    }


def load_video_spec() -> Dict[str, Any]:
    width = 1920
    height = 1080
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        video_resolution = cfg.get("video", {}).get("resolution") or []
        image_cfg = cfg.get("image", {})
        if len(video_resolution) >= 2:
            width = int(video_resolution[0])
            height = int(video_resolution[1])
        else:
            width = int(image_cfg.get("output_width") or image_cfg.get("width") or width)
            height = int(image_cfg.get("output_height") or image_cfg.get("height") or height)

    return {
        "width": width,
        "height": height,
        "aspect_ratio": aspect_ratio_label(width, height),
        "orientation": "horizontal landscape" if width >= height else "vertical portrait",
    }


def aspect_ratio_label(width: int, height: int) -> str:
    if width == 0 or height == 0:
        return "16:9"
    ratio = width / height
    if abs(ratio - (16 / 9)) < 0.03:
        return "16:9"
    if abs(ratio - (9 / 16)) < 0.03:
        return "9:16"
    if abs(ratio - 1) < 0.03:
        return "1:1"
    return f"{width}:{height}"


def manual_style_guide(style_profile: Dict[str, Any], video_spec: Dict[str, Any]) -> str:
    return (
        f"{video_spec['width']}x{video_spec['height']} {video_spec['aspect_ratio']} {video_spec['orientation']}. "
        f"Style: {MANUAL_IMAGE_STYLE}"
    )


def compose_manual_prompt(
    item: Dict[str, Any],
    raw_prompt: str,
    slot_type: str,
    video_spec: Dict[str, Any],
    style_profile: Dict[str, Any],
    parent: Dict[str, Any] | None = None,
    number: int | None = None,
) -> str:
    intent = item.get("visual_intent", "concept_art")
    topic = style_profile.get("topic") or ""
    narration = str((parent or item).get("narration") or "").strip()
    visual_role = item.get("visual_role") or item.get("visual_role_hint") or "context"
    source_title = item.get("source_title") or (parent or {}).get("source_title") or ""
    source_url = item.get("source_url") or (parent or {}).get("source_url") or ""
    negative = default_negative_prompt()

    objective = raw_prompt or narration or f"Create a visual for {topic}".strip()
    prompt_parts = [
        f"Create one finished video frame at {video_spec['width']}x{video_spec['height']} pixels, {video_spec['aspect_ratio']} {video_spec['orientation']}.",
        f"Use this as part of a cohesive TrendForge documentary video about {topic}.",
        f"Visual slot: {slot_type}; visual intent: {intent}; narrative role: {visual_role}.",
        f"Main visual objective: {objective}",
    ]
    anchors = extract_script_alignment_anchors(
        narration=narration,
        objective=objective,
        source_title=source_title,
    )
    if anchors:
        prompt_parts.append(
            "Script anchors to depict clearly (as visuals, not text): "
            + ", ".join(anchors[:6])
            + "."
        )

    if source_title:
        prompt_parts.append(f"Evidence/source context to imply visually: {source_title}.")
    if source_url:
        prompt_parts.append(f"Source URL for context only, do not render it as text: {source_url}.")
    if narration and narration != objective:
        prompt_parts.append(f"Narration this image supports: {narration[:500]}")

    prompt_parts.extend(
        [
            manual_style_guide(style_profile, video_spec),
            "Keep the frame polished, specific, and editorial with a strong central visual idea and balanced whitespace.",
            "Do not include readable words, letters, numbers, captions, headlines, body text, UI panels, label boxes, legends, charts, arrows, or callout diagrams.",
            "Avoid photorealism, glossy 3D, dark cyberpunk rendering, messy layouts, garbled typography, UI screenshots, watermarks, logos, distorted hands, or meme/cartoon styling.",
            f"Negative prompt: {negative}.",
        ]
    )
    return " ".join(part for part in prompt_parts if part.strip())


def extract_script_alignment_anchors(
    narration: str,
    objective: str,
    source_title: str,
) -> List[str]:
    """Extract compact anchor phrases so manual images stay tied to narration."""
    text = " ".join(part for part in (narration, objective, source_title) if part).strip()
    if not text:
        return []

    anchors: List[str] = []

    # Keep explicit entities/phrases first.
    for match in re.findall(r"\b[A-Z][A-Za-z0-9&.-]{2,}(?:\s+[A-Z][A-Za-z0-9&.-]{2,}){0,3}\b", text):
        if match not in anchors:
            anchors.append(match)

    # Keep years and metric tokens.
    for match in re.findall(r"\b(?:19|20)\d{2}\b|\$?\d+(?:\.\d+)?\s?(?:%|percent|million|billion|trillion|x)?", text):
        token = match.strip()
        if token and token not in anchors:
            anchors.append(token)

    # Add high-signal action/context words.
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", text.lower())
    for word in words:
        if word in ANCHOR_STOPWORDS:
            continue
        if word in {"announced", "launch", "launched", "released", "reported", "approved", "regulation", "policy", "model", "chip", "cloud", "infrastructure", "revenue", "users"}:
            if word not in anchors:
                anchors.append(word)

    return anchors[:10]


def default_negative_prompt() -> str:
    return "watermark, logo, readable text, fake text, pseudo text, gibberish text, glyphs, letters, numbers, captions, headline, body text, labels, legends, charts, arrows, callouts, UI panels, plaque, sign, wordmark, typography, garbled typography, misspelled labels, blurry, malformed anatomy, extra fingers, low quality, washed out, low contrast, empty close-up, cluttered layout, photorealism, glossy 3D render, miniature city, miniature model, isometric diorama, aerial view, top-down view, random cubes, geometric debris, generic server boxes, repeated objects, Japanese pastiche, anime, manga, ukiyo-e, woodblock print, pagoda, torii gate, Mount Fuji, rising sun disc, cherry blossom, great wave, samurai, picture frame, framed artwork, canvas print, triptych, diptych, wall art, gallery wall, room interior, product mockup, drop shadow border, white outer margin"


def ai_image_style_prompt() -> str:
    """Compact version of the manual style for local SD prompts."""
    return AI_IMAGE_STYLE


def wait_for_manual_images(manifest: Dict[str, Any], poll_seconds: float = 2.0) -> Dict[str, List[str]]:
    """Block until the UI confirms that numbered manual images are ready."""
    confirmation_path = Path(manifest["confirmation_path"])
    logger.info("Manual image generation is waiting for user confirmation.")
    logger.info("Use the UI prompt window, save numbered files, then click Confirm images.")

    last_notice = 0.0
    while not confirmation_path.exists():
        now = time.monotonic()
        if now - last_notice > 20:
            missing = validate_manual_image_files(manifest).get("missing", [])
            logger.info(f"Waiting for manual images: {len(missing)} missing")
            last_notice = now
        time.sleep(poll_seconds)

    validation = validate_manual_image_files(manifest)
    if validation["missing"]:
        detail = ", ".join(validation["missing"][:8])
        raise RuntimeError(f"Manual image confirmation exists, but files are missing: {detail}")

    logger.info("Manual images confirmed; continuing to video assembly.")
    return group_manual_paths_by_segment(manifest, validation["files"])


def validate_manual_image_files(manifest: Dict[str, Any]) -> Dict[str, Any]:
    files: Dict[str, str] = {}
    missing: List[str] = []
    for entry in manifest.get("entries", []):
        path = find_numbered_image(entry["file_prefix"])
        if path:
            files[str(entry["number"])] = str(path)
        else:
            missing.append(entry["suggested_filename"])
    return {"ok": not missing, "missing": missing, "files": files}


def group_manual_paths_by_segment(manifest: Dict[str, Any], files: Dict[str, str]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = {}
    for entry in manifest.get("entries", []):
        path = files.get(str(entry["number"]))
        if not path:
            continue
        grouped.setdefault(entry["segment_id"], []).append(path)
    return grouped


def find_numbered_image(file_prefix: str) -> Path | None:
    for extension in SUPPORTED_EXTENSIONS:
        exact = INPUT_DIR / f"{file_prefix}{extension}"
        if exact.exists():
            return exact

    matches = sorted(
        path
        for path in INPUT_DIR.glob(f"{file_prefix}*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    return matches[0] if matches else None


def load_current_manifest() -> Dict[str, Any]:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError("Manual image manifest is not ready yet.")
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def confirm_manual_images() -> Dict[str, Any]:
    manifest = load_current_manifest()
    validation = validate_manual_image_files(manifest)
    if not validation["ok"]:
        return {
            "ok": False,
            "missing": validation["missing"],
            "input_dir": manifest.get("input_dir", str(INPUT_DIR)),
        }

    confirmation_path = Path(manifest["confirmation_path"])
    confirmation_path.parent.mkdir(parents=True, exist_ok=True)
    confirmation_path.write_text(
        json.dumps({"confirmed_at": datetime.now().isoformat(timespec="seconds")}, indent=2),
        encoding="utf-8",
    )
    return {"ok": True, "count": len(validation["files"]), "input_dir": manifest.get("input_dir", str(INPUT_DIR))}
