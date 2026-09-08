from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from media_studio import __version__
from media_studio.core.capabilities import detect
from media_studio.core.commands import build_plan
from media_studio.core.execution import Executor
from media_studio.core.probe import probe
from media_studio.core.validation import same_file, unique_output, validate
from media_studio.gui.queue_page import QueuePage, open_local
from media_studio.gui.settings import SettingsDialog
from media_studio.gui.theme import apply_theme
from media_studio.gui.widgets import OperationCard, button, icon, label, panel
from media_studio.gui.workbench import Workbench
from media_studio.gui.workers import Task
from media_studio.models import Job, MediaError, human_time
from media_studio.storage import Store


class MainWindow(QMainWindow):
    def __init__(self, store: Store | None = None, auto_detect: bool = True):
        super().__init__()
        self.store = store or Store()
        self.caps = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(8)
        self.tasks = set()
        self.active: dict[str, threading.Event] = {}
        self.queue_running = False
        self.preparing = False
        self._closing = False
        self._detect_token = 0
        self.setWindowTitle("Media Studio — Convert & Compress")
        self.setWindowIcon(icon("convert", "#6854D8", 64))
        self.resize(1220, 900)
        self.setMinimumSize(980, 720)
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(205)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(18, 28, 18, 20)
        nav.setSpacing(7)
        brand_row = QHBoxLayout()
        mark = label("")
        mark.setPixmap(icon("convert", "#6854D8", 28).pixmap(28, 28))
        brand_row.addWidget(mark)
        brand_row.addWidget(label("Media Studio", "brand"))
        nav.addLayout(brand_row)
        nav.addSpacing(6)
        nav.addWidget(label("A better space for your media.", "muted", True))
        nav.addSpacing(32)
        nav.addWidget(label("WORKSPACE", "eyebrow"))
        self.nav_buttons = {}
        for title, key, glyph in [
            ("Overview", "home", "home"),
            ("Convert", "convert", "convert"),
            ("Compress", "compress", "compress"),
            ("Processing queue", "queue", "queue"),
            ("History", "history", "history"),
        ]:
            btn = button(title, lambda checked=False, k=key: self.navigate(k), glyph=glyph)
            btn.setObjectName("nav")
            btn.setCheckable(True)
            self.nav_buttons[key] = btn
            nav.addWidget(btn)
        nav.addStretch()
        local_frame, local_layout = panel()
        local_layout.setContentsMargins(12, 13, 12, 13)
        local_layout.addWidget(label("LOCAL BY DESIGN", "eyebrow"))
        local_layout.addWidget(label("Your files stay yours.\nProcessing happens here.", "muted", True))
        nav.addWidget(local_frame)
        nav.addSpacing(8)
        nav.addWidget(button("Settings", self.open_settings, glyph="settings"))
        nav.addWidget(button("About Media Studio", self.about, glyph="info"))
        nav.addSpacing(6)
        nav.addWidget(label(f"VERSION {__version__}", "muted"))
        layout.addWidget(sidebar)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.home = self._home()
        self.pages.addWidget(self.home)
        self.workbench = Workbench(self.store)
        self.workbench.files_requested.connect(self.analyze_files)
        self.workbench.jobs_requested.connect(self.enqueue)
        self.workbench.error.connect(self.show_error)
        self.pages.addWidget(self.workbench)
        self.queue_page = QueuePage()
        self.queue_page.start_requested.connect(self.start_queue)
        self.queue_page.cancel_requested.connect(self.cancel_jobs)
        self.queue_page.remove_requested.connect(self.remove_job)
        self.queue_page.move_requested.connect(self.move_job)
        self.queue_page.error.connect(self.show_error)
        self.pages.addWidget(self.queue_page)
        self.history_page = self._history()
        self.pages.addWidget(self.history_page)
        self.setCentralWidget(central)
        self.engine_status = label("Checking FFmpeg…", "muted")
        self.statusBar().addPermanentWidget(self.engine_status)
        self.statusBar().showMessage("Ready when you are")
        self._shortcuts()
        self.navigate("home")
        if self.store.warning:
            self.statusBar().showMessage(self.store.warning)
        if auto_detect:
            QTimer.singleShot(0, self.refresh_capabilities)

    def _home(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(36, 34, 36, 28)
        root.setSpacing(20)
        top = QHBoxLayout()
        top.addWidget(label("LESS FRICTION. MORE POSSIBILITY.", "eyebrow"))
        top.addStretch()
        top.addWidget(label("IMAGE  /  VIDEO  /  AUDIO", "muted"))
        root.addLayout(top)
        root.addWidget(label("Good things come\nin the right format.", "title"))
        root.addWidget(
            label(
                "Convert, compress, and carry on. Powerful media tools,\nwith just the controls you need.",
                "muted",
                True,
            )
        )
        cards = QHBoxLayout()
        cards.setSpacing(20)
        for operation in ("convert", "compress"):
            card = OperationCard(operation)
            card.chosen.connect(self.open_workflow)
            cards.addWidget(card, 1)
        root.addLayout(cards)
        frame, tips = panel()
        row = QHBoxLayout()
        for title, body in [
            ("01   Start simple", "Pick your files and a format.\nRecommended settings do the rest."),
            ("02   Go deeper", "Switch to Advanced for\ncodec-aware creative control."),
            ("03   Keep moving", "Queue a batch and let\nyour computer take it from here."),
        ]:
            col = QVBoxLayout()
            col.addWidget(label(title, "sectionTitle"))
            col.addWidget(label(body, "muted", True))
            row.addLayout(col, 1)
        tips.addLayout(row)
        root.addWidget(frame)
        root.addStretch()
        self.home_engine = label("Finding your media tools…", "muted", True)
        root.addWidget(self.home_engine)
        return page

    def _history(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(30, 28, 30, 24)
        root.setSpacing(18)
        root.addWidget(label("A RECORD OF WHAT YOU’VE MADE", "eyebrow"))
        root.addWidget(label("Processing history", "title"))
        root.addWidget(
            label(
                "Stored locally. Remove an entry at any time; your media files stay untouched.", "muted", True
            )
        )
        row = QHBoxLayout()
        row.addWidget(button("Open output", lambda: self.open_history(False), glyph="arrow"))
        row.addWidget(button("Open folder", lambda: self.open_history(True), glyph="folder"))
        row.addStretch()
        row.addWidget(button("Remove entry", self.remove_history))
        row.addWidget(button("Clear history", self.clear_history))
        root.addLayout(row)
        self.history_table = QTableWidget(0, 6)
        self.history_table.setHorizontalHeaderLabels(
            ["DATE", "FILE", "OPERATION", "STATUS", "SIZE CHANGE", "TIME"]
        )
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setShowGrid(False)
        self.history_table.verticalHeader().hide()
        self.history_table.verticalHeader().setDefaultSectionSize(52)
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.history_table.cellDoubleClicked.connect(lambda *_: self.open_history(False))
        root.addWidget(self.history_table, 1)
        self.history_note = label("", "muted")
        root.addWidget(self.history_note)
        self.refresh_history()
        return page

    def _shortcuts(self):
        for text, shortcut, callback in [
            ("Add files", QKeySequence.StandardKey.Open, self.browse_from_menu),
            ("Settings", QKeySequence.StandardKey.Preferences, self.open_settings),
            ("Quit", QKeySequence.StandardKey.Quit, self.close),
        ]:
            action = QAction(text, self)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            self.addAction(action)

    def browse_from_menu(self):
        if self.pages.currentWidget() != self.workbench:
            self.open_workflow("convert", "video")
        self.workbench.browse()

    def navigate(self, page):
        for key, btn in self.nav_buttons.items():
            btn.setChecked(key == page)
        if page in {"convert", "compress"}:
            self.workbench.configure(page, self.workbench.kind)
            self.pages.setCurrentWidget(self.workbench)
        else:
            self.pages.setCurrentWidget(
                {"home": self.home, "queue": self.queue_page, "history": self.history_page}[page]
            )
        if page == "history":
            self.refresh_history()

    def open_workflow(self, operation, kind):
        self.navigate(operation)
        self.workbench.configure(operation, kind)

    def run_task(self, function, result=None, error=None, progress=None, finished=None):
        task = Task(function)
        self.tasks.add(task)
        if result:
            task.signals.result.connect(result)
        task.signals.error.connect(error or self.show_error)
        if progress:
            task.signals.progress.connect(progress)

        def done():
            self.tasks.discard(task)
            if finished:
                finished()

        task.signals.finished.connect(done)
        self.pool.start(task)
        return task

    def refresh_capabilities(self):
        self._detect_token += 1
        token = self._detect_token
        self.engine_status.setText("Checking media tools…")
        settings = self.store.settings.copy()

        def ready(caps):
            if token != self._detect_token:
                return
            self.caps = caps
            self.workbench.set_capabilities(caps)
            short = caps.version.split(" Copyright")[0]
            self.engine_status.setText(short + "  ·  Ready")
            self.engine_status.setObjectName("success")
            self.home_engine.setText(
                f"●  {short} is ready  ·  {len(caps.encoders)} detected encoders  ·  All processing is local"
            )
            self.statusBar().showMessage("Media tools are ready. Add files to begin.")

        def failed(exc):
            if token != self._detect_token:
                return
            self.caps = None
            self.workbench.caps = None
            self.workbench.update_preview()
            self.engine_status.setText("Media tools unavailable · Open Settings")
            self.home_engine.setText(
                "FFmpeg / FFprobe could not start. Open Settings to select working executables."
            )
            self.show_error(exc)

        self.run_task(lambda _: detect(settings["ffmpeg"], settings["ffprobe"]), ready, failed)

    def analyze_files(self, paths):
        if not self.caps:
            self.show_error(MediaError("Configure working FFmpeg and FFprobe executables in Settings first."))
            return
        caps = self.caps
        self.statusBar().showMessage(f"Analyzing {len(paths)} file(s)…")
        self.workbench.drop.setEnabled(False)

        def analyze(_):
            result, errors = [], []
            for value in dict.fromkeys(paths):
                if self._closing:
                    break
                try:
                    result.append(probe(Path(value), caps.ffprobe))
                except MediaError as exc:
                    errors.append(f"{Path(value).name}: {exc}\n{exc.details}")
            return result, errors

        def ready(data):
            sources, errors = data
            self.workbench.add_sources(sources)
            self.statusBar().showMessage(
                f"Added {len(sources)} file(s). Detected media types determine their workflow."
            )
            if errors:
                self.show_error(
                    MediaError(
                        f"{len(errors)} file(s) could not be analyzed. Other valid files were added.",
                        "\n\n".join(errors),
                    )
                )

        self.run_task(analyze, ready, finished=lambda: self.workbench.drop.setEnabled(True))

    def _collision(self, output: Path):
        box = QMessageBox(self)
        box.setWindowTitle("Output already exists")
        box.setText(f"{output.name} already exists.")
        box.setInformativeText(
            "Replace the existing output, automatically rename the new file, or cancel adding these jobs."
        )
        replace_button = box.addButton("Replace", QMessageBox.ButtonRole.DestructiveRole)
        rename_button = box.addButton("Rename automatically", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(rename_button)
        box.exec()
        return (
            "replace"
            if box.clickedButton() == replace_button
            else "rename"
            if box.clickedButton() == rename_button
            else "cancel"
        )

    def enqueue(self, start):
        if self.preparing:
            return
        try:
            options = self.workbench.options()
            sources = list(self.workbench.current_sources)
            if not sources:
                raise MediaError("Add at least one source file first.")
            if self.store.settings["ask_directory"]:
                folder = QFileDialog.getExistingDirectory(self, "Choose output folder")
                if not folder:
                    return
                self.workbench.directory.setText(folder)
            reserved = {j.output.resolve() for j in self.queue_page.jobs}
            all_sources = [s.path for group in self.workbench.sources.values() for s in group]
            all_sources += [j.source.path for j in self.queue_page.jobs]
            jobs = []
            for source in sources:
                output = self.workbench.output_for(source, options)
                if any(same_file(path, output) for path in all_sources) or output.resolve() in reserved:
                    output = unique_output(output, reserved | {p.resolve() for p in all_sources})
                mode = "rename"
                if output.exists() or output.is_symlink():
                    mode = self.store.settings["collision"]
                    if mode == "ask":
                        mode = self._collision(output)
                    if mode == "cancel":
                        return
                    if mode == "rename":
                        output = unique_output(output, reserved)
                jobs.append(
                    Job(source, output, replace(options, tags=dict(options.tags)), replace=mode == "replace")
                )
                reserved.add(output.resolve())
            caps = self.caps
            self.preparing = True
            self.workbench.start.setEnabled(False)
            self.workbench.add_queue.setEnabled(False)
            self.statusBar().showMessage("Validating output settings…")

            def prepare(_):
                for job in jobs:
                    validate(job.source, job.output, job.options, caps, replace=job.replace)
                    build_plan(job.source, job.output, job.options, caps)
                    if job.options.cover == "replace":
                        cover = probe(Path(job.options.cover_path), caps.ffprobe)
                        if cover.kind != "image":
                            raise MediaError("Replacement cover artwork must be an image.")
                return jobs

            def ready(prepared):
                self.queue_page.jobs.extend(prepared)
                self.queue_page.refresh()
                if self.store.settings["remember"]:
                    self.store.settings.setdefault("last_options", {})[
                        f"{options.operation}:{options.kind}"
                    ] = options.to_dict()
                    self.safe_save(self.store.save_settings)
                self.navigate("queue")
                self.statusBar().showMessage(f"Added {len(prepared)} job(s) to the queue.")
                if start:
                    self.start_queue()

            def done():
                self.preparing = False
                self.workbench.update_preview()

            self.run_task(prepare, ready, finished=done)
        except MediaError as exc:
            self.show_error(exc)

    def start_queue(self):
        if not self.caps:
            self.show_error(MediaError("Configure FFmpeg in Settings before starting the queue."))
            return
        self.queue_running = True
        self._dispatch()

    def _dispatch(self):
        if not self.queue_running or self._closing:
            return
        while len(self.active) < self.store.settings["jobs"]:
            job = next((j for j in self.queue_page.jobs if j.status == "Waiting"), None)
            if not job:
                if not self.active:
                    self.queue_running = False
                    self.statusBar().showMessage("Queue finished. Select a job to review its result.")
                break
            cancel = threading.Event()
            self.active[job.id] = cancel
            job.status = "Validating"
            self.queue_page.update_job(job)
            executor = Executor(self.caps)
            self.run_task(
                lambda notify, j=job, e=executor, c=cancel: e.run(j, c, notify),
                self._job_finished,
                lambda exc, j=job: self._job_crashed(j, exc),
                lambda progress, j=job: self.queue_page.update_job(j, progress),
            )

    def _job_crashed(self, job, exc):
        job.status, job.error, job.log = "Failed", str(exc), repr(exc)
        self._job_finished(job)

    def _job_finished(self, job):
        self.active.pop(job.id, None)
        self.queue_page.update_job(job)
        self.safe_save(lambda: self.store.record(job))
        self.refresh_history()
        if job.status == "Completed" and self.store.settings["open_completed"] and not self._closing:
            open_local(job.output.parent)
        QTimer.singleShot(0, self._dispatch)

    def cancel_jobs(self, all_jobs=False):
        selected = self.queue_page.selected()
        if all_jobs:
            self.queue_running = False
            for cancel in self.active.values():
                cancel.set()
            for job in self.queue_page.jobs:
                if job.status == "Waiting":
                    job.status, job.error = "Cancelled", "Cancelled before processing."
                    self.safe_save(lambda j=job: self.store.record(j))
        else:
            current = (
                selected
                if selected and selected.id in self.active
                else next((job for job in self.queue_page.jobs if job.id in self.active), None)
            )
            if current:
                self.active[current.id].set()
            elif selected and selected.status == "Waiting":
                selected.status, selected.error = "Cancelled", "Cancelled before processing."
                self.safe_save(lambda: self.store.record(selected))
        self.queue_page.refresh()

    def remove_job(self):
        job = self.queue_page.selected()
        if job:
            if job.id in self.active:
                self.show_error(MediaError("Cancel this running job before removing it."))
                return
            self.queue_page.jobs.remove(job)
            self.queue_page.updates.pop(job.id, None)
            self.queue_page.refresh()

    def move_job(self, direction):
        jobs = self.queue_page.jobs
        job = self.queue_page.selected()
        if not job or job.status != "Waiting":
            return
        index = jobs.index(job)
        target = index + direction
        while 0 <= target < len(jobs) and jobs[target].status != "Waiting":
            target += direction
        if 0 <= target < len(jobs):
            jobs[index], jobs[target] = jobs[target], jobs[index]
            self.queue_page.refresh()
            self.queue_page.table.selectRow(target)

    def refresh_history(self):
        history = [item for item in self.store.history if isinstance(item, dict)]
        self.store.history = history
        self.history_table.setRowCount(len(history))
        for row, item in enumerate(history):
            old, new = item.get("original_size", 0), item.get("output_size", 0)
            reduction = f"{(1 - new / old) * 100:.1f}%" if old and item.get("status") == "Completed" else "—"
            values = [
                str(item.get("date", ""))[:16].replace("T", " ") + " UTC",
                Path(str(item.get("input", ""))).name,
                str(item.get("operation", "")).title(),
                str(item.get("status", "")),
                reduction,
                human_time(item.get("elapsed", 0)),
            ]
            for col, value in enumerate(values):
                self.history_table.setItem(row, col, QTableWidgetItem(value))
        self.history_note.setText(
            f"{len(history)} saved entries · History is {'enabled' if self.store.settings['history'] else 'disabled'}"
            if history
            else "No processing history yet."
        )

    def open_history(self, folder):
        row = self.history_table.currentRow()
        if 0 <= row < len(self.store.history):
            item = self.store.history[row]
            if item.get("status") != "Completed":
                self.show_error(MediaError("This job did not create a completed output."))
                return
            path = Path(item["output"])
            if folder:
                path = path.parent
            if not path.exists() or not open_local(path):
                self.show_error(MediaError("This output is no longer available at its saved location."))

    def remove_history(self):
        row = self.history_table.currentRow()
        if 0 <= row < len(self.store.history):
            del self.store.history[row]
            self.safe_save(lambda: self.store.write("history.json", self.store.history))
            self.refresh_history()

    def clear_history(self):
        if (
            self.store.history
            and QMessageBox.question(
                self, "Clear history", "Remove all saved history entries? Media files will be kept."
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.store.history.clear()
            self.safe_save(lambda: self.store.write("history.json", []))
            self.refresh_history()

    def open_settings(self):
        dialog = SettingsDialog(self.store.settings, self.caps, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.store.settings.update(dialog.values())
            self.safe_save(self.store.save_settings)
            apply_theme(QApplication.instance(), self.store.settings["theme"])
            self.workbench.directory.setText(self.store.settings["output_directory"])
            self.refresh_capabilities()
            self.refresh_history()

    def about(self):
        QMessageBox.about(
            self,
            "About Media Studio",
            f"Media Studio {__version__}\n\nA native Python desktop app for converting and compressing images, video and audio.\n\nBuilt with PySide6. Processing by FFmpeg; inspection by FFprobe.\n\nImage workflows export one still frame. Format and encoder choices are filtered against the installed tools.\n\nProject license: GPL version 2. FFmpeg and Qt retain their respective licenses.",
        )

    def safe_save(self, function):
        try:
            function()
        except MediaError as exc:
            if not self._closing:
                self.show_error(exc)

    def show_error(self, error):
        if self._closing:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Media Studio")
        box.setText(str(error))
        details = getattr(error, "details", "")
        if details:
            box.setDetailedText(details)
        box.exec()

    def closeEvent(self, event: QCloseEvent):
        if self.tasks or self.active or self.pool.activeThreadCount():
            event.ignore()
            if not self._closing:
                if (
                    self.active
                    and QMessageBox.question(
                        self,
                        "Close Media Studio",
                        "Cancel running jobs and close? Incomplete outputs will be removed.",
                    )
                    != QMessageBox.StandardButton.Yes
                ):
                    return
                self._closing = True
                self.cancel_jobs(True)
                self.setEnabled(False)
                self.statusBar().showMessage("Stopping media tools safely…")
            QTimer.singleShot(150, self.close)
            return
        event.accept()
