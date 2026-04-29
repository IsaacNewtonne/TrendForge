"""TrendForge - AI Image Generation Module

Generates images for video segments using Stable Diffusion XL or FLUX.
With proper prompt engineering: style anchors, negative prompts per segment type,
and aspect-ratio-aware composition.
"""

import os
import yaml
import hashlib
import random
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from loguru import logger
import re

from modules.image_diagnostics import analyze_image, is_video_ready_image

# Configuration
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

# Style anchors - locked visuals that make content consistent
STYLE_ANCHORS = {
    "hook": {
        "prompt": "cinematic lighting, dramatic, high contrast, film grain, documentary style",
        "negative": "cartoon, anime, watermark, text, blurry, low quality"
    },
    "fact": {
        "prompt": "data visualization, clean, professional, infographic style, 4k",
        "negative": "cartoon, watermark, text, logo, blurry, distortion"
    },
    "opinion": {
        "prompt": "interview style, professional lighting, clean background, news broadcast",
        "negative": "watermark, text, logo, blurry, nsfw, UI elements"
    },
    "verdict": {
        "prompt": "thoughtful, cinematic, conclusion, balanced lighting, reflective",
        "negative": "watermark, text, logo, blurry, distorted hands"
    },
    "transition": {
        "prompt": "abstract, smooth transition, cinematic, minimal",
        "negative": "watermark, text, nsfw, disturbing"
    }
}

# Colour grades by emotion
COLOUR_GRADES = {
    "danger": "warm orange tint, high contrast, alarm tones",
    "money": "green undertone, premium, gold accents",
    "ai": "cool blue, futuristic, cyberpunk aesthetic",
    "curiosity": "mysterious, desaturated,Question-mark lighting",
    "shock": "high contrast, red accents, dramatic shadows",
    "default": "cinematic, balanced, neutral grade"
}

torch = None
StableDiffusionXLPipeline = None
StableDiffusionPipeline = None
DIFFUSERS_AVAILABLE: Optional[bool] = None
DIFFUSERS_ERROR: Optional[str] = None
PROMPT_TOKEN_BUDGET = 72
SAFETY_RETRY_PROMPT = (
    "abstract technology documentary scene, clean geometric forms, data-inspired lighting, "
    "professional editorial composition"
)


def ensure_diffusers_available() -> bool:
    """Lazy-load torch and diffusers only when image generation needs them."""
    global torch, StableDiffusionXLPipeline, StableDiffusionPipeline, DIFFUSERS_AVAILABLE, DIFFUSERS_ERROR

    if DIFFUSERS_AVAILABLE is not None:
        return DIFFUSERS_AVAILABLE

    try:
        import torch as torch_module
        from diffusers import (
            StableDiffusionPipeline as sd_pipeline,
            StableDiffusionXLPipeline as sdxl_pipeline,
        )

        torch = torch_module
        StableDiffusionPipeline = sd_pipeline
        StableDiffusionXLPipeline = sdxl_pipeline
        DIFFUSERS_AVAILABLE = True
        DIFFUSERS_ERROR = None
    except Exception as e:
        DIFFUSERS_AVAILABLE = False
        DIFFUSERS_ERROR = str(e)

    return DIFFUSERS_AVAILABLE

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False


def detect_emotion_from_topic(topic: str) -> str:
    """Detect emotion for colour grading.
    
    Args:
        topic: Video topic
        
    Returns:
        Emotion key
    """
    topic_lower = topic.lower()
    
    if any(w in topic_lower for w in ["exposed", "scandal", "lie", "fake"]):
        return "shock"
    if any(w in topic_lower for w in ["danger", "risk", "warning", "avoid"]):
        return "danger"
    if any(w in topic_lower for w in ["money", "rich", "profit", "cost"]):
        return "money"
    if any(w in topic_lower for w in ["ai", "gpt", "robot", "automation"]):
        return "ai"
    if any(w in topic_lower for w in ["why", "how", "mystery", "secret"]):
        return "curiosity"
    
    return "default"


def compact_prompt(prompt: str, token_budget: int = PROMPT_TOKEN_BUDGET) -> str:
    """Keep SD 1.5 prompts below CLIP's 77-token limit."""
    normalized = re.sub(r"\s+", " ", str(prompt or "")).strip(" ,")
    clauses = [clause.strip() for clause in normalized.split(",") if clause.strip()]
    kept: List[str] = []
    token_count = 0

    for clause in clauses:
        clause_tokens = len(re.findall(r"\w+|[^\w\s]", clause))
        if kept and token_count + clause_tokens > token_budget:
            break
        kept.append(clause)
        token_count += clause_tokens

    compacted = ", ".join(kept)
    words = compacted.split()
    if len(words) > token_budget:
        compacted = " ".join(words[:token_budget]).rstrip(" ,")
    return compacted or normalized[:320]


def engineer_prompt(segment: Dict[str, Any], topic: str, width: int, height: int) -> str:
    """Engineer a proper image prompt with style anchors.
    
    Args:
        segment: Script segment with type and text
        topic: Video topic
        width: Image width
        height: Image height
        
    Returns:
        Engineered prompt string
    """
    seg_type = segment.get("type", "fact")
    raw_text = segment.get("image_prompt", f"Image about {topic}")
    
    # Remove generic terms
    raw_text = re.sub(r",?\s*cinematic,?\s*4K", "", raw_text, flags=re.IGNORECASE)
    raw_text = re.sub(r",?\s*high quality", "", raw_text, flags=re.IGNORECASE)
    
    # Get style anchor
    style = STYLE_ANCHORS.get(seg_type, STYLE_ANCHORS["fact"])
    style_prompt = style["prompt"]
    
    # Get colour grade
    emotion = detect_emotion_from_topic(topic)
    colour_grade = COLOUR_GRADES.get(emotion, COLOUR_GRADES["default"])
    
    # Aspect ratio awareness
    aspect = "16:9" if width >= height else "9:16"
    if aspect == "16:9":
        composition = "wide shot, center composition"
    else:
        composition = "portrait, center composition"
    
    # Build final prompt
    prompt = f"{raw_text}, {style_prompt}, {colour_grade}, {composition}, {aspect} aspect ratio, photorealistic"
    
    return prompt


def get_negative_prompt(segment_type: str, topic: str) -> str:
    """Get negative prompt for segment type.
    
    Args:
        segment_type: Segment type (hook, fact, etc)
        topic: Video topic
        
    Returns:
        Negative prompt string
    """
    seg_type = segment_type
    base = STYLE_ANCHORS.get(seg_type, STYLE_ANCHORS["fact"])
    negative = base.get("negative", "")
    
    # Add topic-specific negatives
    topic_negative = ", ".join([
        "text overlay",
        " watermark",
        " signature",
        " username",
        " UI elements",
        "chart labels"
    ])
    
    return f"{negative}, {topic_negative}"


def load_image_config() -> dict:
    """Load image generation configuration."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f)
            return cfg.get("image", {})
    return {}


def output_dimensions(cfg: dict) -> tuple[int, int]:
    """Return final saved dimensions for generated art."""
    return (
        int(cfg.get("output_width") or cfg.get("width", 1920)),
        int(cfg.get("output_height") or cfg.get("height", 1080)),
    )


def postprocess_generated_image(image: Any, cfg: dict) -> Any:
    """Upscale and lightly sharpen generated art for the video timeline."""
    if not cfg.get("upscale_to_output", False):
        return image

    target_width, target_height = output_dimensions(cfg)
    if image.width == target_width and image.height == target_height:
        return image

    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps

        resample = getattr(Image, "Resampling", Image).LANCZOS
        processed = ImageOps.fit(
            image.convert("RGB"),
            (target_width, target_height),
            method=resample,
            centering=(0.5, 0.5),
        )

        contrast = float(cfg.get("upscale_contrast", 1.02))
        sharpness = float(cfg.get("upscale_sharpness", 1.12))
        if contrast != 1.0:
            processed = ImageEnhance.Contrast(processed).enhance(contrast)
        if sharpness != 1.0:
            processed = ImageEnhance.Sharpness(processed).enhance(sharpness)
        processed = processed.filter(ImageFilter.UnsharpMask(radius=1.1, percent=80, threshold=3))
        logger.info(f"Upscaled generated image: {image.width}x{image.height} -> {target_width}x{target_height}")
        return processed
    except Exception as e:
        logger.warning(f"Image upscale failed; using native generated size: {e}")
        return image


def get_device_status() -> Dict[str, Any]:
    """Return image-generation runtime status without loading a model."""
    global torch

    try:
        if torch is None:
            import torch as torch_module

            torch = torch_module
    except Exception as e:
        return {
            "diffusers": False,
            "cuda": False,
            "device": "unavailable",
            "reason": f"torch import failed: {e}",
        }

    cuda = torch.cuda.is_available()
    return {
        "diffusers": DIFFUSERS_AVAILABLE,
        "cuda": cuda,
        "device": torch.cuda.get_device_name(0) if cuda else "cpu",
        "reason": "" if cuda else "CUDA is not available to torch",
    }


# Lazy-loaded pipeline
_pipeline = None
_pipeline_key: Optional[Tuple[str, str, str, str, str, str, bool]] = None


def resolve_torch_dtype(value: str, device: str):
    """Resolve config precision names to torch dtypes."""
    normalized = str(value or "auto").lower()
    if device != "cuda":
        return torch.float32
    if normalized in {"fp32", "float32", "full"}:
        return torch.float32
    if normalized in {"fp16", "float16", "half"}:
        return torch.float16
    return torch.float16


def unload_pipeline():
    """Release the cached diffusion pipeline before retrying with safer precision."""
    global _pipeline, _pipeline_key

    _pipeline = None
    _pipeline_key = None
    try:
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def get_pipeline(require_cuda: bool = True, dtype_override: Optional[str] = None):
    """Get or create the image generation pipeline."""
    global _pipeline, _pipeline_key

    cfg = load_image_config()
    model_path = cfg.get("model_path", "./models/sdxl/")
    model_id = cfg.get("model_id", "runwayml/stable-diffusion-v1-5")
    engine = cfg.get("engine", "sd15")
    disable_safety_checker = bool(cfg.get("disable_safety_checker", False))
    dtype_name = dtype_override or cfg.get("dtype", "auto")
    vae_dtype_name = cfg.get("vae_dtype", "auto")
    low_vram_mode = str(cfg.get("low_vram_mode", "") or "").lower()
    cache_key = (
        engine,
        model_path,
        model_id,
        str(dtype_name),
        str(vae_dtype_name),
        low_vram_mode,
        disable_safety_checker,
    )

    if _pipeline is not None and _pipeline_key == cache_key:
        return _pipeline
    if _pipeline is not None:
        unload_pipeline()
    
    if not ensure_diffusers_available():
        return None

    if require_cuda and not torch.cuda.is_available():
        logger.warning("CUDA is not available; skipping local SDXL load")
        return None
    
    try:
        # Determine device
        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = resolve_torch_dtype(dtype_name, device)
        if str(vae_dtype_name or "auto").lower() == "auto":
            vae_dtype = dtype
        else:
            vae_dtype = resolve_torch_dtype(vae_dtype_name, device)
        
        local_model_ready = Path(model_path, "model_index.json").exists()
        source = model_path if local_model_ready else model_id
        logger.info(f"Loading image model ({engine}, dtype={dtype}, vae_dtype={vae_dtype}): {source}")

        pipeline_cls = StableDiffusionXLPipeline if engine == "sdxl" else StableDiffusionPipeline
        load_kwargs = {
            "torch_dtype": dtype,
            "use_safetensors": True,
        }
        if disable_safety_checker and pipeline_cls is StableDiffusionPipeline:
            load_kwargs.update({
                "safety_checker": None,
                "requires_safety_checker": False,
            })

        _pipeline = pipeline_cls.from_pretrained(source, **load_kwargs)

        if disable_safety_checker:
            disable_pipeline_safety_checker(_pipeline)

        if device == "cuda" and hasattr(_pipeline, "vae") and vae_dtype != dtype:
            _pipeline.vae.to(dtype=vae_dtype)
            logger.info(f"VAE precision set to {vae_dtype}")

        # Enable low-VRAM placement. Diffusers offload hooks should be installed
        # before moving the full pipeline to CUDA, otherwise peak VRAM stays high.
        if device == "cuda" and low_vram_mode == "sequential_cpu_offload":
            _pipeline.enable_sequential_cpu_offload()
            logger.info("Sequential CPU offload enabled")
        elif device == "cuda" and cfg.get("enable_cpu_offload", False):
            _pipeline.enable_model_cpu_offload()
            logger.info("Model CPU offload enabled")
        elif device == "cuda":
            _pipeline = _pipeline.to(device)
            try:
                _pipeline.enable_attention_slicing()
            except Exception:
                pass
        try:
            _pipeline.enable_vae_slicing()
        except Exception:
            pass
        
        try:
            _pipeline.set_progress_bar_config(disable=True)
        except Exception:
            pass

        _pipeline_key = cache_key
        logger.info(f"{engine.upper()} pipeline loaded on {device}")
        return _pipeline
        
    except Exception as e:
        logger.error(f"Failed to load pipeline: {e}")
        unload_pipeline()
        return None


def disable_pipeline_safety_checker(pipe: Any):
    """Disable diffusers black-frame safety filtering for local editorial renders."""
    disabled = False
    if hasattr(pipe, "safety_checker"):
        pipe.safety_checker = None
        disabled = True
    if hasattr(pipe, "requires_safety_checker"):
        pipe.requires_safety_checker = False
        disabled = True

    if disabled:
        logger.info("Diffusers safety checker disabled for local image generation")


def generate_images(script: Dict[str, Any], allow_placeholder: bool = False) -> List[str]:
    """Generate images for each script segment with engineered prompts.
    
    Attempts GPU-based generation first. Placeholder generation is opt-in so
    production runs do not silently ship weak visuals.
    
    Args:
        script: Script dictionary with segments
        
    Returns:
        List of image file paths
    """
    if not ensure_diffusers_available():
        if allow_placeholder:
            logger.warning("diffusers not available, using placeholder images")
            return generate_placeholder_images(script)
        raise RuntimeError("diffusers/torch are not available for AI image generation")
    
    # Check if GPU is available
    gpu_available = torch.cuda.is_available()
    if not gpu_available:
        if allow_placeholder:
            logger.warning("GPU not available, using placeholder images")
            return generate_placeholder_images(script)
        raise RuntimeError("CUDA is not available to torch; local AI images would be too slow")
    
    cfg = load_image_config()
    
    # Create output directory
    image_dir = Path("./temp/images")
    image_dir.mkdir(parents=True, exist_ok=True)
    
    segments = script.get("segments", [])
    topic = script.get("topic", "")
    
    if not segments:
        raise RuntimeError("No segments in script to generate images for.")
    
    # Get video dimensions
    width = cfg.get("width", 1920)
    height = cfg.get("height", 1080)
    
    logger.info(f"Generating {len(segments)} images with engineered prompts...")
    
    image_paths = []
    
    # Generate for each segment using SDXL
    for i, segment in enumerate(segments):
        logger.info(f"AI art {i + 1}/{len(segments)}: {segment.get('type', 'segment')}")
        prompt = compact_prompt(engineer_prompt(segment, topic, width, height))
        negative = get_negative_prompt(segment.get("type", "fact"), topic)
        seg_type = segment.get("type", "fact")
        
        image_path = image_dir / f"frame_{i:03d}_{seg_type}.png"
        
        # Generate with SDXL
        image = generate_ai_image(prompt, cfg, negative_prompt=negative)
        
        if image is None:
            raise RuntimeError(f"SDXL failed to generate image for segment {i}")
        
        image.save(str(image_path))
        image_paths.append(str(image_path))
        logger.info(f"AI art saved {i + 1}/{len(segments)}: {image_path}")
    
    logger.info(f"Images generated: {len(image_paths)}")
    return image_paths


def generate_ai_image(prompt: str, cfg: dict, negative_prompt: Optional[str] = None) -> Optional[Any]:
    """Generate an image using AI.
    
    Args:
        prompt: Image generation prompt
        cfg: Image configuration
        
    Returns:
        PIL Image or None
    """
    pipe = get_pipeline(require_cuda=True)
    
    if pipe is None:
        return None
    
    def generate_with_pipe(active_pipe: Any, active_prompt: str, active_steps: int, active_guidance: float):
        return active_pipe(
            active_prompt,
            negative_prompt=negative,
            num_inference_steps=active_steps,
            guidance_scale=active_guidance,
            width=width,
            height=height
        )

    def retry_with_fp32() -> Optional[Any]:
        if not retry_fp32 or str(cfg.get("dtype", "auto")).lower() in {"fp32", "float32", "full"}:
            return None
        logger.warning("Retrying image generation with fp32 precision")
        unload_pipeline()
        fp32_pipe = get_pipeline(require_cuda=True, dtype_override="fp32")
        if fp32_pipe is None:
            return None
        try:
            result = generate_with_pipe(
                fp32_pipe,
                retry_prompt,
                max(8, min(steps, 12)),
                min(guidance_scale, 6.0),
            )
            image = result.images[0]
            if black_frame_guard and is_probably_black_image(image):
                logger.warning("fp32 retry also produced a black frame")
                return None
            return postprocess_generated_image(image, cfg)
        except Exception as e:
            logger.error(f"fp32 retry failed: {e}")
            return None

    try:
        # Generation parameters
        width = cfg.get("width", 1920)
        height = cfg.get("height", 1080)
        steps = cfg.get("steps", 30)
        guidance_scale = cfg.get("guidance_scale", 7.5)
        negative = negative_prompt or cfg.get("negative_prompt", "watermark, text, logo, blurry, nsfw")
        
        safety_disabled = bool(cfg.get("disable_safety_checker", False))
        black_frame_guard = bool(cfg.get("black_frame_guard", False))
        attempts = max(1, int(cfg.get("nsfw_retry_attempts", 2)) + 1)
        retry_fp32 = bool(cfg.get("retry_fp32_on_black", True))
        base_prompt = compact_prompt(prompt)
        retry_prompt = compact_prompt(SAFETY_RETRY_PROMPT)

        rejected_for_black = False
        for attempt in range(attempts):
            active_prompt = base_prompt if attempt == 0 else retry_prompt
            result = generate_with_pipe(pipe, active_prompt, steps, guidance_scale)

            image = result.images[0]
            flagged = any(getattr(result, "nsfw_content_detected", []) or [])
            black_frame = black_frame_guard and is_probably_black_image(image)
            if flagged or black_frame:
                rejected_for_black = rejected_for_black or black_frame
                reason = "safety checker" if flagged else "black-frame guard"
                logger.warning(
                    f"AI image rejected by {reason}"
                    f" (attempt {attempt + 1}/{attempts})"
                )
                if safety_disabled and not black_frame_guard:
                    return postprocess_generated_image(image, cfg)
                continue

            return postprocess_generated_image(image, cfg)

        if rejected_for_black:
            fp32_image = retry_with_fp32()
            if fp32_image is not None:
                return fp32_image

        logger.warning("AI image generation produced only blocked frames; using fallback art")
        return None
        
    except Exception as e:
        logger.error(f"AI image generation failed: {e}")
        fp32_image = retry_with_fp32()
        if fp32_image is not None:
            return fp32_image
        return None


def is_probably_black_image(image: Any) -> bool:
    """Detect black frames returned by diffusers safety filtering."""
    try:
        from PIL import ImageStat

        stat = ImageStat.Stat(image.convert("RGB"))
        mean = sum(stat.mean) / len(stat.mean)
        extrema = image.convert("RGB").getextrema()
        max_value = max(channel[1] for channel in extrema)
        return mean < 2 and max_value < 8
    except Exception:
        return False


def create_placeholder_image(prompt: str, width: int = 1920, height: int = 1080) -> Any:
    """Create a placeholder image with text.
    
    Args:
        prompt: Text to show on image
        width: Image width
        height: Image height
        
    Returns:
        PIL Image
    """
    from PIL import Image, ImageDraw, ImageFont
    
    # Create gradient background
    if NUMPY_AVAILABLE:
        img = create_gradient_image(width, height)
    else:
        img = Image.new("RGB", (width, height), (20, 20, 40))
    
    draw = ImageDraw.Draw(img)
    
    # Add text
    text_color = (200, 200, 200)
    try:
        # Try to load a font
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
    except:
        font = ImageFont.load_default()
    
    # Draw text centered
    text = f"[Image: {prompt[:50]}...]"
    
    # Get text size
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
    except:
        text_width, text_height = 400, 50
    
    x = (width - text_width) // 2
    y = (height - text_height) // 2
    
    draw.text((x, y), text, fill=text_color, font=font)
    
    return img


def generate_placeholder_images(script: Dict[str, Any]) -> List[str]:
    """Create deterministic placeholder frames for test-only runs."""
    cfg = load_image_config()
    width, height = output_dimensions(cfg)
    image_dir = Path("./temp/images")
    image_dir.mkdir(parents=True, exist_ok=True)

    paths: List[str] = []
    for i, segment in enumerate(script.get("segments", [])):
        seg_type = segment.get("type", "segment")
        prompt = segment.get("image_prompt") or segment.get("text", "")
        output_path = image_dir / f"placeholder_{i:03d}_{seg_type}.png"
        create_placeholder_image(prompt, width, height).save(output_path)
        paths.append(str(output_path))

    return paths


def generate_storyboard_art(
    segment: Dict[str, Any],
    style_profile: Dict[str, Any],
    output_dir: Path = Path("./temp/images"),
    allow_ai: bool = True,
) -> str:
    """Generate one consistent art frame for a storyboard segment.

    Uses local SDXL when CUDA is ready. Otherwise, creates deterministic
    editorial fallback art so analogies/concepts still get unique visuals.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    segment_id = segment.get("id", "segment")
    visual_intent = segment.get("visual_intent", "concept_art")
    output_path = output_dir / f"{segment_id}_{visual_intent}.png"
    prompt = storyboard_prompt(segment, style_profile)

    if allow_ai and get_device_status().get("cuda"):
        logger.info(f"Generating AI art for {segment_id} ({visual_intent})")
        cfg = load_image_config()
        negative = style_profile.get("negative") or cfg.get("negative_prompt")
        image = generate_ai_image(prompt, cfg, negative_prompt=negative)
        if image is not None:
            image.save(output_path)
            diagnostics = analyze_image(output_path)
            logger.info(
                f"AI art diagnostics for {segment_id}: "
                f"brightness={diagnostics['mean_brightness']}, contrast={diagnostics['contrast']}"
            )
            if is_video_ready_image(output_path):
                logger.info(f"AI art ready for {segment_id}: {output_path}")
                return str(output_path)

            logger.warning(f"AI art rejected for {segment_id}: {diagnostics}")
            retry_image = generate_ai_image(SAFETY_RETRY_PROMPT, cfg, negative_prompt=negative)
            if retry_image is not None:
                retry_image.save(output_path)
                retry_diagnostics = analyze_image(output_path)
                if is_video_ready_image(output_path):
                    logger.info(f"AI art retry ready for {segment_id}: {output_path}")
                    return str(output_path)
                logger.warning(f"AI art retry rejected for {segment_id}: {retry_diagnostics}")

    logger.info(f"Creating fallback art for {segment_id} ({visual_intent})")
    create_symbolic_art(prompt, style_profile, output_path)
    return str(output_path)


def storyboard_prompt(segment: Dict[str, Any], style_profile: Dict[str, Any]) -> str:
    """Build a consistent prompt from segment intent and video style."""
    intent = segment.get("visual_intent", "concept_art")
    prompt = segment.get("visual_prompt") or segment.get("image_prompt") or segment.get("narration", "")
    positive_prompt = (
        f"{prompt}, visual intent: {intent}, {style_profile.get('palette')}, "
        f"{style_profile.get('camera')}, {style_profile.get('lighting')}, "
        f"{style_profile.get('composition')}"
    )
    return compact_prompt(positive_prompt)


def create_symbolic_art(prompt: str, style_profile: Dict[str, Any], output_path: Path):
    """Create deterministic non-text visual art for fallback/local runs."""
    from PIL import Image, ImageDraw, ImageFilter

    width, height = output_dimensions(load_image_config())
    seed_input = f"{style_profile.get('topic', '')}|{prompt}"
    seed = int(hashlib.sha256(seed_input.encode("utf-8")).hexdigest()[:12], 16)
    rng = random.Random(seed)

    bg_top = (24, 24, 32)
    bg_bottom = (44, 43, 56)
    img = Image.new("RGB", (width, height), bg_top)
    draw = ImageDraw.Draw(img, "RGBA")

    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(int(bg_top[i] * (1 - ratio) + bg_bottom[i] * ratio) for i in range(3))
        draw.line([(0, y), (width, y)], fill=color)

    accent = (239, 159, 39, 210)
    primary = (100, 92, 210, 220)
    cool = (64, 170, 220, 160)

    # Large editorial shapes, stable per segment.
    for i in range(8):
        cx = rng.randint(int(width * 0.12), int(width * 0.88))
        cy = rng.randint(int(height * 0.12), int(height * 0.88))
        radius = rng.randint(90, 260)
        color = [primary, accent, cool][i % 3]
        bbox = (cx - radius, cy - radius, cx + radius, cy + radius)
        draw.ellipse(bbox, fill=color)

    # Documentary-style frame lines and subtle grid.
    for x in range(0, width, 160):
        draw.line([(x, 0), (x, height)], fill=(255, 255, 255, 12), width=1)
    for y in range(0, height, 120):
        draw.line([(0, y), (width, y)], fill=(255, 255, 255, 10), width=1)

    draw.rectangle((60, 60, width - 60, height - 60), outline=(255, 255, 255, 28), width=2)
    draw.rectangle((78, 78, width - 78, height - 78), outline=(239, 159, 39, 42), width=1)

    img = img.filter(ImageFilter.GaussianBlur(radius=4))
    sharpened = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay = ImageDraw.Draw(sharpened, "RGBA")
    overlay.rectangle((60, 60, width - 60, height - 60), outline=(255, 255, 255, 40), width=2)
    img = Image.alpha_composite(img.convert("RGBA"), sharpened).convert("RGB")
    img.save(output_path)


def create_gradient_image(width: int, height: int) -> Any:
    """Create a gradient background image.
    
    Args:
        width: Image width
        height: Image height
        
    Returns:
        PIL Image
    """
    from PIL import Image
    import numpy as np
    
    # Create gradient
    gradient = np.linspace(0, 1, height)
    gradient = np.tile(gradient, (width, 1))
    gradient = np.transpose(gradient)
    
    # Map to RGB
    r = (gradient * 30).astype(np.uint8)
    g = (gradient * 30).astype(np.uint8)
    b = (gradient * 60).astype(np.uint8)
    
    # Stack channels
    img_array = np.stack([r, g, b], axis=2)
    
    img = Image.fromarray(img_array, mode="RGB")
    
    return img


def generate_test_image(
    prompt: str = "a cinematic cat",
    output_path: str = "test_image.png",
    allow_placeholder: bool = False,
) -> str:
    """Generate a test image.
    
    Args:
        prompt: Test prompt
        output_path: Output path
    """
    cfg = load_image_config()
    
    image = None
    
    if get_pipeline(require_cuda=False) is not None:
        image = generate_ai_image(prompt, cfg)
    
    if image is None and allow_placeholder:
        image = create_placeholder_image(prompt)
    
    if image is None:
        raise RuntimeError("Image test failed; no AI image was produced.")

    image.save(output_path)
    logger.info(f"Test image saved to: {output_path}")
    return output_path


def check_gpu_available() -> bool:
    """Check if GPU is available for image generation.
    
    Returns:
        True if GPU available
    """
    return bool(get_device_status().get("cuda"))


def get_image_dimensions(preset: str = "1080p") -> tuple:
    """Get image dimensions for preset.
    
    Args:
        preset: Resolution preset
        
    Returns:
        Tuple of (width, height)
    """
    presets = {
        "480p": (854, 480),
        "720p": (1280, 720),
        "1080p": (1920, 1080),
        "1440p": (2560, 1440),
        "4k": (3840, 2160)
    }
    
    return presets.get(preset, (1920, 1080))
