"""Verify and install TrendForge runtime dependencies before launch."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
WINDOWS_PACKAGES = {
    "ollama": "Ollama.Ollama",
    "ffmpeg": "Gyan.FFmpeg",
}
OLLAMA_MODELS = ("qwen3.5:4b", "qwen3.5:9b")
ANSI_RESET = "\033[0m"
ANSI_CLEAR_LINE = "\033[2K"
PALETTE = ("\033[38;5;51m", "\033[38;5;45m", "\033[38;5;39m", "\033[38;5;99m", "\033[38;5;135m")
FIRE = ("\033[38;5;226m", "\033[38;5;220m", "\033[38;5;214m", "\033[38;5;208m", "\033[38;5;196m")
GREEN = "\033[38;5;82m"
RED = "\033[38;5;203m"
YELLOW = "\033[38;5;220m"
MUTED = "\033[38;5;244m"
BOLD = "\033[1m"


def enable_terminal_color() -> bool:
    if not sys.stdout.isatty() and os.environ.get("FORCE_COLOR") != "1":
        return False
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


COLOR_ENABLED = enable_terminal_color()


def color(text: str, code: str) -> str:
    return f"{code}{text}{ANSI_RESET}" if COLOR_ENABLED else text


def clear_line() -> str:
    return ANSI_CLEAR_LINE if COLOR_ENABLED else ""


def status(kind: str, message: str) -> None:
    colors = {
        "ready": GREEN,
        "install": YELLOW,
        "check": PALETTE[0],
        "missing": RED,
        "unavailable": RED,
        "error": RED,
    }
    print(f"{color(f'[{kind}]', BOLD + colors.get(kind, MUTED))} {message}")


def stage(number: int, total: int, label: str) -> None:
    badge = color(f"[{number}/{total}]", BOLD + PALETTE[(number - 1) % len(PALETTE)])
    print(f"\n{badge} {color(label.upper(), BOLD)}")


def boot_animation() -> None:
    banner = (
        "  _______                   ______                    ",
        " |__   __|                 |  ____|                   ",
        "    | |_ __ ___ _ __   __| |__ ___  _ __ __ _  ___ ",
        "    | | '__/ _ \\ '_ \\ / _` |  __/ _ \\| '__/ _` |/ _ \\",
        "    | | | |  __/ | | | (_| | | | (_) | | | (_| |  __/",
        "    |_|_|  \\___|_| |_|\\__, |_|  \\___/|_|  \\__, |\\___|",
        "                       __/ |                __/ |     ",
        "                      |___/                |___/      ",
    )
    print()
    for index, line in enumerate(banner):
        print(color(BOLD + line if COLOR_ENABLED else line, PALETTE[index % len(PALETTE)]))
        time.sleep(0.035)
    print(color("           A I   V I D E O   C O N T R O L   R O O M", MUTED))
    print()

    spark_positions = (2, 9, 15, 25, 36, 47, 55)
    flame_shapes = ("  .  ", " .*. ", ".*^*.", "*^^^*", "\\^^^/")
    for frame in range(18):
        sparks = [" "] * 60
        for index, start in enumerate(spark_positions):
            position = (start + frame * (index % 3 + 1)) % len(sparks)
            sparks[position] = "*" if (frame + index) % 2 else "+"
        flame = flame_shapes[frame % len(flame_shapes)]
        flame_color = FIRE[frame % len(FIRE)]
        core = activity_frame(frame, 22)
        line = (
            f"  {color(''.join(sparks), FIRE[(frame // 2) % len(FIRE)])} "
            f"{color(flame, flame_color)}  "
            f"{color('FORGE CORE', BOLD + PALETTE[frame % len(PALETTE)])} "
            f"{color(core, PALETTE[frame % len(PALETTE)])}"
        )
        print(f"\r{clear_line()}{line}", end="", flush=True)
        time.sleep(0.065)
    print(
        f"\r{clear_line()}  "
        f"{color('[ FORGE CORE ONLINE ]', BOLD + GREEN)} "
        f"{color('systems hot - pipeline ready', MUTED)}\n"
    )


def activity_frame(position: int, width: int = 18) -> str:
    cycle = (width - 1) * 2
    offset = position % cycle
    cursor = offset if offset < width else cycle - offset
    cells = ["-"] * width
    cells[cursor] = ">"
    if cursor > 0:
        cells[cursor - 1] = "="
    return "[" + "".join(cells) + "]"


def animated_activity_frame(position: int, width: int = 18) -> str:
    raw = activity_frame(position, width)
    return color(raw, PALETTE[(position // 2) % len(PALETTE)])


def run(
    command: list[str],
    check: bool = True,
    capture: bool = False,
    activity: str | None = None,
) -> subprocess.CompletedProcess:
    if not activity:
        return subprocess.run(
            command,
            cwd=ROOT,
            check=check,
            text=True,
            capture_output=capture,
            creationflags=CREATE_NO_WINDOW,
        )

    started = time.monotonic()
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=output,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=CREATE_NO_WINDOW,
        )
        frame = 0
        while process.poll() is None:
            elapsed = time.monotonic() - started
            print(
                f"\r{clear_line()}  {color(f'{activity:<34}', BOLD)} "
                f"{animated_activity_frame(frame)} "
                f"{color(f'{elapsed:6.1f}s', MUTED)}",
                end="",
                flush=True,
            )
            frame += 1
            time.sleep(0.12)
        elapsed = time.monotonic() - started
        success = process.returncode == 0
        state = color("done", BOLD + GREEN) if success else color("FAILED", BOLD + RED)
        print(
            f"\r{clear_line()}  {color(f'{activity:<34}', BOLD)} "
            f"{color('[' + '=' * 18 + ']', GREEN if success else RED)} "
            f"{state} {color(f'({elapsed:.1f}s)', MUTED)}"
            + " " * 8
        )
        output.seek(0)
        text_output = output.read()

    completed = subprocess.CompletedProcess(
        command,
        process.returncode,
        stdout=text_output if capture else None,
        stderr=None,
    )
    if check and process.returncode:
        if text_output.strip():
            print("\n--- installer output ---")
            print(text_output.rstrip())
            print("--- end installer output ---")
        raise subprocess.CalledProcessError(process.returncode, command, output=text_output)
    return completed


def command_available(name: str) -> bool:
    return shutil.which(name) is not None


def install_windows_package(command: str, package_id: str, check_only: bool) -> bool:
    if command_available(command):
        status("ready", command)
        return True
    if check_only:
        status("missing", f"{command} ({package_id})")
        return False
    if not command_available("winget"):
        raise RuntimeError(f"{command} is missing and WinGet is unavailable.")
    status("install", package_id)
    run(
        [
            "winget",
            "install",
            "--id",
            package_id,
            "--exact",
            "--silent",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ],
        activity=f"Installing {package_id}",
    )
    return True


def chrome_available() -> bool:
    candidates = [
        shutil.which("chrome"),
        os.environ.get("PROGRAMFILES", "") + r"\Google\Chrome\Application\chrome.exe",
        os.environ.get("PROGRAMFILES(X86)", "") + r"\Google\Chrome\Application\chrome.exe",
        os.environ.get("LOCALAPPDATA", "") + r"\Google\Chrome\Application\chrome.exe",
    ]
    return any(candidate and Path(candidate).is_file() for candidate in candidates)


def ensure_chrome(check_only: bool) -> bool:
    if chrome_available():
        status("ready", "Google Chrome")
        return True
    if check_only:
        status("missing", "Google Chrome")
        return False
    if not command_available("winget"):
        raise RuntimeError("Google Chrome is missing and WinGet is unavailable.")
    status("install", "Google Chrome")
    run(
        [
            "winget",
            "install",
            "--id",
            "Google.Chrome",
            "--exact",
            "--silent",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ],
        activity="Installing Google Chrome",
    )
    return True


def ensure_python_packages(check_only: bool) -> bool:
    if check_only:
        result = run([sys.executable, "-m", "pip", "check"], check=False)
        return result.returncode == 0
    status("check", "Python dependencies")
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(ROOT / "requirements.txt"),
        ],
        activity="Checking Python packages",
    )
    return True


def ensure_ollama_running(check_only: bool) -> bool:
    result = run(["ollama", "list"], check=False, capture=True)
    if result.returncode == 0:
        return True
    if check_only:
        status("unavailable", "Ollama service")
        return False
    subprocess.Popen(
        ["ollama", "serve"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )
    started = time.monotonic()
    for frame in range(20):
        print(
            f"\r{clear_line()}  {color(f'{'Starting Ollama service':<34}', BOLD)} "
            f"{animated_activity_frame(frame)} "
            f"{color(f'{time.monotonic() - started:6.1f}s', MUTED)}",
            end="",
            flush=True,
        )
        time.sleep(1)
        if run(["ollama", "list"], check=False, capture=True).returncode == 0:
            print(
                f"\r{clear_line()}  {color(f'{'Starting Ollama service':<34}', BOLD)} "
                f"{color('[' + '=' * 18 + ']', GREEN)} "
                f"{color('done', BOLD + GREEN)} "
                f"{color(f'({time.monotonic() - started:.1f}s)', MUTED)}"
                + " " * 8
            )
            return True
    print()
    raise RuntimeError("Ollama is installed but its service did not start.")


def ensure_ollama_models(check_only: bool) -> bool:
    result = run(["ollama", "list"], check=True, capture=True)
    installed = result.stdout.lower()
    ok = True
    for model in OLLAMA_MODELS:
        if model.lower() in installed:
            status("ready", f"Ollama model {model}")
            continue
        ok = False
        if check_only:
            status("missing", f"Ollama model {model}")
        else:
            status("install", f"Ollama model {model}")
            run(["ollama", "pull", model], activity=f"Downloading {model}")
            ok = True
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    boot_animation()
    checks = []
    total_stages = 5
    try:
        stage(1, total_stages, "Python runtime")
        checks.append(ensure_python_packages(args.check_only))
        stage(2, total_stages, "External media tools")
        for command, package_id in WINDOWS_PACKAGES.items():
            checks.append(install_windows_package(command, package_id, args.check_only))
        stage(3, total_stages, "Browser capture")
        checks.append(ensure_chrome(args.check_only))
        stage(4, total_stages, "Ollama service")
        if command_available("ollama"):
            checks.append(ensure_ollama_running(args.check_only))
            if checks[-1]:
                stage(5, total_stages, "Local AI models")
                checks.append(ensure_ollama_models(args.check_only))
        else:
            stage(5, total_stages, "Local AI models (waiting for next boot)")
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"[error] Startup dependency check failed: {exc}", file=sys.stderr)
        return 1

    summary = {"ready": sum(bool(value) for value in checks), "total": len(checks)}
    print(f"Startup dependency check: {json.dumps(summary)}")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
