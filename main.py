"""TrendForge - AI Faceless YouTube Video Generator

Main CLI entry point that orchestrates the complete pipeline.
"""

import click
import yaml
import os
import sys
import logging
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from loguru import logger

# Set up FFmpeg for MoviePy BEFORE any imports that might load moviepy
try:
    import imageio_ffmpeg
    os.environ['IMAGEIO_FFMPEG_EXE'] = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    pass  # imageio-ffmpeg not installed, will rely on system ffmpeg or fail later

from modules.scraper import get_topic, scrape_web
from modules.source_discovery import build_source_plan
from modules.researcher import analyse_content
from modules.scriptwriter import generate_script
from modules.tts import render_voiceover
from modules.thumbgen import generate_thumbnail
from modules.editor import assemble_timeline, add_intro_clip, add_outro_clip, add_background_music, apply_intro_outro_narration_clips
from modules.image_diagnostics import analyze_image
from modules.imagegen import ensure_realesrgan_model, generate_test_image, get_device_status
from modules.manual_images import create_manual_image_manifest, wait_for_manual_images
from modules.renderer import export_video, resolve_ffmpeg_path
from modules.storyboard import (
    attach_audio_to_storyboard,
    attach_visuals_to_storyboard,
    build_storyboard,
    has_blocking_issues,
    storyboard_audio_files,
    storyboard_visual_files,
)
from modules.visuals import create_storyboard_source_visuals, create_storyboard_visuals
from modules.process_guard import stop_existing_trendforge_workers
from modules.checkpoints import CheckpointStore


PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def remove_dead_local_proxy():
    """Ignore the placeholder localhost:9 proxy that blocks web scraping."""
    for key in PROXY_ENV_VARS:
        value = os.environ.get(key, "")
        if "127.0.0.1:9" in value or "localhost:9" in value:
            os.environ.pop(key, None)


def set_workspace_temp():
    """Keep runtime temp files inside the project to avoid locked user temp dirs."""
    runtime_temp = Path("./temp/runtime").resolve()
    runtime_temp.mkdir(parents=True, exist_ok=True)
    for key in ("TEMP", "TMP", "TMPDIR"):
        os.environ[key] = str(runtime_temp)
    tempfile.tempdir = str(runtime_temp)


def setup_logging(verbose: bool = False, log_file: str = None):
    """Configure logging with loguru."""
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
    )
    if log_file:
        logger.add(
            log_file,
            level=level,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
            rotation="10 MB",
            retention="7 days"
        )


def load_config():
    """Load configuration from config.yaml."""
    # Look in the same directory as the script
    script_dir = Path(__file__).parent
    config_path = script_dir / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"config.yaml not found at {config_path}")
    with open(config_path) as f:
        return yaml.safe_load(f)


def setup_directories(config: dict):
    """Create necessary directories."""
    dirs = [
        config.get("output", {}).get("directory", "./output/"),
        config.get("output", {}).get("temp_directory", "./temp/"),
        "./logs/",
        "./temp/audio/",
        "./temp/images/",
        "./temp/screenshots/",
        "./temp/storyboard_visuals/",
        "./temp/manual_images/",
        "./input_images/",
        "./Assets/fonts/",
        "./Assets/music/",
    ]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)


def apply_cli_overrides(
    cfg: dict,
    visual_source: Optional[str],
    max_screenshot_urls: Optional[int],
    captures_per_url: Optional[int],
    codec: Optional[str],
    bitrate: Optional[str],
    preset: Optional[str],
    tts_voice: Optional[str],
    tts_speed: Optional[float],
) -> dict:
    """Apply CLI overrides to the loaded configuration."""
    cfg.setdefault("visuals", {})
    cfg.setdefault("video", {})
    cfg.setdefault("screenshots", {})
    cfg.setdefault("tts", {})

    if visual_source:
        cfg["visuals"]["source"] = visual_source
    if max_screenshot_urls is not None:
        cfg["screenshots"]["max_urls"] = max_screenshot_urls
    if captures_per_url is not None:
        cfg["screenshots"]["captures_per_url"] = captures_per_url
    if codec:
        cfg["video"]["codec"] = codec
    if bitrate:
        cfg["video"]["bitrate"] = bitrate
    if preset:
        cfg["video"]["preset"] = preset
    if tts_voice:
        cfg["tts"]["voice"] = tts_voice
    if tts_speed is not None:
        cfg["tts"]["speed"] = float(tts_speed)

    return cfg


def log_runtime_status():
    """Log the runtime capabilities that affect speed and output quality."""
    image_status = get_device_status()
    ffmpeg_path = resolve_ffmpeg_path()
    logger.info(f"Python: {sys.version.split()[0]}")
    logger.info(f"Visual device: {image_status.get('device')} ({image_status.get('reason') or 'ready'})")
    logger.info(f"FFmpeg: {ffmpeg_path or 'not found'}")
    try:
        from modules.renderer import choose_video_codec, load_video_config

        logger.info(f"Video encoder: {choose_video_codec(load_video_config())}")
    except Exception as exc:
        logger.warning(f"Video encoder check failed: {exc}")


def get_topic_and_scrape(subject: Optional[str] = None) -> tuple:
    """Get topic and scrape web content.
    
    Args:
        subject: Optional user-provided subject
        
    Returns:
        Tuple of (topic, raw_content)
    """
    topic = get_topic(subject)
    source_plan = build_source_plan(topic)
    raw_content = scrape_web(topic, source_plan=source_plan)
    return topic, raw_content, source_plan


def save_storyboard_debug(storyboard: Dict[str, Any], path: str = "./temp/storyboard.json"):
    """Persist the storyboard contract for debugging/auditing."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(storyboard, f, indent=2, ensure_ascii=False)
    logger.info(f"Storyboard debug saved: {output_path}")


def log_storyboard_validation(
    storyboard: Dict[str, Any],
    label: str,
    suppress_pending_visuals: bool = False,
):
    """Log storyboard validation issues in a compact, readable way."""
    issues = storyboard.get("validation", [])
    if suppress_pending_visuals:
        issues = [
            issue
            for issue in issues
            if issue.get("message") != "Audio segment has no attached visual yet."
        ]
    errors = [issue for issue in issues if issue.get("severity") == "error"]
    warnings = [issue for issue in issues if issue.get("severity") == "warning"]
    logger.info(f"{label}: {len(errors)} errors, {len(warnings)} warnings")
    confirmation = storyboard.get("visual_confirmation") or {}
    if confirmation:
        logger.info(
            "Visual proof coverage: "
            f"{confirmation.get('confirmed_count', 0)}/{confirmation.get('required_count', 0)} "
            f"claims confirmed ({confirmation.get('confirmation_ratio', 1.0)})"
        )
    for issue in errors[:5]:
        logger.error(f"Storyboard {issue.get('segment_id')}: {issue.get('message')}")
    for issue in warnings[:5]:
        logger.warning(f"Storyboard {issue.get('segment_id')}: {issue.get('message')}")


def enforce_visual_confirmation_policy(
    storyboard: Dict[str, Any],
    cfg: Dict[str, Any],
    stage: str,
) -> None:
    """Optionally block the run when proof-required claims lack visual confirmation."""
    source_cfg = (cfg or {}).get("source_visuals", {}) or {}
    if not bool(source_cfg.get("enforce_visual_confirmation_ratio", True)):
        return
    gate_stage = str(source_cfg.get("visual_confirmation_gate_stage", "post_visuals")).strip().lower()
    if gate_stage == "post_visuals" and stage != "post-visual generation":
        return

    confirmation = storyboard.get("visual_confirmation") or {}
    required = int(confirmation.get("required_count") or 0)
    if required <= 0:
        return

    try:
        ratio = float(confirmation.get("confirmation_ratio", 1.0))
    except (TypeError, ValueError):
        ratio = 1.0

    try:
        min_ratio = float(source_cfg.get("min_visual_confirmation_ratio", 0.8))
    except (TypeError, ValueError):
        min_ratio = 0.8
    min_ratio = max(0.0, min(1.0, min_ratio))

    if ratio >= min_ratio:
        return

    unsupported = confirmation.get("unsupported_segments") or []
    sample = ", ".join(
        f"{item.get('id')}@{item.get('evidence_match_confidence')}"
        for item in unsupported[:5]
    )
    detail = f" Unsupported sample: {sample}." if sample else ""
    raise RuntimeError(
        "Visual-script alignment gate failed "
        f"at {stage}: confirmation ratio {ratio:.3f} < required {min_ratio:.3f} "
        f"({confirmation.get('confirmed_count', 0)}/{required} claims confirmed)."
        + detail
    )


def export_and_thumbnail(timeline: Dict[str, Any], topic: str, screenshot_files: List[str], cfg: dict) -> str:
    """Export video (thumbnail generation disabled - user creates thumbnails manually).
    
    Args:
        timeline: Timeline dictionary with clips and transitions
        topic: Video topic
        screenshot_files: List of screenshot file paths
        cfg: Configuration dictionary
        
    Returns:
        Output video file path
    """
    output_path = export_video(timeline, topic)
    
    # Thumbnail generation disabled - user creates thumbnails manually
    # if cfg.get("output", {}).get("thumbnail", True):
    #     logger.info("Generating thumbnail...")
    #     thumb_path = generate_thumbnail(topic, screenshot_files[0] if screenshot_files else None)
    #     logger.success(f"Thumbnail saved to: {thumb_path}")
    
    return output_path


def merge_visual_path_maps(*path_maps: Dict[str, Any]) -> Dict[str, Any]:
    """Merge segment visual path maps while preserving per-segment visual order."""
    merged: Dict[str, List[str]] = {}
    for path_map in path_maps:
        for segment_id, paths in (path_map or {}).items():
            if isinstance(paths, list):
                values = paths
            elif paths:
                values = [paths]
            else:
                values = []
            merged.setdefault(segment_id, []).extend(values)
    return merged


def create_visual_assets(
    storyboard: Dict[str, Any],
    visual_mode: str,
    request_ai_art: bool = False,
) -> Dict[str, Any]:
    """Create or collect storyboard visual assets for the selected visual mode."""
    if visual_mode == "manual":
        logger.info("Manual visual mode selected: using user-provided images only.")
        manifest = create_manual_image_manifest(storyboard, include_source_primary=True)
        if manifest.get("entries"):
            return wait_for_manual_images(manifest)

        raise RuntimeError("Manual visual mode produced no image prompts.")

    if visual_mode == "auto" and request_ai_art:
        logger.info("Auto visual mode with requested AI art handoff: source visuals stay automatic.")
        source_paths = create_storyboard_source_visuals(storyboard)
        manifest = create_manual_image_manifest(
            storyboard,
            include_source_primary=False,
            include_source_refresh=False,
        )
        if not manifest.get("entries"):
            logger.info("Requested AI art handoff found no AI-art slots; continuing with source visuals only.")
            return source_paths

        manual_paths = wait_for_manual_images(manifest)
        return merge_visual_path_maps(source_paths, manual_paths)

    return create_storyboard_visuals(
        storyboard,
        allow_ai_art=visual_mode != "screenshots",
    )


@click.command()
@click.option("--subject", "-s", default=None, help="Topic to research. Leave blank for trending.")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed logs.")
@click.option("--skip-video", is_flag=True, help="Skip video rendering (for testing modules).")
@click.option("--config", "-c", default="config.yaml", help="Path to config file.")
@click.option(
    "--visual-source",
    type=click.Choice(["auto", "screenshots", "ai", "manual"]),
    default=None,
    help="Visual source for segments.",
)
@click.option("--max-screenshot-urls", type=int, default=None, help="Maximum URLs to screenshot.")
@click.option("--captures-per-url", type=int, default=None, help="Screenshots to capture per URL.")
@click.option(
    "--codec",
    type=click.Choice(["auto", "libx264", "h264_nvenc"]),
    default=None,
    help="Video encoder.",
)
@click.option("--bitrate", default=None, help="Video bitrate, e.g. 12000k.")
@click.option(
    "--preset",
    type=click.Choice(["fast", "medium", "slow"]),
    default=None,
    help="CPU encoder preset.",
)
@click.option("--tts-voice", default=None, help="Kokoro voice ID.")
@click.option("--tts-speed", type=float, default=None, help="Kokoro speaking speed.")
@click.option("--image-test", default=None, help="Generate one AI test image with this prompt, then exit.")
@click.option("--image-test-output", default="./temp/image_test.png", help="Output path for --image-test.")
@click.option("--no-kill-existing", is_flag=True, help="Do not stop stale TrendForge worker processes on startup.")
@click.option("--no-resume", is_flag=True, help="Ignore saved stage checkpoints and rebuild every stage.")
@click.option(
    "--request-ai-art",
    is_flag=True,
    help="In auto visual mode, pause for user-provided images only for AI-art slots.",
)
def main(
    subject,
    verbose,
    skip_video,
    config,
    visual_source,
    max_screenshot_urls,
    captures_per_url,
    codec,
    bitrate,
    preset,
    tts_voice,
    tts_speed,
    image_test,
    image_test_output,
    no_kill_existing,
    no_resume,
    request_ai_art,
):
    """TrendForge - AI Faceless YouTube Video Generator.
    
    Given a subject (or no subject for trending topics), TrendForge will:
    1. Research the web for the latest information
    2. Separate facts from opinions using AI
    3. Generate a structured script
    4. Create voiceover narration
    5. Capture screenshots from sources
    6. Assemble and render a complete video
    """
    start_time = datetime.now()
    remove_dead_local_proxy()
    set_workspace_temp()
    
    # Setup
    config_path = Path(config)
    if config_path.exists():
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
    else:
        logger.warning(f"Config file {config} not found, using defaults")
        cfg = load_config()
    cfg = apply_cli_overrides(
        cfg,
        visual_source,
        max_screenshot_urls,
        captures_per_url,
        codec,
        bitrate,
        preset,
        tts_voice,
        tts_speed,
    )
    
    log_file = f"./logs/{start_time.strftime('%Y-%m-%d_%H-%M-%S')}.log"
    setup_logging(verbose, log_file)
    setup_directories(cfg)
    ensure_optional_model_assets(cfg)

    launched_by_server = bool(os.environ.get("TRENDFORGE_RUN_ID"))
    if not no_kill_existing and not launched_by_server:
        def log_cleanup(message: str) -> None:
            if message.startswith("Stopped"):
                logger.info(message)
            else:
                logger.warning(message)

        stop_existing_trendforge_workers(Path(__file__).resolve().parent, log=log_cleanup)
    
    logger.info("="*60)
    logger.info("TrendForge v0.2 - AI Faceless YouTube Video Generator")
    logger.info("="*60)
    log_runtime_status()
    
    if verbose:
        logger.debug(f"Configuration: {cfg}")

    if image_test:
        output_path = generate_test_image(image_test, image_test_output)
        diagnostics = analyze_image(output_path)
        logger.info(f"Image diagnostics: {diagnostics}")
        if diagnostics.get("is_black") or diagnostics.get("is_blank") or diagnostics.get("is_low_contrast"):
            raise click.ClickException(f"Image test produced a rejected frame: {diagnostics}")
        logger.success(f"Image test passed: {output_path}")
        return
    
    # Pipeline execution
    try:
        # Analytics - start tracking
        from modules.analytics import log_generation_start, log_completion, get_channel
        
        visual_mode = cfg.get("visuals", {}).get("source", "auto")
        logger.info(f"Visual source mode: {visual_mode}")
        checkpoint = CheckpointStore(subject, cfg) if subject else None

        def restore(stage: str, validator=None):
            if no_resume or checkpoint is None:
                return None
            value = checkpoint.load(stage, validator=validator)
            if value is not None:
                logger.info(f"Checkpoint restored: {stage} ({checkpoint.run_id})")
            return value

        # Define pipeline steps
        steps = [
            ("[1/7] Research Phase: Planning and scraping web for content...", lambda: get_topic_and_scrape(subject)),
            ("[2/7] Analysis Phase: Separating facts from opinions using AI...", lambda: analyse_content(raw_content)),
            ("[3/7] Script Generation: Creating structured video script and storyboard...", lambda: generate_script(topic, analysis)),
            (
                "[4/7] Voiceover: Rendering narration...",
                lambda: render_voiceover(
                    script,
                    voice_override=cfg.get("tts", {}).get("voice"),
                    speed_override=cfg.get("tts", {}).get("speed"),
                ),
            ),
            (
                "[5/7] Visuals: Creating storyboard-aligned visuals...",
                lambda: create_visual_assets(storyboard, visual_mode, request_ai_art=request_ai_art),
            ),
            ("[6/7] Video Assembly: Combining audio with visuals...", None),
            ("[7/7] Output: Rendering final video...", lambda: export_and_thumbnail(timeline, topic, visual_files, cfg))
        ]
        
        # Execute pipeline with progress bars
        for i, (desc, func) in enumerate(steps, 1):
            logger.info(desc)
            # Special handling for steps that need previous results
            if i == 1:
                saved = restore(
                    "research",
                    lambda value: isinstance(value, dict)
                    and bool(value.get("topic"))
                    and isinstance(value.get("raw_content"), list)
                    and isinstance(value.get("source_plan"), dict),
                )
                if saved:
                    topic = saved["topic"]
                    raw_content = saved["raw_content"]
                    source_plan = saved["source_plan"]
                else:
                    topic, raw_content, source_plan = func()
                    checkpoint = CheckpointStore(topic, cfg)
                    checkpoint.save("research", {
                        "topic": topic,
                        "raw_content": raw_content,
                        "source_plan": source_plan,
                    })
                source = "user" if subject else "trending"
                log_generation_start(topic, source)
                logger.info(f"Topic: {topic}")
                logger.info(f"Source plan queries: {len(source_plan.get('search_queries', []))}")
                logger.info(f"Scraped {len(raw_content)} sources")
            elif i == 2:
                analysis = restore("analysis", lambda value: isinstance(value, dict) and bool(value.get("facts")))
                if analysis is None:
                    analysis = func()
                    analysis["source_plan"] = source_plan
                    checkpoint.save("analysis", analysis)
                else:
                    analysis["source_plan"] = source_plan
            elif i == 3:
                saved = restore(
                    "script",
                    lambda value: isinstance(value, dict)
                    and isinstance(value.get("script"), dict)
                    and isinstance(value.get("storyboard"), dict),
                )
                if saved:
                    script = saved["script"]
                    storyboard = saved["storyboard"]
                else:
                    script = func()
                    storyboard = build_storyboard(script, raw_content, analysis)
                    storyboard["source_plan"] = source_plan
                    checkpoint.save("script", {"script": script, "storyboard": storyboard})
                save_storyboard_debug(storyboard)
                log_storyboard_validation(storyboard, "Storyboard draft")
                enforce_visual_confirmation_policy(storyboard, cfg, "storyboard draft")
                if has_blocking_issues(storyboard):
                    raise RuntimeError("Storyboard has blocking validation errors before narration.")
            elif i == 4:
                saved = restore(
                    "audio",
                    lambda value: isinstance(value, dict)
                    and isinstance(value.get("audio_files"), list)
                    and bool(value.get("audio_files"))
                    and isinstance(value.get("storyboard"), dict),
                )
                if saved:
                    audio_files = saved["audio_files"]
                    storyboard = saved["storyboard"]
                else:
                    audio_files = func()
                    storyboard = attach_audio_to_storyboard(storyboard, audio_files)
                    checkpoint.save("audio", {"audio_files": audio_files, "storyboard": storyboard})
                save_storyboard_debug(storyboard)
                log_storyboard_validation(
                    storyboard,
                    "Storyboard after narration",
                    suppress_pending_visuals=True,
                )
                logger.info(f"Voiceover complete: {len(audio_files)} audio segments")
                
                if skip_video:
                    logger.info("Skipping video rendering (--skip-video flag set)")
                    elapsed = datetime.now() - start_time
                    log_completion(topic, True, duration=elapsed.total_seconds())
                    return
            elif i == 5:
                saved = restore(
                    "visuals",
                    lambda value: isinstance(value, dict)
                    and isinstance(value.get("visual_paths"), dict)
                    and bool(value.get("visual_paths"))
                    and isinstance(value.get("storyboard"), dict),
                )
                if saved:
                    visual_paths = saved["visual_paths"]
                    storyboard = saved["storyboard"]
                else:
                    visual_paths = func()
                    storyboard = attach_visuals_to_storyboard(storyboard, visual_paths)
                    checkpoint.save("visuals", {"visual_paths": visual_paths, "storyboard": storyboard})
                save_storyboard_debug(storyboard)
                log_storyboard_validation(storyboard, "Storyboard after visuals")
                enforce_visual_confirmation_policy(storyboard, cfg, "post-visual generation")
                if has_blocking_issues(storyboard):
                    raise RuntimeError("Storyboard has blocking validation errors after visual generation.")
                visual_files = storyboard_visual_files(storyboard)
                logger.info(f"Visual assets ready: {len(visual_files)}")
            elif i == 6:
                # Step 6 - special handling for intro skip logic
                intro_path = cfg.get("video", {}).get("intro_clip", "./assets/intro.mp4")
                outro_path = cfg.get("video", {}).get("outro_clip", "./assets/outro.mp4")
                # Intro/outro clips are silent in this project, so keep the generated
                # narration and place it over those clips during assembly.
                skip_first = False
                skip_last = False
                ordered_audio_files = storyboard_audio_files(storyboard, audio_files)
                visuals_by_segment = {
                    segment.get("id"): segment.get("visual_path")
                    for segment in storyboard.get("segments", [])
                    if segment.get("visual_path")
                }
                ordered_visual_files = [
                    visuals_by_segment[item.get("storyboard_id")]
                    for item in ordered_audio_files
                    if item.get("storyboard_id") in visuals_by_segment
                ]
                timeline = assemble_timeline(ordered_audio_files, ordered_visual_files, script, skip_first_segment=skip_first, skip_last_segment=skip_last)
                timeline = apply_intro_outro_narration_clips(timeline, intro_path, outro_path)
                
                # Add intro clip only when there is no intro narration segment to carry it.
                intro_path = cfg.get("video", {}).get("intro_clip", "./assets/intro.mp4")
                if Path(intro_path).exists() and not timeline.get("intro_clip_applied"):
                    from modules.editor import add_intro_clip
                    timeline = add_intro_clip(timeline, intro_path)
                    logger.info(f"Intro: {intro_path}")
                else:
                    logger.info("Tip: Add intro.mp4 to ./Assets/ for branded opening")
                
                # Add outro clip  
                outro_path = cfg.get("video", {}).get("outro_clip", "./assets/outro.mp4")
                if Path(outro_path).exists() and not timeline.get("outro_clip_applied"):
                    from modules.editor import add_outro_clip
                    timeline = add_outro_clip(timeline, outro_path)
                    logger.info(f"Outro: {outro_path}")
                else:
                    logger.info("Tip: Add outro.mp4 to ./Assets/ for subscribeCTA")
                
                # Add background music
                music_path = Path("./Assets/music/bg_music.mp3")
                if music_path.exists():
                    from modules.editor import add_background_music
                    volume = cfg.get("video", {}).get("music_volume", 0.08)
                    timeline = add_background_music(timeline, str(music_path), volume)
                    logger.info("Background music: ON")
                
                logger.info("Timeline assembled with branded segments")
            elif i == 7:
                output_path = func()
                logger.success(f"Video saved to: {output_path}")
                
                # Generate thumbnail - DISABLED
                # if cfg.get("output", {}).get("thumbnail", True):
                #     logger.info("Generating thumbnail...")
                #     thumb_path = generate_thumbnail(topic, screenshot_files[0] if screenshot_files else None)
                #     logger.success(f"Thumbnail saved to: {thumb_path}")
                
                # Summary
                elapsed = datetime.now() - start_time
                logger.info("="*60)
                logger.success(f"Pipeline complete in {elapsed.total_seconds():.1f} seconds")
                logger.success(f"Output: {output_path}")
                logger.info("="*60)
                
                # Log success
                from modules.analytics import log_completion
                log_completion(topic, True, duration=elapsed.total_seconds())
                
                return  # Exit successfully
        
    except Exception as e:
        # Log failure
        try:
            from modules.analytics import log_completion
            log_completion(topic if 'topic' in dir() else "unknown", False, str(e))
        except:
            pass
        
        logger.exception(f"Pipeline failed: {e}")
        sys.exit(1)


def ensure_optional_model_assets(cfg: dict) -> None:
    """Best-effort local model bootstrap for optional quality features."""
    image_cfg = cfg.get("image", {}) if isinstance(cfg, dict) else {}
    if str(image_cfg.get("upscale_method", "")).lower() in {"realesrgan", "real-esrgan"}:
        ensure_realesrgan_model(image_cfg)


if __name__ == "__main__":
    main()
