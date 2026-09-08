"""Capture README screenshots from real Qt widgets and actual FFmpeg results.

Run from an installed checkout with: python scripts/capture_screenshots.py
Only generated sample media and an isolated temporary preferences directory are used.
"""

from __future__ import annotations

import argparse
import os
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTabWidget

from media_studio.core.process import capture
from media_studio.gui.main_window import MainWindow
from media_studio.gui.settings import SettingsDialog
from media_studio.gui.theme import apply_theme
from media_studio.storage import Store


class DocumentationWindow(MainWindow):
    def show_error(self, error):
        # Surface failures to the capture script instead of leaving a modal dialog open.
        self.capture_errors.append(error)


def wait_for(window, condition, timeout=60):
    deadline = time.monotonic() + timeout
    while not condition():
        if window.capture_errors:
            error = window.capture_errors[0]
            raise RuntimeError(f"{error}\n{getattr(error, 'details', '')}")
        if time.monotonic() >= deadline:
            raise TimeoutError("Screenshot preparation did not finish in time.")
        QTest.qWait(25)
    QTest.qWait(100)


def select(combo, value):
    index = combo.findData(value)
    if index < 0:
        raise RuntimeError(f"Required screenshot option is unavailable: {value}")
    combo.setCurrentIndex(index)


def save(widget, directory, filename):
    widget.clearFocus()
    QTest.qWait(150)
    destination = directory / filename
    if not widget.grab().save(str(destination), "PNG"):
        raise RuntimeError(f"Could not save {destination}")
    print(f"Captured {filename} ({destination.stat().st_size:,} bytes)", flush=True)


def generate_samples(caps, directory):
    image = directory / "color-study.bmp"
    video = directory / "sample-reel.mov"
    audio = directory / "studio-tone.wav"
    base = [caps.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    capture(
        base
        + [
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=1600x1000:duration=0.04",
            "-frames:v",
            "1",
            "-update",
            "1",
            str(image),
        ]
    )
    capture(
        base
        + [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=30:duration=6",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=6",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "17",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(video),
        ]
    )
    capture(
        base
        + [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:sample_rate=48000:duration=6",
            "-c:a",
            "pcm_s24le",
            str(audio),
        ]
    )
    return image, video, audio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/screenshots"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setStyle("Fusion")
    app.setApplicationName("Media Studio")
    apply_theme(app, "light")
    # Prefer a short, anonymous path in screenshots; never use the user's actual media or preferences.
    temporary_root = "/tmp" if Path("/tmp").is_dir() else None
    with tempfile.TemporaryDirectory(prefix="media-studio-demo-", dir=temporary_root) as name:
        demo = Path(name)
        exports = demo / "exports"
        exports.mkdir()
        store = Store(demo / "preferences")
        store.settings["output_directory"] = str(exports)
        store.settings["collision"] = "rename"
        store.settings["jobs"] = 2
        store.settings["ffmpeg"] = os.environ.get("TEST_FFMPEG", "")
        store.settings["ffprobe"] = os.environ.get("TEST_FFPROBE", "")
        window = DocumentationWindow(store, auto_detect=False)
        window.capture_errors = []
        window.resize(1280, 960)
        window.show()
        try:
            window.refresh_capabilities()
            wait_for(window, lambda: window.caps is not None and not window.tasks)
            save(window, args.output, "01-overview.png")

            samples = generate_samples(window.caps, demo)
            window.open_workflow("convert", "image")
            window.analyze_files([str(path) for path in samples])
            wait_for(window, lambda: not window.tasks)
            workbench = window.workbench
            select(workbench.format, "jpg")
            workbench.filename.setText("color-study.jpg")
            save(window, args.output, "02-simple-conversion.png")
            window.enqueue(False)
            wait_for(window, lambda: len(window.queue_page.jobs) == 1 and not window.tasks)

            window.open_workflow("compress", "video")
            workbench.filename.clear()
            select(workbench.format, "mp4")
            select(workbench.mode, "advanced")
            workbench.editor.controls["quality"].setValue(24)
            save(window, args.output, "03-advanced-video.png")
            window.enqueue(False)
            wait_for(window, lambda: len(window.queue_page.jobs) == 2 and not window.tasks)

            window.open_workflow("compress", "audio")
            select(workbench.format, "flac")
            window.enqueue(False)
            wait_for(window, lambda: len(window.queue_page.jobs) == 3 and not window.tasks)
            window.start_queue()
            wait_for(window, lambda: not window.tasks and not window.active)
            for job in window.queue_page.jobs:
                if job.status != "Completed":
                    raise RuntimeError(f"Screenshot job failed: {job.error}\n{job.log}")
            window.queue_page.table.selectRow(1)
            save(window, args.output, "04-completed-queue.png")

            window.navigate("history")
            save(window, args.output, "05-history.png")
            settings = SettingsDialog(store.settings, window.caps, window)
            settings.findChild(QTabWidget).setCurrentIndex(2)
            settings.show()
            save(settings, args.output, "06-settings.png")
            settings.close()

            apply_theme(app, "dark")
            window.navigate("home")
            save(window, args.output, "07-dark-theme.png")
        finally:
            window._closing = True
            window.cancel_jobs(True)
            wait_for(window, lambda: not window.tasks and not window.active)
            window.close()
    print(f"Saved 7 screenshots to {args.output.resolve()}", flush=True)


if __name__ == "__main__":
    main()
