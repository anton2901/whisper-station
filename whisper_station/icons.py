"""Иконки в стиле «станция»: микрофон внутри орбиты, рисуются кодом.

Никаких файлов и зависимостей от темы: трей получает QPixmap, меню приложений —
совпадающий по рисунку SVG из `packaging/whisper-station.svg`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

# Единственный источник рисунка приложения: тот же SVG, что ставится в меню.
SVG_CANDIDATES = (
    Path("/usr/share/icons/hicolor/scalable/apps/whisper-station.svg"),
    Path(__file__).resolve().parent.parent / "packaging" / "whisper-station.svg",
)

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


def svg_path() -> Path | None:
    for candidate in SVG_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def app_icon() -> QIcon:
    """Иконка приложения: рендерим тот же SVG, что видит меню приложений."""
    path = svg_path()
    if path is not None:
        try:
            from PySide6.QtSvg import QSvgRenderer

            size = 256
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            QSvgRenderer(str(path)).render(painter, QRectF(0, 0, size, size))
            painter.end()
            return QIcon(pixmap)
        except Exception:  # noqa: BLE001 - без SVG остаётся запасной рисунок
            pass
    return _fallback_app_icon()


def _fallback_app_icon() -> QIcon:
    size = 256
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#101a2e"))
    painter.drawRoundedRect(QRectF(22, 22, size - 44, size - 44), 48, 48)
    painter.setBrush(QColor("#ffffff"))
    painter.drawRoundedRect(QRectF(110, 92, 36, 68), 18, 18)
    painter.setPen(QPen(QColor("#ffffff"), 10))
    painter.drawArc(QRectF(92, 100, 72, 64), 200 * 16, 140 * 16)
    painter.end()
    return QIcon(pixmap)
