import pytest
from PySide6.QtCore import Qt

from media_studio.gui.editor import AdvancedEditor, change_encoder
from media_studio.gui.main_window import MainWindow
from media_studio.gui.theme import apply_theme
from media_studio.models import Options
from media_studio.presets import recommended
from media_studio.storage import Store


def test_preferences_presets_and_privacy(tmp_path):
    store = Store(tmp_path)
    store.settings["history"] = False
    store.settings["theme"] = "dark"
    store.save_settings()
    store.save_preset("My settings", Options(format="mkv"))
    restored = Store(tmp_path)
    assert restored.settings["history"] is False
    assert restored.settings["theme"] == "dark"
    assert restored.presets["My settings"]["format"] == "mkv"
    (tmp_path / "settings.json").write_text("corrupt")
    assert Store(tmp_path).warning


@pytest.mark.integration
def test_editor_is_encoder_aware(qtbot, caps):
    png = AdvancedEditor(caps, recommended(caps, "image", "compress", "png"))
    qtbot.addWidget(png)
    assert (
        "compression_level" in png.controls
        and "audio_bitrate" not in png.controls
        and "quality" not in png.controls
    )
    jpeg = AdvancedEditor(caps, recommended(caps, "image", "compress", "jpg"))
    qtbot.addWidget(jpeg)
    assert (
        "quality" in jpeg.controls
        and "lossless" not in jpeg.controls
        and "compression_level" not in jpeg.controls
    )
    flac = AdvancedEditor(caps, recommended(caps, "audio", "compress", "flac"))
    qtbot.addWidget(flac)
    assert "compression_level" in flac.controls and "audio_bitrate" not in flac.controls
    copied = AdvancedEditor(caps, change_encoder(caps, recommended(caps, "video", "convert", "mp4"), "copy"))
    qtbot.addWidget(copied)
    assert "resize" not in copied.controls and "quality" not in copied.controls


@pytest.mark.integration
def test_gui_real_conversion_and_history(qtbot, qapp, caps, media, tmp_path, no_dialogs):
    store = Store(tmp_path / "data")
    apply_theme(qapp, "light")
    window = MainWindow(store, auto_detect=False)
    qtbot.addWidget(window)
    window.caps = caps
    window.workbench.set_capabilities(caps)
    window.show()
    window.open_workflow("compress", "image")
    window.workbench.add_sources([media["image"]])
    window.workbench.directory.setText(str(tmp_path))
    window.workbench.format.setCurrentIndex(window.workbench.format.findData("png"))
    qtbot.mouseClick(window.workbench.start, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: bool(window.queue_page.jobs), timeout=10000)
    qtbot.waitUntil(lambda: window.queue_page.jobs[0].status in {"Completed", "Failed"}, timeout=20000)
    qtbot.waitUntil(lambda: not window.tasks, timeout=10000)
    job = window.queue_page.jobs[0]
    assert job.status == "Completed", job.log
    assert store.history[0]["status"] == "Completed"
    assert not no_dialogs
    window.navigate("history")
    assert window.history_table.rowCount() == 1
    window.close()


@pytest.mark.integration
def test_mode_switch_command_preview_and_presets(qtbot, caps, media, tmp_path, no_dialogs):
    window = MainWindow(Store(tmp_path), auto_detect=False)
    qtbot.addWidget(window)
    window.caps = caps
    w = window.workbench
    w.set_capabilities(caps)
    window.open_workflow("convert", "video")
    w.add_sources([media["video"]])
    w.mode.setCurrentIndex(1)
    quality = w.editor.controls["quality"]
    quality.setValue(19)
    assert "-crf 19" in w.preview.toPlainText()
    w.editor.controls["encoder"].setCurrentIndex(w.editor.controls["encoder"].findData("copy"))
    assert w.options().encoder == "copy"
    assert "-c:v copy" in w.preview.toPlainText()
    assert "resize" not in w.editor.controls
    w.mode.setCurrentIndex(0)
    assert w.options().encoder == "libx264"
    assert not no_dialogs
    window.close()


@pytest.mark.integration
def test_all_editor_defaults_build_commands(qtbot, caps, media, tmp_path):
    from media_studio.core.commands import build_plan

    for kind in ("image", "video", "audio"):
        for fmt in caps.formats(kind):
            o = recommended(caps, kind, "convert", fmt.key)
            editor = AdvancedEditor(caps, o)
            qtbot.addWidget(editor)
            build_plan(media[kind], tmp_path / ("out." + fmt.key), editor.values(), caps)


@pytest.mark.integration
def test_batch_reservations_concurrency_and_disabled_history(qtbot, caps, media, tmp_path, no_dialogs):
    import shutil
    from media_studio.core.probe import probe

    files = []
    for folder in ("first", "second"):
        path = tmp_path / folder / "same.png"
        path.parent.mkdir()
        shutil.copyfile(media["image"].path, path)
        files.append(probe(path, caps.ffprobe))
    store = Store(tmp_path / "data")
    store.settings.update(jobs=2, history=False)
    window = MainWindow(store, auto_detect=False)
    qtbot.addWidget(window)
    window.caps = caps
    window.workbench.set_capabilities(caps)
    window.open_workflow("convert", "image")
    window.workbench.add_sources(files)
    window.workbench.directory.setText(str(tmp_path / "outputs"))
    window.enqueue(False)
    qtbot.waitUntil(lambda: len(window.queue_page.jobs) == 2, timeout=10000)
    outputs = {job.output.name for job in window.queue_page.jobs}
    assert outputs == {"same.png", "same_2.png"}
    window.queue_page.table.selectRow(1)
    moved = window.queue_page.jobs[1]
    window.move_job(-1)
    assert window.queue_page.jobs[0] is moved
    window.start_queue()
    qtbot.waitUntil(
        lambda: all(j.status in {"Completed", "Failed"} for j in window.queue_page.jobs), timeout=20000
    )
    qtbot.waitUntil(lambda: not window.tasks, timeout=10000)
    assert all(j.status == "Completed" for j in window.queue_page.jobs)
    assert store.history == []
    assert not (store.directory / "history.json").exists()
    assert not no_dialogs
    window.close()


def test_missing_tools_are_reported_without_crashing(qtbot, tmp_path, no_dialogs):
    store = Store(tmp_path)
    store.settings.update(ffmpeg=str(tmp_path / "missing-ffmpeg"), ffprobe=str(tmp_path / "missing-ffprobe"))
    window = MainWindow(store, auto_detect=False)
    qtbot.addWidget(window)
    window.refresh_capabilities()
    qtbot.waitUntil(lambda: bool(no_dialogs), timeout=10000)
    qtbot.waitUntil(lambda: not window.tasks, timeout=10000)
    assert "could not start" in str(no_dialogs[0])
    assert not window.workbench.start.isEnabled()
    assert "unavailable" in window.engine_status.text()
    window.close()
