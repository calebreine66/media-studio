from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from media_studio.gui.widgets import button, label


class SettingsDialog(QDialog):
    def __init__(self, settings, caps, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Media Studio settings")
        self.resize(690, 600)
        self.controls = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(18)
        root.addWidget(label("Make yourself at home", "title"))
        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        def page(name):
            widget = QWidget()
            form = QFormLayout(widget)
            form.setContentsMargins(18, 20, 18, 20)
            form.setSpacing(16)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            tabs.addTab(widget, name)
            return form

        def check(form, key, title):
            control = QCheckBox(title)
            control.setChecked(settings[key])
            self.controls[key] = control
            form.addRow(control)

        def combo(form, key, title, choices):
            control = QComboBox()
            for name, val in choices:
                control.addItem(name, val)
            control.setCurrentIndex(max(0, control.findData(settings[key])))
            control.setAccessibleName(title)
            self.controls[key] = control
            form.addRow(title, control)

        def path(form, key, title, directory=False):
            row = QHBoxLayout()
            control = QLineEdit(settings[key])
            control.setAccessibleName(title)
            control.setPlaceholderText("Automatic" if key != "output_directory" else "Source folder")
            self.controls[key] = control
            row.addWidget(control)

            def browse():
                value = (
                    QFileDialog.getExistingDirectory(self, title)
                    if directory
                    else QFileDialog.getOpenFileName(self, title)[0]
                )
                if value:
                    control.setText(value)

            row.addWidget(button("Browse", browse))
            form.addRow(title, row)

        general = page("General")
        path(general, "output_directory", "Default output folder", True)
        check(general, "ask_directory", "Ask for an output folder when adding jobs")
        check(general, "open_completed", "Open output folder after completion")
        combo(
            general,
            "collision",
            "Existing output files",
            [
                ("Ask every time", "ask"),
                ("Automatically rename", "rename"),
                ("Replace existing outputs", "replace"),
            ],
        )
        general.addRow(
            label(
                "Original source files are always protected. Replace applies only to other output files.",
                "muted",
                True,
            )
        )
        check(general, "remember", "Remember last-used settings")
        check(general, "history", "Keep processing history on this computer")
        general.addRow(
            label(
                "Disabling history stops new entries. Existing entries can be cleared from History. Diagnostics stay in memory for the current session.",
                "muted",
                True,
            )
        )
        appearance = page("Appearance")
        combo(
            appearance, "theme", "Theme", [("Light", "light"), ("Dark", "dark"), ("Follow system", "system")]
        )
        appearance.addRow(
            label("The interface follows your operating system’s display scaling.", "muted", True)
        )
        ffmpeg = page("FFmpeg")
        path(ffmpeg, "ffmpeg", "FFmpeg executable")
        path(ffmpeg, "ffprobe", "FFprobe executable")
        ffmpeg.addRow(
            label(
                caps.version if caps else "No working FFmpeg / FFprobe installation detected.", "muted", True
            )
        )
        if caps:
            ffmpeg.addRow(
                label(
                    f"{len(caps.encoders)} encoders · {len(caps.decoders)} decoders · {len(caps.muxers)} muxers · {len(caps.filters)} filters",
                    "muted",
                    True,
                )
            )
            ffmpeg.addRow(
                label(
                    "Hardware APIs: "
                    + (", ".join(caps.hardware) or "none")
                    + "\nSelectable hardware encoders have passed a local test encode.",
                    "muted",
                    True,
                )
            )
        ffmpeg.addRow(
            label(
                "Leave paths blank to search the bundled bin folder and PATH. Save refreshes capabilities in the background.",
                "muted",
                True,
            )
        )
        performance = page("Performance")
        for key, title, bounds in [
            ("jobs", "Simultaneous jobs", (1, 4)),
            ("threads", "Default CPU threads", (0, 128)),
        ]:
            control = QSpinBox()
            control.setRange(*bounds)
            control.setValue(settings[key])
            self.controls[key] = control
            performance.addRow(title, control)
        performance.addRow(
            label(
                "0 threads lets FFmpeg decide. More simultaneous jobs can increase memory and disk use. Some encoders control their own threading.",
                "muted",
                True,
            )
        )
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button("Cancel", self.reject))
        actions.addWidget(button("Save & refresh", self.accept, True))
        root.addLayout(actions)

    def values(self):
        result = {}
        for key, control in self.controls.items():
            if isinstance(control, QCheckBox):
                result[key] = control.isChecked()
            elif isinstance(control, QComboBox):
                result[key] = control.currentData()
            elif isinstance(control, QSpinBox):
                result[key] = control.value()
            else:
                result[key] = control.text().strip()
        return result
