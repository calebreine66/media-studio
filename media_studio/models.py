from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class MediaInfo:
    path: Path
    kind: str
    container: str
    size: int
    duration: float
    streams: tuple[dict, ...]
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def video(self) -> dict:
        return next(
            (
                s
                for s in self.streams
                if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
            ),
            {},
        )

    @property
    def audio(self) -> dict:
        return next((s for s in self.streams if s.get("codec_type") == "audio"), {})

    @property
    def subtitles(self) -> tuple[dict, ...]:
        return tuple(s for s in self.streams if s.get("codec_type") == "subtitle")


@dataclass
class Options:
    kind: str = "video"
    operation: str = "convert"
    format: str = "mp4"
    encoder: str = "libx264"
    quality: int = 23
    lossless: bool = False
    compression_level: int = 6
    preset: str = "medium"
    rate_control: str = "quality"
    bitrate: int = 2500
    max_bitrate: int = 0
    buffer_size: int = 0
    two_pass: bool = False
    target_mb: float = 0
    resize: str = "original"
    width: int = 1920
    height: int = 1080
    scale_percent: int = 100
    keep_aspect: bool = True
    scaler: str = "lanczos"
    fps: str = ""
    pixel_format: str = ""
    profile: str = ""
    level: str = ""
    gop: int = 0
    b_frames: int = -1
    alpha: str = "preserve"
    background: str = "#ffffff"
    color_space: str = ""
    color_range: str = ""
    color_primaries: str = ""
    color_transfer: str = ""
    rotate: str = "none"
    flip: str = "none"
    deinterlace: bool = False
    denoise: bool = False
    sharpen: bool = False
    grayscale: bool = False
    crop: str = ""
    audio_mode: str = "convert"
    audio_encoder: str = "aac"
    audio_bitrate: int = 192
    audio_rate_control: str = "bitrate"
    audio_quality: int = 4
    sample_rate: int = 0
    channels: int = 0
    sample_format: str = ""
    volume_db: float = 0
    normalize: bool = False
    metadata: str = "preserve"
    tags: dict[str, str] = field(default_factory=dict)
    chapters: bool = True
    subtitles: str = "remove"
    attachments: bool = False
    cover: str = "remove"
    cover_path: str = ""
    expert: str = ""
    threads: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Options:
        defaults = cls()
        allowed = {f.name for f in fields(cls)}
        clean = {}
        for key, value in data.items():
            if key not in allowed:
                continue
            original = getattr(defaults, key)
            if isinstance(original, float) and type(value) in (int, float):
                clean[key] = float(value)
            elif type(value) is type(original):
                clean[key] = value
        return cls(**clean)


@dataclass
class Job:
    source: MediaInfo
    output: Path
    options: Options
    replace: bool = False
    id: str = field(default_factory=lambda: uuid4().hex)
    status: str = "Waiting"
    progress: float = 0
    output_size: int = 0
    elapsed: float = 0
    error: str = ""
    log: str = ""


@dataclass(frozen=True)
class Progress:
    percent: float
    elapsed: float
    timestamp: float
    speed: str
    remaining: float | None
    stage: str = "Encoding"


class MediaError(Exception):
    """An actionable error safe to display in the interface."""

    def __init__(self, message: str, details: str = ""):
        super().__init__(message)
        self.details = details


def human_size(size: int | float) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024 or unit == "TB":
            return f"{value:,.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return ""


def human_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"
