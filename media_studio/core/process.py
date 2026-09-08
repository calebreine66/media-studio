from __future__ import annotations

import os
import subprocess

from media_studio.models import MediaError


def process_kwargs() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def capture(args: list[str], timeout: float = 30) -> str:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **process_kwargs(),
        )
    except FileNotFoundError as exc:
        raise MediaError(
            "FFmpeg or FFprobe was not found. Choose its executable in Settings.", str(exc)
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError("Media inspection timed out. The file or executable may be unresponsive.") from exc
    except OSError as exc:
        raise MediaError(
            "The media executable could not be started. Check its path and permissions.", str(exc)
        ) from exc
    if result.returncode != 0:
        raise MediaError("The media tool could not complete this request.", result.stderr[-18000:])
    return result.stdout
