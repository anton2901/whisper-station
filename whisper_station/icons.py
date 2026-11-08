"""Иконки в стиле «станция»: микрофон внутри орбиты, рисуются кодом.

Никаких файлов и зависимостей от темы: трей получает QPixmap, меню приложений —
совпадающий по рисунку SVG из `packaging/whisper-station.svg`.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPen, QPixmap

SIZE = 64
IDLE_COLOR = "#3f9fd8"
RECORDING_COLOR = "#d0504a"
BUSY_COLOR = "#c9a227"


def _base(color: str) -> QPixmap:
    pixmap = QPixmap(SIZE, SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QRectF(1, 1, SIZE - 2, SIZE - 2))
    return pixmap


def _draw_orbit(painter: QPainter, alpha: int = 210) -> None:
    pen = QPen(QColor(255, 255, 255, alpha), 2.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QRectF(12, 12, 40, 40))
    # «спутник» на орбите — маленькая точка сверху справа
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 235))
    painter.drawEllipse(QRectF(44, 13, 6, 6))


def _draw_mic(painter: QPainter) -> None:
    painter.setBrush(QColor("#ffffff"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(QRectF(27, 18, 10, 20), 5, 5)
    pen = QPen(QColor("#ffffff"), 3.2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(22, 24, 20, 20), 200 * 16, 140 * 16)
    painter.drawLine(32, 45, 32, 50)


def tray_icon(state: str) -> QIcon:
    color = {"recording": RECORDING_COLOR, "busy": BUSY_COLOR}.get(state, IDLE_COLOR)
    pixmap = _base(color)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    _draw_orbit(painter, alpha=150 if state == "idle" else 190)
    if state == "recording":
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(24, 24, 16, 16), 3, 3)
    elif state == "busy":
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(Qt.PenStyle.NoPen)
        for offset in (20, 29, 38):
            painter.drawEllipse(QRectF(offset, 29, 6, 6))
    else:
        _draw_mic(painter)
    painter.end()
    return QIcon(pixmap)


def app_icon() -> QIcon:
    """Иконка приложения: ночное небо, орбита, микрофон."""
    size = 256
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # Поля по краям: в меню приложений иконку иначе обрезает собственный маска-скругление.
    painter.translate(size / 2, size / 2)
    painter.scale(0.84, 0.84)
    painter.translate(-size / 2, -size / 2)

    gradient = QLinearGradient(0, 0, 0, size)
    gradient.setColorAt(0.0, QColor("#101a2e"))
    gradient.setColorAt(1.0, QColor("#060a12"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(QRectF(4, 4, size - 8, size - 8), 56, 56)

    # звёзды
    stars = ((48, 62, 2.6), (196, 78, 2.0), (74, 190, 1.8), (182, 178, 2.4), (128, 40, 1.6))
    for x, y, radius in stars:
        painter.setBrush(QColor(255, 255, 255, 150))
        painter.drawEllipse(QRectF(x - radius, y - radius, radius * 2, radius * 2))

    center = size / 2
    ring = QRectF(center - 74, center - 74, 148, 148)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    pen = QPen(QColor("#5fc4f5"), 9)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawArc(ring, 30 * 16, 300 * 16)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#bfe9ff"))
    painter.drawEllipse(QRectF(center + 56, center - 78, 20, 20))

    # микрофон
    painter.setBrush(QColor("#ffffff"))
    painter.drawRoundedRect(QRectF(center - 22, center - 52, 44, 82), 22, 22)
    pen = QPen(QColor("#ffffff"), 12)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(center - 42, center - 24, 84, 76), 200 * 16, 140 * 16)
    painter.drawLine(int(center), int(center + 52), int(center), int(center + 66))
    painter.end()
    return QIcon(pixmap)
