"""TrendForge - Text-to-Speech Module

Uses Kokoro TTS - natural open-source TTS with multiple voices.
"""

import os
import tempfile
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
from loguru import logger
import shutil

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

# Kokoro TTS
try:
    from kokoro_onnx import Kokoro
    from kokoro_onnx.config import EspeakConfig
    KOKORO_AVAILABLE = True
except ImportError:
    KOKORO_AVAILABLE = False
    raise RuntimeError(
        "Kokoro TTS is required. Install with:\n"
        "  pip install kokoro-tts\n"
    )

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    raise RuntimeError("numpy required. pip install numpy")

try:
    import soundfile as sf
    SOUNDFILE_AVAILABLE = True
except ImportError:
    SOUNDFILE_AVAILABLE = False
    raise RuntimeError("soundfile required. pip install soundfile")


# Default voice
DEFAULT_VOICE = "af_snow"
KOKORO_VOICES = {
    "af_bella": "Bella (American female)",
    "af_sarah": "Sarah (American female)",
    "af_sky": "Sky (American female)",
    "af_nicole": "Nicole (American female)",
    "af_snow": "Snow (American female)",
    "am_adam": "Adam (American male)",
    "am_michael": "Michael (American male)",
    "bf_emma": "Emma (British female)",
    "bf_isabella": "Isabella (British female)",
    "bm_george": "George (British male)",
    "bm_lewis": "Lewis (British male)",
}

# Chatterbox is a more natural, MIT-licensed local TTS (beats ElevenLabs in blind
# tests) with voice cloning and emotion control. It is optional: install
# chatterbox-tts in a compatible environment and set tts.engine: chatterbox.
CHATTERBOX_AVAILABLE = False
try:
    import torch  # noqa: F401
    from chatterbox.tts import ChatterboxTTS  # type: ignore

    CHATTERBOX_AVAILABLE = True
except Exception:
    ChatterboxTTS = None  # type: ignore

# A short reference clip lets Chatterbox clone a consistent, natural persona.
CHATTERBOX_REFERENCE_AUDIO = None  # optional path to a .wav reference clip


def load_tts_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f).get("tts", {})
    return {}


def load_intro_outro_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return (yaml.safe_load(f) or {}).get("intro_outro", {})
    return {}


def list_kokoro_voices() -> Dict[str, str]:
    """Return known Kokoro voice IDs and labels."""
    cfg_voice = load_tts_config().get("voice")
    voices = dict(KOKORO_VOICES)
    if cfg_voice and cfg_voice not in voices:
        voices[cfg_voice] = f"{cfg_voice} (configured)"
    return voices


def download_models():
    """Download Kokoro model files if needed."""
    model_dir = Path(__file__).resolve().parent.parent / "models"
    model_dir.mkdir(exist_ok=True)
    
    model_path = model_dir / "kokoro-v1.0.onnx"
    voices_path = model_dir / "voices-v1.0.bin"
    
    if model_path.exists() and voices_path.exists():
        return str(model_path), str(voices_path)
    
    logger.info("Downloading Kokoro models...")
    
    # Download model
    model_url = "https://github.com/nazdridoy/kokoro-tts/releases/download/v1.0.0/kokoro-v1.0.onnx"
    voices_url = "https://github.com/nazdridoy/kokoro-tts/releases/download/v1.0.0/voices-v1.0.bin"
    
    import urllib.request
    urllib.request.urlretrieve(model_url, model_path)
    urllib.request.urlretrieve(voices_url, voices_path)
    
    return str(model_path), str(voices_path)


# Lazy-loaded model
_kokoro = None
_ESPEAK_PATCHED = False


def configure_espeak_runtime() -> EspeakConfig:
    """Use the bundled espeak runtime without relying on fragile temp DLL copies."""
    global _ESPEAK_PATCHED
    import espeakng_loader

    runtime_temp = Path("./temp/runtime").resolve()
    runtime_temp.mkdir(parents=True, exist_ok=True)
    for key in ("TEMP", "TMP", "TMPDIR"):
        os.environ[key] = str(runtime_temp)
    tempfile.tempdir = str(runtime_temp)

    lib_path = Path(espeakng_loader.get_library_path()).resolve()
    data_path = Path(espeakng_loader.get_data_path()).resolve()
    os.environ["PHONEMIZER_ESPEAK_LIBRARY"] = str(lib_path)
    os.environ["PHONEMIZER_ESPEAK_DATA_PATH"] = str(data_path)

    try:
        espeakng_loader.make_library_available()
    except Exception as exc:
        logger.debug(f"espeak DLL directory setup skipped: {exc}")

    if not _ESPEAK_PATCHED:
        try:
            import phonemizer.backend.espeak.api as espeak_api

            original_copy = espeak_api.shutil.copy

            def copy_espeak_library(src, dst, follow_symlinks=True):
                src_path = Path(src)
                dst_path = Path(dst)
                if src_path.name.lower() == "espeak-ng.dll":
                    dst_path.parent.mkdir(parents=True, exist_ok=True)
                    dst_path.write_bytes(src_path.read_bytes())
                    return str(dst_path)
                return original_copy(src, dst, follow_symlinks=follow_symlinks)

            espeak_api.shutil.copy = copy_espeak_library
            original_init = espeak_api.EspeakAPI.__init__

            def direct_espeak_init(self, library, data_path):
                self._library = None
                if data_path is not None:
                    data_path = str(data_path).encode("utf-8")

                try:
                    library_path = Path(library).resolve()
                    self._library = espeak_api.ctypes.cdll.LoadLibrary(str(library_path))
                except OSError as error:
                    raise RuntimeError(f"failed to load espeak library: {error}") from None

                try:
                    if self._library.espeak_Initialize(0x02, 0, data_path, 0) <= 0:
                        raise RuntimeError("failed to initialize espeak shared library")
                except AttributeError:
                    raise RuntimeError("failed to load espeak library") from None

                self._library_path = library_path
                self._tempdir = None

            def direct_delete_win32(self):
                try:
                    if self._library is not None:
                        self._library.espeak_Terminate()
                except AttributeError:
                    pass

            espeak_api.EspeakAPI.__init__ = direct_espeak_init
            espeak_api.EspeakAPI._delete_win32 = direct_delete_win32
            espeak_api.EspeakAPI._trendforge_original_init = original_init
            _ESPEAK_PATCHED = True
        except Exception as exc:
            logger.debug(f"espeak copy patch skipped: {exc}")

    return EspeakConfig(lib_path=str(lib_path), data_path=str(data_path))


def get_kokoro():
    """Get or create Kokoro TTS instance."""
    global _kokoro
    if _kokoro is not None:
        return _kokoro
    
    model_path, voices_path = download_models()
    _kokoro = Kokoro(model_path, voices_path, espeak_config=configure_espeak_runtime())
    logger.info("Kokoro TTS loaded")
    return _kokoro


def render_voiceover(
    script: Dict[str, Any],
    voice_override: Optional[str] = None,
    speed_override: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Render voiceover audio with duration-matched timing.

    Dispatches to the configured engine (kokoro or chatterbox). Chatterbox is a
    more natural, fully local, MIT-licensed alternative with voice cloning.
    
    Args:
        script: Script dictionary with segments
        
    Returns:
        List of audio dicts with 'path', 'segment', 'duration'
    """
    cfg = load_tts_config()
    engine = str(cfg.get("engine", "kokoro")).lower()
    if engine == "chatterbox":
        return render_voiceover_chatterbox(
            script,
            voice_override=voice_override,
            speed_override=speed_override,
            exaggeration=float(cfg.get("chatterbox_exaggeration", 0.5)),
            reference_audio=cfg.get("chatterbox_reference_audio"),
        )

    if not KOKORO_AVAILABLE:
        raise RuntimeError("Kokoro required. pip install kokoro-tts")
    
    cfg = load_tts_config()
    intro_outro_cfg = load_intro_outro_config()
    audio_dir = Path("./temp/audio")
    audio_dir.mkdir(parents=True, exist_ok=True)
    
    segments = script.get("segments", [])
    if not segments:
        raise RuntimeError("No segments to render")
    
    logger.info(f"Rendering {len(segments)} voice segments...")
    
    kokoro = get_kokoro()
    voice = voice_override or cfg.get("voice", DEFAULT_VOICE)
    speed = float(speed_override if speed_override is not None else cfg.get("speed", 1.05))
    audio_files = []
    
    for i, segment in enumerate(segments):
        text = segment.get("text", "")
        seg_type = segment.get("type", "fact")
        
        if not text or len(text.strip()) < 5:
            continue
        
        audio_path = audio_dir / f"segment_{i:03d}.wav"
        
        try:
            # Generate audio
            samples, sample_rate = kokoro.create(text, voice=voice, speed=speed, lang="en-us")
            
            delivery = segment.get("delivery", {}) if isinstance(segment.get("delivery"), dict) else {}
            pause_after = float(delivery.get("pause_after", 0.0) or 0.0)
            if pause_after > 0 and NUMPY_AVAILABLE:
                silence = np.zeros(int(sample_rate * min(1.5, max(0.0, pause_after))), dtype=samples.dtype)
                samples = np.concatenate([samples, silence])

            samples = pad_intro_outro_audio(
                samples,
                sample_rate,
                segment,
                i,
                len(segments),
                intro_outro_cfg,
            )
            
            # Get duration after delivery pause is included.
            duration = len(samples) / sample_rate
            
            # Save as WAV
            sf.write(str(audio_path), samples, sample_rate)
            
            audio_files.append({
                "path": str(audio_path),
                "segment": segment,
                "script_index": i,
                "duration": duration,
                "segment_type": seg_type,
                "voice": voice,
                "delivery": delivery,
            })
            
            logger.debug(f"segment {i}: {duration:.2f}s")
            
        except Exception as e:
            logger.warning(f"Segment {i} failed: {e}")
            continue
    
    logger.info(f"Voiceover done: {len(audio_files)} segments")
    if not audio_files:
        raise RuntimeError("Voiceover failed: Kokoro did not render any audio segments.")
    return audio_files


def pad_intro_outro_audio(
    samples: Any,
    sample_rate: int,
    segment: Dict[str, Any],
    index: int,
    segment_count: int,
    intro_outro_cfg: Dict[str, Any],
) -> Any:
    """Pad intro/outro narration so branded clips can play for their intended length."""
    role = segment.get("timing_role")
    if not role:
        if index == 0:
            role = "intro"
        elif index == segment_count - 1:
            role = "outro"

    if role not in {"intro", "outro"}:
        return samples

    target = intro_outro_cfg.get(f"{role}_target_seconds", intro_outro_cfg.get("clip_target_seconds", 0))
    try:
        target_seconds = float(target or 0)
    except (TypeError, ValueError):
        return samples
    if target_seconds <= 0:
        return samples

    current_seconds = len(samples) / max(1, sample_rate)
    if current_seconds >= target_seconds:
        if current_seconds > target_seconds + 0.35:
            logger.warning(
                f"{role.title()} narration is {current_seconds:.1f}s, longer than target "
                f"{target_seconds:.1f}s. Shorten intro_outro.{role}_text to fit the clip."
            )
        return samples

    missing = target_seconds - current_seconds
    silence = np.zeros(int(sample_rate * missing), dtype=samples.dtype)
    logger.debug(f"Padded {role} narration from {current_seconds:.2f}s to {target_seconds:.2f}s")
    return np.concatenate([samples, silence])


def render_voice_sample(
    text: str = "Welcome to Trend Forge. This is a quick sample of the selected voice.",
    voice: Optional[str] = None,
    speed: Optional[float] = None,
) -> str:
    """Render a short Kokoro voice sample for UI playback."""
    cfg = load_tts_config()
    voice = voice or cfg.get("voice", DEFAULT_VOICE)
    speed = float(speed if speed is not None else cfg.get("speed", 1.05))
    sample_dir = Path("./temp/audio/samples")
    sample_dir.mkdir(parents=True, exist_ok=True)
    safe_voice = "".join(ch for ch in voice if ch.isalnum() or ch in {"_", "-"})
    output = sample_dir / f"{safe_voice}_{str(speed).replace('.', '_')}.wav"

    kokoro = get_kokoro()
    samples, sample_rate = kokoro.create(text, voice=voice, speed=speed, lang="en-us")
    sf.write(str(output), samples, sample_rate)
    logger.info(f"Voice sample saved: {output}")
    return str(output)


# ---------------------------------------------------------------------------
# Chatterbox engine (optional, more natural than Kokoro)
# ---------------------------------------------------------------------------

_CHATTERBOX_MODEL = None


def get_chatterbox():
    """Get or create the Chatterbox TTS instance (GPU if available)."""
    global _CHATTERBOX_MODEL
    if _CHATTERBOX_MODEL is not None:
        return _CHATTERBOX_MODEL
    if not CHATTERBOX_AVAILABLE:
        raise RuntimeError(
            "Chatterbox TTS is not installed. pip install chatterbox-tts "
            "(in a compatible environment) and set tts.engine: chatterbox."
        )
    device = "cuda" if getattr(__import__("torch", fromlist=["cuda"]), "cuda", None) and __import__("torch").cuda.is_available() else "cpu"
    _CHATTERBOX_MODEL = ChatterboxTTS.from_pretrained(device=device)
    logger.info(f"Chatterbox TTS loaded on {device}")
    return _CHATTERBOX_MODEL


def render_voice_sample_chatterbox(
    text: str = "Welcome to Trend Forge. This is a quick sample of the selected voice.",
    speed: Optional[float] = None,
    exaggeration: float = 0.5,
    reference_audio: Optional[str] = None,
) -> str:
    """Render a short Chatterbox voice sample for UI playback."""
    cfg = load_tts_config()
    speed = float(speed if speed is not None else cfg.get("speed", 1.05))
    sample_dir = Path("./temp/audio/samples")
    sample_dir.mkdir(parents=True, exist_ok=True)
    output = sample_dir / "chatterbox_sample.wav"

    model = get_chatterbox()
    # Chatterbox uses ~50 tokens/sec; approximate speed via cfg alone.
    params = {"exaggeration": exaggeration, "temperature": 0.7}
    ref = reference_audio or CHATTERBOX_REFERENCE_AUDIO
    if ref:
        params["audio_prompt_path"] = ref
    wav = model.generate(text, **params)
    sf.write(str(output), wav.squeeze(0).numpy(), model.sr)
    logger.info(f"Chatterbox voice sample saved: {output}")
    return str(output)


def render_voiceover_chatterbox(
    script: Dict[str, Any],
    voice_override: Optional[str] = None,
    speed_override: Optional[float] = None,
    exaggeration: float = 0.5,
    reference_audio: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Render voiceover audio with Chatterbox TTS (natural, local, optional cloning)."""
    if not CHATTERBOX_AVAILABLE:
        raise RuntimeError("Chatterbox TTS is not installed. Set tts.engine: kokoro or install chatterbox-tts.")

    cfg = load_tts_config()
    intro_outro_cfg = load_intro_outro_config()
    audio_dir = Path("./temp/audio")
    audio_dir.mkdir(parents=True, exist_ok=True)

    segments = script.get("segments", [])
    if not segments:
        raise RuntimeError("No segments to render")

    model = get_chatterbox()
    speed = float(speed_override if speed_override is not None else cfg.get("speed", 1.05))
    ref = reference_audio or CHATTERBOX_REFERENCE_AUDIO or voice_override
    audio_files = []

    for i, segment in enumerate(segments):
        text = segment.get("text", "")
        seg_type = segment.get("type", "fact")
        if not text or len(text.strip()) < 5:
            continue

        audio_path = audio_dir / f"segment_{i:03d}.wav"
        try:
            params = {"exaggeration": exaggeration, "temperature": 0.7}
            if ref:
                params["audio_prompt_path"] = ref
            wav = model.generate(text, **params)
            samples = wav.squeeze(0).numpy()
            sample_rate = int(model.sr)

            delivery = segment.get("delivery", {}) if isinstance(segment.get("delivery"), dict) else {}
            pause_after = float(delivery.get("pause_after", 0.0) or 0.0)
            if pause_after > 0 and NUMPY_AVAILABLE:
                silence = np.zeros(int(sample_rate * min(1.5, max(0.0, pause_after))), dtype=samples.dtype)
                samples = np.concatenate([samples, silence])

            samples = pad_intro_outro_audio(
                samples, sample_rate, segment, i, len(segments), intro_outro_cfg
            )
            duration = len(samples) / sample_rate
            sf.write(str(audio_path), samples, sample_rate)
            audio_files.append({
                "path": str(audio_path),
                "segment": segment,
                "script_index": i,
                "duration": duration,
                "segment_type": seg_type,
                "voice": "chatterbox",
                "delivery": delivery,
            })
            logger.debug(f"segment {i}: {duration:.2f}s")
        except Exception as e:
            logger.warning(f"Chatterbox segment {i} failed: {e}")
            continue

    logger.info(f"Chatterbox voiceover done: {len(audio_files)} segments")
    if not audio_files:
        raise RuntimeError("Voiceover failed: Chatterbox did not render any audio segments.")
    return audio_files


def get_segment_duration(audio_path: str) -> float:
    """Get duration of audio file."""
    try:
        info = sf.info(audio_path)
        return info.duration
    except:
        return 3.0


def estimate_clip_duration(audio_duration: float, speed: float = 1.0) -> float:
    """Estimate clip display duration based on audio."""
    adjusted = audio_duration / speed
    return adjusted + 0.5


def generate_test_audio(text: str = "Hello, this is TrendForge.", output: str = "test.wav"):
    """Generate a test audio sample."""
    kokoro = get_kokoro()
    cfg = load_tts_config()
    speed = cfg.get("speed", 1.05)
    voice = cfg.get("voice", DEFAULT_VOICE)
    samples, sr = kokoro.create(text, voice=voice, speed=speed)
    sf.write(output, samples, sr)
    logger.info(f"Test saved to {output}")
