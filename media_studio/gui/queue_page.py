from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QPlainTextEdit,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from media_studio.gui.widgets import button, label, panel
from media_studio.models import Job, Progress, human_size, human_time


def open_local(path: Path):
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class QueuePage(QWidget):
    start_requested = Signal()
    cancel_requested = Signal(bool)
    remove_requested = Signal()
    move_requested = Signal(int)
    error = Signal(object)

    def __init__(self):
        super().__init__()
        self.jobs: list[Job] = []
        self.updates: dict[str, Progress] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 24)
        layout.setSpacing(18)
        layout.addWidget(label("A LITTLE WORK IN THE BACKGROUND", "eyebrow"))
        layout.addWidget(label("Your processing queue", "title"))
        self.summary = label("Add files from Convert or Compress to get started.", "muted")
        layout.addWidget(self.summary)
        toolbar = QHBoxLayout()
        toolbar.addWidget(button("Start queue", self.start_requested.emit, True, "arrow"))
        toolbar.addWidget(button("Move up", lambda: self.move_requested.emit(-1)))
        toolbar.addWidget(button("Move down", lambda: self.move_requested.emit(1)))
        toolbar.addWidget(button("Remove", self.remove_requested.emit))
        toolbar.addStretch()
        toolbar.addWidget(button("Cancel current", lambda: self.cancel_requested.emit(False)))
        toolbar.addWidget(button("Cancel all", lambda: self.cancel_requested.emit(True)))
        layout.addLayout(toolbar)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["FILE", "TYPE / INPUT", "OUTPUT", "STATUS", "PROGRESS", "ORIGINAL", "RESULT"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(54)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.update_detail)
        self.table.cellDoubleClicked.connect(lambda *_: self.show_log())
        layout.addWidget(self.table, 1)
        frame, detail = panel("Job details")
        self.detail_title = label("Your files stay on your computer.", "sectionTitle")
        self.detail_text = label("Progress, processing speed and results will appear here.", "muted", True)
        self.detail_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail.addWidget(self.detail_title)
        detail.addWidget(self.detail_text)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1000)
        detail.addWidget(self.progress)
        buttons = QHBoxLayout()
        self.open_file = button("Open output", lambda: self.open_selected(False), glyph="arrow")
        self.open_folder = button("Open folder", lambda: self.open_selected(True), glyph="folder")
        buttons.addWidget(self.open_file)
        buttons.addWidget(self.open_folder)
        buttons.addStretch()
        buttons.addWidget(button("View log / copy diagnostics", self.show_log, glyph="info"))
        detail.addLayout(buttons)
        layout.addWidget(frame)
        self.update_detail()

    def selected(self):
        row = self.table.currentRow()
        return self.jobs[row] if 0 <= row < len(self.jobs) else None

    def refresh(self):
        selected = self.selected()
        selected_id = selected.id if selected else ""
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.jobs))
        for row, job in enumerate(self.jobs):
            self._row(row, job)
        if selected_id:
            row = next((i for i, job in enumerate(self.jobs) if job.id == selected_id), 0)
            self.table.selectRow(row)
        elif self.jobs:
            self.table.selectRow(0)
        self.table.blockSignals(False)
        self.update_summary()
        self.update_detail()

    def _row(self, row, job):
        values = [
            job.source.path.name,
            f"{job.source.kind.title()} · {job.source.container.split(',')[0]}",
            job.options.format.upper(),
            job.status,
            f"{job.progress:.0f}%",
            human_size(job.source.size),
            human_size(job.output_size) if job.status == "Completed" else "—",
        ]
        for col, value in enumerate(values):
            item = self.table.item(row, col)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(row, col, item)
            item.setText(value)
            item.setToolTip(job.error if col == 3 and job.error else str(job.output) if col == 2 else value)

    def update_job(self, job, progress=None):
        if progress:
            self.updates[job.id] = progress
        if job in self.jobs:
            self._row(self.jobs.index(job), job)
        self.update_summary()
        self.update_detail()

    def update_summary(self):
        counts = {
            state: sum(j.status == state for j in self.jobs)
            for state in ["Waiting", "Completed", "Failed", "Cancelled"]
        }
        active = sum(j.status in {"Converting", "Compressing", "Validating"} for j in self.jobs)
        self.summary.setText(
            f"{len(self.jobs)} jobs  ·  {active} processing  ·  {counts['Waiting']} waiting  ·  "
            f"{counts['Completed']} completed  ·  {counts['Failed']} failed  ·  {counts['Cancelled']} cancelled"
        )

    def update_detail(self):
        job = self.selected()
        if not job:
            self.open_file.setEnabled(False)
            self.open_folder.setEnabled(False)
            self.progress.setValue(0)
            self.detail_title.setText("Your files stay on your computer.")
            self.detail_text.setText("Select a job to see its progress or result.")
            return
        self.open_file.setEnabled(job.status == "Completed")
        self.open_folder.setEnabled(job.status == "Completed")
        self.detail_title.setText(f"{job.status}  ·  {job.source.path.name}")
        self.progress.setValue(int(job.progress * 10))
        text = f"Input: {job.source.path}\nOutput: {job.output}"
        if job.status == "Completed":
            difference = (1 - job.output_size / job.source.size) * 100 if job.source.size else 0
            delta = f"{difference:.1f}% smaller" if difference >= 0 else f"{-difference:.1f}% larger"
            text += f"\n{human_size(job.source.size)} → {human_size(job.output_size)}  ·  {delta}  ·  {human_time(job.elapsed)}"
        elif job.error:
            text += "\n" + job.error
        elif update := self.updates.get(job.id):
            eta = human_time(update.remaining) if update.remaining is not None else "calculating"
            text += (
                f"\n{update.stage}  ·  {update.percent:.1f}%  ·  Elapsed {human_time(update.elapsed)}"
                f"  ·  Processed {human_time(update.timestamp)}  ·  Speed {update.speed or '—'}  ·  Remaining {eta}"
            )
        self.detail_text.setText(text)

    def open_selected(self, folder):
        job = self.selected()
        if job and job.status == "Completed":
            path = job.output.parent if folder else job.output
            if not path.exists() or not open_local(path):
                from media_studio.models import MediaError

                self.error.emit(
                    MediaError("The output could not be opened. It may have been moved or deleted.")
                )

    def show_log(self):
        job = self.selected()
        if not job:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Job diagnostics")
        dialog.resize(780, 520)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label("Diagnostic details", "sectionTitle"))
        layout.addWidget(label("Logs include local filenames. Review them before sharing.", "muted"))
        text = QPlainTextEdit(job.log or job.error or "This job has not started yet.")
        text.setReadOnly(True)
        layout.addWidget(text)
        row = QHBoxLayout()
        row.addWidget(
            button(
                "Copy diagnostics",
                lambda: (
                    text.copy()
                    if text.textCursor().hasSelection()
                    else __import__("PySide6.QtWidgets", fromlist=["QApplication"])
                    .QApplication.clipboard()
                    .setText(text.toPlainText())
                ),
            )
        )
        row.addStretch()
        row.addWidget(button("Close", dialog.accept))
        layout.addLayout(row)
        dialog.exec()
