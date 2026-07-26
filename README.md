# TrendForge

🎬 **TrendForge is an AI-assisted faceless video generator.**

Give it a subject and it can research sources, plan a storyboard, write narration, generate voiceover, create or capture visuals, and assemble a YouTube-ready video.

This project is evolving. Feedback, experiments, bug reports, and pull requests are welcome.

## What it does

- 🔎 Researches a topic from web and news-style sources.
- 🧠 Separates facts from opinions with an OpenAI-compatible model endpoint.
- ✍️ Writes structured narration for long-form faceless videos.
- 🗣️ Generates voiceover with Kokoro.
- 🖼️ Creates visuals from source cards, screenshots, and local SDXL art.
- 👁️ Checks screenshot quality with a local Ollama vision model.
- 🎞️ Assembles motion, transitions, captions, intro/outro clips, and audio into a final video.

## Default model and hardware profile

The default configuration is tuned for an NVIDIA GPU with **8 GB VRAM** and a computer with **16 GB system RAM**:

| Task | Default model | Notes |
| --- | --- | --- |
| Research, script, narration | `minimax-m2.5:cloud` | OpenAI-compatible Ollama cloud model |
| Screenshot vision QA | `qwen3.5:9b` | 6.6 GB Q4 multimodal model; unloaded after each check |
| Image generation | `Lykon/dreamshaper-xl-lightning` | SDXL Lightning, FP16, 4 steps |

SDXL renders AI-art frames at `1152x896`, then TrendForge upscales them 2x to `2304x1792`. Model-level CPU offload and VAE tiling reduce peak memory use.

The vision model and image model are not kept in VRAM together. `vision_keep_alive: 0` tells Ollama to release Qwen after each screenshot check so SDXL has the GPU available.

## Requirements

- Windows 10 or 11
- Python 3.11 or 3.12
- NVIDIA GPU with CUDA support and 8 GB VRAM recommended
- 16 GB system RAM
- Current NVIDIA driver
- FFmpeg available on `PATH`
- Ollama
- Chrome for screenshot capture

## Quick start

Clone and enter the repository:

```powershell
git clone https://github.com/IsaacNewtonne/TrendForge.git
cd TrendForge
```

Create the environment and install Python dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Confirm that PyTorch can see the GPU:

```powershell
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU only')"
```

If that reports `False`, install the CUDA build of PyTorch using the command generated at [pytorch.org/get-started/locally](https://pytorch.org/get-started/locally/), then run the check again.

Install the local screenshot vision model:

```powershell
ollama pull qwen3.5:9b
```

The research/script default uses `minimax-m2.5:cloud`. Sign in to Ollama if required by your Ollama installation. To use another OpenAI-compatible model, edit `opencode.model` and `opencode.base_url` in `config.yaml`.

Start TrendForge:

```powershell
.\run.bat
```

On every launch, the bootstrap checks the main Python requirements, Ollama,
FFmpeg, Chrome, and the required Ollama models. Missing components are installed
automatically. The first launch can therefore take considerably longer while
packages or models download.

The UI opens at <http://127.0.0.1:8510>.

### Interrupted-run recovery

TrendForge checkpoints each completed pipeline stage under `temp/checkpoints/`. Running the same
topic again with the same effective configuration restores completed research, analysis, script,
voiceover, and visual stages. Audio and image assets are copied into the run-specific checkpoint so
another topic cannot overwrite them. An interrupted stage is rerun automatically.

To deliberately rebuild every stage from scratch, use CLI mode with `--no-resume`.

The first AI-art run downloads the FP16 DreamShaper XL Lightning model from Hugging Face into the local model cache. Model files are ignored by Git.

## CLI mode

```powershell
.\run.bat --skip-ui --subject "artificial intelligence"
```

Or run the Python entry point directly:

```powershell
.\.venv\Scripts\python.exe main.py --subject "artificial intelligence"
```

## Useful checks

Test local SDXL image generation:

```powershell
.\.venv\Scripts\python.exe main.py --image-test "cinematic technology documentary scene" -v
```

Test screenshot vision QA:

```powershell
.\.venv\Scripts\python.exe -m modules.screenshot_vision path\to\screenshot.png --model qwen3.5:9b
```

Run the test suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## Image settings

The main 8 GB profile lives in `config.yaml`:

```yaml
image:
  engine: sdxl
  model_id: Lykon/dreamshaper-xl-1-0
  variant: fp16
  scheduler: deis_multistep
  acceleration: none
  dtype: fp16
  vae_id: madebyollin/sdxl-vae-fp16-fix
  vae_dtype: fp16
  steps: 25
  guidance_scale: 6.0
  width: 1152
  height: 896
  require_native_resolution: false
  upscale_to_output: true
  upscale_scale: 2
  upscale_method: realesrgan
  detail_pass:
    enabled: true
    steps: 12
    strength: 0.22
    guidance_scale: 5.0
  enable_cpu_offload: true
  enable_attention_slicing: false
  enable_vae_tiling: true
```

The final-quality profile uses full DreamShaper XL with its recommended DEIS scheduler, an FP16-safe SDXL VAE, a restrained img2img detail pass, and Real-ESRGAN upscaling. Model CPU offload and VAE tiling keep the workflow within the RTX 4060 Laptop GPU's 8 GB VRAM budget. Torch 2 already uses memory-efficient scaled-dot-product attention, so additional attention slicing is disabled by default.

If image generation runs out of VRAM, close other GPU-heavy programs first. For a last-resort lower-memory mode, set `image.low_vram_mode: sequential_cpu_offload`; it is considerably slower than the default model offload.

## Project structure

```text
TrendForge/
  main.py                  CLI pipeline entry point
  server.py                FastAPI web server
  ui.py                    Streamlit UI
  config.yaml              Main app and hardware profile
  requirements.txt         Python dependencies
  frontend/                Browser UI assets
  modules/                 Pipeline modules
  tests/                   Unit tests
  Assets/                  Branding, intro/outro, and docs
```

Generated `temp/`, `output/`, and `logs/` folders are ignored by Git. Local model files under `models/` are also ignored.

## Secrets

Do not commit `.env`. Copy `.env.example` and add real Pixabay or Pexels keys only if you want those fallback media providers. Fully local runs can keep the placeholders.

## License

MIT
