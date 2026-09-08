from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from media_studio.core.commands import build_plan
from media_studio.core.validation import suggested_output
from media_studio.gui.editor import AdvancedEditor, change_encoder
from media_studio.gui.widgets import DropZone, button, label, panel
from media_studio.models import MediaError, MediaInfo, Options, human_size, human_time
from media_studio.presets import builtins, quality_description, recommended


class Workbench(QWidget):
    files_requested = Signal(list)
    jobs_requested = Signal(bool)
    error = Signal(object)

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.caps = None
        self.operation, self.kind = "convert", "video"
        self.sources: dict[str, list[MediaInfo]] = {"video": [], "image": [], "audio": []}
        self.editor = None
        self.loading = False
        self.preset_options = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 28, 30, 24)
        root.setSpacing(16)
        self.eyebrow = label("YOUR MEDIA, REIMAGINED", "eyebrow")
        root.addWidget(self.eyebrow)
        header = QHBoxLayout()
        self.title = label("Convert video", "title")
        header.addWidget(self.title)
        header.addStretch()
        self.mode = QComboBox()
        self.mode.addItem("Simple mode", "simple")
        self.mode.addItem("Advanced mode", "advanced")
        self.mode.setAccessibleName("Processing mode")
        self.mode.currentIndexChanged.connect(self._mode_changed)
        header.addWidget(self.mode)
        root.addLayout(header)
        self.subtitle = label("A new format. The same possibilities.", "muted")
        root.addWidget(self.subtitle)
        types = QHBoxLayout()
        self.type_group = QButtonGroup(self)
        self.type_buttons = {}
        for kind in ("video", "image", "audio"):
            btn = button(
                kind.title(), lambda checked=False, k=kind: self.configure(self.operation, k), glyph=kind
            )
            btn.setCheckable(True)
            btn.setObjectName("segment")
            self.type_group.addButton(btn)
            self.type_buttons[kind] = btn
            types.addWidget(btn)
        types.addStretch()
        root.addLayout(types)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)
        source_panel, source_layout = panel("01  Source files")
        source_panel.setMinimumWidth(260)
        self.drop = DropZone()
        self.drop.browse.connect(self.browse)
        self.drop.files.connect(self.files_requested)
        self.drop.setMinimumHeight(170)
        source_layout.addWidget(self.drop)
        self.add_more = button("Add more files", self.browse, glyph="plus")
        source_layout.addWidget(self.add_more)
        path_row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText("Or paste a local file path…")
        self.path.setAccessibleName("Source file path")
        self.path.returnPressed.connect(self.add_path)
        path_row.addWidget(self.path)
        path_row.addWidget(button("Add", self.add_path))
        source_layout.addLayout(path_row)
        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(100)
        self.file_list.setMaximumHeight(180)
        self.file_list.currentRowChanged.connect(self._source_changed)
        source_layout.addWidget(self.file_list)
        row = QHBoxLayout()
        self.file_count = label("No files added", "muted")
        row.addWidget(self.file_count)
        row.addStretch()
        row.addWidget(button("Remove", self.remove_source))
        source_layout.addLayout(row)
        self.source_info = label("Add a file to see its actual media properties.", "muted", True)
        self.source_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.source_info)
        source_layout.addWidget(scroll, 1)
        splitter.addWidget(source_panel)
        output_panel, output_layout = panel("02  Output settings")
        output_panel.setMinimumWidth(390)
        output_scroll = QScrollArea()
        output_scroll.setWidgetResizable(True)
        output_body = QWidget()
        out = QVBoxLayout(output_body)
        out.setContentsMargins(0, 0, 8, 0)
        out.setSpacing(14)
        output_scroll.setWidget(output_body)
        output_layout.addWidget(output_scroll, 1)
        self.format = QComboBox()
        self.format.setAccessibleName("Output format")
        self.format.currentIndexChanged.connect(self._format_changed)
        row = QHBoxLayout()
        row.addWidget(label("Format"))
        row.addWidget(self.format, 1)
        out.addLayout(row)
        self.quality = QComboBox()
        for name, value in [
            ("High quality", "high"),
            ("Balanced · recommended", "balanced"),
            ("Smaller file", "small"),
            ("Maximum compression", "smallest"),
        ]:
            self.quality.addItem(name, value)
        self.quality.setCurrentIndex(1)
        self.quality.setAccessibleName("Quality preset")
        self.quality.currentIndexChanged.connect(self._simple_quality_changed)
        self.simple_box = QWidget()
        simple = QVBoxLayout(self.simple_box)
        simple.setContentsMargins(0, 0, 0, 0)
        simple.addWidget(label("Quality preference", "muted"))
        simple.addWidget(self.quality)
        simple.addWidget(
            label(
                "Choose a format and a quality preference. We’ll handle the encoding settings.", "muted", True
            )
        )
        out.addWidget(self.simple_box)
        self.presets_row = QWidget()
        row = QHBoxLayout(self.presets_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.preset = QComboBox()
        self.preset.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.preset.setMinimumContentsLength(8)
        self.preset.setAccessibleName("Saved preset")
        self.preset.activated.connect(self.apply_preset)
        row.addWidget(self.preset, 1)
        row.addWidget(button("Save preset", self.save_preset))
        row.addWidget(button("Reset", self.reset, glyph="history"))
        out.addWidget(self.presets_row)
        self.editor_host = QWidget()
        self.editor_layout = QVBoxLayout(self.editor_host)
        self.editor_layout.setContentsMargins(0, 0, 0, 0)
        out.addWidget(self.editor_host, 1)
        self.implications = label("", "muted", True)
        out.addWidget(self.implications)
        self.image_note = label(
            "Image workflows export a single still frame. Animated GIF/WebP inputs use their first frame.",
            "muted",
            True,
        )
        out.addWidget(self.image_note)
        destination = QHBoxLayout()
        self.directory = QLineEdit(self.store.settings["output_directory"])
        self.directory.setPlaceholderText("Source folder (default)")
        self.directory.setAccessibleName("Output directory")
        self.directory.textChanged.connect(self.update_preview)
        destination.addWidget(self.directory, 1)
        destination.addWidget(button("Browse", self.browse_directory, glyph="folder"))
        out.addWidget(label("Save to", "muted"))
        out.addLayout(destination)
        self.filename = QLineEdit()
        self.filename.setPlaceholderText("Automatic filename")
        self.filename.setAccessibleName("Output filename")
        self.filename.textChanged.connect(self.update_preview)
        out.addWidget(self.filename)
        self.output_summary = label("", "muted", True)
        out.addWidget(self.output_summary)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(105)
        self.preview.setPlaceholderText("Add a source to preview the generated FFmpeg command.")
        self.preview.setAccessibleName("FFmpeg command preview")
        out.addWidget(self.preview)
        buttons = QHBoxLayout()
        self.add_queue = button("Add to queue", lambda: self.jobs_requested.emit(False), glyph="queue")
        self.start = button(
            "Convert files", lambda: self.jobs_requested.emit(True), primary=True, glyph="convert"
        )
        buttons.addWidget(self.add_queue)
        buttons.addWidget(self.start, 1)
        output_layout.addLayout(buttons)
        splitter.addWidget(output_panel)
        splitter.setSizes([340, 600])
        self._mode_changed()
        self.configure("convert", "video")

    @property
    def advanced(self):
        return self.mode.currentData() == "advanced"

    @property
    def current_sources(self):
        return self.sources[self.kind]

    def set_capabilities(self, caps):
        self.caps = caps
        self.configure(self.operation, self.kind)

    def configure(self, operation, kind):
        self.operation, self.kind = operation, kind
        self.title.setText(f"{operation.title()} {kind}")
        self.subtitle.setText(
            "A new format. The same possibilities."
            if operation == "convert"
            else "Find your balance between file size and quality."
        )
        self.type_buttons[kind].setChecked(True)
        self.start.setText(f"{operation.title()} files")
        self.image_note.setVisible(kind == "image")
        self._refresh_sources()
        if not self.caps:
            self.start.setEnabled(False)
            self.add_queue.setEnabled(False)
            return
        self.loading = True
        self.format.clear()
        for fmt in self.caps.formats(kind):
            self.format.addItem(fmt.label, fmt.key)
        try:
            options = recommended(self.caps, kind, operation)
            remembered = (
                self.store.settings.get("last_options", {}).get(f"{operation}:{kind}", {})
                if self.store.settings["remember"]
                else {}
            )
            if isinstance(remembered, dict) and remembered:
                candidate = Options.from_dict(remembered)
                if candidate.kind == kind and candidate.operation == operation:
                    fmt = self.caps.format(kind, candidate.format)
                    if (
                        candidate.encoder == "copy"
                        or candidate.encoder in fmt.encoders
                        and candidate.encoder in self.caps.encoders
                    ):
                        options = candidate
            self.format.setCurrentIndex(self.format.findData(options.format))
            self._set_editor(options)
            self.refresh_presets()
        except MediaError as exc:
            self.error.emit(exc)
        finally:
            self.loading = False
        self.update_preview()

    def _refresh_sources(self):
        previous = self.file_list.currentRow()
        self.file_list.clear()
        for source in self.current_sources:
            item = QListWidgetItem(
                f"{source.path.name}\n{source.kind.title()} · {human_size(source.size)} · {source.container.split(',')[0].upper()}"
            )
            item.setToolTip(str(source.path))
            self.file_list.addItem(item)
        self.file_list.setCurrentRow(min(max(0, previous), len(self.current_sources) - 1))
        count = len(self.current_sources)
        self.drop.setVisible(count == 0)
        self.add_more.setVisible(count > 0)
        self.file_count.setText(
            f"{count} file{'s' if count != 1 else ''} · {human_size(sum(s.size for s in self.current_sources))}"
            if count
            else "No files added"
        )
        self.filename.setEnabled(count <= 1) if hasattr(self, "filename") else None
        self._source_changed()

    def add_sources(self, sources):
        for source in sources:
            target = self.sources[source.kind]
            if all(s.path != source.path for s in target):
                target.append(source)
        if sources and not self.current_sources:
            self.configure(self.operation, sources[0].kind)
        self._refresh_sources()
        if self.operation == "compress" and sources and not self.advanced:
            aliases = {"jpeg": "jpg", "mjpeg": "jpg", "tif": "tiff"}
            source = sources[0]
            desired = (
                aliases.get(source.video.get("codec_name", ""), source.video.get("codec_name", ""))
                if source.kind == "image"
                else source.path.suffix[1:].lower()
            )
            if self.format.findData(desired) >= 0:
                self.format.setCurrentIndex(self.format.findData(desired))
        self.update_preview()

    def browse(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add media files", "", "Media files (*)")
        if paths:
            self.files_requested.emit(paths)

    def add_path(self):
        text = self.path.text().strip().strip('"')
        if text:
            self.files_requested.emit([text])
            self.path.clear()

    def remove_source(self):
        row = self.file_list.currentRow()
        if 0 <= row < len(self.current_sources):
            del self.current_sources[row]
            self._refresh_sources()
            self.update_preview()

    def browse_directory(self):
        path = QFileDialog.getExistingDirectory(self, "Choose output folder", self.directory.text())
        if path:
            self.directory.setText(path)

    def _source_changed(self, *_):
        row = self.file_list.currentRow()
        if not 0 <= row < len(self.current_sources):
            self.source_info.setText("Add a file to see its actual media properties.")
        else:
            s = self.current_sources[row]
            details = [f"SOURCE  ·  {s.container}", "", s.path.name, human_size(s.size)]
            if s.duration:
                details.append(f"Duration  {human_time(s.duration)}")
            if s.video:
                v = s.video
                details += [
                    f"Dimensions  {v.get('width', '?')} × {v.get('height', '?')}",
                    f"Video / image  {v.get('codec_name', '?')}",
                    f"Pixel format  {v.get('pix_fmt', 'unknown')}",
                ]
                try:
                    fps = float(Fraction(v.get("avg_frame_rate", "0/1")))
                    if s.kind == "video":
                        details.append(f"Frame rate  {fps:.3f} fps")
                except (ValueError, ZeroDivisionError):
                    pass
                if v.get("bit_rate"):
                    details.append(f"Video bitrate  {int(v['bit_rate']) // 1000:,} kbps")
                for key in ["color_space", "color_range", "color_primaries", "color_transfer"]:
                    if v.get(key):
                        details.append(f"{key.replace('_', ' ').title()}  {v[key]}")
            if s.audio:
                a = s.audio
                details += [
                    "",
                    f"Audio  {a.get('codec_name', '?')}",
                    f"Sample rate  {a.get('sample_rate', '?')} Hz",
                    f"Channels  {a.get('channels', '?')} · {a.get('channel_layout', 'unspecified')}",
                ]
                if a.get("bit_rate"):
                    details.append(f"Audio bitrate  {int(a['bit_rate']) // 1000:,} kbps")
            if s.subtitles:
                details.append(f"Subtitle tracks  {len(s.subtitles)}")
            self.source_info.setText("\n".join(details))
        if hasattr(self, "preview"):
            self.update_preview()

    def _set_editor(self, o):
        if self.editor:
            self.editor_layout.removeWidget(self.editor)
            self.editor.deleteLater()
        self.editor = AdvancedEditor(self.caps, o)
        self.editor.changed.connect(self.update_preview)
        self.editor.encoder_changed.connect(self._encoder_changed)
        self.editor.audio_changed.connect(self._audio_changed)
        self.editor_layout.addWidget(self.editor)

    def _encoder_changed(self, encoder):
        if self.loading:
            return
        o = change_encoder(self.caps, self.editor.values(), encoder)
        self._set_editor(o)
        self.update_preview()

    def _audio_changed(self, encoder):
        if self.loading:
            return
        o = replace(
            self.editor.values(),
            audio_encoder=encoder,
            sample_format="",
            sample_rate=0,
            audio_rate_control="bitrate",
            audio_quality=4,
        )
        tab = self.editor.tabs.currentIndex()
        self._set_editor(o)
        self.editor.tabs.setCurrentIndex(tab)
        self.update_preview()

    def _format_changed(self, *_):
        if self.loading or not self.caps or not self.format.currentData():
            return
        self._set_editor(
            recommended(
                self.caps, self.kind, self.operation, self.format.currentData(), self.quality.currentData()
            )
        )
        self.update_preview()

    def _simple_quality_changed(self, *_):
        if not self.advanced:
            self._format_changed()

    def _mode_changed(self, *_):
        self.simple_box.setVisible(not self.advanced)
        self.editor_host.setVisible(self.advanced)
        self.editor_host.setMinimumHeight(350 if self.advanced else 0)
        self.presets_row.setVisible(self.advanced)
        self.preview.setVisible(self.advanced)
        self.update_preview()

    def options(self):
        if not self.caps:
            raise MediaError("FFmpeg is not ready. Open Settings to configure the media tools.")
        o = (
            self.editor.values()
            if self.advanced and self.editor
            else recommended(
                self.caps, self.kind, self.operation, self.format.currentData(), self.quality.currentData()
            )
        )
        if not self.advanced:
            o.threads = self.store.settings["threads"]
        return o

    def output_for(self, source, o):
        directory = (
            Path(self.directory.text().strip()).expanduser()
            if self.directory.text().strip()
            else source.path.parent
        )
        return suggested_output(
            source, directory, o, self.filename.text().strip() if len(self.current_sources) == 1 else ""
        )

    def update_preview(self, *_):
        if self.loading or not hasattr(self, "preview"):
            return
        available = bool(self.caps and self.current_sources)
        self.start.setEnabled(available)
        self.add_queue.setEnabled(available)
        try:
            o = self.options()
            self.implications.setText(quality_description(o))
            if not self.current_sources:
                self.preview.clear()
                self.output_summary.setText("Files are processed locally on your computer.")
                return
            s = self.current_sources[max(0, self.file_list.currentRow())]
            output = self.output_for(s, o)
            summary = f"OUTPUT  ·  {output.name}"
            if o.kind != "audio":
                summary += f"\n{o.encoder} · {o.resize.replace('_', ' ')} resolution"
            else:
                summary += (
                    f"\n{o.encoder} · {o.audio_bitrate} kbps"
                    if o.encoder not in {"flac", "alac", "copy"} and not o.encoder.startswith("pcm_")
                    else f"\n{o.encoder}"
                )
            if len(self.current_sources) > 1:
                summary += f"\nThe same settings apply to all {len(self.current_sources)} files. Filenames are generated individually."
            self.output_summary.setText(summary)
            self.preview.setPlainText(build_plan(s, output, o, self.caps).preview)
        except MediaError as exc:
            self.preview.setPlainText("Check settings: " + str(exc))
            self.output_summary.setText(str(exc))
        except Exception as exc:
            self.preview.setPlainText("Settings preview unavailable: " + str(exc))

    def refresh_presets(self):
        self.preset_options = builtins(self.caps, self.kind, self.operation)
        for name, data in self.store.presets.items():
            if isinstance(data, dict) and data.get("kind") == self.kind:
                self.preset_options["Custom · " + name] = replace(
                    Options.from_dict(data), operation=self.operation
                )
        self.preset.clear()
        self.preset.addItem("Choose a preset…", "")
        for name in self.preset_options:
            self.preset.addItem(name, name)

    def apply_preset(self, *_):
        key = self.preset.currentData()
        if key not in self.preset_options:
            return
        o = self.preset_options[key]
        try:
            self.caps.format(o.kind, o.format)
            if o.encoder != "copy" and o.encoder not in self.caps.encoders:
                raise MediaError("This preset requires an encoder that is not installed.")
            self.loading = True
            self.format.setCurrentIndex(self.format.findData(o.format))
            self._set_editor(o)
        except MediaError as exc:
            self.error.emit(exc)
        finally:
            self.loading = False
        self.update_preview()

    def save_preset(self):
        name, ok = QInputDialog.getText(self, "Save custom preset", "Preset name")
        if ok and name.strip():
            try:
                self.store.save_preset(name.strip(), self.options())
                self.refresh_presets()
            except MediaError as exc:
                self.error.emit(exc)

    def reset(self):
        self._format_changed()
