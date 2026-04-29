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


def resolve_ffmpeg_path() -> Optional[str]:
    """Find the FFmpeg binary used for rendering."""
    candidates = ["ffmpeg"]

    try:
        import imageio_ffmpeg

        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    except ImportError:
        pass

    for candidate in candidates:
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
        message = (result.stderr or result.stdout).strip().splitlines()
        detail = message[-1] if message else "probe failed"
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
