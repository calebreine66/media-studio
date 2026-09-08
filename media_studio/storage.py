from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from media_studio.models import Job, MediaError, Options


DEFAULTS = {
    "output_directory": "",
    "ask_directory": False,
    "open_completed": False,
    "collision": "ask",
    "remember": True,
    "history": True,
    "theme": "light",
    "ffmpeg": "",
    "ffprobe": "",
    "jobs": 1,
    "threads": 0,
}


def config_directory() -> Path:
    if override := os.environ.get("MEDIA_STUDIO_DATA_DIR"):
        return Path(override)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Media Studio"
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", str(Path.home()))) / "Media Studio"
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "media-studio"


class Store:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or config_directory()
        self.warning = ""
        self.settings = {**DEFAULTS, **self._read("settings.json", {})}
        # Reject malformed preferences before they reach widgets or subprocesses.
        for key, default in DEFAULTS.items():
            if type(self.settings.get(key)) is not type(default):
                self.settings[key] = default
        if self.settings["collision"] not in {"ask", "rename", "replace"}:
            self.settings["collision"] = "ask"
        self.settings["jobs"] = max(1, min(4, self.settings["jobs"]))
        self.settings["threads"] = max(0, min(128, self.settings["threads"]))
        if not isinstance(self.settings.get("last_options", {}), dict):
            self.settings["last_options"] = {}
        self.history = [
            item
            for item in self._read("history.json", [])
            if isinstance(item, dict)
            and all(isinstance(item.get(k), str) for k in ("date", "input", "output", "status", "operation"))
            and all(
                type(item.get(k)) in (int, float) and item[k] >= 0
                for k in ("original_size", "output_size", "elapsed")
            )
        ]
        self.presets = self._read("presets.json", {})

    def _read(self, name: str, fallback):
        path = self.directory / name
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, type(fallback)):
                raise ValueError("Unexpected document type")
            return value
        except FileNotFoundError:
            return fallback
        except (OSError, ValueError) as exc:
            self.warning = f"Could not load {name}; defaults are in use. {exc}"
            return fallback

    def write(self, name: str, value) -> None:
        temporary = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".save-", dir=self.directory)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / name)
        except OSError as exc:
            raise MediaError(
                "Preferences could not be saved. Check the application data folder permissions.", str(exc)
            ) from exc
        finally:
            if temporary and Path(temporary).exists():
                Path(temporary).unlink(missing_ok=True)

    def save_settings(self) -> None:
        self.write("settings.json", self.settings)

    def record(self, job: Job) -> None:
        if not self.settings["history"]:
            return
        self.history.insert(
            0,
            {
                "id": job.id,
                "date": datetime.now(timezone.utc).isoformat(),
                "operation": job.options.operation,
                "input": str(job.source.path),
                "output": str(job.output),
                "input_format": job.source.container,
                "output_format": job.options.format,
                "original_size": job.source.size,
                "output_size": job.output_size,
                "status": job.status,
                "elapsed": job.elapsed,
            },
        )
        self.history = self.history[:500]
        self.write("history.json", self.history)

    def save_preset(self, name: str, options: Options) -> None:
        self.presets[name] = options.to_dict()
        self.write("presets.json", self.presets)
