"""Process cleanup helpers for TrendForge worker runs."""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import Callable, Iterable


LogFn = Callable[[str], None]


def stop_existing_trendforge_workers(
    root: Path | str | None = None,
    log: LogFn | None = None,
) -> list[dict[str, str]]:
    """Stop stale TrendForge worker processes before starting a new run.

    This targets pipeline workers and their obvious helper processes only. It
    deliberately avoids stopping the UI/server process so the caller can launch
    a replacement worker immediately.
    """
    project_root = Path(root or Path(__file__).resolve().parent.parent).resolve()
    if os.name == "nt":
        return _stop_windows_workers(project_root, log)
    return _stop_posix_workers(project_root, log)


def _stop_windows_workers(root: Path, log: LogFn | None) -> list[dict[str, str]]:
    root_text = str(root)
    escaped_root = root_text.replace("'", "''")
    current_pid = os.getpid()
    script = f"""
$Root = '{escaped_root}'
$RootPattern = [regex]::Escape($Root)
$CurrentPid = {current_pid}
$CurrentProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$CurrentPid"
$ParentPid = if ($CurrentProcess) {{ $CurrentProcess.ParentProcessId }} else {{ -1 }}
$Names = @('python.exe','pythonw.exe','ffmpeg.exe','chromedriver.exe','chrome.exe')
$Targets = Get-CimInstance Win32_Process | Where-Object {{
    $_.ProcessId -ne $CurrentPid -and
    $_.ProcessId -ne $ParentPid -and
    $_.Name -in $Names -and
    $_.CommandLine -match $RootPattern -and
    (
        (($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -match '(?i)main\\.py') -or
        ($_.Name -eq 'ffmpeg.exe') -or
        ($_.Name -eq 'chromedriver.exe') -or
        ($_.Name -eq 'chrome.exe' -and $_.CommandLine -match '(?i)temp[\\\\/]chrome_profiles')
    )
}}
foreach ($p in $Targets) {{
    $cmd = ($p.CommandLine -replace '\\r?\\n', ' ')
    try {{
        Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
        "STOPPED|$($p.ProcessId)|$($p.Name)|$cmd"
    }} catch {{
        "FAILED|$($p.ProcessId)|$($p.Name)|$($_.Exception.Message)"
    }}
}}
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    stopped = _parse_cleanup_output(result.stdout.splitlines(), log)
    if result.returncode != 0 and log:
        message = (result.stderr or result.stdout or "unknown error").strip().splitlines()
        log(f"TrendForge process cleanup skipped: {message[0] if message else 'unknown error'}")
    return stopped


def _stop_posix_workers(root: Path, log: LogFn | None) -> list[dict[str, str]]:
    result = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,comm=,args="],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        if log:
            log("TrendForge process cleanup skipped: process listing failed")
        return []

    current_pid = os.getpid()
    parent_pid = os.getppid()
    root_text = str(root)
    stopped: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        pid_text, ppid_text, name, command = parts
        try:
            pid = int(pid_text)
            ppid = int(ppid_text)
        except ValueError:
            continue
        if pid in {current_pid, parent_pid} or root_text not in command:
            continue
        if not _is_posix_trendforge_worker(name, command):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            stopped.append({"pid": str(pid), "name": name, "command": command})
            if log:
                log(f"Stopped stale TrendForge process PID {pid} ({name})")
        except OSError as exc:
            if log:
                log(f"Failed to stop stale TrendForge process PID {pid}: {exc}")
    return stopped


def _is_posix_trendforge_worker(name: str, command: str) -> bool:
    lower_name = Path(name).name.lower()
    lower_command = command.lower()
    if lower_name.startswith("python") and "main.py" in lower_command:
        return True
    if lower_name == "ffmpeg":
        return True
    if lower_name in {"chromedriver", "chrome", "chromium"} and "temp/chrome_profiles" in lower_command:
        return True
    return False


def _parse_cleanup_output(lines: Iterable[str], log: LogFn | None) -> list[dict[str, str]]:
    stopped: list[dict[str, str]] = []
    for line in lines:
        status, *parts = line.split("|", 3)
        if status == "STOPPED" and len(parts) == 3:
            pid, name, command = parts
            stopped.append({"pid": pid, "name": name, "command": command})
            if log:
                log(f"Stopped stale TrendForge process PID {pid} ({name})")
        elif status == "FAILED" and len(parts) >= 3 and log:
            pid, name, reason = parts[:3]
            log(f"Failed to stop stale TrendForge process PID {pid} ({name}): {reason}")
    return stopped
