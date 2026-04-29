"""TrendForge - Video Editor Module

Assembles video timeline with premium transitions:
- Ken Burns (zoom in/out, slow pan)
- Crossfade
- Slide transitions
- Glitch effect for shock segments
- Audio-synced duration
"""

import os
import yaml
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
from loguru import logger

# Patch PIL for MoviePy compatibility
try:
    from PIL import Image
    if not hasattr(Image, 'ANTIALIAS'):
        Image.ANTIALIAS = Image.LANCZOS
except ImportError:
    pass

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

# Require MoviePy
try:
    from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip
    from moviepy.video.fx import resize, fadein, fadeout
    try:
        from moviepy.video.fx import blur
    except ImportError:
        blur = None
    try:
        from moviepy.video.fx.all import dim
    except ImportError:
        dim = None
    from moviepy.video.VideoClip import ImageClip, ColorClip
    MOVIEPY_AVAILABLE = True
except Exception as e:
    MOVIEPY_AVAILABLE = False
    raise RuntimeError(f"MoviePy required. Install: pip install moviepy ({e})")


# Transition presets by segment type
TRANSITION_PRESETS = {
    "hook": {
        "effect": "ken_burns_zoom_in",
        "duration": 0.8,
        "scale_start": 1.0,
        "scale_end": 1.15,
    },
    "fact": {
        "effect": "crossfade",
        "duration": 0.5,
    },
    "opinion": {
        "effect": "slide_left",
        "duration": 0.6,
    },
    "verdict": {
        "effect": "ken_burns_zoom_out",
        "duration": 0.8,
        "scale_start": 1.1,
        "scale_end": 1.0,
    },
    "transition": {
        "effect": "flash",
        "duration": 0.3,
    }
}


def load_video_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f).get("video", {})
    return {}


def load_motion_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return (yaml.safe_load(f) or {}).get("motion", {})
    return {}


def assemble_timeline(
    audio_files: List[Dict[str, Any]],
    screenshot_files: List[str],
    script: Dict[str, Any],
    skip_first_segment: bool = False,
    skip_last_segment: bool = False
) -> Dict[str, Any]:
    """Assemble timeline with premium transitions and audio-synced durations.
    
    Args:
        audio_files: List with 'path', 'duration', 'segment_type'
        image_files: List of image paths
        script: Script dictionary
        skip_first_segment: If True, skip first audio segment (for when intro video handles intro audio)
        skip_last_segment: If True, skip last audio segment (for when outro video handles outro audio)
        
    Returns:
        Timeline with clips and transitions
    """
    cfg = load_video_config()
    
    if not MOVIEPY_AVAILABLE:
        raise RuntimeError("MoviePy required. pip install moviepy")
    
    # Skip first segment if intro video is handling intro audio
    if skip_first_segment and audio_files:
        audio_files = audio_files[1:]
        if screenshot_files:
            screenshot_files = screenshot_files[1:]
        logger.info("Skipping first segment (intro video handles intro audio)")
    
    # Skip last segment if outro video is handling outro audio
    if skip_last_segment and audio_files:
        audio_files = audio_files[:-1]
        if screenshot_files:
            screenshot_files = screenshot_files[:-1]
        logger.info("Skipping last segment (outro video handles outro audio)")
    
    logger.info(f"Assembling {len(audio_files)} segments with transitions...")
    
    logger.info(f"Assembling {len(audio_files)} segments with transitions...")
    
    width = cfg.get("resolution", [1920, 1080])[0]
    height = cfg.get("resolution", [1920, 1080])[1]
    fps = cfg.get("fps", 30)
    
    clips = []
    transitions = []  # Track what transition used
    
    for i, audio_file in enumerate(audio_files):
        segment = audio_file.get("segment", {})
        audio_path = audio_file.get("path", "")
        audio_duration = audio_file.get("duration", 3.0)
        seg_type = segment.get("type", "fact")
        motion_hint = audio_file.get("motion_hint") or "slow_push_in"
        visual_intent = audio_file.get("visual_intent") or ""
        
        # Get visual - every segment must use its own asset. Do not recycle
        # earlier paths, because repeated visuals make long videos feel stale.
        if screenshot_files and len(screenshot_files) > 0:
            if i < len(screenshot_files):
                image_path = screenshot_files[i]
            else:
                image_path = ""
            use_screenshot = Path(image_path).exists()
        else:
            use_screenshot = False
            image_path = ""  # Not used when no screenshots
        
        # Get transition preset for this segment type
        preset = TRANSITION_PRESETS.get(seg_type, TRANSITION_PRESETS["fact"])
        
        # Create image clip
        if use_screenshot:
            img_clip = ImageClip(image_path).resize(newsize=(width, height))
        else:
            img_clip = ColorClip(size=(width, height), color=(20, 20, 40)).set_duration(audio_duration)
        
        # Apply transition effect
        if preset["effect"] == "ken_burns_zoom_in":
            clip = apply_motion(
                img_clip,
                audio_duration,
                motion_hint=motion_hint,
                visual_intent=visual_intent,
                default_start=preset.get("scale_start", 1.0),
                default_end=preset.get("scale_end", 1.15),
            )
        elif preset["effect"] == "ken_burns_zoom_out":
            clip = apply_motion(
                img_clip,
                audio_duration,
                motion_hint=motion_hint,
                visual_intent=visual_intent,
                default_start=preset.get("scale_start", 1.1),
                default_end=preset.get("scale_end", 1.0),
            )
        elif preset["effect"] == "crossfade":
            clip = apply_crossfade(img_clip, audio_duration, preset.get("duration", 0.5))
        elif preset["effect"] == "slide_left":
            clip = apply_slide(img_clip, audio_duration, "left", preset.get("duration", 0.6))
        elif preset["effect"] == "flash":
            clip = apply_flash(img_clip, audio_duration, preset.get("duration", 0.3))
        else:
            clip = img_clip.set_duration(audio_duration)
        
        # Load audio
        if audio_path and Path(audio_path).exists():
            audio = AudioFileClip(audio_path)
            clip = clip.set_audio(audio)
        
        clips.append(clip)
        transitions.append(preset["effect"])
        
        logger.debug(f"segment {i}: {seg_type} = {preset['effect']}, {audio_duration:.1f}s")
    
    timeline = {
        "clips": clips,
        "transitions": transitions,
        "config": cfg,
        "type": "moviepy"
    }
    
    logger.info(f"Timeline: {len(clips)} clips, transitions: {transitions}")
    return timeline


# ========== TRANSITION EFFECTS ==========

def apply_ken_burns(clip, duration: float, scale_start: float = 1.0, scale_end: float = 1.15):
    """Ken Burns effect - slow zoom (in or out).
    
    Args:
        clip: Image clip
        duration: Total duration
        scale_start: Start scale (1.0 = original)
        scale_end: End scale (1.15 = 15% zoom in)
        
    Returns:
        Clip with Ken Burns
    """
    return apply_motion(clip, duration, default_start=scale_start, default_end=scale_end)


def apply_motion(
    clip,
    duration: float,
    motion_hint: str = "slow_push_in",
    visual_intent: str = "",
    default_start: float = 1.0,
    default_end: float = 1.1,
):
    """Continuous zoom/pan for still visuals while preserving frame size."""
    motion_cfg = load_motion_config()
    if not motion_cfg.get("enabled", True):
        return clip.set_duration(duration)

    width, height = clip.size
    max_zoom = float(motion_cfg.get("ai_art_max_zoom", 1.12))
    if visual_intent in {"source_card", "source_screenshot"}:
        max_zoom = float(motion_cfg.get("source_card_max_zoom", 1.04))
    elif "screenshot" in visual_intent:
        max_zoom = float(motion_cfg.get("screenshot_max_zoom", 1.08))

    if motion_hint == "slow_pull_back":
        start, end = min(max_zoom, max(default_start, 1.04)), 1.0
    elif motion_hint == "source_push_in":
        start, end = 1.0, max_zoom
    else:
        start, end = default_start, min(max_zoom, max(default_end, 1.04))

    clip = clip.set_duration(duration)

    def scale_at(t):
        progress = min(1.0, max(0.0, t / max(duration, 0.01)))
        eased = progress * progress * (3 - 2 * progress)
        return start + (end - start) * eased

    moving = clip.resize(lambda t: scale_at(t))

    def position_at(t):
        scale = scale_at(t)
        extra_w = max(0, width * scale - width)
        extra_h = max(0, height * scale - height)
        progress = min(1.0, max(0.0, t / max(duration, 0.01)))
        if motion_hint == "pan_left":
            x = -extra_w * progress
        elif motion_hint == "pan_right":
            x = -extra_w * (1 - progress)
        else:
            x = -extra_w / 2
        y = -extra_h / 2
        return (x, y)

    return CompositeVideoClip([moving.set_position(position_at)], size=(width, height)).set_duration(duration)


def apply_crossfade(clip, duration: float, fade_duration: float = 0.5):
    """Simple crossfade in/out.
    
    Args:
        clip: Image clip  
        duration: Total duration
        fade_duration: Fade length
        
    Returns:
        Clip with fades
    """
    # Set duration FIRST before fades (MoviePy requires duration for fade operations)
    clip = clip.set_duration(duration)
    
    if fade_duration > 0:
        clip = clip.fadein(fade_duration)
        clip = clip.fadeout(fade_duration)
    
    return clip


def apply_slide(clip, duration: float, direction: str = "left", slide_duration: float = 0.6):
    """Slide transition.
    
    Args:
        clip: Image clip
        duration: Total duration
        direction: left, right, up, down
        slide_duration: Slide length
        
    Returns:
        Clip with slide
    """
    # Basic crossfade for now - full slide needs position transforms
    return apply_crossfade(clip, duration, slide_duration)


def apply_flash(clip, duration: float, flash_duration: float = 0.3):
    """Flash/glitch effect for shock segments.
    
    Args:
        clip: Image clip
        duration: Total duration
        flash_duration: Flash effect length
        
    Returns:
        Clip with flash effect
    """
    try:
        # Check if dim effect is available
        if dim is None:
            # Fallback: just return normal clip if dim is not available
            return clip.set_duration(duration)
        
        # Add brightness flash at start
        bright = clip.fx(dim, 0.3).set_duration(flash_duration)
        normal = clip.set_duration(flash_duration)
        
        # Fade in from flash
        result = concatenate_videoclips([bright, normal], method="compose")
        result = result.set_duration(duration)
        
        return result
    except Exception as e:
        logger.warning(f"Flash effect failed: {e}, using normal clip")
        return clip.set_duration(duration)


def crossfade_between(clip_a, clip_b, crossfade_duration: float):
    """Crossfade between two clips.
    
    Args:
        clip_a: First clip
        clip_b: Second clip  
        crossfade_duration: Fade length
        
    Returns:
        Crossfaded clip
    """
    # Ensure both clips have duration - get from whichever has it, or default
    dur_a = getattr(clip_a, 'duration', None)
    dur_b = getattr(clip_b, 'duration', None)
    
    # If either missing duration, use the other's or assume 10s
    if dur_a is None and dur_b is None:
        default_dur = 10.0
        clip_a = clip_a.set_duration(default_dur)
        clip_b = clip_b.set_duration(default_dur)
    elif dur_a is None:
        clip_a = clip_a.set_duration(dur_b)
    elif dur_b is None:
        clip_b = clip_b.set_duration(dur_a)
    
    clip_a_faded = clip_a.fadeout(crossfade_duration)
    clip_b_faded = clip_b.fadein(crossfade_duration)
    
    return CompositeVideoClip([clip_a_faded, clip_b_faded])


# ========== ADDITIONAL EFFECTS ==========

def apply_blur_in(clip, duration: float, blur_max: float = 3.0):
    """Blur in effect.
    
    Args:
        clip: Image clip
        duration: Total duration
        blur_max: Max blur strength
        
    Returns:
        Clip with blur in
    """
    blurred = clip.fx(blur, blur_max)
    result = crossfade_between(blurred, clip, duration * 0.2)
    return result.set_duration(duration)


def apply_subtitle_overlay(clip, text: str, font_size: int = 52):
    """Add text overlay (for captions).
    
    Args:
        clip: Image clip
        text: Text to overlay
        font_size: Font size
        
    Returns:
        Clip with text
    """
    # Would use TextClip from moviepy - placeholder
    return clip


# ========== TIMELINE HELPERS ==========

def add_intro_clip(timeline: Dict, intro_path: str) -> Dict:
    """Add branded intro clip at the START of video.
    
    If it's a combined intro-outro file, use the FIRST HALF as intro.
    Keeps original audio from the intro clip.
    """
    if not Path(intro_path).exists():
        logger.warning(f"Intro not found: {intro_path}")
        return timeline
    
    try:
        intro = VideoFileClip(intro_path)
        
        # If duration > 15s, assume it's intro-outro combined - split in half
        if intro.duration > 15:
            intro = intro.subclip(0, intro.duration / 2)
            logger.info(f"Intro half: {intro.duration:.1f}s")
        
        # Ensure audio is included (if intro has audio)
        if intro.audio is not None:
            logger.info("Intro audio: ON")
        
        clips = timeline.get("clips", [])
        clips.insert(0, intro)
        timeline["clips"] = clips
        logger.info(f"Intro added: {intro.duration:.1f}s")
    except Exception as e:
        logger.error(f"Intro error: {e}")
    
    return timeline


def apply_intro_outro_narration_clips(timeline: Dict, intro_path: str, outro_path: str) -> Dict:
    """Use silent intro/outro videos as visuals under first/last narration audio."""
    clips = timeline.get("clips", [])
    if not clips:
        return timeline

    if intro_path and Path(intro_path).exists():
        replaced = replace_clip_visual_with_video(
            clips[0],
            intro_path,
            timeline.get("config", {}),
            use_second_half=False,
        )
        if replaced is not None:
            clips[0] = replaced
            timeline["intro_clip_applied"] = True
            logger.info(f"Intro clip used under narration: {intro_path}")

    if outro_path and Path(outro_path).exists() and clips:
        replaced = replace_clip_visual_with_video(
            clips[-1],
            outro_path,
            timeline.get("config", {}),
            use_second_half=True,
        )
        if replaced is not None:
            clips[-1] = replaced
            timeline["outro_clip_applied"] = True
            logger.info(f"Outro clip used under narration: {outro_path}")

    timeline["clips"] = clips
    return timeline


def replace_clip_visual_with_video(base_clip, video_path: str, cfg: Dict[str, Any], use_second_half: bool = False):
    """Create a video-backed clip with the base narration audio and duration."""
    try:
        from moviepy.video.fx.all import loop

        width = cfg.get("resolution", [1920, 1080])[0]
        height = cfg.get("resolution", [1920, 1080])[1]
        target_duration = base_clip.duration
        audio = base_clip.audio
        video = VideoFileClip(video_path)

        if video.duration > 15:
            midpoint = video.duration / 2
            if use_second_half:
                video = video.subclip(midpoint, video.duration)
            else:
                video = video.subclip(0, midpoint)

        video = video.resize(newsize=(width, height))
        if video.duration < target_duration:
            video = video.fx(loop, duration=target_duration)
        else:
            video = video.subclip(0, min(video.duration, target_duration))
        video = video.set_duration(target_duration)
        if audio is not None:
            video = video.set_audio(audio)
        return video
    except Exception as e:
        logger.warning(f"Could not place narration over {video_path}: {e}")
        return None


def add_outro_clip(timeline: Dict, outro_path: str) -> Dict:
    """Add branded outro clip at the END of video.
    
    If it's a combined intro-outro file, use the SECOND HALF as outro.
    Keeps original audio from the outro clip.
    """
    if not Path(outro_path).exists():
        logger.warning(f"Outro not found: {outro_path}")
        return timeline
    
    try:
        outro = VideoFileClip(outro_path)
        
        # If duration > 15s, assume it's intro-outro combined - use second half
        if outro.duration > 15:
            outro = outro.subclip(outro.duration / 2)
            logger.info(f"Outro half: {outro.duration:.1f}s")
        
        # Ensure audio is included (if outro has audio)
        if outro.audio is not None:
            logger.info("Outro audio: ON")
        
        clips = timeline.get("clips", [])
        clips.append(outro)
        timeline["clips"] = clips
        logger.info(f"Outro added: {outro.duration:.1f}s")
    except Exception as e:
        logger.error(f"Outro error: {e}")
    
    return timeline


def add_background_music(timeline: Dict, music_path: str, volume: float = 0.08) -> Dict:
    """Add background music with ducking.
    
    Args:
        timeline: Timeline dict
        music_path: Music file path
        volume: Music volume ( ducked under voice)
    """
    if not Path(music_path).exists() or volume <= 0:
        return timeline
    
    try:
        from moviepy.audio.fx.all import volumex
        
        music = AudioFileClip(music_path)
        
        # Duck music under voice - reduce volume
        music = music.fx(volumex, volume)
        
        timeline["background_music"] = music
        logger.info(f"Background music added, volume: {volume}")
    except Exception as e:
        logger.error(f"Music error: {e}")
    
    return timeline


def calculate_total_duration(timeline: Dict) -> float:
    """Get total video duration."""
    total = 0.0
    for clip in timeline.get("clips", []):
        total += clip.duration
    return total


def get_segment_order(timeline: Dict) -> List[str]:
    """Get segment types in order."""
    types = []
    for clip in timeline.get("clips", []):
        # Would extract from segment metadata
        types.append("segment")
    return types
