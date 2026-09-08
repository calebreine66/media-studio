from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from media_studio.gui.main_window import MainWindow
from media_studio.gui.theme import apply_theme
from media_studio.storage import Store


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Media Studio")
    app.setOrganizationName("Media Studio")
    app.setStyle("Fusion")
    store = Store()
    apply_theme(app, store.settings["theme"])
    window = MainWindow(store)
    window.show()
    sys.exit(app.exec())
