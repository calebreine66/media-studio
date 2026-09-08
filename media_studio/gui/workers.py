from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class TaskSignals(QObject):
    result = Signal(object)
    error = Signal(object)
    progress = Signal(object)
    finished = Signal()


class Task(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = TaskSignals()

    @Slot()
    def run(self):
        try:
            self.signals.result.emit(self.function(self.signals.progress.emit))
        except Exception as exc:
            self.signals.error.emit(exc)
        finally:
            self.signals.finished.emit()
