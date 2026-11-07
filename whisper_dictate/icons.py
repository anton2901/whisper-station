"""Иконки трея рисуются кодом: без файлов и без зависимостей от темы."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

SIZE = 64
IDLE_COLOR = "#3d6ea8"
RECORDING_COLOR = "#c0392b"
BUSY_COLOR = "#b8860b"


def _pixmap(color: str) -> QPixmap:
    pixmap = QPixmap(SIZE, SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QRectF(2, 2, SIZE - 4, SIZE - 4))
    return pixmap


def _draw_mic(painter: QPainter) -> None:
    painter.setBrush(QColor("#ffffff"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(QRectF(26, 14, 12, 24), 6, 6)
    pen = QPen(QColor("#ffffff"), 4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(20, 22, 24, 24), 200 * 16, 140 * 16)
    painter.drawLine(32, 46, 32, 52)
    painter.drawLine(24, 52, 40, 52)


def tray_icon(state: str) -> QIcon:
    color = {"recording": RECORDING_COLOR, "busy": BUSY_COLOR}.get(state, IDLE_COLOR)
    pixmap = _pixmap(color)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if state == "recording":
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(22, 22, 20, 20), 4, 4)
    elif state == "busy":
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(Qt.PenStyle.NoPen)
        for offset in (20, 30, 40):
            painter.drawEllipse(QRectF(offset, 29, 6, 6))
    else:
        _draw_mic(painter)
    painter.end()
    return QIcon(pixmap)


def app_icon() -> QIcon:
    pixmap = _pixmap(IDLE_COLOR)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    _draw_mic(painter)
    painter.end()
    return QIcon(pixmap)
