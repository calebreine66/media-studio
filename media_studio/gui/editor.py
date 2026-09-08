from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from media_studio.core.capabilities import Capabilities
from media_studio.gui.widgets import button, label
from media_studio.models import Options
from media_studio.presets import LOSSLESS, QUALITY_VIDEO, SWITCHABLE_LOSSLESS, TWO_PASS, recommended


class AdvancedEditor(QWidget):
    changed = Signal()
    encoder_changed = Signal(str)
    audio_changed = Signal(str)

    def __init__(self, caps: Capabilities, options: Options):
        super().__init__()
        self.caps, self.base = caps, options
        self.controls = {}
        self.rows = {}
        self.tags = {}
        self.loading = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs)
        self._build()
        self.loading = False
        self._visibility()

    def tab(self, name: str, description: str = "") -> QFormLayout:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(18, 18, 18, 18)
        if description:
            outer.addWidget(label(description, "muted", True))
        form = QFormLayout()
        form.setSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        outer.addLayout(form)
        outer.addStretch()
        scroll.setWidget(page)
        self.tabs.addTab(scroll, name)
        return form

    def field(self, form, key, title, choices=None, bounds=None, tooltip="", kind="", value=None):
        val = getattr(self.base, key) if value is None else value
        if choices is not None:
            control = QComboBox()
            control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            control.setMinimumContentsLength(8)
            control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            for item in choices:
                text, data = item if isinstance(item, tuple) else (str(item), item)
                control.addItem(text, data)
            idx = control.findData(val)
            control.setCurrentIndex(max(0, idx))
            control.currentIndexChanged.connect(self._changed)
        elif isinstance(val, bool):
            control = QCheckBox(title)
            control.setChecked(val)
            title = ""
            control.toggled.connect(self._changed)
        elif isinstance(val, (int, float)):
            control = QDoubleSpinBox() if isinstance(val, float) else QSpinBox()
            control.setRange(*(bounds or (0, 100)))
            control.setValue(val)
            control.valueChanged.connect(self._changed)
        elif kind == "multiline":
            control = QPlainTextEdit(val)
            control.setMaximumHeight(100)
            control.textChanged.connect(self._changed)
        else:
            control = QLineEdit(str(val))
            control.textChanged.connect(self._changed)
        if tooltip:
            control.setToolTip(tooltip)
        control.setAccessibleName(title or key.replace("_", " "))
        control.setObjectName("option_" + key)
        self.controls[key] = control
        caption = label(title + ("  ⓘ" if tooltip and title else ""))
        caption.setToolTip(tooltip)
        form.addRow(caption, control)
        self.rows[key] = (form, control)
        return control

    def _build(self):
        o = self.base
        fmt = self.caps.format(o.kind, o.format)
        enc = self.caps.encoders.get(o.encoder)
        primary = self.tab(
            "Encoding", "Settings are matched to the selected encoder and your FFmpeg installation."
        )
        choices = [(e.label, e.name) for e in self.caps.choices(fmt)]
        if o.kind != "image":
            choices.append(("Copy without re-encoding", "copy"))
        self.field(primary, "encoder", "Encoder", choices=choices).currentIndexChanged.connect(
            lambda: (
                self.encoder_changed.emit(self.controls["encoder"].currentData())
                if not self.loading
                else None
            )
        )
        if enc and o.kind != "audio":
            if o.encoder in SWITCHABLE_LOSSLESS:
                self.field(
                    primary,
                    "lossless",
                    "Use lossless encoder mode",
                    tooltip="Preserves data at the encoder input. Resizing, pixel format and color changes can still be lossy.",
                )
            if o.encoder in {"png", "libwebp", "libwebp_anim"}:
                self.field(
                    primary,
                    "compression_level",
                    "Compression effort",
                    bounds=(0, 9 if o.encoder == "png" else 6),
                    tooltip="Higher values spend more time compressing. PNG compression level does not change image quality.",
                )
            if o.kind == "image" and o.encoder not in LOSSLESS | {"gif", "jpeg2000", "libopenjpeg"}:
                self.field(
                    primary,
                    "quality",
                    "Quality · 1–100",
                    bounds=(1, 100),
                    tooltip="Higher image quality generally means larger files.",
                )
            if o.kind == "video" and o.encoder not in LOSSLESS | {"prores_ks"}:
                rate_choices = [("Average bitrate", "bitrate")]
                if o.encoder in QUALITY_VIDEO:
                    rate_choices.insert(0, ("Constant quality · CRF", "quality"))
                if o.encoder in {"libx264", "libx265", "mpeg4", "mpeg2video"}:
                    rate_choices.append(("Constrained constant bitrate", "cbr"))
                self.field(primary, "rate_control", "Rate control", choices=rate_choices)
                if o.encoder in QUALITY_VIDEO:
                    self.field(
                        primary,
                        "quality",
                        "CRF",
                        bounds=(0, 51 if o.encoder in {"libx264", "libx265"} else 63),
                        tooltip="Lower CRF usually means higher quality and larger files. Values are not comparable across codecs.",
                    )
                self.field(primary, "bitrate", "Video bitrate · kbps", bounds=(50, 1000000))
                self.field(
                    primary,
                    "max_bitrate",
                    "Maximum bitrate · kbps",
                    bounds=(0, 1000000),
                    tooltip="0 leaves the maximum unspecified.",
                )
                self.field(
                    primary,
                    "buffer_size",
                    "Rate-control buffer · kbit",
                    bounds=(0, 2000000),
                    tooltip="0 uses an automatic buffer where required.",
                )
                self.field(
                    primary,
                    "target_mb",
                    "Approximate target · MB",
                    bounds=(0, 1000000),
                    tooltip="0 disables target size. Duration, audio bitrate and 2% container overhead determine estimated video bitrate. Exact size is not guaranteed.",
                )
                if o.encoder in TWO_PASS:
                    self.field(
                        primary,
                        "two_pass",
                        "Two-pass encoding",
                        tooltip="Spends a first pass analyzing bitrate allocation; requires bitrate or target-size mode.",
                    )
            if o.encoder in {"libx264", "libx265", "libsvtav1", "libaom-av1", "libvpx-vp9"}:
                presets = [
                    (x.title(), x)
                    for x in [
                        "ultrafast",
                        "superfast",
                        "veryfast",
                        "faster",
                        "fast",
                        "medium",
                        "slow",
                        "slower",
                        "veryslow",
                    ]
                ]
                if o.encoder not in {"libx264", "libx265"}:
                    maximum = {"libsvtav1": 13, "libaom-av1": 8, "libvpx-vp9": 5}[o.encoder]
                    presets = [
                        (f"{i} · {'slowest' if i == 0 else 'fastest' if i == maximum else 'speed'}", str(i))
                        for i in range(maximum + 1)
                    ]
                self.field(
                    primary,
                    "preset",
                    "Encoding speed",
                    choices=presets,
                    tooltip="Slower settings spend more processing time seeking compression efficiency; they do not simply mean higher visual quality.",
                )
        if o.kind == "audio":
            self._audio(primary, o.encoder)
        if o.kind in {"image", "video"} and o.encoder != "copy":
            geometry = self.tab(
                "Picture",
                "Original orientation is applied automatically. Fit keeps the image inside the requested dimensions.",
            )
            self.field(
                geometry,
                "resize",
                "Resolution",
                choices=[
                    ("Keep original", "original"),
                    ("Fit within dimensions", "fit"),
                    ("Custom dimensions", "custom"),
                    ("Scale by percentage", "percent"),
                ],
            )
            self.field(geometry, "width", "Width · px", bounds=(1, 16384))
            self.field(geometry, "height", "Height · px", bounds=(1, 16384))
            self.field(geometry, "scale_percent", "Scale · %", bounds=(1, 400))
            self.field(geometry, "keep_aspect", "Preserve aspect ratio")
            self.field(
                geometry,
                "scaler",
                "Resize algorithm",
                choices=[
                    ("Nearest", "neighbor"),
                    ("Bilinear", "bilinear"),
                    ("Bicubic", "bicubic"),
                    ("Lanczos", "lanczos"),
                    ("Area", "area"),
                ],
            )
            if o.kind == "video":
                self.field(
                    geometry,
                    "fps",
                    "Frame rate",
                    tooltip="Blank keeps original. Enter a number or fraction, such as 30000/1001. Lower frame rates change motion smoothness.",
                )
            if enc.pixels:
                self.field(
                    geometry,
                    "pixel_format",
                    "Pixel format",
                    choices=[("Automatic", "")] + [(p, p) for p in enc.pixels],
                    tooltip="Only pixel formats reported by this encoder are listed. Changing bit depth or chroma subsampling can change quality.",
                )
            if o.kind == "image":
                self.field(
                    geometry,
                    "alpha",
                    "Transparency",
                    choices=[
                        ("Preserve where supported", "preserve"),
                        ("Remove alpha", "remove"),
                        ("Composite on background", "background"),
                    ],
                )
                self.field(
                    geometry,
                    "background",
                    "Background · hex",
                    tooltip="Six-digit RGB color, for example #ffffff.",
                )
            if o.kind == "video" and o.encoder == "libx264":
                self.field(
                    geometry,
                    "profile",
                    "Profile",
                    choices=[("Automatic", "")]
                    + [(p.title(), p) for p in ["baseline", "main", "high", "high10", "high422", "high444"]],
                )
                self.field(
                    geometry,
                    "level",
                    "Level",
                    choices=[("Automatic", "")]
                    + [
                        (p, p)
                        for p in ["3.0", "3.1", "4.0", "4.1", "4.2", "5.0", "5.1", "5.2", "6.0", "6.1", "6.2"]
                    ],
                )
            elif o.encoder == "prores_ks":
                self.field(
                    geometry,
                    "profile",
                    "ProRes profile",
                    choices=[
                        ("Automatic", ""),
                        ("Proxy", "0"),
                        ("LT", "1"),
                        ("Standard", "2"),
                        ("HQ", "3"),
                        ("4444", "4"),
                        ("4444 XQ", "5"),
                    ],
                )
            if o.kind == "video" and o.encoder in {"libx264", "libx265", "mpeg4", "mpeg2video"}:
                self.field(
                    geometry,
                    "gop",
                    "Keyframe interval",
                    bounds=(0, 10000),
                    tooltip="Maximum GOP size in frames. 0 keeps the encoder default.",
                )
                self.field(
                    geometry, "b_frames", "B-frames", bounds=(-1, 16), tooltip="-1 uses the encoder default."
                )
            filters = self.tab(
                "Filters",
                "Filters change decoded media. Color fields below tag output characteristics; they do not perform HDR tone mapping.",
            )
            self.field(
                filters,
                "rotate",
                "Rotate",
                choices=[
                    ("None", "none"),
                    ("90° clockwise", "clockwise"),
                    ("90° counterclockwise", "counterclockwise"),
                    ("180°", "180"),
                ],
            )
            self.field(
                filters,
                "flip",
                "Flip",
                choices=[("None", "none"), ("Horizontal", "horizontal"), ("Vertical", "vertical")],
            )
            self.field(
                filters,
                "crop",
                "Crop · w:h:x:y",
                tooltip="Blank disables cropping. Use numeric pixels, for example 1280:720:0:0. Cropping precedes rotation.",
            )
            for key, title, supported in [
                ("deinterlace", "Deinterlace", "yadif"),
                ("denoise", "Reduce visual noise", "hqdn3d"),
                ("sharpen", "Gentle sharpening", "unsharp"),
                ("grayscale", "Grayscale", "format"),
            ]:
                if supported in self.caps.filters:
                    self.field(filters, key, title)
            self.field(
                filters,
                "color_space",
                "Color-space tag",
                choices=[("Automatic", "")] + [(v, v) for v in ["bt709", "bt470bg", "smpte170m", "bt2020nc"]],
            )
            self.field(
                filters,
                "color_range",
                "Color range",
                choices=[("Automatic", ""), ("Limited · TV", "tv"), ("Full · PC", "pc")],
            )
            self.field(
                filters,
                "color_primaries",
                "Color primaries",
                choices=[("Automatic", "")] + [(v, v) for v in ["bt709", "bt470bg", "smpte170m", "bt2020"]],
            )
            self.field(
                filters,
                "color_transfer",
                "Transfer tag",
                choices=[("Automatic", "")]
                + [(v, v) for v in ["bt709", "smpte170m", "iec61966-2-1", "smpte2084", "arib-std-b67"]],
            )
        if o.kind == "video":
            audio = self.tab(
                "Audio",
                "The first audio track is processed. Stream copy is checked against the output container.",
            )
            self.field(
                audio,
                "audio_mode",
                "Audio handling",
                choices=[
                    ("Convert audio", "convert"),
                    ("Copy without re-encoding", "copy"),
                    ("Remove audio", "remove"),
                ],
            )
            self.field(
                audio,
                "audio_encoder",
                "Audio encoder",
                choices=[(e.label, e.name) for e in self.caps.choices(fmt, True)],
            ).currentIndexChanged.connect(
                lambda: (
                    self.audio_changed.emit(self.controls["audio_encoder"].currentData())
                    if not self.loading
                    else None
                )
            )
            self._audio(audio, o.audio_encoder)
        metadata = self.tab(
            "Metadata",
            "Only metadata supported by the destination format can be retained. Empty edit fields leave copied values unchanged.",
        )
        self.field(
            metadata,
            "metadata",
            "Source metadata",
            choices=[("Preserve supported metadata", "preserve"), ("Remove source metadata", "remove")],
        )
        if o.kind != "image":
            self.field(metadata, "chapters", "Preserve chapters where supported")
        if o.kind == "video":
            self.field(
                metadata,
                "subtitles",
                "Subtitles",
                choices=[
                    ("Remove", "remove"),
                    ("Copy compatible streams", "copy"),
                    ("Convert text subtitles", "convert"),
                ],
            )
            if o.format == "mkv":
                self.field(metadata, "attachments", "Preserve attachments")
        if o.kind == "audio":
            for key in ["title", "artist", "album", "track", "genre", "date", "comment"]:
                field = QLineEdit(o.tags.get(key, ""))
                field.setAccessibleName(key.title())
                field.textChanged.connect(self._changed)
                self.tags[key] = field
                metadata.addRow(key.title(), field)
            if o.format in {"mp3", "m4a", "flac"}:
                self.field(
                    metadata,
                    "cover",
                    "Cover artwork",
                    choices=[("Remove", "remove"), ("Preserve", "preserve"), ("Replace", "replace")],
                )
                cover = self.field(metadata, "cover_path", "Cover image path")
                metadata.addRow("", button("Browse artwork", lambda: self._browse_cover(cover)))
        expert = self.tab(
            "Expert",
            "Additional output tuning parameters may override generated settings and may fail for a particular encoder. Inputs, outputs and file-reading filters are restricted for file safety.",
        )
        self.field(
            expert,
            "expert",
            "Additional arguments",
            kind="multiline",
            tooltip="Examples: -aq-strength 0.8, -rc-lookahead 40, -sc_threshold 0. See README for the supported output tuning options.",
        )
        self.field(
            expert,
            "threads",
            "CPU threads",
            bounds=(0, 128),
            tooltip="0 lets FFmpeg choose. Some encoders manage their own threads.",
        )

    def _audio(self, form, encoder):
        if encoder == "copy" or encoder not in self.caps.encoders:
            return
        enc = self.caps.encoders[encoder]
        if encoder == "flac":
            self.field(form, "compression_level", "Lossless compression effort", bounds=(0, 12))
        elif encoder not in LOSSLESS:
            modes = [("Target bitrate", "bitrate")]
            if encoder in {"libmp3lame", "libvorbis", "aac"}:
                modes.append(("Quality-based VBR", "quality"))
            if encoder == "libopus":
                modes += [("Variable bitrate", "vbr"), ("Constant bitrate", "cbr")]
            self.field(form, "audio_rate_control", "Bitrate mode", choices=modes)
            self.field(form, "audio_bitrate", "Audio bitrate · kbps", bounds=(8, 1536))
            if encoder in {"libmp3lame", "libvorbis", "aac"}:
                self.field(
                    form,
                    "audio_quality",
                    "VBR quality",
                    bounds=(0, 9),
                    tooltip="MP3: 0 is highest quality, 9 lowest. Vorbis/AAC: larger quality values generally increase quality and size.",
                )
        self.field(
            form,
            "sample_rate",
            "Sample rate · Hz",
            bounds=(0, 384000),
            tooltip="0 keeps the source rate when supported. Encoder rates: "
            + (", ".join(map(str, enc.sample_rates)) or "automatic"),
        )
        self.field(
            form,
            "channels",
            "Channels",
            choices=[
                ("Keep original", 0),
                ("Mono", 1),
                ("Stereo", 2),
                ("5.1 · 6 channels", 6),
                ("7.1 · 8 channels", 8),
            ],
        )
        if enc.sample_formats:
            self.field(
                form,
                "sample_format",
                "Sample format",
                choices=[("Automatic", "")] + [(v, v) for v in enc.sample_formats],
            )
        self.field(form, "volume_db", "Volume gain · dB", bounds=(-60, 30))
        if "loudnorm" in self.caps.filters:
            self.field(
                form,
                "normalize",
                "Normalize loudness to −16 LUFS",
                tooltip="Single-pass EBU R128 loudness normalization, −1.5 dB true peak. Results depend on source content.",
            )

    def _browse_cover(self, control):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select cover image", "", "Images (*.jpg *.jpeg *.png);;All files (*)"
        )
        if path:
            control.setText(path)

    def values(self) -> Options:
        values = self.base.to_dict()
        for key, control in self.controls.items():
            if isinstance(control, QComboBox):
                values[key] = control.currentData()
            elif isinstance(control, QCheckBox):
                values[key] = control.isChecked()
            elif isinstance(control, (QSpinBox, QDoubleSpinBox)):
                values[key] = control.value()
            elif isinstance(control, QPlainTextEdit):
                values[key] = control.toPlainText().strip()
            else:
                values[key] = control.text().strip()
        if self.tags:
            values["tags"] = {
                key: control.text().strip() for key, control in self.tags.items() if control.text().strip()
            }
        o = Options.from_dict(values)
        if o.kind == "audio":
            o.audio_encoder = o.encoder
        if o.kind == "video" and o.audio_mode != "convert":
            o.sample_rate, o.channels, o.sample_format, o.volume_db, o.normalize = 0, 0, "", 0.0, False
        if o.rate_control == "quality" and not o.target_mb or o.lossless:
            o.two_pass = False
        if o.lossless:
            o.target_mb = 0
        return o

    def _visible(self, key, visible):
        if key in self.rows:
            form, control = self.rows[key]
            form.setRowVisible(control, bool(visible))

    def _visibility(self):
        o = self.values()
        for key in ("width", "height"):
            self._visible(key, o.resize in {"custom", "fit"})
        self._visible("scale_percent", o.resize == "percent")
        self._visible("keep_aspect", o.resize == "custom")
        self._visible("scaler", o.resize != "original")
        self._visible("background", o.alpha == "background")
        self._visible("cover_path", o.cover == "replace")
        if o.kind == "video":
            self._visible("quality", o.rate_control == "quality" and not o.target_mb and not o.lossless)
            for key in ("bitrate", "max_bitrate", "buffer_size", "two_pass"):
                self._visible(key, (o.rate_control != "quality" or o.target_mb > 0) and not o.lossless)
            self._visible("bitrate", o.rate_control != "quality" and not o.target_mb and not o.lossless)
            self._visible("target_mb", not o.lossless)
            self._visible("rate_control", not o.lossless)
            for key in (
                "audio_encoder",
                "audio_rate_control",
                "audio_bitrate",
                "audio_quality",
                "sample_rate",
                "sample_format",
                "channels",
                "volume_db",
                "normalize",
            ):
                self._visible(key, o.audio_mode == "convert")
        audio_active = o.kind == "audio" or o.kind == "video" and o.audio_mode == "convert"
        self._visible("audio_quality", audio_active and o.audio_rate_control == "quality")
        self._visible("audio_bitrate", audio_active and o.audio_rate_control != "quality")

    def _changed(self, *_):
        if not self.loading:
            self._visibility()
            self.changed.emit()


def change_encoder(caps: Capabilities, o: Options, encoder: str) -> Options:
    fresh = recommended(caps, o.kind, o.operation, o.format)
    fields = {
        "encoder": encoder,
        "lossless": False,
        "quality": fresh.quality,
        "profile": "",
        "level": "",
        "preset": "6"
        if encoder == "libsvtav1"
        else "4"
        if encoder == "libaom-av1"
        else "2"
        if encoder == "libvpx-vp9"
        else "medium",
        "rate_control": "quality" if encoder in QUALITY_VIDEO or o.kind == "image" else "bitrate",
        "pixel_format": "",
        "two_pass": False,
        "target_mb": 0,
        "expert": "",
        "b_frames": -1,
        "sample_format": "",
        "audio_rate_control": "bitrate",
    }
    if o.kind == "video" and encoder in QUALITY_VIDEO - {"libx264", "libx265"}:
        fields["quality"] = 31
    if encoder == "copy":
        for key in (
            "resize",
            "fps",
            "crop",
            "rotate",
            "flip",
            "deinterlace",
            "denoise",
            "sharpen",
            "grayscale",
            "color_space",
            "color_range",
            "color_primaries",
            "color_transfer",
            "gop",
        ):
            fields[key] = getattr(Options(), key)
        if o.kind == "audio":
            fields.update(sample_rate=0, channels=0, volume_db=0.0, normalize=False)
    return replace(o, **fields)
