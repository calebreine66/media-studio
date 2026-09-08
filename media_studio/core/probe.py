from __future__ import annotations

import json
import math
from pathlib import Path

from media_studio.core.process import capture
from media_studio.models import MediaError, MediaInfo


def number(value: object, default: float = 0) -> float:
    try:
        result = float(str(value))
        return result if math.isfinite(result) else default
    except (ValueError, TypeError):
        return default


def probe(path: Path, ffprobe: str) -> MediaInfo:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise MediaError("Select an existing local media file.")
    try:
        data = json.loads(
            capture(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file,pipe,crypto,data",
                    "-show_format",
                    "-show_streams",
                    "-of",
                    "json",
                    str(path),
                ],
                timeout=45,
            )
        )
    except MediaError as exc:
        raise MediaError(
            f"Could not read {path.name}. The media may be corrupt or unsupported.", exc.details
        ) from exc
    except (ValueError, OSError) as exc:
        raise MediaError("FFprobe returned invalid media information.", str(exc)) from exc
    streams = tuple(data.get("streams", []))
    container = data.get("format", {})
    name = container.get("format_name", "unknown")
    videos = [
        s
        for s in streams
        if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
    ]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if not videos and not audios:
        raise MediaError("This file does not contain a supported image, video, or audio stream.")
    duration = number(container.get("duration")) or max(
        (number(s.get("duration")) for s in streams), default=0
    )
    image_container = any(x in name for x in ("image2", "_pipe", "gif", "ico", "webp"))
    # AVIF is an ISO BMFF still image; inspect the actual major brand instead of the suffix.
    avif = str(container.get("tags", {}).get("major_brand", "")).strip() in ("avif", "avis")
    kind = "image" if videos and not audios and (image_container or avif) else "video" if videos else "audio"
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise MediaError("The source file is no longer accessible.", str(exc)) from exc
    return MediaInfo(path, kind, name, size, duration, streams, container.get("tags", {}))
