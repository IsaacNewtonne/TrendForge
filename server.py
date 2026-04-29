import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

app = FastAPI(title="TrendForge")

ROOT = Path(__file__).resolve().parent

app.mount("/static", StaticFiles(directory=str(ROOT / "frontend")), name="static")


class GenerateRequest(BaseModel):
    topic: Optional[str] = None
    visualSource: Literal["auto", "screenshots", "ai"] = "auto"
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
        status["ffmpeg"] = "bundled" if ffmpeg_path.exists() else "not found"
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


@app.post("/api/generate")
async def generate_video(payload: GenerateRequest, request: Request):
    async def stream_logs():
        cmd = [sys.executable, "-u", "main.py"]
        topic = (payload.topic or "").strip()
        if topic and topic.strip():
            cmd.extend(["--subject", topic])

        cmd.extend(["--visual-source", payload.visualSource])
        cmd.extend(["--codec", payload.codec])
        cmd.extend(["--bitrate", payload.bitrate])
        cmd.extend(["--preset", payload.preset])
        if payload.ttsVoice:
            cmd.extend(["--tts-voice", payload.ttsVoice])
        if payload.ttsSpeed is not None:
            cmd.extend(["--tts-speed", str(payload.ttsSpeed)])

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        process = None
        try:
            yield f"data: Running: {' '.join(cmd)}\n\n"
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
            )

            while True:
                if await request.is_disconnected():
                    process.terminate()
                    break

                line = await process.stdout.readline()
                if not line:
                    break
                line_str = line.decode("utf-8", errors="replace").strip()
                if line_str:
                    yield f"data: {line_str}\n\n"

            await process.wait()
            yield f"data: [DONE] {process.returncode}\n\n"
        except Exception as exc:
            yield f"data: ERROR: {type(exc).__name__}: {exc}\n\n"
            yield "data: [DONE] 1\n\n"
        finally:
            if process and process.returncode is None:
                process.terminate()
                await process.wait()

    return StreamingResponse(stream_logs(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("TRENDFORGE_PORT", "8510"))
    uvicorn.run(app, host="127.0.0.1", port=port)
