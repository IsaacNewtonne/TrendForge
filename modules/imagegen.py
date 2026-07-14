"""TrendForge - AI Image Generation Module

Generates images for video segments using Stable Diffusion XL or FLUX.
With proper prompt engineering: style anchors, negative prompts per segment type,
and aspect-ratio-aware composition.
"""

import os
import yaml
import json
import hashlib
import random
import sys
import types
import urllib.request
import inspect
import threading
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from loguru import logger
import re

from modules.image_diagnostics import analyze_image, is_video_ready_image
from modules.manual_images import ai_image_style_prompt, default_negative_prompt

# Configuration
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
AI_RUNTIME_STATUS_PATH = Path("./temp/ai_runtime_status.json")

# Style anchors - locked visuals that make content consistent
STYLE_ANCHORS = {
    "hook": {
        "prompt": "cinematic documentary establishing shot, dramatic depth of field, bold center composition, rich shadow detail, slightly desaturated editorial palette, moody atmospheric lighting, film grain, wide shot, premium documentary style",
        "negative": "watermark, logo, readable text, fake text, pseudo text, gibberish text, glyphs, letters, numbers, captions, headline, body text, labels, legends, charts, arrows, callouts, UI panels, flat interface screen, plaque, sign, wordmark, inscription, typography, printed words, garbled typography, misspelled labels, dark neon cyberpunk, black background, blurry, distorted UI, extra fingers, low quality, photorealistic, washed out, low contrast, empty close-up, cluttered layout, meme styling"
    },
    "fact": {
        "prompt": "clean editorial evidence visual, precise isometric miniature diorama, soft retro-futurist diagram aesthetic, minimalist flat pastel colors on warm off-white background, thin charcoal outlines, subtle muted shading, light print texture, balanced whitespace, tidy outlines, soft airbrushed focal glow, polished magazine illustration",
        "negative": "watermark, logo, readable text, fake text, pseudo text, gibberish text, glyphs, letters, numbers, captions, headline, body text, labels, legends, charts, arrows, callouts, UI panels, flat interface screen, plaque, sign, wordmark, inscription, typography, printed words, garbled typography, misspelled labels, dark neon cyberpunk, black background, blurry, distorted UI, extra fingers, low quality, photorealistic, washed out, low contrast, empty close-up, cluttered layout"
    },
    "analogy_art": {
        "prompt": "striking visual metaphor illustration, bold compositional contrast, symbolic object juxtaposition, slightly surreal miniature diorama aesthetic, dusty blue and pale gold accents, clean focal point with dramatic negative space, soft retro-futurist mood, editorial illustration style, vivid yet restrained palette",
        "negative": "watermark, logo, readable text, fake text, pseudo text, gibberish text, glyphs, letters, numbers, captions, headline, body text, labels, legends, charts, arrows, callouts, UI panels, flat interface screen, plaque, sign, wordmark, inscription, typography, printed words, garbled typography, misspelled labels, dark neon cyberpunk, black background, blurry, distorted UI, extra fingers, low quality, photorealistic, washed out, low contrast, cluttered layout"
    },
    "concept_art": {
        "prompt": "thoughtful conceptual illustration, soft retro-futurist isometric scene, warm off-white background, layered technical objects with natural elements, pastel dusty blue sage green pale gold, thin charcoal outlines, subtle print texture, soft focal glow, balanced whitespace, elegant editorial poster aesthetic",
        "negative": "watermark, logo, readable text, fake text, pseudo text, gibberish text, glyphs, letters, numbers, captions, headline, body text, labels, legends, charts, arrows, callouts, UI panels, flat interface screen, plaque, sign, wordmark, inscription, typography, printed words, garbled typography, misspelled labels, dark neon cyberpunk, black background, blurry, distorted UI, extra fingers, low quality, photorealistic, washed out, low contrast, empty close-up, cluttered layout"
    },
    "brand_or_concept": {
        "prompt": "branded cinematic documentary visual, premium quality editorial composition, dramatic lighting with subtle color grading, slightly above eye-level view, confident center composition, soft depth, warm sophisticated palette, clean modern aesthetic with print texture feel, polished documentary poster style",
        "negative": "watermark, logo, readable text, fake text, pseudo text, gibberish text, glyphs, letters, numbers, captions, headline, body text, labels, legends, charts, arrows, callouts, UI panels, flat interface screen, plaque, sign, wordmark, inscription, typography, printed words, garbled typography, misspelled labels, dark neon cyberpunk, black background, blurry, distorted UI, extra fingers, low quality, photorealistic, washed out, low contrast, empty close-up, cluttered layout"
    },
    "chart_visual": {
        "prompt": "clean editorial infographic illustration, stylized data visualization in miniature diorama form, soft isometric chart aesthetic, pastel color palette on off-white background, subtle shadow and texture, balanced composition with clear focal hierarchy, polished magazine diagram style",
        "negative": "watermark, logo, readable text, fake text, pseudo text, gibberish text, glyphs, letters, numbers, captions, headline, body text, labels, legends, UI panels, flat interface screen, plaque, sign, wordmark, inscription, typography, printed words, garbled typography, misspelled labels, dark neon cyberpunk, black background, blurry, distorted UI, extra fingers, low quality, photorealistic, washed out, low contrast, cluttered layout"
    },
    "product_visual": {
        "prompt": "product showcase illustration, clean isometric device/object presentation, soft studio lighting on miniature diorama, warm off-white background, pastel tech palette with pale gold accents, subtle print texture and soft glow, balanced whitespace, polished editorial product shot style",
        "negative": "watermark, logo, readable text, fake text, pseudo text, gibberish text, glyphs, letters, numbers, captions, headline, body text, labels, legends, UI panels, flat interface screen, plaque, sign, wordmark, inscription, typography, printed words, garbled typography, misspelled labels, dark neon cyberpunk, black background, blurry, distorted UI, extra fingers, low quality, washed out, low contrast, cluttered layout"
    },
    "social_post_visual": {
        "prompt": "stylized social media post illustration, miniature diorama of a phone or feed interface, soft pastel social palette, warm off-white background, subtle shadow and print texture, editorial reinterpretation rather than literal screenshot, balanced composition, clean miniature aesthetic",
        "negative": "watermark, logo, readable text, fake text, pseudo text, gibberish text, glyphs, letters, numbers, captions, headline, body text, labels, legends, UI panels, flat interface screen, plaque, sign, wordmark, inscription, typography, printed words, garbled typography, misspelled labels, dark neon cyberpunk, black background, blurry, distorted UI, extra fingers, low quality, photorealistic, washed out, low contrast, cluttered layout"
    },
    "article_visual": {
        "prompt": "editorial article illustration, stylized publication cover in miniature diorama form, soft newsprint aesthetic on warm off-white background, dusty blue and pale gold palette, subtle print texture and soft glow, confident center composition, polished magazine illustration style",
        "negative": "watermark, logo, readable text, fake text, pseudo text, gibberish text, glyphs, letters, numbers, captions, headline, body text, labels, legends, UI panels, flat interface screen, plaque, sign, wordmark, inscription, typography, printed words, garbled typography, misspelled labels, dark neon cyberpunk, black background, blurry, distorted UI, extra fingers, low quality, photorealistic, washed out, low contrast, cluttered layout"
    },
    "comparison_visual": {
        "prompt": "split comparison illustration, two-panel miniature diorama with clear visual contrast, warm off-white background, soft pastel palette distinguishing each side, subtle shadow and depth, balanced composition, clean editorial comparison aesthetic",
        "negative": "watermark, logo, readable text, fake text, pseudo text, gibberish text, glyphs, letters, numbers, captions, headline, body text, labels, legends, UI panels, flat interface screen, plaque, sign, wordmark, inscription, typography, printed words, garbled typography, misspelled labels, dark neon cyberpunk, black background, blurry, distorted UI, extra fingers, low quality, photorealistic, washed out, low contrast, cluttered layout"
    },
    "clip_visual": {
        "prompt": "video clip illustration, stylized film frame in miniature diorama form, warm cinematic palette, soft retro-futurist aesthetic on off-white background, subtle film grain and soft glow, balanced composition, editorial video interpretation style",
        "negative": "watermark, logo, readable text, fake text, pseudo text, gibberish text, glyphs, letters, numbers, captions, headline, body text, labels, legends, UI panels, flat interface screen, plaque, sign, wordmark, inscription, typography, printed words, garbled typography, misspelled labels, dark neon cyberpunk, black background, blurry, distorted UI, extra fingers, low quality, washed out, low contrast, cluttered layout"
    },
}

# Colour grades by emotion
COLOUR_GRADES = {
    "danger": "soft pale gold accent, calm editorial tension",
    "money": "sage green and pale gold accents, tidy symbolic economy objects",
    "ai": "dusty blue and sage green technology objects, quiet futuristic editorial style",
    "curiosity": "soft muted contrast, symbolic mystery object, balanced whitespace",
    "shock": "subtle pale gold focal glow, restrained editorial contrast",
    "default": "flat pastel editorial color, soft print texture, balanced whitespace"
}

torch = None
StableDiffusionXLPipeline = None
StableDiffusionPipeline = None
LCMScheduler = None
DPMSolverMultistepScheduler = None
DIFFUSERS_AVAILABLE: Optional[bool] = None
DIFFUSERS_ERROR: Optional[str] = None
_REALESRGAN_UPSAMPLER = None
_REALESRGAN_KEY: Optional[tuple[str, int]] = None
_REALESRGAN_WARNING_SHOWN = False
_AI_RUNTIME_DISABLED_REASON: Optional[str] = None
_AI_RUNTIME_DISABLED_LOGGED = False
_AI_RUNTIME_STATUS_LOADED = False
PROMPT_TOKEN_BUDGET = 77
SAFETY_RETRY_PROMPT = (
    "clean editorial infographic illustration, soft retro-futurist isometric diagram look, "
    "flat pastel colors, warm off-white background, thin charcoal outlines, balanced whitespace, "
    "quiet magazine illustration, no text"
)


def ensure_diffusers_available() -> bool:
    """Lazy-load torch and diffusers only when image generation needs them."""
    global torch, StableDiffusionXLPipeline, StableDiffusionPipeline, LCMScheduler, DPMSolverMultistepScheduler, DIFFUSERS_AVAILABLE, DIFFUSERS_ERROR

    if DIFFUSERS_AVAILABLE is not None:
        return DIFFUSERS_AVAILABLE

    try:
        import torch as torch_module
        from diffusers import (
            DPMSolverMultistepScheduler as dpm_solver_multistep_scheduler,
            LCMScheduler as lcm_scheduler,
            StableDiffusionPipeline as sd_pipeline,
            StableDiffusionXLPipeline as sdxl_pipeline,
        )

        torch = torch_module
        StableDiffusionPipeline = sd_pipeline
        StableDiffusionXLPipeline = sdxl_pipeline
        LCMScheduler = lcm_scheduler
        DPMSolverMultistepScheduler = dpm_solver_multistep_scheduler
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


def clamp_prompt_for_pipeline(prompt: str, pipe: Any) -> str:
    """Clamp positive/negative prompts to the active CLIP tokenizer limit."""
    tokenizer = getattr(pipe, "tokenizer", None)
    if tokenizer is None:
        return compact_prompt(prompt)

    max_length = int(min(getattr(tokenizer, "model_max_length", 77), 77))

    def token_count(text: str) -> int:
        return len(
            tokenizer(
                text,
                truncation=False,
                return_attention_mask=False,
                verbose=False,
            ).input_ids
        )

    normalized = re.sub(r"\s+", " ", str(prompt or "")).strip(" ,")
    if not normalized or token_count(normalized) <= max_length:
        return normalized

    clauses = [clause.strip() for clause in normalized.split(",") if clause.strip()]
    kept: List[str] = []
    for clause in clauses:
        candidate = ", ".join([*kept, clause])
        if token_count(candidate) <= max_length:
            kept.append(clause)

    if kept:
        return ", ".join(kept)

    encoded = tokenizer(normalized, truncation=True, max_length=max_length)
    return tokenizer.decode(encoded.input_ids, skip_special_tokens=True).strip()


def engineer_prompt(segment: Dict[str, Any], topic: str, width: int, height: int) -> str:
    """Engineer a proper image prompt with style anchors.
    
    Args:
        segment: Script segment with type, text, visual_intent
        topic: Video topic
        width: Image width
        height: Image height
        
    Returns:
        Engineered prompt string
    """
    raw_text = segment.get("image_prompt", f"Image about {topic}")
    
    raw_text = re.sub(r",?\s*cinematic,?\s*4K", "", raw_text, flags=re.IGNORECASE)
    raw_text = re.sub(r",?\s*high quality", "", raw_text, flags=re.IGNORECASE)
    
    visual_intent = segment.get("visual_intent", segment.get("type", "fact"))
    style = STYLE_ANCHORS.get(visual_intent, STYLE_ANCHORS.get(segment.get("type", "fact"), STYLE_ANCHORS["fact"]))
    style_prompt = style["prompt"]
    
    emotion = detect_emotion_from_topic(topic)
    colour_grade = COLOUR_GRADES.get(emotion, COLOUR_GRADES["default"])
    
    aspect = "16:9" if width >= height else "9:16"
    if aspect == "16:9":
        composition = "wide shot, center composition"
    else:
        composition = "portrait, center composition"
    
    prompt = f"{raw_text}, {style_prompt}, {colour_grade}, {composition}, {aspect} aspect ratio"
    
    return prompt


def get_negative_prompt(segment_type: str, topic: str, visual_intent: str = "") -> str:
    """Get negative prompt for segment type and visual intent."""
    intent = visual_intent or segment_type
    style = STYLE_ANCHORS.get(intent, STYLE_ANCHORS.get(segment_type, STYLE_ANCHORS["fact"]))
    return style.get("negative") or default_negative_prompt()


def sanitize_visual_prompt_for_image(prompt: str) -> str:
    """Avoid prompt terms that commonly make SD render fake text."""
    cleaned = str(prompt or "")
    replacements = {
        r"\bpolicy papers?\b": "blank policy folders",
        r"\bpapers?\b": "blank sheets",
        r"\bdocuments?\b": "blank document-shaped panels",
        r"\breports?\b": "blank report-shaped cards",
        r"\bheadlines?\b": "source context",
        r"\barticle\b": "source context",
        r"\barticles\b": "source contexts",
        r"\bnewspaper\b": "blank folded paper object",
        r"\bchart\b": "abstract geometric panel",
        r"\bcharts\b": "abstract geometric panels",
        r"\bdiagram\b": "symbolic object layout",
        r"\bdiagrams\b": "symbolic object layouts",
        r"\bposter\b": "editorial frame",
        r"\bposters\b": "editorial frames",
    }
    for pattern, replacement in replacements.items():
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


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

        processed = upscale_with_realesrgan(image, cfg, target_width, target_height)
        if processed is None:
            resample = getattr(Image, "Resampling", Image).LANCZOS
            processed = ImageOps.fit(
                image.convert("RGB"),
                (target_width, target_height),
                method=resample,
                centering=(0.5, 0.5),
            )
            logger.info(
                f"Upscaled generated image with Lanczos: "
                f"{image.width}x{image.height} -> {target_width}x{target_height}"
            )

        contrast = float(cfg.get("upscale_contrast", 1.02))
        sharpness = float(cfg.get("upscale_sharpness", 1.12))
        if contrast != 1.0:
            processed = ImageEnhance.Contrast(processed).enhance(contrast)
        if sharpness != 1.0:
            processed = ImageEnhance.Sharpness(processed).enhance(sharpness)
        processed = processed.filter(ImageFilter.UnsharpMask(radius=1.1, percent=80, threshold=3))
        return processed
    except Exception as e:
        logger.warning(f"Image upscale failed; using native generated size: {e}")
        return image


def upscale_with_realesrgan(image: Any, cfg: dict, target_width: int, target_height: int) -> Optional[Any]:
    """Use optional Real-ESRGAN upscaling when dependency and model are local."""
    method = str(cfg.get("upscale_method", "lanczos") or "lanczos").lower()
    if method not in {"realesrgan", "real-esrgan"}:
        return None

    model_path = Path(str(cfg.get("realesrgan_model_path", "") or ""))
    if not model_path.exists():
        if not ensure_realesrgan_model(cfg):
            log_realesrgan_fallback_once(f"model not found at {model_path}")
            return None

    try:
        import numpy as np
        from PIL import Image, ImageOps
        install_torchvision_functional_tensor_shim()
        from basicsr.archs.rrdbnet_arch import RRDBNet
        from realesrgan import RealESRGANer

        global _REALESRGAN_UPSAMPLER, _REALESRGAN_KEY
        tile = int(cfg.get("realesrgan_tile", 256))
        key = (str(model_path.resolve()), tile)
        if _REALESRGAN_UPSAMPLER is None or _REALESRGAN_KEY != key:
            model = RRDBNet(
                num_in_ch=3,
                num_out_ch=3,
                num_feat=64,
                num_block=23,
                num_grow_ch=32,
                scale=4,
            )
            _REALESRGAN_UPSAMPLER = RealESRGANer(
                scale=4,
                model_path=str(model_path),
                model=model,
                tile=tile,
                tile_pad=10,
                pre_pad=0,
                half=False,
            )
            _REALESRGAN_KEY = key

        output, _ = _REALESRGAN_UPSAMPLER.enhance(np.array(image.convert("RGB")), outscale=4)
        resample = getattr(Image, "Resampling", Image).LANCZOS
        processed = ImageOps.fit(
            Image.fromarray(output),
            (target_width, target_height),
            method=resample,
            centering=(0.5, 0.5),
        )
        logger.info(
            f"Upscaled generated image with Real-ESRGAN: "
            f"{image.width}x{image.height} -> {target_width}x{target_height}"
        )
        return processed
    except Exception as e:
        log_realesrgan_fallback_once(str(e))
        return None


def install_torchvision_functional_tensor_shim() -> None:
    """Provide the old TorchVision import path expected by BasicSR 1.4.2."""
    module_name = "torchvision.transforms.functional_tensor"
    if module_name in sys.modules:
        return

    try:
        from torchvision.transforms.functional import rgb_to_grayscale
    except Exception:
        return

    shim = types.ModuleType(module_name)
    shim.rgb_to_grayscale = rgb_to_grayscale
    sys.modules[module_name] = shim


def ensure_realesrgan_model(cfg: Optional[dict] = None) -> bool:
    """Download the configured Real-ESRGAN model if it is missing."""
    cfg = cfg or load_image_config()
    method = str(cfg.get("upscale_method", "lanczos") or "lanczos").lower()
    if method not in {"realesrgan", "real-esrgan"}:
        return False

    model_path = Path(str(cfg.get("realesrgan_model_path", "") or ""))
    if not model_path:
        return False
    if model_path.exists() and model_path.stat().st_size > 0:
        return True

    model_url = str(cfg.get("realesrgan_model_url", "") or "")
    if not model_url:
        return False

    model_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = model_path.with_suffix(model_path.suffix + ".tmp")
    try:
        logger.info(f"Downloading Real-ESRGAN model: {model_url}")
        urllib.request.urlretrieve(model_url, temp_path)
        if temp_path.stat().st_size < 1_000_000:
            temp_path.unlink(missing_ok=True)
            logger.warning("Real-ESRGAN model download looked incomplete; using fallback upscale")
            return False
        temp_path.replace(model_path)
        logger.info(f"Real-ESRGAN model ready: {model_path}")
        return True
    except Exception as e:
        temp_path.unlink(missing_ok=True)
        logger.warning(f"Real-ESRGAN model download failed; using fallback upscale: {e}")
        return False


def log_realesrgan_fallback_once(reason: str) -> None:
    global _REALESRGAN_WARNING_SHOWN
    if _REALESRGAN_WARNING_SHOWN:
        return
    _REALESRGAN_WARNING_SHOWN = True
    logger.warning(f"Real-ESRGAN unavailable; using Lanczos upscale ({reason})")


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


def is_gtx_16_series_device(device_name: str) -> bool:
    """Return whether a CUDA device is an NVIDIA GTX 16-series card."""
    normalized = re.sub(r"\s+", " ", str(device_name or "")).upper()
    return bool(re.search(r"\bGTX\s*16\d{2}\b", normalized))


def should_force_fp32_vae(device: str, dtype_name: str) -> bool:
    """Use fp32 VAE decode on cards known to produce fp16 black frames."""
    if device != "cuda" or str(dtype_name or "auto").lower() in {"fp32", "float32", "full"}:
        return False
    try:
        return is_gtx_16_series_device(torch.cuda.get_device_name(0))
    except Exception:
        return False


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


def configure_lcm_acceleration(pipe: Any, cfg: dict, engine: str) -> bool:
    """Enable LCM acceleration when the configured LoRA can be loaded."""
    acceleration = str(cfg.get("acceleration", "none") or "none").lower()
    if acceleration not in {"lcm_lora", "lcm"}:
        setattr(pipe, "_trendforge_lcm_enabled", False)
        return False

    if LCMScheduler is None:
        logger.warning("LCM requested but diffusers LCMScheduler is unavailable")
        setattr(pipe, "_trendforge_lcm_enabled", False)
        return False

    lora_id = cfg.get("lcm_lora_id")
    if not lora_id:
        lora_id = "latent-consistency/lcm-lora-sdxl" if engine == "sdxl" else "latent-consistency/lcm-lora-sdv1-5"

    try:
        pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
        lora_source, weight_name = resolve_lcm_lora_source(cfg, lora_id)
        if weight_name:
            pipe.load_lora_weights(lora_source, weight_name=weight_name)
        else:
            pipe.load_lora_weights(lora_source)
        lora_scale = float(cfg.get("lcm_lora_scale", 1.0))
        if cfg.get("lcm_fuse_lora", False) and hasattr(pipe, "fuse_lora"):
            pipe.fuse_lora(lora_scale=lora_scale)
            logger.info("LCM LoRA fused into pipeline")
        setattr(pipe, "_trendforge_lcm_enabled", True)
        setattr(pipe, "_trendforge_lcm_lora_scale", lora_scale)
        logger.info(f"LCM acceleration enabled: {lora_source}")
        return True
    except Exception as e:
        logger.warning(f"LCM acceleration unavailable ({e}); using standard scheduler")
        setattr(pipe, "_trendforge_lcm_enabled", False)
        return False


def configure_scheduler(pipe: Any, cfg: dict) -> None:
    """Apply an optional scheduler suited to the selected checkpoint."""
    scheduler = str(cfg.get("scheduler", "") or "").strip().lower()
    if not scheduler:
        return
    if scheduler in {"dpm_solver_multistep", "dpm++", "dpmpp"}:
        if DPMSolverMultistepScheduler is None:
            logger.warning("DPM-Solver scheduler requested but unavailable")
            return
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
        logger.info("DPM-Solver multistep scheduler enabled")
        return
    logger.warning(f"Unknown image scheduler '{scheduler}'; using the model default")

def resolve_lcm_lora_source(cfg: dict, lora_id: str) -> tuple[str, Optional[str]]:
    """Resolve a local LCM LoRA path before falling back to Hub loading."""
    configured_path = str(cfg.get("lcm_lora_path") or "").strip()
    if configured_path:
        path = Path(configured_path)
        if path.is_file():
            return str(path.parent), path.name
        return configured_path, None

    path = Path(lora_id)
    if path.exists():
        if path.is_file():
            return str(path.parent), path.name
        return str(path), None

    return lora_id, None


def image_generation_settings(cfg: dict, pipe: Any) -> tuple[int, float]:
    """Return step/guidance settings for standard or LCM generation."""
    if getattr(pipe, "_trendforge_lcm_enabled", False):
        return (
            int(cfg.get("lcm_steps", cfg.get("steps", 4))),
            float(cfg.get("lcm_guidance_scale", 1.0)),
        )
    return int(cfg.get("steps", 30)), float(cfg.get("guidance_scale", 7.5))


def resolve_vae_torch_dtype(vae_dtype_name: str, dtype_name: str, device: str, dtype: Any):
    """Resolve VAE precision for the active pipeline."""
    if str(vae_dtype_name or "auto").lower() == "auto":
        return dtype
    return resolve_torch_dtype(vae_dtype_name, device)


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
        str(cfg.get("acceleration", "none")),
        str(cfg.get("scheduler", "")),
        str(cfg.get("variant", "")),
        str(cfg.get("lcm_lora_id", "")),
        str(cfg.get("lcm_lora_scale", "")),
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
        vae_dtype = resolve_vae_torch_dtype(vae_dtype_name, dtype_name, device, dtype)
        if (
            device == "cuda"
            and str(dtype_name or "auto").lower() == "auto"
            and is_gtx_16_series_device(torch.cuda.get_device_name(0))
        ):
            # GTX 16-series cards can be unstable in mixed/half precision for SD pipelines.
            # Use full precision on GPU for correctness (equivalent to no-half behavior).
            dtype = torch.float32
            if str(vae_dtype_name or "auto").lower() == "auto":
                vae_dtype = torch.float32
            logger.info("GTX 16-series detected; using full precision on GPU for stable generation")
        
        local_model_ready = Path(model_path, "model_index.json").exists()
        source = model_path if local_model_ready else model_id
        logger.info(f"Loading image model ({engine}, dtype={dtype}, vae_dtype={vae_dtype}): {source}")

        pipeline_cls = StableDiffusionXLPipeline if engine == "sdxl" else StableDiffusionPipeline
        load_kwargs = {
            "torch_dtype": dtype,
            "use_safetensors": True,
        }
        variant = str(cfg.get("variant", "") or "").strip()
        if variant:
            load_kwargs["variant"] = variant
        if disable_safety_checker and pipeline_cls is StableDiffusionPipeline:
            load_kwargs.update({
                "safety_checker": None,
                "requires_safety_checker": False,
            })

        _pipeline = pipeline_cls.from_pretrained(source, **load_kwargs)

        if disable_safety_checker:
            disable_pipeline_safety_checker(_pipeline)

        configure_scheduler(_pipeline, cfg)
        configure_lcm_acceleration(_pipeline, cfg, engine)

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
        if device == "cuda" and cfg.get("enable_attention_slicing", False):
            try:
                _pipeline.enable_attention_slicing()
            except Exception:
                pass
        try:
            _pipeline.enable_vae_slicing()
        except Exception:
            pass
        if cfg.get("enable_vae_tiling", False):
            try:
                _pipeline.enable_vae_tiling()
                logger.info("VAE tiling enabled")
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
        try:
            heartbeat_seconds = float(cfg.get("inference_heartbeat_seconds", 12))
        except (TypeError, ValueError):
            heartbeat_seconds = 12.0
        if heartbeat_seconds <= 0:
            heartbeat_seconds = 12.0

        try:
            max_seconds = float(cfg.get("max_inference_seconds", 180))
        except (TypeError, ValueError):
            max_seconds = 180.0
        if max_seconds < 0:
            max_seconds = 0.0
        timed_out = False
        start_ts = time.monotonic()
        state = {"step": 0}
        done = threading.Event()

        def heartbeat_loop():
            while not done.wait(max(3.0, heartbeat_seconds)):
                elapsed = time.monotonic() - start_ts
                logger.info(
                    f"AI inference running: elapsed={elapsed:.1f}s, "
                    f"step={state['step']}/{active_steps}"
                )

        heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
        heartbeat_thread.start()

        def maybe_interrupt(pipe_obj: Any):
            nonlocal timed_out
            if max_seconds > 0 and (time.monotonic() - start_ts) > max_seconds:
                timed_out = True
                logger.warning(
                    f"AI inference timeout reached ({max_seconds:.0f}s); "
                    "interrupting this generation attempt."
                )
                try:
                    setattr(pipe_obj, "_interrupt", True)
                except Exception:
                    pass

        def step_end_callback(pipe_obj: Any, step_index: int, _timestep: int, callback_kwargs: Dict[str, Any]):
            state["step"] = int(step_index) + 1
            maybe_interrupt(pipe_obj)
            return callback_kwargs

        def legacy_callback(step_index: int, _timestep: int, _latents: Any):
            state["step"] = int(step_index) + 1
            maybe_interrupt(active_pipe)

        kwargs = {
            "negative_prompt": negative,
            "num_inference_steps": active_steps,
            "guidance_scale": active_guidance,
            "width": width,
            "height": height,
        }
        lora_scale = getattr(active_pipe, "_trendforge_lcm_lora_scale", None)
        if getattr(active_pipe, "_trendforge_lcm_enabled", False) and lora_scale is not None:
            kwargs["cross_attention_kwargs"] = {"scale": float(lora_scale)}

        try:
            call_params = inspect.signature(active_pipe.__call__).parameters
        except Exception:
            call_params = {}

        if hasattr(active_pipe, "_interrupt"):
            try:
                setattr(active_pipe, "_interrupt", False)
            except Exception:
                pass

        if "callback_on_step_end" in call_params:
            kwargs["callback_on_step_end"] = step_end_callback
        elif "callback" in call_params:
            kwargs["callback"] = legacy_callback
            kwargs["callback_steps"] = 1

        logger.info(
            f"AI inference started: steps={active_steps}, guidance={active_guidance}, "
            f"size={width}x{height}"
        )
        try:
            result = active_pipe(active_prompt, **kwargs)
            elapsed = time.monotonic() - start_ts
            logger.info(
                f"AI inference finished: elapsed={elapsed:.1f}s, "
                f"completed_steps={state['step']}/{active_steps}"
            )
            update_ai_runtime_health(cfg, elapsed, timed_out)
            return result
        finally:
            done.set()
            heartbeat_thread.join(timeout=0.2)

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
                steps,
                guidance_scale,
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
        steps, guidance_scale = image_generation_settings(cfg, pipe)
        negative = negative_prompt or cfg.get("negative_prompt", "watermark, text, logo, blurry, nsfw")
        
        safety_disabled = bool(cfg.get("disable_safety_checker", False))
        black_frame_guard = bool(cfg.get("black_frame_guard", False))
        attempts = max(1, int(cfg.get("nsfw_retry_attempts", 2)) + 1)
        retry_fp32 = bool(cfg.get("retry_fp32_on_black", True))
        base_prompt = clamp_prompt_for_pipeline(compact_prompt(prompt), pipe)
        retry_prompt = clamp_prompt_for_pipeline(SAFETY_RETRY_PROMPT, pipe)
        negative = clamp_prompt_for_pipeline(negative, pipe)

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
    cfg = load_image_config()
    require_ai_art = bool(cfg.get("require_ai_art", False))

    if allow_ai and not require_ai_art and ai_runtime_disabled():
        logger.info(f"Skipping AI art for {segment_id}; using fallback art")
    elif allow_ai and not cfg.get("ai_art_enabled", True):
        if require_ai_art:
            raise RuntimeError(f"AI art is required but disabled in config for {segment_id}")
        logger.info(f"Local AI art disabled; creating fallback art for {segment_id} ({visual_intent})")
    elif allow_ai and get_device_status().get("cuda"):
        logger.info(f"Generating AI art for {segment_id} ({visual_intent})")
        negative = default_negative_prompt()
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
            if require_ai_art:
                raise RuntimeError(f"AI art generation failed quality checks for {segment_id}")
    elif require_ai_art:
        raise RuntimeError(f"AI art is required but CUDA pipeline is unavailable for {segment_id}")

    if require_ai_art:
        raise RuntimeError(f"AI art is required but generation failed for {segment_id}")
    logger.info(f"Creating fallback art for {segment_id} ({visual_intent})")
    create_symbolic_art(prompt, style_profile, output_path)
    return str(output_path)


def ai_runtime_disabled() -> bool:
    global _AI_RUNTIME_DISABLED_LOGGED
    ensure_ai_runtime_status_loaded()
    if _AI_RUNTIME_DISABLED_REASON and not _AI_RUNTIME_DISABLED_LOGGED:
        logger.warning(f"AI art runtime disabled for this run: {_AI_RUNTIME_DISABLED_REASON}")
        _AI_RUNTIME_DISABLED_LOGGED = True
    return bool(_AI_RUNTIME_DISABLED_REASON)


def update_ai_runtime_health(cfg: dict, elapsed_seconds: float, timed_out: bool) -> None:
    """Disable AI art for the rest of this run when inference is too slow."""
    global _AI_RUNTIME_DISABLED_REASON
    if _AI_RUNTIME_DISABLED_REASON:
        return
    if not bool(cfg.get("auto_disable_ai_on_slow_inference", True)):
        return

    try:
        slow_threshold = float(cfg.get("slow_inference_seconds", 160))
    except (TypeError, ValueError):
        slow_threshold = 160.0

    if timed_out or elapsed_seconds >= slow_threshold:
        reason = (
            f"inference too slow ({elapsed_seconds:.1f}s)"
            + (" after timeout signal" if timed_out else "")
        )
        _AI_RUNTIME_DISABLED_REASON = reason
        save_ai_runtime_status({"disabled": True, "reason": reason})


def ensure_ai_runtime_status_loaded() -> None:
    global _AI_RUNTIME_STATUS_LOADED, _AI_RUNTIME_DISABLED_REASON
    if _AI_RUNTIME_STATUS_LOADED:
        return
    _AI_RUNTIME_STATUS_LOADED = True
    if os.getenv("TREND_FORGE_FORCE_AI_ART", "").strip().lower() in {"1", "true", "yes", "on"}:
        return
    if os.getenv("TREND_FORGE_RESET_AI_RUNTIME", "").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            AI_RUNTIME_STATUS_PATH.unlink(missing_ok=True)
        except Exception:
            pass
        return
    try:
        if not AI_RUNTIME_STATUS_PATH.exists():
            return
        data = json.loads(AI_RUNTIME_STATUS_PATH.read_text(encoding="utf-8")) or {}
        if bool(data.get("disabled")):
            _AI_RUNTIME_DISABLED_REASON = str(data.get("reason") or "previous run marked AI runtime as too slow")
    except Exception:
        return


def save_ai_runtime_status(data: Dict[str, Any]) -> None:
    try:
        AI_RUNTIME_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        AI_RUNTIME_STATUS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        return


def storyboard_prompt(segment: Dict[str, Any], style_profile: Dict[str, Any]) -> str:
    """Build a consistent prompt from segment intent and video style."""
    intent = segment.get("visual_intent", "concept_art")
    prompt = sanitize_visual_prompt_for_image(
        segment.get("visual_prompt") or segment.get("image_prompt") or segment.get("narration", "")
    )
    positive_prompt = (
        f"NO TEXT, no glyphs, no labels, blank surfaces, {prompt}, "
        f"{ai_image_style_prompt()}, {intent}, finished 16:9 frame"
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
