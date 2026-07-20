"""TrendForge - Streamlit control surface (premium control-room UI)."""

from __future__ import annotations

import html
import re
import subprocess
import sys
import time
from pathlib import Path

import streamlit as st
import yaml

from modules.process_guard import stop_existing_trendforge_workers


ROOT = Path(__file__).resolve().parent
STEPS = ["Research", "Analysis", "Script", "Voice", "Visuals", "Assembly", "Export"]
STEP_START_MARKERS = {
    "Research": "[1/7]",
    "Analysis": "[2/7]",
    "Script": "[3/7]",
    "Voice": "[4/7]",
    "Visuals": "[5/7]",
    "Assembly": "[6/7]",
    "Export": "[7/7]",
}

# Brand palette (mirrors DESIGN.md)
BG = "#0D0D12"
SURFACE = "#16161D"
PRIMARY = "#534AB7"
ACCENT = "#EF9F27"
TEXT = "#FFFFFF"
MUTED = "#A0A0B0"
BORDER = "#2A2A35"


def detect_runtime() -> dict[str, str]:
    status: dict[str, str] = {
        "python": sys.version.split()[0],
        "ai_gpu": "unknown",
        "encoder_gpu": "unknown",
        "ffmpeg": "not found",
        "tts": "unknown",
    }

    try:
        import torch

        if torch.cuda.is_available():
            status["ai_gpu"] = f"CUDA ready ({torch.cuda.get_device_name(0)})"
        else:
            status["ai_gpu"] = "CPU only"
    except Exception as exc:
        status["ai_gpu"] = f"unavailable ({type(exc).__name__})"

    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        status["encoder_gpu"] = result.stdout.strip().splitlines()[0] if result.returncode == 0 else "not found"
    except Exception:
        status["encoder_gpu"] = "not found"

    try:
        import imageio_ffmpeg

        ffmpeg_path = Path(imageio_ffmpeg.get_ffmpeg_exe())
        status["ffmpeg"] = ffmpeg_path.name if ffmpeg_path.exists() else "not found"
    except Exception:
        pass

    try:
        from modules.renderer import load_video_config, nvenc_is_usable, resolve_ffmpeg_path

        cfg_video = load_video_config()
        ffmpeg_path = resolve_ffmpeg_path()
        if ffmpeg_path:
            status["ffmpeg"] = Path(ffmpeg_path).name
        if status["encoder_gpu"] != "not found":
            suffix = "NVENC ready" if nvenc_is_usable(cfg_video) else "NVENC blocked"
            status["encoder_gpu"] = f"{status['encoder_gpu']} ({suffix})"
    except Exception:
        pass

    try:
        from modules.tts import CHATTERBOX_AVAILABLE

        if CHATTERBOX_AVAILABLE:
            status["tts"] = "Kokoro + Chatterbox"
        else:
            status["tts"] = "Kokoro ready"
    except Exception as exc:
        status["tts"] = f"unavailable ({type(exc).__name__})"

    return status


def derive_stage_states(log_text: str, return_code: int | None = None) -> tuple[list[dict[str, str]], int, str]:
    """Derive stage card states from backend logs."""
    states = [
        {"name": name, "status": "queued", "detail": waiting_detail(name)}
        for name in STEPS
    ]

    started_index = -1
    for index, name in enumerate(STEPS):
        if STEP_START_MARKERS[name] in log_text:
            started_index = index
            states[index]["status"] = "running"
            states[index]["detail"] = running_detail(name, log_text)

    for index in range(started_index):
        states[index]["status"] = "complete"
        states[index]["detail"] = complete_detail(states[index]["name"], log_text)

    if "Pipeline complete" in log_text or "Video saved to:" in log_text:
        for state in states:
            state["status"] = "complete"
            state["detail"] = complete_detail(state["name"], log_text)

    if "Pipeline failed" in log_text or return_code not in (None, 0):
        error_index = max(started_index, 0)
        states[error_index]["status"] = "error"
        states[error_index]["detail"] = error_detail(log_text)

    completed = sum(1 for state in states if state["status"] == "complete")
    global_status = "idle"
    if any(state["status"] == "running" for state in states):
        global_status = "running"
    if any(state["status"] == "error" for state in states):
        global_status = "error"
    if completed == len(STEPS):
        global_status = "complete"

    return states, completed, global_status


def waiting_detail(stage: str) -> str:
    waits = {
        "Research": "Waiting to start",
        "Analysis": "Waiting for research",
        "Script": "Waiting for analysis",
        "Voice": "Waiting for storyboard",
        "Visuals": "Waiting for voiceover",
        "Assembly": "Waiting for visuals",
        "Export": "Waiting for assembly",
    }
    return waits[stage]


def running_detail(stage: str, log_text: str) -> str:
    if stage == "Research":
        match = re.search(r"Scraped (\d+) sources", log_text)
        return f"{match.group(1)} sources found" if match else "Scraping sources"
    if stage == "Analysis":
        match = re.search(r"Analysis complete: (\d+) facts, (\d+) opinions", log_text)
        return f"{match.group(1)} facts, {match.group(2)} opinions" if match else "Separating facts and opinions"
    if stage == "Script":
        match = re.search(r"Script generated: (\d+) segments", log_text)
        return f"{match.group(1)} segments generated" if match else "Writing script and storyboard"
    if stage == "Voice":
        total = latest_int(r"Rendering (\d+) voice segments", log_text)
        done = count_matches(r"segment \d+:", log_text)
        if total:
            return f"{min(done, total)}/{total} segments rendered"
        return "Rendering narration"
    if stage == "Visuals":
        current, total = latest_pair(r"Visual (\d+)/(\d+):", log_text)
        if total:
            return f"{current}/{total} visuals prepared"
        return "Creating screenshots and art"
    if stage == "Assembly":
        return "Combining audio and visuals"
    if stage == "Export":
        progress = latest_int(r"Render progress: (\d+)%", log_text)
        return f"{progress}% exported" if progress is not None else "Rendering final file"
    return "Running"


def complete_detail(stage: str, log_text: str) -> str:
    if stage == "Research":
        match = re.search(r"Scraped (\d+) sources", log_text)
        return f"{match.group(1)} sources scraped" if match else "Complete"
    if stage == "Analysis":
        match = re.search(r"Analysis complete: (\d+) facts, (\d+) opinions", log_text)
        return f"{match.group(1)} facts, {match.group(2)} opinions"
    if stage == "Script":
        match = re.search(r"Script generated: (\d+) segments", log_text)
        return f"{match.group(1)} segments + storyboard"
    if stage == "Voice":
        match = re.search(r"Voiceover complete: (\d+) audio segments", log_text)
        return f"{match.group(1)} segments rendered" if match else "Narration rendered"
    if stage == "Visuals":
        match = re.search(r"Visual assets ready: (\d+)", log_text)
        return f"{match.group(1)} visuals ready" if match else "Visuals ready"
    if stage == "Assembly":
        return "Timeline assembled"
    if stage == "Export":
        path = latest_match(r"Video saved to: (.+)", log_text)
        return "Final video saved" if path else "Export complete"
    return "Complete"


def error_detail(log_text: str) -> str:
    message = latest_match(r"Pipeline failed: (.+)", log_text)
    return message[:120] if message else "Generation failed"


def latest_match(pattern: str, text: str) -> str | None:
    matches = re.findall(pattern, text)
    return matches[-1].strip() if matches else None


def latest_int(pattern: str, text: str) -> int | None:
    match = latest_match(pattern, text)
    return int(match) if match is not None and str(match).isdigit() else None


def latest_pair(pattern: str, text: str) -> tuple[int | None, int | None]:
    matches = re.findall(pattern, text)
    if not matches:
        return None, None
    current, total = matches[-1]
    return int(current), int(total)


def count_matches(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text))


def render_progress(progress_slot, stage_slot, log_text: str, return_code: int | None = None):
    states, completed, global_status = derive_stage_states(log_text, return_code)
    progress_slot.progress(completed / len(STEPS), text=f"{completed}/{len(STEPS)} stages - {global_status.title()}")
    cards = "".join(stage_card_html(state) for state in states)
    stage_slot.markdown(f'<div class="tf-stage-grid">{cards}</div>', unsafe_allow_html=True)
    return states, completed, global_status


def stage_card_html(state: dict[str, str]) -> str:
    status = state["status"]
    label = {
        "queued": "Queued",
        "running": "Running",
        "complete": "Complete",
        "error": "Error",
    }[status]
    icon = {
        "queued": "",
        "running": '<span class="tf-spinner"></span>',
        "complete": '<span class="tf-check">✓</span>',
        "error": '<span class="tf-error-icon">!</span>',
    }[status]
    return (
        f'<div class="tf-stage tf-stage-{status}">'
        f'<strong>{html.escape(state["name"])}</strong>'
        f'<div class="tf-stage-label">{icon}<span>{label}</span></div>'
        f'<div class="tf-stage-detail">{html.escape(state["detail"])}</div>'
        f"</div>"
    )


def latest_videos(limit: int = 5) -> list[Path]:
    output_dir = ROOT / "output"
    if not output_dir.exists():
        return []
    return sorted(output_dir.glob("*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)[:limit]


def load_app_config() -> dict:
    config_path = ROOT / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


def render_hook_panel(log_text: str) -> None:
    """Show the hook optimizer winner + retention grade after a run."""
    try:
        from modules.hook_optimizer import read_hook_report
    except Exception:
        return

    report = read_hook_report()
    if not report or not report.get("hooks"):
        return

    st.divider()
    st.subheader("Hook Optimizer")
    st.caption(f"Topic: {report.get('topic', '')}")

    selected = report.get("selected_hook", "")
    st.success(f"**Best hook** (chosen opener)\n\n> {selected}")

    hooks = report.get("hooks", [])
    if len(hooks) > 1:
        with st.expander(f"All {len(hooks)} scored hooks", expanded=False):
            for idx, h in enumerate(hooks):
                scores = h.get("scores", {})
                composite = h.get("composite", 0)
                badge = "✅ chosen" if idx == report.get("selected_index", 0) else ""
                st.markdown(f"**{composite}** {badge}\n\n{h.get('text', '')}")
                if scores:
                    cols = st.columns(4)
                    cols[0].metric("Curiosity", scores.get("curiosity_gap", 0))
                    cols[1].metric("Clarity", scores.get("clarity", 0))
                    cols[2].metric("Clickable", scores.get("clickability", 0))
                    cols[3].metric("Bounce risk", scores.get("risk", 0))
                if h.get("reasoning"):
                    st.caption(h["reasoning"])
                st.divider()

    retention = report.get("retention", {})
    grade = retention.get("overall_grade", "")
    weak = retention.get("weak_indices", [])
    if grade or weak:
        st.subheader("Retention Predictor")
        col_grade, col_weak = st.columns(2)
        col_grade.metric("Retention grade", grade or "—")
        col_weak.metric("Weak segments", len(weak))
        if weak:
            st.warning(
                "Segments flagged as likely drop-off points: "
                + ", ".join(f"#{i + 1}" for i in weak)
            )
            with st.expander("Fix suggestions", expanded=False):
                for seg in retention.get("segments", []):
                    if seg.get("index") in weak:
                        reason = seg.get("reason", "")
                        fix = seg.get("fix", "")
                        st.markdown(f"**Segment {seg['index'] + 1}** — risk {seg.get('retention_risk', 0)}")
                        if reason:
                            st.caption(f"Why: {reason}")
                        if fix:
                            st.caption(f"Fix: {fix}")
                        st.divider()


def render_log_window(log_text: str, height: int) -> None:
    """Render the live log with the newest line pinned to the TOP.

    The viewer scrolls with the latest entry at the top; the controls let the
    user expand the window downward to reveal more history.
    """
    lines = [ln for ln in log_text.splitlines() if ln.strip()]
    ordered = list(reversed(lines))  # newest first
    if not ordered:
        st.info("No log output yet. Start a generation to see live progress.")
        return

    safe = "\n".join(
        html.escape(ln).replace(" ", "&nbsp;").replace("\n", "<br>")
        for ln in ordered
    )
    st.markdown(
        f'<div class="tf-logwin" style="height:{height}px" id="tfLogWin">'
        f'<pre class="tf-logpre">{safe}</pre></div>',
        unsafe_allow_html=True,
    )


LOGO_PATH = ROOT / "Assets" / "Logo.png"

st.set_page_config(
    page_title="TrendForge",
    page_icon=str(LOGO_PATH) if LOGO_PATH.exists() else "TF",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    f"""
    <style>
      :root {{
        --tf-bg: {BG};
        --tf-surface: {SURFACE};
        --tf-primary: {PRIMARY};
        --tf-accent: {ACCENT};
        --tf-text: {TEXT};
        --tf-muted: {MUTED};
        --tf-border: {BORDER};
      }}
      .stApp {{
        background:
          radial-gradient(1200px 600px at 85% -10%, rgba(83,74,183,0.18), transparent 60%),
          radial-gradient(900px 500px at -10% 10%, rgba(239,159,39,0.10), transparent 55%),
          var(--tf-bg);
        color: var(--tf-text);
      }}
      [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, #101018, #0c0c12);
        border-right: 1px solid var(--tf-border);
      }}
      h1, h2, h3 {{ letter-spacing: -0.01em; }}
      .stApp header {{ background: transparent; }}

      /* Metrics */
      div[data-testid="stMetric"] {{
        background: var(--tf-surface);
        border: 1px solid var(--tf-border);
        border-radius: 12px;
        padding: 12px 14px;
        box-shadow: 0 1px 0 rgba(255,255,255,0.02) inset;
      }}
      div[data-testid="stMetric"] label {{ color: var(--tf-muted); font-size: 0.72rem; }}

      /* Stage cards */
      .tf-stage {{
        border: 1px solid var(--tf-border);
        border-radius: 12px;
        padding: 12px 12px;
        min-height: 104px;
        background: var(--tf-surface);
        transition: border-color 160ms ease, background 160ms ease, transform 160ms ease;
      }}
      .tf-stage:hover {{ transform: translateY(-2px); }}
      .tf-stage-grid {{
        display: grid;
        grid-template-columns: repeat(7, minmax(112px, 1fr));
        gap: 10px;
        width: 100%;
      }}
      @media (max-width: 980px) {{
        .tf-stage-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      }}
      .tf-stage-queued {{ border-color: var(--tf-border); background: #121219; color: var(--tf-muted); }}
      .tf-stage-running {{
        border-color: var(--tf-accent);
        background: linear-gradient(180deg, #1B1820, #16121a);
        box-shadow: 0 0 0 1px rgba(239, 159, 39, 0.20), 0 6px 20px rgba(239,159,39,0.06);
      }}
      .tf-stage-complete {{
        border-color: rgba(62, 180, 126, 0.85);
        background: linear-gradient(180deg, #111A18, #0f1715);
      }}
      .tf-stage-error {{
        border-color: rgba(235, 87, 87, 0.95);
        background: linear-gradient(180deg, #211315, #1c1012);
      }}
      .tf-stage-label {{
        display: flex; align-items: center; gap: 7px;
        margin-top: 8px; font-size: 0.86rem; font-weight: 650;
      }}
      .tf-stage-detail {{ color: var(--tf-muted); font-size: 0.76rem; line-height: 1.25; margin-top: 7px; }}
      .tf-check {{ color: #3EB47E; font-weight: 800; }}
      .tf-error-icon {{ color: #EB5757; font-weight: 800; }}
      .tf-spinner {{
        width: 10px; height: 10px; border-radius: 999px; background: var(--tf-accent);
        display: inline-block; animation: tfPulse 1.1s ease-in-out infinite;
      }}
      @keyframes tfPulse {{
        0%, 100% {{ opacity: 0.42; transform: scale(0.72); }}
        50% {{ opacity: 1; transform: scale(1); }}
      }}

      /* Live log window: newest at top */
      .tf-logwin {{
        overflow-y: auto;
        background: #0a0a0f;
        border: 1px solid var(--tf-border);
        border-radius: 12px;
        padding: 10px 12px;
        scroll-behavior: smooth;
      }}
      .tf-logpre {{
        margin: 0;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 12.5px;
        line-height: 1.5;
        color: #c9c9d6;
        white-space: pre-wrap;
        word-break: break-word;
      }}

      .tf-pill {{
        display: inline-flex; align-items: center; gap: 6px;
        padding: 3px 10px; border-radius: 999px; font-size: 0.72rem; font-weight: 600;
        border: 1px solid var(--tf-border); color: var(--tf-muted); background: var(--tf-surface);
      }}
      .tf-pill-ok {{ color: #3EB47E; border-color: rgba(62,180,126,0.5); }}
      .tf-pill-run {{ color: var(--tf-accent); border-color: rgba(239,159,39,0.5); }}
      .tf-muted {{ color: var(--tf-muted); }}
      .tf-hero {{
        background: linear-gradient(135deg, rgba(83,74,183,0.22), rgba(239,159,39,0.08));
        border: 1px solid var(--tf-border);
        border-radius: 16px; padding: 18px 20px; margin-bottom: 14px;
      }}
      section[data-testid="stSidebar"] .stButton > button {{
        border-radius: 10px;
      }}
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
header_cols = st.columns([0.07, 0.93])
if LOGO_PATH.exists():
    header_cols[0].image(str(LOGO_PATH), width=52)
with header_cols[1]:
    st.markdown(
        "<div style='display:flex;align-items:baseline;gap:12px'>"
        "<h1 style='margin:0'>TrendForge</h1>"
        "<span class='tf-pill'>AI Faceless Video Studio</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.caption("Local-first viral video pipeline · research → script → voice → visuals → render")

runtime = detect_runtime()
app_config = load_app_config()

pill_cols = st.columns(5)
pill_cols[0].metric("Python", runtime["python"])
pill_cols[1].metric("AI CUDA", runtime["ai_gpu"])
pill_cols[2].metric("NVENC GPU", runtime["encoder_gpu"])
pill_cols[3].metric("FFmpeg", runtime["ffmpeg"])
pill_cols[4].metric("Voice", runtime["tts"])

# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Generation")
    auto_topic = st.checkbox("Auto topic", value=False, help="Pick a trending topic automatically.")
    topic = st.text_input("Topic", value="artificial intelligence", disabled=auto_topic)
    skip_video = st.checkbox("Skip render", value=False)
    verbose = st.checkbox("Verbose logs", value=False)

    st.header("Voice")
    try:
        from modules.tts import (
            list_kokoro_voices,
            render_voice_sample,
            CHATTERBOX_AVAILABLE,
        )

        engine_options = ["kokoro"]
        if CHATTERBOX_AVAILABLE:
            engine_options.append("chatterbox")
        configured_engine = app_config.get("tts", {}).get("engine", "kokoro")
        tts_engine = st.selectbox(
            "TTS engine",
            options=engine_options,
            index=engine_options.index(configured_engine) if configured_engine in engine_options else 0,
            help="Chatterbox is more natural (MIT, local, voice cloning) but optional.",
        )
        if tts_engine == "chatterbox" and not CHATTERBOX_AVAILABLE:
            st.warning("Chatterbox not installed. pip install chatterbox-tts, then set tts.engine: chatterbox.")
            tts_engine = "kokoro"

        if tts_engine == "chatterbox":
            tts_voice = st.text_input(
                "Reference audio path (optional)",
                value=app_config.get("tts", {}).get("chatterbox_reference_audio", ""),
                help="A short .wav clip to clone a consistent, natural persona.",
            )
            exaggeration = st.slider(
                "Emotion exaggeration",
                min_value=0.0,
                max_value=1.0,
                value=float(app_config.get("tts", {}).get("chatterbox_exaggeration", 0.5)),
                step=0.05,
            )
            tts_speed = st.slider(
                "Voice speed",
                min_value=0.75,
                max_value=1.35,
                value=float(app_config.get("tts", {}).get("speed", 1.05)),
                step=0.05,
            )
            sample_text = st.text_input(
                "Sample line",
                value="Welcome to Trend Forge. This is how the selected voice sounds.",
            )
            if st.button("Play voice sample", use_container_width=True):
                try:
                    from modules.tts import render_voice_sample_chatterbox

                    sample_path = render_voice_sample_chatterbox(
                        sample_text, speed=tts_speed, exaggeration=exaggeration,
                        reference_audio=tts_voice or None,
                    )
                    st.session_state.voice_sample_path = sample_path
                except Exception as exc:
                    st.error(f"Voice sample failed: {exc}")
            if st.session_state.get("voice_sample_path"):
                st.audio(st.session_state.voice_sample_path)
        else:
            voices = list_kokoro_voices()
            voice_ids = list(voices.keys())
            configured_voice = app_config.get("tts", {}).get("voice", "af_bella")
            voice_index = voice_ids.index(configured_voice) if configured_voice in voice_ids else 0
            tts_voice = st.selectbox(
                "Kokoro voice",
                options=voice_ids,
                index=voice_index,
                format_func=lambda voice_id: voices.get(voice_id, voice_id),
            )
            tts_speed = st.slider(
                "Voice speed",
                min_value=0.75,
                max_value=1.35,
                value=float(app_config.get("tts", {}).get("speed", 1.05)),
                step=0.05,
            )
            sample_text = st.text_input(
                "Sample line",
                value="Welcome to Trend Forge. This is how the selected voice sounds.",
            )
            if st.button("Play voice sample", use_container_width=True):
                try:
                    sample_path = render_voice_sample(sample_text, voice=tts_voice, speed=tts_speed)
                    st.session_state.voice_sample_path = sample_path
                except Exception as exc:
                    st.error(f"Voice sample failed: {exc}")
            if st.session_state.get("voice_sample_path"):
                st.audio(st.session_state.voice_sample_path)
    except Exception as exc:
        tts_voice = app_config.get("tts", {}).get("voice", "af_bella")
        tts_speed = float(app_config.get("tts", {}).get("speed", 1.05))
        st.warning(f"Voice controls unavailable: {type(exc).__name__}")

    st.header("Visuals")
    st.caption("Storyboard rules stay on: source claims use screenshots; analogies and concepts use art.")
    visual_source = st.selectbox(
        "Visual source",
        options=["auto", "screenshots", "ai"],
        index=0,
        help="Auto tries AI images first when CUDA is ready, then falls back to screenshots.",
    )
    max_urls = st.slider("Screenshot URLs", min_value=1, max_value=16, value=12)
    captures_per_url = st.slider("Shots per URL", min_value=1, max_value=4, value=1)

    st.header("Render")
    codec = st.selectbox("Codec", options=["auto", "libx264", "h264_nvenc"], index=0)
    bitrate = st.selectbox("Bitrate", options=["8000k", "12000k", "16000k", "24000k"], index=1)
    render_preset = st.selectbox("Preset", options=["fast", "medium", "slow"], index=1)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "log" not in st.session_state:
    st.session_state.log = ""
if "last_return_code" not in st.session_state:
    st.session_state.last_return_code = None
if "current_run" not in st.session_state:
    st.session_state.current_run = {"id": "idle", "log": "", "return_code": None, "status": "idle"}
if "log_window_height" not in st.session_state:
    st.session_state.log_window_height = 280

# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------
progress_slot = st.empty()
stage_slot = st.empty()
status_slot = st.empty()

run_log = st.session_state.current_run.get("log", st.session_state.log)
run_return_code = st.session_state.current_run.get("return_code", st.session_state.last_return_code)
render_progress(progress_slot, stage_slot, run_log, run_return_code)

st.markdown('<div class="tf-hero">', unsafe_allow_html=True)
gen_cols = st.columns([4, 1])
with gen_cols[0]:
    st.markdown("### Generate a faceless video")
    st.caption("Enter a topic (or let it pick a trending one) and TrendForge researches, scripts, voices, and renders it locally.")
with gen_cols[1]:
    running_before_click = derive_stage_states(run_log, run_return_code)[2] == "running"
    generate = st.button(
        "Generating..." if running_before_click else "Generate video",
        type="primary",
        use_container_width=True,
        disabled=running_before_click,
        key="generate_button",
    )
st.markdown("</div>", unsafe_allow_html=True)

if generate:
    if not auto_topic and not topic.strip():
        st.error("Enter a topic or enable auto topic.")
    else:
        cmd = [sys.executable, "main.py"]
        if not auto_topic:
            cmd.extend(["--subject", topic.strip()])
        if skip_video:
            cmd.append("--skip-video")
        if verbose:
            cmd.append("--verbose")
        cmd.extend(["--visual-source", visual_source])
        cmd.extend(["--max-screenshot-urls", str(max_urls)])
        cmd.extend(["--captures-per-url", str(captures_per_url)])
        cmd.extend(["--codec", codec])
        cmd.extend(["--bitrate", bitrate])
        cmd.extend(["--preset", render_preset])
        cmd.extend(["--tts-voice", tts_voice])
        cmd.extend(["--tts-speed", str(tts_speed)])
        cmd.extend(["--tts-engine", tts_engine])
        if tts_engine == "chatterbox":
            cmd.extend(["--chatterbox-exaggeration", str(exaggeration)])
            if tts_voice:
                cmd.extend(["--chatterbox-reference", tts_voice])

        run_id = f"run-{int(time.time())}"
        st.session_state.current_run = {"id": run_id, "log": "", "return_code": None, "status": "running"}
        st.session_state.log = ""
        st.session_state.last_return_code = None
        status_slot.info(f"Generation running: {run_id}")
        render_progress(progress_slot, stage_slot, "", None)
        st.markdown(
            '<div class="tf-logwin" style="height:280px"><pre class="tf-logpre">Starting TrendForge...</pre></div>',
            unsafe_allow_html=True,
        )

        cleanup_messages: list[str] = []
        stop_existing_trendforge_workers(ROOT, log=cleanup_messages.append)
        if cleanup_messages:
            st.session_state.log += "\n".join(cleanup_messages) + "\n"

        process = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        assert process.stdout is not None
        for line in iter(process.stdout.readline, ""):
            if line:
                st.session_state.log += line
                st.session_state.current_run = {
                    **st.session_state.current_run,
                    "log": st.session_state.log,
                    "status": "running",
                }
                render_progress(progress_slot, stage_slot, st.session_state.log, None)
                render_log_window(st.session_state.log, st.session_state.log_window_height)

        process.stdout.close()
        st.session_state.last_return_code = process.wait()
        final_status = "complete" if st.session_state.last_return_code == 0 else "error"
        st.session_state.current_run = {
            **st.session_state.current_run,
            "log": st.session_state.log,
            "return_code": st.session_state.last_return_code,
            "status": final_status,
        }
        render_progress(progress_slot, stage_slot, st.session_state.log, st.session_state.last_return_code)
        render_log_window(st.session_state.log, st.session_state.log_window_height)

        if st.session_state.last_return_code == 0:
            status_slot.success(f"Generation completed: {st.session_state.current_run['id']}")
            st.success("Generation completed.")
        else:
            status_slot.error(f"Generation failed: {st.session_state.current_run['id']}")
            st.error("Generation failed. Check the log below.")

# ---------------------------------------------------------------------------
# Log controls + window
# ---------------------------------------------------------------------------
st.divider()
ctrl_cols = st.columns([2, 1])
with ctrl_cols[0]:
    st.subheader("Live log")
with ctrl_cols[1]:
    st.session_state.log_window_height = st.slider(
        "Log window height",
        min_value=120,
        max_value=720,
        value=st.session_state.log_window_height,
        step=20,
        help="Expand the log window downward to reveal more history. Newest line is always at the top.",
    )

active_log = st.session_state.log or run_log
render_log_window(active_log, st.session_state.log_window_height)

with st.expander("Raw full output", expanded=False):
    st.code(active_log[-12000:])

# ---------------------------------------------------------------------------
# Right panel: hook/retention + recent videos
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Recent videos")
videos = latest_videos()
if not videos:
    st.info("No rendered videos yet.")
else:
    selected = st.selectbox("Output", options=videos, format_func=lambda path: path.name)
    st.video(str(selected))
    for video in videos:
        st.caption(f"{video.name} - {video.stat().st_size / (1024 * 1024):.1f} MB")

render_hook_panel(active_log)
