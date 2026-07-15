"""Durable stage checkpoints for interrupted TrendForge runs."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional


CHECKPOINT_VERSION = 1


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")


def _safe_name(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value[:48] or "untitled"


def files_exist(value: Any) -> bool:
    """Validate every path field in nested checkpoint data."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"path", "audio_path", "visual_path"} and item:
                if not Path(str(item)).exists():
                    return False
            if not files_exist(item):
                return False
    elif isinstance(value, list):
        return all(files_exist(item) for item in value)
    return True


class CheckpointStore:
    """Persist JSON stage results atomically under a stable run fingerprint."""

    def __init__(self, topic: str, config: Dict[str, Any], root: Path = Path("./temp/checkpoints")):
        fingerprint = hashlib.sha256(_json_bytes(config)).hexdigest()[:12]
        self.run_id = f"{_safe_name(topic)}-{fingerprint}"
        self.directory = root / self.run_id
        self.directory.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.directory / "manifest.json"
        self.manifest = self._read(self.manifest_path) or {
            "version": CHECKPOINT_VERSION,
            "topic": topic,
            "config_fingerprint": fingerprint,
            "stages": {},
        }

    @staticmethod
    def _read(path: Path) -> Optional[Any]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def _write_atomic(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False, default=str)
            handle.flush()
        temporary.replace(path)

    def save(self, stage: str, value: Any) -> None:
        value = self._snapshot_files(stage, value)
        stage_path = self.directory / f"{stage}.json"
        self._write_atomic(stage_path, value)
        self.manifest["stages"][stage] = {
            "file": stage_path.name,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_atomic(self.manifest_path, self.manifest)

    def _snapshot_files(self, stage: str, value: Any, key: str = "") -> Any:
        """Copy referenced assets into this run so shared temp names cannot overwrite them."""
        if isinstance(value, dict):
            return {name: self._snapshot_files(stage, item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [self._snapshot_files(stage, item, key) for item in value]
        if key in {"path", "audio_path", "visual_path"} and value:
            source = Path(str(value))
            if source.is_file():
                digest = hashlib.sha256(str(source.resolve()).encode("utf-8")).hexdigest()[:10]
                target = self.directory / "assets" / stage / f"{digest}_{source.name}"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                return str(target)
        return value

    def load(self, stage: str, validator: Optional[Callable[[Any], bool]] = None) -> Optional[Any]:
        entry = self.manifest.get("stages", {}).get(stage)
        if not entry:
            return None
        value = self._read(self.directory / entry.get("file", ""))
        if value is None or not files_exist(value):
            return None
        if validator is not None and not validator(value):
            return None
        return value
