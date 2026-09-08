import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from media_studio.core.capabilities import detect
from media_studio.core.process import capture
from media_studio.core.probe import probe
from media_studio.models import MediaError


@pytest.fixture(scope="session")
def caps():
    try:
        return detect(os.environ.get("TEST_FFMPEG", ""), os.environ.get("TEST_FFPROBE", ""))
    except MediaError as exc:
        pytest.skip(f"Working FFmpeg/FFprobe required: {exc}; {exc.details}")


@pytest.fixture(scope="session")
def media(caps, tmp_path_factory):
    folder = tmp_path_factory.mktemp("media")
    args = [caps.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    capture(
        args
        + [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x96:rate=24:duration=1.5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=1.5",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-shortest",
            str(folder / "video.mp4"),
        ]
    )
    capture(
        args
        + [
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=128x96:duration=0.1",
            "-frames:v",
            "1",
            "-update",
            "1",
            str(folder / "image.png"),
        ]
    )
    capture(
        args
        + [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:sample_rate=44100:duration=1.5",
            "-c:a",
            "pcm_s16le",
            str(folder / "audio.wav"),
        ]
    )
    return {
        kind: probe(folder / filename, caps.ffprobe)
        for kind, filename in [("video", "video.mp4"), ("image", "image.png"), ("audio", "audio.wav")]
    }


@pytest.fixture
def no_dialogs(monkeypatch):
    from media_studio.gui.main_window import MainWindow

    errors = []
    monkeypatch.setattr(MainWindow, "show_error", lambda self, error: errors.append(error))
    return errors
