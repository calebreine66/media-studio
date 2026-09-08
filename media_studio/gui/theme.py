from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette


def apply_theme(app, choice: str) -> None:
    dark = choice == "dark" or choice == "system" and app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    colors = dict(
        bg="#15171D" if dark else "#F6F7FB",
        panel="#20232D" if dark else "#FFFFFF",
        sidebar="#191C24" if dark else "#FFFFFF",
        ink="#ECEEF5" if dark else "#202535",
        muted="#A5ADBF" if dark else "#717B90",
        border="#343A4A" if dark else "#E4E8F0",
        field="#282D3A" if dark else "#F9FAFD",
        purple="#9D8CFF" if dark else "#6854D8",
        tint="#332F4D" if dark else "#F0EDFC",
        green="#71D9AE" if dark else "#198560",
    )
    colors["assets"] = (Path(__file__).parent / "assets").as_posix()
    palette = QPalette()
    for role, key in (
        (QPalette.ColorRole.Window, "bg"),
        (QPalette.ColorRole.WindowText, "ink"),
        (QPalette.ColorRole.Base, "panel"),
        (QPalette.ColorRole.AlternateBase, "field"),
        (QPalette.ColorRole.Text, "ink"),
        (QPalette.ColorRole.Button, "panel"),
        (QPalette.ColorRole.ButtonText, "ink"),
        (QPalette.ColorRole.Highlight, "purple"),
    ):
        palette.setColor(role, QColor(colors[key]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(palette)
    app.setStyleSheet(
        """
        QWidget { color: %(ink)s; font-family: 'Inter', 'SF Pro Text', 'Segoe UI', 'DejaVu Sans'; font-size: 13px; }
        QMainWindow, QDialog, #page { background: %(bg)s; }
        QLabel { background: transparent; }
        QLabel#muted { color: %(muted)s; }
        QLabel#eyebrow { color: %(purple)s; font-size: 11px; font-weight: 700; letter-spacing: 2px; }
        QLabel#title { font-size: 30px; font-weight: 700; letter-spacing: -1px; }
        QLabel#sectionTitle { font-size: 17px; font-weight: 650; }
        QLabel#brand { font-size: 20px; font-weight: 750; letter-spacing: -0.5px; }
        QLabel#success { color: %(green)s; }
        QFrame#sidebar { background: %(sidebar)s; border-right: 1px solid %(border)s; }
        QFrame#panel { background: %(panel)s; border: 1px solid %(border)s; border-radius: 14px; }
        QFrame#subtle { background: %(field)s; border: 1px solid %(border)s; border-radius: 10px; }
        QFrame#drop { background: %(field)s; border: 2px dashed %(border)s; border-radius: 12px; }
        QFrame#hero { background: %(tint)s; border-radius: 18px; }
        QPushButton { background: %(panel)s; border: 1px solid %(border)s; border-radius: 8px;
                      padding: 9px 15px; font-weight: 550; min-height: 18px; }
        QPushButton:hover { background: %(tint)s; border-color: %(purple)s; }
        QPushButton:pressed { background: %(border)s; }
        QPushButton:disabled { color: %(muted)s; background: %(field)s; border-color: %(border)s; }
        QPushButton#primary { color: white; background: #6854D8; border-color: #6854D8; }
        QPushButton#primary:hover { background: #5944C3; }
        QPushButton#primary:disabled { color: #D4D0E8; background: #9C91C8; border-color: #9C91C8; }
        QPushButton#nav { text-align: left; border: none; padding: 12px 14px; background: transparent; }
        QPushButton#nav:checked { color: %(purple)s; background: %(tint)s; }
        QPushButton#nav:hover { background: %(field)s; }
        QPushButton#segment:checked { background: %(tint)s; color: %(purple)s; border-color: %(purple)s; }
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {
            background: %(field)s; border: 1px solid %(border)s; border-radius: 7px; padding: 7px 10px;
            selection-background-color: #6854D8; min-height: 18px; }
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: %(purple)s; }
        QComboBox { padding-right: 24px; }
        QComboBox::drop-down { border: none; width: 22px; }
        QComboBox::down-arrow { image: url("%(assets)s/chevron-down.svg"); width: 14px; height: 14px; }
        QSpinBox::up-button, QDoubleSpinBox::up-button { border: none; width: 20px; margin-top: 2px; }
        QSpinBox::down-button, QDoubleSpinBox::down-button { border: none; width: 20px; margin-bottom: 2px; }
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url("%(assets)s/chevron-up.svg"); width: 12px; height: 12px; }
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url("%(assets)s/chevron-down.svg"); width: 12px; height: 12px; }
        QComboBox QAbstractItemView { background: %(panel)s; selection-background-color: %(tint)s;
                                    selection-color: %(ink)s; border: 1px solid %(border)s; padding: 4px; }
        QCheckBox { spacing: 9px; padding: 5px 0; }
        QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid %(border)s;
                              border-radius: 4px; background: %(field)s; }
        QCheckBox::indicator:checked { background: #6854D8; border-color: #6854D8; image: url("%(assets)s/check.svg"); }
        QTabWidget::pane { border: 1px solid %(border)s; border-radius: 10px; background: %(panel)s; }
        QTabBar::tab { color: %(muted)s; padding: 10px 14px; margin-right: 3px; }
        QTabBar::tab:selected { color: %(purple)s; border-bottom: 2px solid %(purple)s; }
        QScrollArea { background: transparent; border: none; }
        QScrollArea > QWidget > QWidget { background: %(panel)s; }
        QListWidget, QTableWidget { background: %(panel)s; border: 1px solid %(border)s; border-radius: 9px;
                                   alternate-background-color: %(field)s; gridline-color: %(border)s; }
        QListWidget::item { padding: 9px; border-bottom: 1px solid %(border)s; }
        QListWidget::item:selected, QTableWidget::item:selected { background: %(tint)s; color: %(ink)s; }
        QTableWidget::item { padding: 9px; border: none; }
        QHeaderView::section { background: %(field)s; color: %(muted)s; padding: 11px 8px;
                               border: none; border-bottom: 1px solid %(border)s; font-size: 11px; font-weight: 650; }
        QProgressBar { background: %(border)s; border: none; border-radius: 4px; height: 8px; text-align: center; }
        QProgressBar::chunk { background: #7967DF; border-radius: 4px; }
        QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
        QScrollBar::handle:vertical { background: %(border)s; border-radius: 4px; min-height: 30px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QStatusBar { color: %(muted)s; background: %(sidebar)s; border-top: 1px solid %(border)s; }
        QToolTip { color: %(ink)s; background: %(panel)s; border: 1px solid %(border)s; padding: 8px; }
        QSplitter::handle { background: transparent; }
    """
        % colors
    )
