from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


PATHS = {
    "home": '<path d="m3 10 9-7 9 7v10H3z"/><path d="M9 20v-7h6v7"/>',
    "convert": '<path d="M4 7h15m-4-4 4 4-4 4M20 17H5m4-4-4 4 4 4"/>',
    "compress": '<path d="m4 4 6 6M4 10h6V4m10 16-6-6m0 6v-6h6"/>',
    "video": '<rect x="3" y="5" width="13" height="14" rx="3"/><path d="m16 10 5-3v10l-5-3"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-6 5 7"/>',
    "audio": '<path d="M9 18V5l11-2v13M9 8l11-2"/><ellipse cx="6" cy="18" rx="3" ry="3"/><ellipse cx="17" cy="16" rx="3" ry="3"/>',
    "queue": '<path d="M8 5h13M8 12h13M8 19h13"/><circle cx="3" cy="5" r="1"/><circle cx="3" cy="12" r="1"/><circle cx="3" cy="19" r="1"/>',
    "history": '<path d="M3 10a9 9 0 1 1 1 7M3 4v6h6m3-4v6l4 3"/>',
    "settings": '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="16" cy="17" r="3"/>',
    "folder": '<path d="M3 7V4h7l3 3h8v13H3z"/>',
    "plus": '<path d="M12 4v16M4 12h16"/>',
    "upload": '<path d="M12 16V3m-5 5 5-5 5 5M3 15v6h18v-6"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
    "arrow": '<path d="M4 12h16m-6-6 6 6-6 6"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-11v1"/>',
}


def icon(name: str, color: str = "#7B72A4", size: int = 22) -> QIcon:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        + PATHS.get(name, PATHS["info"])
        + "</svg>"
    )
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


def label(text: str, style: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if style:
        widget.setObjectName(style)
    return widget


def button(text: str, callback=None, primary: bool = False, glyph: str = "") -> QPushButton:
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        widget.setObjectName("primary")
    if glyph:
        widget.setIcon(icon(glyph, "#FFFFFF" if primary else "#7B72A4"))
        widget.setIconSize(QSize(18, 18))
    if callback:
        widget.clicked.connect(callback)
    return widget


def panel(title: str = "") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(14)
    if title:
        layout.addWidget(label(title, "sectionTitle"))
    return frame, layout


class DropZone(QFrame):
    files = Signal(list)
    browse = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("drop")
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)
        symbol = QLabel()
        symbol.setPixmap(icon("upload", "#8473E2", 30).pixmap(30, 30))
        symbol.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(symbol)
        title = label("Drop your files here", "sectionTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        subtitle = label("Add one file or a whole batch", "muted")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)
        browse = button("Browse files", self.browse.emit, glyph="plus")
        layout.addWidget(browse, alignment=Qt.AlignmentFlag.AlignCenter)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.files.emit([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
        event.acceptProposedAction()


class MediaArt(QWidget):
    def __init__(self, operation: str):
        super().__init__()
        self.operation = operation
        self.setMinimumHeight(130)
        self.setMaximumHeight(145)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        for dx, dy, angle, color in ((-53, 3, -12, "#E6E0FB"), (54, -2, 12, "#D9EAE9"), (0, 0, 0, "#FFFFFF")):
            painter.save()
            painter.translate(cx + dx, cy + dy)
            painter.rotate(angle)
            painter.setPen(QPen(QColor("#D5D1E7"), 1))
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(QRectF(-41, -47, 82, 94), 12, 12)
            name = "image" if dx < 0 else "audio" if dx > 0 else self.operation
            pixmap = icon(name, "#7460CA" if dx <= 0 else "#5C968B", 32).pixmap(32, 32)
            painter.drawPixmap(-16, -23, pixmap)
            painter.setPen(QPen(QColor("#D9D5E9"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(-19, 22, 19, 22)
            painter.restore()


class OperationCard(QFrame):
    chosen = Signal(str, str)

    def __init__(self, operation: str):
        super().__init__()
        self.setObjectName("panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(13)
        layout.addWidget(MediaArt(operation))
        heading = label(
            "Convert your media" if operation == "convert" else "Make room for more", "sectionTitle"
        )
        layout.addWidget(heading)
        layout.addWidget(
            label(
                "The right format for wherever it goes."
                if operation == "convert"
                else "Smaller files. Quality on your terms.",
                "muted",
                True,
            )
        )
        row = QHBoxLayout()
        for kind in ("video", "image", "audio"):
            btn = button(
                kind.title(), lambda checked=False, k=kind: self.chosen.emit(operation, k), glyph=kind
            )
            row.addWidget(btn)
        layout.addLayout(row)
        layout.addWidget(
            button(
                "Start converting" if operation == "convert" else "Start compressing",
                lambda: self.chosen.emit(operation, "video"),
                primary=operation == "convert",
                glyph="arrow",
            )
        )
