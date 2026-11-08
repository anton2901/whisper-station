#!/usr/bin/env python3
"""Экспорт PNG и контактный лист бренд-пака whisper-station.

Источник рисунка один — `brand/app.svg` (он же ставится в систему как
иконка приложения). Скрипт не рисует иконку заново, а только рендерит
её в нужных размерах и собирает `board.png`.

Запуск: python3 brand/make_board.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPen,
)
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).parent
APP_SVG = ROOT / "app.svg"
TRAY_SVG = ROOT / "tray.svg"
APP_SIZES = (512, 256, 128, 64)
TRAY_SIZES = (16, 22, 32)

PALETTE = (
    ("#101a2e", "космос, верх"),
    ("#060a12", "космос, низ"),
    ("#5fc4f5", "орбита"),
    ("#bfe9ff", "луна"),
    ("#eaf6ff", "текст"),
    ("#8fa0b8", "вторичный"),
    ("#e05a4f", "запись"),
    ("#e0b050", "ожидание"),
)

BG = QColor("#14141a")
TEXT = QColor("#eaeaf2")
MUTED = QColor("#8f90a0")


def render_svg(svg: str, size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(
        painter, QRectF(0, 0, size, size)
    )
    painter.end()
    return image


def tray_svg(ink: str) -> str:
    return TRAY_SVG.read_text(encoding="utf-8").replace("#000000", ink)


def export_pngs() -> None:
    app_svg = APP_SVG.read_text(encoding="utf-8")
    for size in APP_SIZES:
        render_svg(app_svg, size).save(str(ROOT / f"app-{size}.png"))
    for ink, name in (("#14141a", "light"), ("#f2f3f7", "dark")):
        for size in TRAY_SIZES:
            render_svg(tray_svg(ink), size).save(str(ROOT / f"tray-{name}-{size}.png"))
    print("PNG: app-* и tray-{light,dark}-* записаны")


def _text(painter: QPainter, x: float, y: float, text: str, size: float,
          color: QColor = TEXT, bold: bool = False, mono: bool = False) -> None:
    font = QFont("monospace" if mono else "DejaVu Sans")
    font.setPointSizeF(size)
    font.setBold(bold)
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(QRectF(x, y, 900, size * 2.4), int(Qt.AlignmentFlag.AlignLeft), text)


def _strip(painter: QPainter, x: float, y: float, title: str, dark: bool) -> None:
    bg = QColor("#191920") if dark else QColor("#ececf1")
    ink = "dark" if dark else "light"
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(bg)
    painter.drawRoundedRect(QRectF(x, y, 520, 96), 12, 12)
    _text(painter, x + 18, y + 8, title, 10, MUTED if dark else QColor("#6b6f7a"))
    cursor = x + 18
    for size in TRAY_SIZES:
        glyph = render_svg(tray_svg("#f2f3f7" if dark else "#14141a"), size)
        icon_y = y + 44 + (32 - size) / 2
        painter.drawImage(QRectF(cursor, icon_y, size, size), glyph)
        _text(painter, cursor, y + 78, f"{size}", 7, MUTED if dark else QColor("#6b6f7a"), mono=True)
        cursor += 64
    label = f"{ink} панель"
    _text(painter, x + 250, y + 50, label, 10, MUTED if dark else QColor("#6b6f7a"))


def build_board() -> None:
    width, height = 1600, 1060
    board = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    board.fill(BG)
    painter = QPainter(board)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    _text(painter, 56, 40, "whisper-station", 34, TEXT, bold=True)
    _text(painter, 56, 96, "Локальная диктовка · бренд-пак 0.3.0", 13, MUTED)
    _text(painter, 56, 122, "Иконка приложения — микрофон в орбите; трей — монохромный глиф",
          11, MUTED)

    # иконка приложения и размеры
    app_svg = APP_SVG.read_text(encoding="utf-8")
    painter.drawImage(QRectF(56, 180, 256, 256), render_svg(app_svg, 256))
    _text(painter, 56, 448, "app.svg / app.png", 10, MUTED, mono=True)
    cursor = 360
    baseline = 180 + 256
    for size in (128, 64, 32):
        painter.drawImage(QRectF(cursor, baseline - size, size, size), render_svg(app_svg, size))
        _text(painter, cursor, baseline + 10, f"{size}px", 8, MUTED, mono=True)
        cursor += size + 56

    # трей
    _strip(painter, 56, 520, "tray", dark=False)
    _strip(painter, 620, 520, "tray", dark=True)
    _text(painter, 56, 640, "16 / 22 / 32 px, отдельные файлы для светлой и тёмной панели",
          10, MUTED)

    # палитра
    _text(painter, 56, 690, "Палитра", 18, TEXT, bold=True)
    x, y = 56, 730
    for index, (color, note) in enumerate(PALETTE):
        if index == 4:
            x, y = 56, 830
        painter.setPen(QPen(QColor(255, 255, 255, 28), 1))
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(QRectF(x, y, 120, 56), 8, 8)
        _text(painter, x, y + 60, color, 8.5, TEXT, mono=True)
        _text(painter, x, y + 78, note, 7.5, MUTED)
        x += 150

    # образец HUD
    hud = QRectF(960, 690, 580, 92)
    gradient = QLinearGradient(0, hud.top(), 0, hud.bottom())
    gradient.setColorAt(0.0, QColor(16, 26, 46, 240))
    gradient.setColorAt(1.0, QColor(6, 10, 18, 240))
    painter.setPen(QPen(QColor(95, 196, 245, 110), 1))
    painter.setBrush(gradient)
    painter.drawRoundedRect(hud, 16, 16)
    _text(painter, hud.left() + 20, hud.top() + 18, "● REC  0:07", 12, QColor("#7fd0ff"), mono=True)
    _text(painter, hud.left() + 20, hud.top() + 52, "WHISPER STATION", 8, QColor("#8fa0b8"), mono=True)
    wave = QRectF(hud.left() + 210, hud.center().y() - 14, hud.width() - 240, 28)
    pen = QPen(QColor("#5fc4f5"), 2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    import math
    for step in range(0, int(wave.width()) - 6, 6):
        phase = step / wave.width()
        amp = 0.15 + 0.85 * abs(math.sin(phase * 13)) * (0.5 + 0.5 * math.sin(phase * 3))
        y = wave.center().y() - amp * 12
        painter.drawLine(int(wave.left() + step), int(y), int(wave.left() + step + 3), int(y))
    _text(painter, 960, 800, "HUD: 480×64, градиентная лента, моно-подпись", 10, MUTED)

    _text(painter, 56, 980, "Файлы: app.svg, app-512/256/128/64.png, tray.svg, "
                            "tray-{light,dark}-{16,22,32}.png, board.png", 10, MUTED, mono=True)
    painter.end()
    board.save(str(ROOT / "board.png"))
    print("board.png собран")


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1] or ["brand"])
    del app
    export_pngs()
    build_board()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
