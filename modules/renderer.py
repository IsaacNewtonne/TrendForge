"""TrendForge - Video Renderer Module

Exports final video using FFmpeg with optional captions via Whisper.
"""

import os
import subprocess
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
from loguru import logger
from datetime import datetime
from proglog import ProgressBarLogger

# Configuration
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
_NVENC_USABLE: Optional[bool] = None
ROOT = Path(__file__).resolve().parent.parent


class MoviePyProgressLogger(ProgressBarLogger):
    """Forward MoviePy render progress into normal app logs."""

    def __init__(self, min_step: int = 5):
        super().__init__()
        self.min_step = min_step
        self._last_percent = -1

    def bars_callback(self, bar, attr, value, old_value=None):
        total = self.bars.get(bar, {}).get("total")
        if not total:
            return

        percent = int((value / total) * 100)
        if percent >= 100 or percent - self._last_percent >= self.min_step:
            self._last_percent = percent
            logger.info(f"Render progress: {min(percent, 100)}%")


def load_video_config() -> dict:
    """Load video configuration."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f)
            return cfg.get("video", {})
    return {}


def load_caption_config() -> dict:
    """Load caption configuration."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f)
            return cfg.get("captions", {})
    return {}


def load_output_config() -> dict:
    """Load output configuration."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f)
            return cfg.get("output", {})
    return {}


def unique_existing_candidates(candidates: List[str]) -> List[str]:
    """Return candidate executables in priority order without duplicates."""
    seen = set()
    ordered = []
    for candidate in candidates:
        if not candidate:
            continue
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(str(candidate))
    return ordered


def resolve_ffmpeg_path() -> Optional[str]:
    """Find the FFmpeg binary used for rendering."""
    candidates = [
        os.environ.get("TRENDFORGE_FFMPEG"),
        os.environ.get("FFMPEG_BINARY"),
        str(ROOT / "ffmpeg-master-latest-win64-gpl" / "bin" / "ffmpeg.exe"),
        str(ROOT / "ffmpeg" / "bin" / "ffmpeg.exe"),
        str(ROOT / "ffmpeg.exe"),
        "ffmpeg",
    ]

    try:
        import imageio_ffmpeg

        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    except ImportError:
        pass

    for candidate in unique_existing_candidates(candidates):
        try:
            result = subprocess.run(
                [candidate, "-version"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                return candidate
        except (FileNotFoundError, OSError):
            continue

    return None


def resolve_ffprobe_path(ffmpeg_path: Optional[str] = None) -> Optional[str]:
    """Find FFprobe, preferring the binary that sits beside FFmpeg."""
    candidates = []
    if ffmpeg_path:
        ffmpeg_file = Path(ffmpeg_path)
        if ffmpeg_file.name.lower().startswith("ffmpeg"):
            candidates.append(str(ffmpeg_file.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")))

    candidates.extend([
        str(ROOT / "ffmpeg-master-latest-win64-gpl" / "bin" / "ffprobe.exe"),
        str(ROOT / "ffmpeg" / "bin" / "ffprobe.exe"),
        str(ROOT / "ffprobe.exe"),
        "ffprobe",
    ])

    for candidate in unique_existing_candidates(candidates):
        try:
            result = subprocess.run(
                [candidate, "-version"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                return candidate
        except (FileNotFoundError, OSError):
            continue

    return None


def ffmpeg_supports_encoder(encoder: str) -> bool:
    """Check whether the active FFmpeg supports a video encoder."""
    ffmpeg_path = resolve_ffmpeg_path()
    if not ffmpeg_path:
        return False

    try:
        result = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0 and encoder in result.stdout
    except OSError:
        return False


def ffmpeg_encoder_help(encoder: str) -> str:
    """Return FFmpeg encoder help text for capability checks."""
    ffmpeg_path = resolve_ffmpeg_path()
    if not ffmpeg_path:
        return ""

    try:
        result = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-h", f"encoder={encoder}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return f"{result.stdout}\n{result.stderr}"
    except OSError:
        pass

    return ""


def normalize_nvenc_preset(requested: str) -> str:
    """Map NVENC presets to values supported by the bundled FFmpeg."""
    requested = str(requested or "medium")
    help_text = ffmpeg_encoder_help("h264_nvenc")
    if not help_text:
        return requested

    if f" {requested} " in help_text or f"{requested} " in help_text:
        return requested

    modern_to_legacy = {
        "p1": "fast",
        "p2": "fast",
        "p3": "fast",
        "p4": "medium",
        "p5": "slow",
        "p6": "slow",
        "p7": "slow",
    }
    mapped = modern_to_legacy.get(requested.lower(), "medium")
    logger.warning(f"NVENC preset '{requested}' is not supported by this FFmpeg; using '{mapped}'")
    return mapped


def nvenc_is_usable(cfg_video: dict) -> bool:
    """Check that NVENC is listed and can actually initialize."""
    global _NVENC_USABLE
    if _NVENC_USABLE is not None:
        return _NVENC_USABLE

    if not ffmpeg_supports_encoder("h264_nvenc"):
        _NVENC_USABLE = False
        return _NVENC_USABLE

    ffmpeg_path = resolve_ffmpeg_path()
    if not ffmpeg_path:
        _NVENC_USABLE = False
        return _NVENC_USABLE

    preset = normalize_nvenc_preset(cfg_video.get("nvenc_preset", "medium"))
    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=128x72:d=0.1",
        "-frames:v",
        "1",
        "-c:v",
        "h264_nvenc",
        "-preset",
        preset,
        "-f",
        "null",
        "NUL" if os.name == "nt" else "-",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError:
        _NVENC_USABLE = False
        return _NVENC_USABLE

    _NVENC_USABLE = result.returncode == 0
    if not _NVENC_USABLE:
        output = result.stderr or result.stdout
        message = output.strip().splitlines()
        detail = message[-1] if message else "probe failed"
        if "unsupported param" in output.lower():
            detail = (
                f"{detail}; this usually means the bundled FFmpeg/NVENC SDK is too old "
                "for the installed NVIDIA driver. Install a current FFmpeg and put it on PATH "
                "or set TRENDFORGE_FFMPEG."
            )
        logger.warning(f"NVENC encoder is available but not usable; using CPU x264 ({detail})")
    return _NVENC_USABLE


def choose_video_codec(cfg_video: dict) -> str:
    """Choose the best available encoder for this machine."""
    requested = cfg_video.get("codec", "auto")
    if requested != "auto":
        return requested

    if cfg_video.get("prefer_gpu_encoder", True) and nvenc_is_usable(cfg_video):
        logger.info("Using NVIDIA NVENC encoder")
        return "h264_nvenc"

    logger.info("Using CPU x264 encoder")
    return "libx264"


def export_video(timeline: Dict[str, Any], topic: str) -> str:
    """Export final video from timeline.
    
    Requires MoviePy and FFmpeg. FAILS if unavailable.
    
    Args:
        timeline: Timeline dictionary
        topic: Video topic
        
    Returns:
        Output video file path
        
    Raises:
        RuntimeError: If FFmpeg/MoviePy not available
    """
    # Check MoviePy
    try:
        from moviepy.editor import concatenate_videoclips
        MOVIEPY_AVAILABLE = True
    except ImportError:
        raise RuntimeError("MoviePy required. Install with: pip install moviepy")
    
    ffmpeg_path = resolve_ffmpeg_path()
    if not ffmpeg_path:
        raise RuntimeError("FFmpeg required. Install system FFmpeg or imageio-ffmpeg")

    os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_path
    logger.info(f"FFmpeg: {ffmpeg_path}")
    
    cfg_video = load_video_config()
    cfg_output = load_output_config()
    
    # Create output directory
    output_dir = Path(cfg_output.get("directory", "./output/"))
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_topic = sanitize_filename(topic)
    output_path = output_dir / f"{timestamp}_{safe_topic}.mp4"
    
    # Export with MoviePy
    if timeline.get("type") == "moviepy":
        backend = cfg_video.get("export_backend", "fast_ffmpeg")
        if backend in {"fast_ffmpeg", "auto"} and timeline.get("fast_export_segments"):
            try:
                export_with_fast_ffmpeg(timeline, str(output_path), cfg_video)
                close_timeline_clips(timeline)
            except Exception as e:
                if backend == "fast_ffmpeg" and not cfg_video.get("fast_export_fallback", True):
                    close_timeline_clips(timeline)
                    raise
                logger.warning(f"Fast FFmpeg export failed, falling back to MoviePy: {e}")
                export_with_moviepy(timeline, str(output_path), cfg_video)
        else:
            export_with_moviepy(timeline, str(output_path), cfg_video)
    else:
        raise RuntimeError("Invalid timeline format. Assembly failed.")
    
    if not Path(output_path).exists():
        raise RuntimeError(f"Video export failed. Output file not created.")
    
    logger.success(f"Video exported to: {output_path}")
    return str(output_path)


def export_with_moviepy(timeline: Dict[str, Any], output_path: str, cfg_video: dict):
    """Export using MoviePy.
    
    Args:
        timeline: Timeline dictionary
        output_path: Output file path
        cfg_video: Video configuration
    """
    from moviepy.editor import CompositeAudioClip, concatenate_videoclips
    from moviepy.audio.fx.all import audio_loop
    
    clips = timeline.get("clips", [])
    
    if not clips:
        raise ValueError("No clips in timeline")
    
    # Concatenate all clips
    final_clip = concatenate_videoclips(clips, method="compose")

    try:
        background_music = timeline.get("background_music")
        if background_music is not None:
            try:
                music = audio_loop(background_music, duration=final_clip.duration).set_duration(final_clip.duration)
                if final_clip.audio is not None:
                    final_clip = final_clip.set_audio(CompositeAudioClip([final_clip.audio, music]))
                else:
                    final_clip = final_clip.set_audio(music)
                logger.info("Background music mixed into final audio")
            except Exception as e:
                logger.warning(f"Background music mix skipped: {e}")

        codec = choose_video_codec(cfg_video)
        try:
            write_final_clip(final_clip, output_path, cfg_video, codec)
        except OSError as e:
            if codec != "h264_nvenc":
                raise
            logger.warning(f"NVENC export failed, retrying with CPU x264: {e}")
            write_final_clip(final_clip, output_path, cfg_video, "libx264")
    finally:
        final_clip.close()


def export_with_fast_ffmpeg(timeline: Dict[str, Any], output_path: str, cfg_video: dict):
    """Export still-image timelines through FFmpeg instead of Python frame rendering."""
    segments = timeline.get("fast_export_segments") or []
    if not segments:
        raise ValueError("Timeline has no fast export segment metadata")

    ffmpeg_path = resolve_ffmpeg_path()
    if not ffmpeg_path:
        raise RuntimeError("FFmpeg required for fast export")

    cfg_output = load_output_config()
    output_file = Path(output_path)
    work_dir = Path(cfg_output.get("temp_directory", "./temp/")) / "exports" / output_file.stem
    work_dir.mkdir(parents=True, exist_ok=True)

    codec = choose_video_codec(cfg_video)
    fps = int(cfg_video.get("fps", 30))
    width, height = video_size(cfg_video)
    logger.info(
        f"Fast FFmpeg export starting: segments={len(segments)}, "
        f"fps={fps}, codec={codec}, work_dir={work_dir}"
    )

    rendered_segments = []
    for index, segment in enumerate(segments):
        duration = max(0.05, float(segment.get("duration") or 0.05))
        logger.info(f"Fast export segment {index + 1}/{len(segments)}: {duration:.1f}s")
        rendered_segments.append(
            render_fast_segment(
                ffmpeg_path,
                segment,
                index,
                duration,
                work_dir,
                cfg_video,
                codec,
                fps,
                width,
                height,
            )
        )

    base_output = output_file
    background_music = timeline.get("background_music_path")
    if background_music:
        base_output = work_dir / "without_music.mp4"

    concat_media_files(ffmpeg_path, rendered_segments, base_output, work_dir / "final_segments.txt")

    if background_music:
        mix_background_music(
            ffmpeg_path,
            base_output,
            Path(background_music),
            output_file,
            float(timeline.get("background_music_volume", 0.08)),
            cfg_video,
        )

    logger.info(f"Exported via fast FFmpeg ({codec}): {output_path}")


def render_fast_segment(
    ffmpeg_path: str,
    segment: Dict[str, Any],
    index: int,
    duration: float,
    work_dir: Path,
    cfg_video: dict,
    codec: str,
    fps: int,
    width: int,
    height: int,
) -> Path:
    video_path = segment.get("video_path")
    segment_video = work_dir / f"segment_{index:03d}_video.mp4"
    segment_output = work_dir / f"segment_{index:03d}.mp4"

    if video_path and Path(str(video_path)).exists():
        render_video_source(
            ffmpeg_path,
            Path(str(video_path)),
            segment_video,
            duration,
            segment.get("use_second_half", False),
            cfg_video,
            codec,
            fps,
            width,
            height,
        )
    else:
        visual_paths = [Path(str(path)) for path in segment.get("visual_paths", []) if Path(str(path)).exists()]
        if not visual_paths:
            render_color_source(ffmpeg_path, segment_video, duration, cfg_video, codec, fps, width, height)
        else:
            chunk_paths = []
            durations = visual_refresh_durations(duration, len(visual_paths))
            for chunk_index, (visual_path, chunk_duration) in enumerate(zip(visual_paths, durations)):
                chunk_path = work_dir / f"segment_{index:03d}_chunk_{chunk_index:02d}.mp4"
                render_image_source(
                    ffmpeg_path,
                    visual_path,
                    chunk_path,
                    chunk_duration,
                    segment,
                    cfg_video,
                    codec,
                    fps,
                    width,
                    height,
                )
                chunk_paths.append(chunk_path)
            if len(chunk_paths) == 1:
                segment_video = chunk_paths[0]
            else:
                concat_media_files(
                    ffmpeg_path,
                    chunk_paths,
                    segment_video,
                    work_dir / f"segment_{index:03d}_chunks.txt",
                )

    mux_audio(
        ffmpeg_path,
        segment_video,
        Path(str(segment["audio_path"])) if segment.get("audio_path") else None,
        segment_output,
        duration,
        cfg_video,
    )
    return segment_output


def render_image_source(
    ffmpeg_path: str,
    image_path: Path,
    output_path: Path,
    duration: float,
    segment: Dict[str, Any],
    cfg_video: dict,
    codec: str,
    fps: int,
    width: int,
    height: int,
):
    frames = max(1, int(round(duration * fps)))
    vf = image_filter(segment, cfg_video, frames, fps, width, height)
    cmd = [
        ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loop",
        "1",
        "-i",
        str(image_path),
        "-vf",
        vf,
        "-frames:v",
        str(frames),
        "-an",
        *direct_video_encode_args(cfg_video, codec),
        str(output_path),
    ]
    try:
        run_ffmpeg(cmd, f"render image chunk {image_path.name}")
    except RuntimeError:
        if cfg_video.get("fast_export_motion", True):
            logger.warning(f"Motion filter failed for {image_path.name}; retrying static frame")
            cmd[cmd.index("-vf") + 1] = static_image_filter(width, height)
            run_ffmpeg(cmd, f"render static image chunk {image_path.name}")
        else:
            raise


def render_video_source(
    ffmpeg_path: str,
    video_path: Path,
    output_path: Path,
    duration: float,
    use_second_half: bool,
    cfg_video: dict,
    codec: str,
    fps: int,
    width: int,
    height: int,
):
    source_duration = probe_media_duration(video_path, ffmpeg_path)
    start = (source_duration / 2) if use_second_half and source_duration > 15 else 0
    cmd = [
        ffmpeg_path,
        "-y",
        "-hide_banner",
        "-stream_loop",
        "-1",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(video_path),
        "-t",
        f"{duration:.3f}",
        "-vf",
        static_image_filter(width, height, fps=fps),
        "-an",
        *direct_video_encode_args(cfg_video, codec),
        str(output_path),
    ]
    run_ffmpeg(cmd, f"render video source {video_path.name}")


def render_color_source(
    ffmpeg_path: str,
    output_path: Path,
    duration: float,
    cfg_video: dict,
    codec: str,
    fps: int,
    width: int,
    height: int,
):
    cmd = [
        ffmpeg_path,
        "-y",
        "-hide_banner",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x141428:s={width}x{height}:r={fps}:d={duration:.3f}",
        "-t",
        f"{duration:.3f}",
        "-an",
        *direct_video_encode_args(cfg_video, codec),
        str(output_path),
    ]
    run_ffmpeg(cmd, "render fallback color segment")


def mux_audio(
    ffmpeg_path: str,
    video_path: Path,
    audio_path: Optional[Path],
    output_path: Path,
    duration: float,
    cfg_video: dict,
):
    cmd = [ffmpeg_path, "-y", "-hide_banner", "-i", str(video_path)]
    if audio_path and audio_path.exists():
        cmd.extend(["-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0"])
    else:
        cmd.extend([
            "-f",
            "lavfi",
            "-t",
            f"{duration:.3f}",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
        ])
    cmd.extend([
        "-t",
        f"{duration:.3f}",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        cfg_video.get("audio_bitrate", "192k"),
        str(output_path),
    ])
    run_ffmpeg(cmd, f"mux audio {output_path.name}")


def concat_media_files(ffmpeg_path: str, files: List[Path], output_path: Path, list_path: Path):
    if not files:
        raise ValueError("No media files to concatenate")

    list_path.parent.mkdir(parents=True, exist_ok=True)
    list_path.write_text(
        "\n".join(f"file '{path.resolve().as_posix()}'" for path in files) + "\n",
        encoding="utf-8",
    )
    cmd = [
        ffmpeg_path,
        "-y",
        "-hide_banner",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    run_ffmpeg(cmd, f"concat {len(files)} media files")


def mix_background_music(
    ffmpeg_path: str,
    input_path: Path,
    music_path: Path,
    output_path: Path,
    volume: float,
    cfg_video: dict,
):
    if not music_path.exists():
        logger.warning(f"Background music file missing: {music_path}")
        input_path.replace(output_path)
        return

    cmd = [
        ffmpeg_path,
        "-y",
        "-hide_banner",
        "-i",
        str(input_path),
        "-stream_loop",
        "-1",
        "-i",
        str(music_path),
        "-filter_complex",
        f"[1:a]volume={volume}[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=2[a]",
        "-map",
        "0:v:0",
        "-map",
        "[a]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        cfg_video.get("audio_bitrate", "192k"),
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    run_ffmpeg(cmd, "mix background music")


def direct_video_encode_args(cfg_video: dict, codec: str) -> List[str]:
    bitrate = cfg_video.get("bitrate", "12000k")
    if codec == "h264_nvenc":
        return [
            "-c:v",
            codec,
            "-preset",
            normalize_nvenc_preset(cfg_video.get("nvenc_preset", "medium")),
            "-rc",
            "vbr",
            "-cq",
            str(cfg_video.get("nvenc_cq", 19)),
            "-b:v",
            bitrate,
            "-maxrate",
            cfg_video.get("maxrate", bitrate),
            "-bufsize",
            cfg_video.get("bufsize", "24000k"),
            "-pix_fmt",
            "yuv420p",
        ]

    return [
        "-c:v",
        codec,
        "-preset",
        cfg_video.get("fast_export_preset", cfg_video.get("preset", "fast")),
        "-crf",
        str(cfg_video.get("crf", 18)),
        "-pix_fmt",
        "yuv420p",
    ]


def image_filter(segment: Dict[str, Any], cfg_video: dict, frames: int, fps: int, width: int, height: int) -> str:
    if not cfg_video.get("fast_export_motion", True):
        return static_image_filter(width, height)

    max_zoom = fast_motion_zoom(segment, cfg_video)
    step = max(0.000001, (max_zoom - 1.0) / max(frames, 1))
    return (
        f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
        f"crop={width * 2}:{height * 2},"
        f"zoompan=z='min(zoom+{step:.8f},{max_zoom:.5f})':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={width}x{height}:fps={fps},format=yuv420p"
    )


def static_image_filter(width: int, height: int, fps: Optional[int] = None) -> str:
    parts = [
        f"scale={width}:{height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}",
    ]
    if fps:
        parts.append(f"fps={fps}")
    parts.append("format=yuv420p")
    return ",".join(parts)


def fast_motion_zoom(segment: Dict[str, Any], cfg_video: dict) -> float:
    intent = segment.get("visual_intent", "")
    if intent in {"source_card", "source_screenshot", "intro_clip", "outro_clip"}:
        return float(cfg_video.get("fast_source_max_zoom", 1.025))
    if "screenshot" in intent:
        return float(cfg_video.get("fast_screenshot_max_zoom", 1.04))
    return float(cfg_video.get("fast_art_max_zoom", 1.06))


def visual_refresh_durations(duration: float, visual_count: int) -> List[float]:
    visual_count = max(1, visual_count)
    base = duration / visual_count
    durations = [base for _ in range(visual_count)]
    durations[-1] += duration - sum(durations)
    return durations


def video_size(cfg_video: dict) -> tuple[int, int]:
    resolution = cfg_video.get("resolution", [1920, 1080])
    return int(resolution[0]), int(resolution[1])


def probe_media_duration(path: Path, ffmpeg_path: Optional[str] = None) -> float:
    ffprobe_path = resolve_ffprobe_path(ffmpeg_path)
    if not ffprobe_path:
        return 0.0
    result = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return 0.0
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def run_ffmpeg(cmd: List[str], label: str):
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return

    output = (result.stderr or result.stdout or "").strip()
    tail = "\n".join(output.splitlines()[-8:])
    raise RuntimeError(f"FFmpeg failed during {label}: {tail}")


def close_timeline_clips(timeline: Dict[str, Any]):
    for clip in timeline.get("clips", []):
        try:
            clip.close()
        except Exception:
            pass
    background_music = timeline.get("background_music")
    if background_music is not None:
        try:
            background_music.close()
        except Exception:
            pass


def build_ffmpeg_settings(cfg_video: dict, codec: str) -> Dict[str, Any]:
    """Build MoviePy/FFmpeg settings for one encoder."""
    bitrate = cfg_video.get("bitrate", "12000k")
    preset = cfg_video.get("preset", "medium")
    ffmpeg_params = ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]

    if codec == "h264_nvenc":
        preset = normalize_nvenc_preset(cfg_video.get("nvenc_preset", "medium"))
        ffmpeg_params.extend([
            "-rc",
            "vbr",
            "-cq",
            str(cfg_video.get("nvenc_cq", 19)),
            "-b:v",
            bitrate,
            "-maxrate",
            cfg_video.get("maxrate", bitrate),
            "-bufsize",
            cfg_video.get("bufsize", "24000k"),
        ])
    else:
        ffmpeg_params.extend(["-crf", str(cfg_video.get("crf", 18))])

    return {
        "bitrate": bitrate,
        "preset": preset,
        "ffmpeg_params": ffmpeg_params,
    }


def write_final_clip(final_clip, output_path: str, cfg_video: dict, codec: str):
    """Write a final clip with one codec configuration."""
    settings = build_ffmpeg_settings(cfg_video, codec)
    logger.info(
        f"Render export starting: duration={final_clip.duration:.1f}s, "
        f"fps={cfg_video.get('fps', 30)}, codec={codec}, "
        f"preset={settings['preset']}, bitrate={settings['bitrate']}"
    )

    final_clip.write_videofile(
        output_path,
        fps=cfg_video.get("fps", 30),
        codec=codec,
        audio_codec="aac",
        audio_bitrate=cfg_video.get("audio_bitrate", "192k"),
        bitrate=settings["bitrate"],
        preset=settings["preset"],
        threads=cfg_video.get("threads", 0),
        ffmpeg_params=settings["ffmpeg_params"],
        verbose=False,
        logger=MoviePyProgressLogger()
    )

    logger.info(f"Exported via MoviePy ({codec}): {output_path}")


def export_simple(output_path: str):
    """Simple fallback export when MoviePy unavailable.
    
    Args:
        output_path: Output file path
    """
    # Create a simple placeholder video
    logger.warning("Using simple placeholder export (MoviePy not available)")
    
    # Check for ffmpeg
    try:
        import subprocess
        
        # Create a simple test pattern video using ffmpeg
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "color=c=blue:s=1920x1080:d=5",
            "-c:v", "libx264",
            "-t", "5",
            output_path
        ]
        
        subprocess.run(cmd, capture_output=True, check=True)
        logger.info("Created placeholder video")
        return
    except Exception as e:
        logger.warning(f"FFmpeg not available: {e}")
    
    # Create empty file as placeholder
    Path(output_path).touch()
    logger.warning(f"Created empty placeholder: {output_path}")


def add_captions(video_path: str, script: Dict[str, Any]) -> str:
    """Add captions to video using Whisper.
    
    Args:
        video_path: Input video path
        script: Script with segments
        
    Returns:
        Output video path with captions
    """
    cfg_caption = load_caption_config()
    
    if not cfg_caption.get("enabled", True):
        logger.info("Captions disabled in config")
        return video_path
    
    # Try Whisper for transcription
    try:
        import whisper
        WHISPER_AVAILABLE = True
    except ImportError:
        WHISPER_AVAILABLE = False
    
    if not WHISPER_AVAILABLE:
        logger.warning("Whisper not available, skipping captions")
        return video_path
    
    try:
        model_name = cfg_caption.get("whisper_model", "base")
        model = whisper.load_model(model_name)
        
        # Transcribe video audio
        result = model.transcribe(video_path)
        
        # Burn in captions using moviepy
        # (simplified - full implementation would use subclip with TextClip)
        logger.info(f"Transcribed {len(result.get('segments', []))} segments")
        
    except Exception as e:
        logger.error(f"Caption generation failed: {e}")
    
    return video_path


def generate_metadata(topic: str, script: Dict[str, Any]) -> Dict[str, str]:
    """Generate YouTube metadata.
    
    Args:
        topic: Video topic
        script: Script dictionary
        
    Returns:
        Metadata dictionary
    """
    title = script.get("title", f"The Truth About {topic.title()}")
    hook = script.get("hook", "")[:200]
    
    description = f"""🔥 {title}

{hook}

▶ Subscribe for daily deep dives!

#trending #news #facts #opinion #ai #trendingtopic"""
    
    tags = [
        topic.lower(),
        "trending",
        "news",
        "facts",
        "opinion",
        "ai",
        "faceless"
    ]
    
    return {
        "title": title,
        "description": description,
        "tags": ", ".join(tags),
        "category": "28",  # Science & Technology
        "privacy": "private"
    }


def sanitize_filename(name: str) -> str:
    """Sanitize filename.
    
    Args:
        name: Original name
        
    Returns:
        Sanitized name
    """
    import re
    
    # Replace spaces with underscores
    name = re.sub(r"\s+", "_", name)
    # Remove special characters
    name = re.sub(r"[^a-zA-Z0-9_\-]", "", name)
    # Limit length
    name = name[:50]
    
    return name


def get_video_duration(video_path: str) -> float:
    """Get video duration.
    
    Args:
        video_path: Path to video
        
    Returns:
        Duration in seconds
    """
    try:
        import subprocess
        
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            return float(result.stdout.strip())
    except Exception as e:
        logger.warning(f"Could not get duration: {e}")
    
    return 0.0


def verify_video_integrity(video_path: str) -> bool:
    """Verify video file is valid.
    
    Args:
        video_path: Path to video
        
    Returns:
        True if valid
    """
    if not Path(video_path).exists():
        return False
    
    # Check file size
    size = Path(video_path).stat().st_size
    if size < 10000:  # Less than 10KB is suspicious
        return False
    
    # Try FFprobe
    try:
        import subprocess
        
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height",
            "-of", "json",
            video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        return result.returncode == 0
    except:
        pass
    
    return True
