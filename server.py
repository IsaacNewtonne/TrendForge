import asyncio
import os
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, Request
from fastapi import HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from modules.process_guard import stop_existing_trendforge_workers

app = FastAPI(title="TrendForge")

ROOT = Path(__file__).resolve().parent

app.mount("/static", StaticFiles(directory=str(ROOT / "frontend")), name="static")
app.mount("/assets", StaticFiles(directory=str(ROOT / "Assets")), name="assets")


PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def remove_dead_local_proxy(env: dict[str, str]) -> None:
    """Drop the placeholder localhost:9 proxy that breaks normal web requests."""
    for key in PROXY_ENV_VARS:
        value = env.get(key, "")
        if "127.0.0.1:9" in value or "localhost:9" in value:
            env.pop(key, None)


def set_workspace_temp(env: dict[str, str]) -> None:
    """Keep runtime temp files inside the workspace to avoid locked user temp dirs."""
    runtime_temp = ROOT / "temp" / "runtime"
    runtime_temp.mkdir(parents=True, exist_ok=True)
    for key in ("TEMP", "TMP", "TMPDIR"):
        env[key] = str(runtime_temp)


def sse_data(message: str) -> str:
    """Format a message as an SSE data event, preserving multiline tracebacks."""
    return "".join(f"data: {line}\n" for line in str(message).splitlines()) + "\n"


def stop_process(process: subprocess.Popen, timeout: float = 5.0) -> bool:
    """Best-effort child process shutdown that does not mask the real error."""
    if process.poll() is not None:
        return True

    try:
        process.terminate()
        process.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=timeout)
            return True
        except (PermissionError, OSError, subprocess.TimeoutExpired):
            return False
    except (PermissionError, OSError):
        return False


class GenerateRequest(BaseModel):
    topic: Optional[str] = None
    visualSource: Literal["auto", "screenshots", "ai", "manual"] = "auto"
    requestAiArt: bool = False
    codec: Literal["auto", "libx264", "h264_nvenc"] = "auto"
    bitrate: Literal["8000k", "12000k", "16000k", "24000k"] = "12000k"
    preset: Literal["fast", "medium", "slow"] = "medium"
    ttsVoice: Optional[str] = None
    ttsSpeed: Optional[float] = Field(default=None, ge=0.75, le=1.35)


@app.get("/")
async def root():
    with open(ROOT / "frontend" / "index.html", "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace('href="styles.css"', 'href="/static/styles.css"')
    html = html.replace('src="app.js"', 'src="/static/app.js"')
    return HTMLResponse(content=html)


@app.get("/api/status")
async def runtime_status():
    status = {
        "python": sys.version.split()[0],
        "aiEngine": "unknown",
        "encoderGpu": "unknown",
        "ffmpeg": "not found",
        "tts": "unknown",
        "voices": {},
    }

    try:
        import torch

        if torch.cuda.is_available():
            status["aiEngine"] = f"CUDA ready ({torch.cuda.get_device_name(0)})"
        else:
            status["aiEngine"] = "CPU only"
    except Exception as exc:
        status["aiEngine"] = f"unavailable ({type(exc).__name__})"

    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        status["encoderGpu"] = result.stdout.strip().splitlines()[0] if result.returncode == 0 else "not found"
    except Exception:
        status["encoderGpu"] = "not found"

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
        if status["encoderGpu"] != "not found":
            suffix = "NVENC ready" if nvenc_is_usable(cfg_video) else "NVENC blocked"
            status["encoderGpu"] = f"{status['encoderGpu']} ({suffix})"
    except Exception:
        pass

    try:
        import kokoro_onnx  # noqa: F401

        status["tts"] = "Kokoro ONNX ready"
    except Exception as exc:
        status["tts"] = f"unavailable ({type(exc).__name__})"

    try:
        from modules.tts import list_kokoro_voices

        status["voices"] = list_kokoro_voices()
    except Exception:
        status["voices"] = {}

    return status


@app.get("/api/manual-images/manifest")
async def manual_images_manifest():
    try:
        from modules.manual_images import load_current_manifest, validate_manual_image_files

        manifest = load_current_manifest()
        validation = validate_manual_image_files(manifest)
        manifest["validation"] = validation
        return manifest
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/manual-images/confirm")
async def manual_images_confirm():
    from modules.manual_images import confirm_manual_images

    result = confirm_manual_images()
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)
    return result


@app.post("/api/generate")
async def generate_video(payload: GenerateRequest, request: Request):
    async def stream_logs():
        python_exe = Path(sys.executable)
        if not python_exe.exists():
            raise RuntimeError(f"Python executable not found: {python_exe}")

        cmd = [str(python_exe), "-B", "-u", "main.py"]
        topic = (payload.topic or "").strip()
        if topic and topic.strip():
            cmd.extend(["--subject", topic])

        cmd.extend(["--visual-source", payload.visualSource])
        if payload.requestAiArt:
            cmd.append("--request-ai-art")
        cmd.extend(["--codec", payload.codec])
        cmd.extend(["--bitrate", payload.bitrate])
        cmd.extend(["--preset", payload.preset])
        if payload.ttsVoice:
            cmd.extend(["--tts-voice", payload.ttsVoice])
        if payload.ttsSpeed is not None:
            cmd.extend(["--tts-speed", str(payload.ttsSpeed)])

        env = os.environ.copy()
        remove_dead_local_proxy(env)
        set_workspace_temp(env)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["TRENDFORGE_RUN_ID"] = datetime.now().strftime("%Y%m%d%H%M%S")

        process = None
        try:
            cleanup_messages: list[str] = []
            await asyncio.to_thread(
                stop_existing_trendforge_workers,
                ROOT,
                cleanup_messages.append,
            )
            for message in cleanup_messages:
                yield sse_data(message)
            yield sse_data(f"Running: {' '.join(cmd)}")
            process = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            while True:
                line = await asyncio.to_thread(process.stdout.readline)
                if not line:
                    break
                line_str = line.strip()
                if line_str:
                    yield sse_data(line_str)

            await asyncio.to_thread(process.wait)
            yield sse_data(f"[DONE] {process.returncode}")
        except Exception as exc:
            yield sse_data(f"ERROR: {type(exc).__name__}: {exc}")
            yield sse_data(traceback.format_exc().rstrip())
            yield sse_data("[DONE] 1")
        finally:
            if process and process.poll() is None:
                stopped = await asyncio.to_thread(stop_process, process)
                if not stopped:
                    # The UI stream may already be closed here, so keep this local.
                    print(f"WARNING: Could not terminate child process {process.pid}", file=sys.stderr)

    return StreamingResponse(stream_logs(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("TRENDFORGE_PORT", "8510"))
    uvicorn.run(app, host="127.0.0.1", port=port)
