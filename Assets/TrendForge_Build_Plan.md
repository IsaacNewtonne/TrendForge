# TrendForge

## AI Faceless YouTube Video Generator

**Complete Build Plan - v0.1 Beta**

|                    |                                        |
|--------------------|----------------------------------------|
| **Status**         | Pre-alpha / Planning                   |
| **Platform**       | Linux / macOS / Windows (WSL2)         |
| **Python**         | 3.11+                                  |
| **Licence**        | MIT / All dependencies open-source     |
| **Copyright risk** | **Zero - all generated or CC0 assets** |

## 1. Project Overview

TrendForge is a fully automated, faceless YouTube video production pipeline. Given a subject (or no subject at all), it researches the web, generates a structured script that separates verified facts from opinions, produces a natural-sounding voiceover, assembles high-quality visuals, and exports a broadcast-ready MP4 — all inside a Python virtual environment with zero manual steps.

Key goals
- Fully automated: one command, one finished video
- No copyright exposure: all images AI-generated (Stable Diffusion / FLUX) or CC0 stock
- Natural voice: Kokoro TTS for human-quality narration, no robotic synthesis
- Honest framing: every video ends with a structured fact vs. opinion conclusion
- User control: set a subject or let the AI pick the day’s top trending topic
- Clean environment: runs entirely inside a Python venv, outputs to /videos/

## 2. Pipeline Architecture

The pipeline has eight sequential layers. Each layer is an independent Python module so you can test, swap, or upgrade any component without touching the rest.

| **\#** | **Layer**        | **Module**              | **Tools**                       |
|--------|------------------|-------------------------|---------------------------------|
| **①**  | **Input**        | main.py / config.yaml   | Click CLI, argparse             |
| **②**  | **Research**     | modules/scraper.py      | Scrapling, pytrends, Reddit API |
| **③**  | **Fact/Opinion** | modules/researcher.py   | OpenCode local LLM              |
| **④**  | **Script**       | modules/scriptwriter.py | OpenCode prompt chain           |
| **⑤**  | **Voice**        | modules/tts.py          | Kokoro TTS / Piper TTS          |
| **⑥**  | **Visuals**      | modules/imagegen.py     | SDXL / FLUX.1-schnell           |
| **⑦**  | **Edit**         | modules/editor.py       | MoviePy, FFmpeg                 |
| **⑧**  | **Output**       | modules/renderer.py     | FFmpeg H.264, Whisper captions  |

## 3. File Structure

```text
trendforge/
├── venv/                        # Python virtual environment (git-ignored)
├── main.py                      # CLI entry point
├── config.yaml                  # All user settings
├── requirements.txt             # Pinned Python dependencies
├── .env                         # API keys (Pixabay, Pexels) - git-ignored
├── modules/
│   ├── __init__.py
│   ├── scraper.py               # Web scraping + trend detection
│   ├── researcher.py            # OpenCode API + fact/opinion split
│   ├── scriptwriter.py          # Script structure generator
│   ├── tts.py                   # Kokoro / Piper TTS engine
│   ├── imagegen.py              # Stable Diffusion / FLUX images
│   ├── stockfetch.py            # Pixabay / Pexels fallback
│   ├── editor.py                # MoviePy timeline assembler
│   ├── renderer.py              # FFmpeg final export + metadata
│   └── thumbgen.py              # Auto-thumbnail generator
├── assets/
│   ├── intro.mp4                # Branded intro (3-8 sec)
│   ├── outro.mp4                # Subscribe card outro
│   ├── fonts/
│   │   ├── Inter-Bold.ttf
│   │   └── Inter-Regular.ttf
│   └── music/                   # Pre-downloaded CC0 tracks
├── models/                      # Downloaded model weights (git-ignored)
│   ├── kokoro/                  # Kokoro TTS weights
│   ├── sdxl/                    # Stable Diffusion SDXL weights
│   └── whisper/                 # Whisper model weights
├── temp/                        # Intermediate files (auto-cleared)
├── output/                      # Finished MP4 files land here
└── logs/                        # Run logs per video
```

## 4. requirements.txt

Paste this file exactly into trendforge/requirements.txt — all packages are MIT or Apache 2.0 licensed.

```txt
# ── Core ──────────────────────────────────────────────────
python-dotenv==1.0.0
pyyaml==6.0.1
click==8.1.7
loguru==0.7.2
tqdm==4.66.1

# ── Scraping & Research ───────────────────────────────────
scrapling==0.2.9              # Stealth web scraping
pytrends==4.9.2              # Google Trends API
requests==2.31.0
feedparser==6.0.11           # Google News RSS
wikipedia-api==0.6.0
beautifulsoup4==4.12.3
lxml==5.1.0

# ── NLP / AI Orchestration ────────────────────────────────
openai==1.30.0               # OpenCode uses OpenAI-compatible API
transformers==4.40.0
torch==2.3.0                 # CPU default; GPU: torch==2.3.0+cu121
sentencepiece==0.2.0

# ── Text-to-Speech (Kokoro) ───────────────────────────────
kokoro==0.9.2                # pip install kokoro
soundfile==0.12.1
pydub==0.25.1
numpy==1.26.4

# ── Image Generation (Stable Diffusion) ───────────────────
diffusers==0.27.2
accelerate==0.30.0
safetensors==0.4.3
Pillow==10.3.0
invisible-watermark==0.2.0   # SDXL safety requirement

# ── Stock Footage APIs ────────────────────────────────────
pixabay-python==0.1.1
py-pexels==1.0.2

# ── Video & Audio Assembly ────────────────────────────────
moviepy==1.0.3
imageio==2.34.0
imageio-ffmpeg==0.4.9
decorator==4.4.2             # MoviePy dependency

# ── Captions (Whisper) ────────────────────────────────────
openai-whisper==20231117
ffmpeg-python==0.2.0

# ── AI Music (MusicGen / Meta) ────────────────────────────
audiocraft==1.3.0            # pip install audiocraft

# ── Thumbnail Generation ──────────────────────────────────
Pillow==10.3.0               # already listed above
colour==0.1.5
```

## 5. config.yaml

```yaml
# TrendForge Configuration

opencode:
  base_url: http://localhost:11434/v1   # OpenCode local API
  model: opencode                        # or your local model name
  temperature: 0.7

scraping:
  max_sources: 10                        # sources per topic
  regions: ["US", "GB", "AU"]          # Google Trends regions
  reddit_subreddits: ["worldnews", "technology", "science", "todayilearned"]

tts:
  engine: kokoro                         # kokoro | piper | coqui
  voice: af_bella                        # Kokoro voice ID
  speed: 1.05                            # slightly faster = more engaging
  output_format: wav

image:
  engine: sdxl                           # sdxl | flux | stock
  model_path: ./models/sdxl/
  steps: 30
  guidance_scale: 7.5
  width: 1920
  height: 1080
  negative_prompt: "watermark, text, logo, blurry, nsfw"
  fallback_stock: pixabay                # fallback if GPU unavailable

video:
  resolution: [1920, 1080]               # 1080p (change to [3840,2160] for 4K)
  fps: 30
  bitrate: 8000k
  intro_clip: ./assets/intro.mp4
  outro_clip: ./assets/outro.mp4
  transition_duration: 0.5
  music_volume: 0.08                     # ducked under voiceover
  music_source: musicgen                 # musicgen | freesound | local

captions:
  enabled: true
  whisper_model: base                    # tiny | base | small | medium
  font: ./assets/fonts/Inter-Bold.ttf
  font_size: 52
  color: "#FFFFFF"
  outline_color: "#000000"
  position: bottom                       # bottom | center

output:
  directory: ./output/
  temp_directory: ./temp/
  format: mp4
  thumbnail: true
  auto_metadata: true                    # generates title, description, tags
```

## 6. Step-by-Step Setup Guide

|                     |
|---------------------|
| **① Prerequisites** |

System requirements
- Python 3.11 or higher
- FFmpeg installed system-wide (brew install ffmpeg / apt install ffmpeg)
- Git
- 8 GB RAM minimum (16 GB recommended for SDXL image generation)
- NVIDIA GPU optional but strongly recommended for image generation and Whisper
- OpenCode running locally (see opencode.ai for installation)

Install FFmpeg

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt update && sudo apt install ffmpeg -y

# Windows (WSL2 recommended)
sudo apt update && sudo apt install ffmpeg -y

# Verify
ffmpeg -version
```

|                          |
|--------------------------|
| **② Create the Project** |

```bash
# Clone or create project folder
mkdir trendforge && cd trendforge

# Create virtual environment
python3.11 -m venv venv

# Activate (Linux / macOS)
source venv/bin/activate

# Activate (Windows PowerShell)
# .\venv\Scripts\Activate.ps1

# Confirm you are inside the venv
which python    # should show .../trendforge/venv/bin/python
```

|                                   |
|-----------------------------------|
| **③ Install Python Dependencies** |

```bash
# Upgrade pip first
pip install --upgrade pip

# Install all requirements
pip install -r requirements.txt

# GPU users: replace torch with CUDA build after install
pip install torch==2.3.0+cu121 --index-url https://download.pytorch.org/whl/cu121

# Verify torch sees your GPU (optional)
python -c "import torch; print(torch.cuda.is_available())"
```

|                          |
|--------------------------|
| **④ Install Kokoro TTS** |

Kokoro is the primary TTS engine. It produces the most natural-sounding English voices of any open-source model as of 2025.

```bash
# Install Kokoro from PyPI
pip install kokoro soundfile

# Download voice model weights (auto on first run, or manually)
python -c "from kokoro import generate; print('Kokoro ready')"

# Test a voice render
python -c "
from kokoro import generate
import soundfile as sf
audio, sr = generate('Hello, this is TrendForge.', voice='af_bella', speed=1.0)
sf.write('test_voice.wav', audio, sr)
print('Voice test saved to test_voice.wav')
"
```

|                                      |
|--------------------------------------|
| **⑤ Download Stable Diffusion SDXL** |

All images generated by TrendForge are AI-generated and owned entirely by you — no copyright risk.

```bash
# Create models directory
mkdir -p models/sdxl

# Download SDXL base model via huggingface-cli
pip install huggingface_hub
huggingface-cli download stabilityai/stable-diffusion-xl-base-1.0 \
  --local-dir ./models/sdxl/ \
  --include '*.safetensors' '*.json' '*.txt'

# Test image generation
python -c "
from diffusers import StableDiffusionXLPipeline
import torch
pipe = StableDiffusionXLPipeline.from_pretrained(
  './models/sdxl',
  torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
)
img = pipe('futuristic city skyline, cinematic lighting, 4K').images[0]
img.save('test_image.png')
print('Image saved to test_image.png')
"
```

|                          |
|--------------------------|
| **⑥ Configure OpenCode** |

OpenCode must be running locally before TrendForge starts. It acts as the research brain, script writer, and fact/opinion classifier.

```bash
# Start OpenCode (in a separate terminal)
opencode serve

# Verify OpenCode API is reachable
curl http://localhost:11434/v1/models

# Update config.yaml if your port differs
# opencode:
#   base_url: http://localhost:YOUR_PORT/v1
```

|                              |
|------------------------------|
| **⑦ Set Up API Keys (.env)** |

Only the stock media APIs require keys — both offer generous free tiers. All other components run fully locally.

```bash
# Create .env file in project root
cat > .env << 'EOF'
PIXABAY_API_KEY=your_pixabay_key_here
PEXELS_API_KEY=your_pexels_key_here
EOF

# Get free keys at:
# Pixabay: https://pixabay.com/api/docs/
# Pexels:  https://www.pexels.com/api/
```

|                          |
|--------------------------|
| **⑧ Add Branded Assets** |

Place your intro and outro clips in the assets/ folder. These are the TrendForge-branded segments that bookend every video.

```bash
# Create assets directory
mkdir -p assets/fonts assets/music

# Add your intro.mp4 (3-8 seconds, 1920x1080)
# Add your outro.mp4 (subscribe card, 5-10 seconds)
cp /path/to/your/intro.mp4 assets/intro.mp4
cp /path/to/your/outro.mp4 assets/outro.mp4

# Download free fonts (Inter is recommended)
# https://fonts.google.com/specimen/Inter
cp Inter-Bold.ttf assets/fonts/
cp Inter-Regular.ttf assets/fonts/

# Optional: add pre-downloaded CC0 music tracks
# https://freesound.org  or  https://www.youtube.com/audiolibrary
```

|                 |
|-----------------|
| **⑨ First Run** |

```bash
# Make sure venv is active
source venv/bin/activate

# Run with a specific subject
python main.py --subject "artificial intelligence"

# Run with auto trending topic (no subject)
python main.py

# Run with verbose logging
python main.py --subject "space exploration" --verbose

# Output will appear in:
# ./output/YYYY-MM-DD_HH-MM-SS_<topic>.mp4
# ./output/YYYY-MM-DD_HH-MM-SS_<topic>_thumb.jpg
```

## 7. Module Reference

main.py — CLI Entry Point

```python
# main.py
import click
from modules.scraper import get_topic, scrape_web
from modules.researcher import analyse_content
from modules.scriptwriter import generate_script
from modules.tts import render_voiceover
from modules.imagegen import generate_images
from modules.editor import assemble_timeline
from modules.renderer import export_video

@click.command()
@click.option('--subject', default=None, help='Topic to research. Leave blank for trending.')
@click.option('--verbose', is_flag=True, help='Show detailed logs.')
def main(subject, verbose):
    topic    = get_topic(subject)           # Step 1: Input
    raw      = scrape_web(topic)             # Step 2: Research
    analysis = analyse_content(raw)          # Step 3: Fact/opinion
    script   = generate_script(analysis)    # Step 4: Script
    audio    = render_voiceover(script)      # Step 5: Voice
    images   = generate_images(script)       # Step 6: Visuals
    timeline = assemble_timeline(            # Step 7: Edit
                 audio, images, script)
    export_video(timeline, topic)            # Step 8: Output

if __name__ == '__main__':
    main()
```

modules/scraper.py — Web Research

Fetches the top trending topic via pytrends if no subject is given, then uses Scrapling to pull content from Google News RSS, Reddit JSON API (no auth needed), and Wikipedia. Returns a list of raw text chunks ready for AI analysis.

```python
from scrapling import Scraper
from pytrends.request import TrendReq
import feedparser, wikipediaapi

def get_topic(subject=None):
    if subject:
        return subject
    pt = TrendReq(hl='en-US', tz=360)
    pt.build_payload(kw_list=[], timeframe='now 1-d')
    return pt.trending_searches(pn='united_states').iloc[0, 0]

def scrape_web(topic):
    results = []
    # Google News RSS
    feed = feedparser.parse(f'https://news.google.com/rss/search?q={topic}')
    for entry in feed.entries[:5]:
        results.append({'source': 'news', 'text': entry.summary})
    # Reddit (no API key for .json)
    scraper = Scraper()
    reddit = scraper.get(
        f'https://www.reddit.com/search.json?q={topic}&limit=10')
    # ... parse and append reddit posts
    # Wikipedia summary
    wiki = wikipediaapi.Wikipedia('en')
    page = wiki.page(topic)
    if page.exists():
        results.append({'source': 'wiki', 'text': page.summary[:2000]})
    return results
```

modules/researcher.py — Fact vs Opinion AI

Passes all scraped content to OpenCode with a structured prompt that extracts verified facts, expert opinions, public sentiment, and conflicting views. Returns a structured JSON object used by the scriptwriter.

```python
from openai import OpenAI
import yaml, json

cfg = yaml.safe_load(open('config.yaml'))
client = OpenAI(base_url=cfg['opencode']['base_url'], api_key='local')

SYSTEM = '''You are a research analyst. Given raw web content, extract:
1. FACTS: Verifiable, source-backed statements only.
2. OPINIONS: Expert views, public sentiment, editorial positions.
3. CONFLICTS: Where sources disagree.
4. VERDICT: A balanced 2-sentence conclusion.
Return ONLY valid JSON with keys: facts, opinions, conflicts, verdict.'''

def analyse_content(raw_chunks):
    combined = '\n\n'.join(c['text'] for c in raw_chunks[:8])
    resp = client.chat.completions.create(
        model=cfg['opencode']['model'],
        messages=[
            {'role': 'system', 'content': SYSTEM},
            {'role': 'user',   'content': combined}
        ],
        temperature=0.3
    )
    return json.loads(resp.choices[0].message.content)
```

modules/tts.py — Kokoro Voice Render

```python
from kokoro import generate
import soundfile as sf
import yaml, os

cfg = yaml.safe_load(open('config.yaml'))['tts']

def render_voiceover(script):
    audio_files = []
    os.makedirs('./temp/audio', exist_ok=True)
    for i, segment in enumerate(script['segments']):
        audio, sr = generate(
            segment['text'],
            voice=cfg['voice'],
            speed=cfg['speed']
        )
        path = f'./temp/audio/segment_{i:03d}.wav'
        sf.write(path, audio, sr)
        audio_files.append({'path': path, 'segment': segment})
    return audio_files
```

modules/imagegen.py — AI Image Generation

```python
from diffusers import StableDiffusionXLPipeline
import torch, yaml, os

cfg = yaml.safe_load(open('config.yaml'))['image']
pipe = None  # lazy load on first call

def get_pipe():
    global pipe
    if pipe is None:
        pipe = StableDiffusionXLPipeline.from_pretrained(
            cfg['model_path'],
            torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
        ).to('cuda' if torch.cuda.is_available() else 'cpu')
    return pipe

def generate_images(script):
    images = []
    os.makedirs('./temp/images', exist_ok=True)
    for i, seg in enumerate(script['segments']):
        prompt = seg.get('image_prompt', seg['text'][:80] + ', cinematic 4K')
        result = get_pipe()(
            prompt, negative_prompt=cfg['negative_prompt'],
            num_inference_steps=cfg['steps'],
            guidance_scale=cfg['guidance_scale'],
            width=cfg['width'], height=cfg['height']
        ).images[0]
        path = f'./temp/images/frame_{i:03d}.png'
        result.save(path)
        images.append(path)
    return images
```

## 8. Build Phases

Build TrendForge in these six phases. Each phase produces a working artefact you can test independently before moving to the next.

| **Phase**   | **Goal**                         | **Done when**                                               | **Est. time** |
|-------------|----------------------------------|-------------------------------------------------------------|---------------|
| **Phase 1** | Scraper + OpenCode research loop | Running python main.py prints structured JSON to console    | **1-2 hrs**   |
| **Phase 2** | TTS voiceover                    | WAV files appear in temp/audio/ for each script segment     | **1 hr**      |
| **Phase 3** | Image generation pipeline        | PNG files appear in temp/images/ matched to segments        | **2-3 hrs**   |
| **Phase 4** | MoviePy assembly                 | Draft MP4 renders with voice + images (no captions yet)     | **2 hrs**     |
| **Phase 5** | Captions + music                 | Whisper captions burn in, MusicGen audio ducked under voice | **2 hrs**     |
| **Phase 6** | Final export + thumbnail         | Polished MP4 + JPG thumbnail in output/ ready to upload     | **1 hr**      |

## 9. Copyright Safety Rules

TrendForge is designed from the ground up to produce copyright-clean content. Follow these rules to stay safe:
- All images are AI-generated via SDXL or FLUX — you own them outright
- Never use scraped article body text verbatim in the script — OpenCode rewrites everything
- Pixabay and Pexels assets are CC0 — safe for commercial YouTube use
- Kokoro / Piper / Coqui TTS are open source — no voice actor rights issues
- MusicGen output is royalty-free by design — Meta’s model licence permits commercial use
- Freesound tracks: filter to CC0 licence only in your search queries
- YouTube Audio Library tracks: all free to use on YouTube without Content ID claims
- Never include copyrighted logos, trademarks, or brand imagery in image prompts
- Wikipedia content is CC BY-SA — rewriting via AI transforms it sufficiently, but always paraphrase

## 10. Common Issues & Fixes

| **Problem**                     | **Fix**                                                                              |
|---------------------------------|--------------------------------------------------------------------------------------|
| **CUDA out of memory (SDXL)**   | Reduce image steps to 20, or set engine: stock in config.yaml to use Pixabay instead |
| **Kokoro voice sounds choppy**  | Increase audio buffer: set chunk_size: 512 in tts.py, or switch voice to af_sky      |
| **OpenCode connection refused** | Ensure opencode serve is running in a separate terminal before starting main.py      |
| **MoviePy import error**        | Run: pip install moviepy==1.0.3 decorator==4.4.2 (version pin is critical)           |
| **pytrends 429 rate limit**     | Add time.sleep(5) between trend requests, or manually set --subject each run         |
| **FFmpeg not found**            | Install FFmpeg system-wide (not in venv): brew install ffmpeg or apt install ffmpeg  |
| **Whisper very slow on CPU**    | Use --model tiny in whisper config, or set captions: enabled: false temporarily      |
| **MusicGen out of memory**      | Use music_source: freesound in config.yaml to use pre-downloaded CC0 tracks          |

## 11. Roadmap

v0.1 — MVP (this document)
- Single-subject research to MP4 pipeline
- Kokoro TTS voiceover
- SDXL image generation
- MoviePy + FFmpeg assembly
- Whisper auto-captions

v0.2 — Quality
- FLUX.1-schnell image upgrade for faster, higher-quality visuals
- Ken Burns effect (slow pan/zoom on still images for motion feel)
- Multi-voice support (interviewer / narrator split)
- Automatic A/B thumbnail testing via YouTube Data API

v0.3 — Automation
- Cron/schedule mode: produce one video per day automatically
- YouTube Data API upload (no manual posting)
- Slack / email notification on completion
- Video series tracking (avoid duplicate topics)

v1.0 — Scale
- Multi-channel support (different subjects per channel)
- Web UI dashboard (FastAPI + React) to monitor queue
- Cloud render option (RunPod / Vast.ai for GPU access)
- Analytics integration: track which topics perform best

> **You are building a production system, not a prototype.**
>
> Every component in this plan is battle-tested open-source software. Take it one phase at a time, test each module in isolation, and you will have a working faceless YouTube channel generating daily videos before the end of your first week of builds.
