# TrendForge

🎬 **TrendForge is an AI-assisted faceless video generator.**

Give it a subject, and it can research sources, plan a storyboard, write narration, generate voiceover, create or capture visuals, and assemble a YouTube-ready video.

This project is still evolving. Feedback, experiments, bug reports, and pull requests are welcome.

## ✨ What It Does

- 🔎 **Researches a topic** from web/news-style sources.
- 🧠 **Separates facts from opinions** using an OpenAI-compatible local model endpoint.
- ✍️ **Writes structured narration** for long-form faceless videos.
- 🗣️ **Generates voiceover** with Kokoro.
- 🖼️ **Creates visuals** using source cards, screenshots, and local Stable Diffusion art.
- 👁️ **Checks screenshot quality** with a local Ollama vision model.
- 🎞️ **Assembles the final video** with motion, transitions, captions, intro/outro clips, and music support.

## 🧩 Current Local Model Setup

- 🧠 Research/script/narration model: `minimax-m2.5:cloud`
- 👁️ Screenshot vision QA model: `qwen3.5:4b`
- 🎨 Local image generation: Stable Diffusion 1.5 style model, currently tuned for a 4GB GTX 1650 Ti

The vision model is only used to judge screenshots. It does not replace the narration or script model.

## 🚀 Quick Start

### Windows

```powershell
cd TrendForge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

For fully local runs, the stock-media keys can stay as placeholders. Add real keys only if you want Pixabay/Pexels fallback media.

Then run:

```powershell
.\run.bat
```

The UI opens at:

```text
http://127.0.0.1:8510
```

### CLI Mode

```powershell
.\run.bat --skip-ui --subject "artificial intelligence"
```

Or directly:

```powershell
.\.venv\Scripts\python.exe main.py --subject "artificial intelligence"
```

## ⚙️ Requirements

- 🐍 Python 3.11+
- 🎞️ FFmpeg
- 🧠 Ollama or another OpenAI-compatible local endpoint
- 🌐 Chrome for screenshot capture
- 🖥️ NVIDIA CUDA GPU recommended for local image generation

The current config is designed to run on modest hardware. Local AI art generates at `896x504` and saves video-ready `1920x1080` frames.

## 🧪 Useful Test Commands

### Test Local Image Generation

```powershell
.\.venv\Scripts\python.exe main.py --image-test "cinematic technology documentary scene" -v
```

### Test Screenshot Vision QA

```powershell
.\.venv\Scripts\python.exe -m modules.screenshot_vision path\to\screenshot.png --model qwen3.5:4b
```

## 🗂️ Project Structure

```text
TrendForge/
  main.py                  CLI pipeline entry point
  server.py                FastAPI web server
  ui.py                    Streamlit UI
  config.yaml              Main app configuration
  requirements.txt         Python dependencies
  frontend/                Browser UI assets
  modules/                 Core pipeline modules
  Assets/                  Branding, intro/outro, docs, optional media
  plans/                   Development notes and roadmap
```

Generated folders such as `temp/`, `output/`, and `logs/` are intentionally ignored by Git.

## 🔐 Secrets And Local Files

Do not commit `.env`.

Use `.env.example` as the template:

```text
PIXABAY_API_KEY=your_key_here
PEXELS_API_KEY=your_key_here
```

Local models, virtual environments, logs, generated videos, and temp files are ignored in `.gitignore`.

## 🎨 Image Generation Notes

The default local image settings are conservative because this project is being tested on a GTX 1650 Ti with 4GB VRAM:

```yaml
image:
  width: 896
  height: 504
  upscale_to_output: true
  output_width: 1920
  output_height: 1080
```

Native `1920x1080` generation is not recommended on 4GB VRAM. It can pin the GPU and take a very long time per frame.

## 👁️ Screenshot Quality QA

TrendForge captures source screenshots with Selenium, then applies:

- 🧹 overlay cleanup
- 📄 DOM/source/headline checks
- 🖼️ blank-frame checks
- 👁️ optional Qwen vision scoring

If a screenshot fails quality checks, TrendForge can retry or fall back to a clean branded source card.

## 🤝 Contributions

Updates are welcome.

Good areas to improve:

- ⚡ Faster local image generation with LCM/SD 1.5 modes
- 👁️ Better screenshot quality scoring
- 🎞️ More polished transitions and motion presets
- 🧪 Automated test coverage
- 📦 Cleaner install and packaging flow
- 🧰 More provider backends for image/TTS/LLM generation

Please avoid committing generated videos, local model files, `.env`, or virtual environments.

## 📄 License

MIT
