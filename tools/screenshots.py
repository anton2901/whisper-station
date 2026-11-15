#!/usr/bin/env python3
"""Скриншоты для README: HUD и окно настроек без живой сессии.

Запуск: QT_QPA_PLATFORM=offscreen python3 tools/screenshots.py
Пишет docs/screenshot-hud.png и docs/screenshot-settings.png.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from whisper_station.config import Config  # noqa: E402
from whisper_station.hud import HEIGHT, WIDTH, Hud  # noqa: E402
from whisper_station.service import ServerManager  # noqa: E402
from whisper_station.settings_ui import SettingsDialog  # noqa: E402

SCALE = 2
PAD = 24


def prepare_hud(app: QApplication) -> Hud:  # noqa: ARG001 - нужен живой QApplication
    hud = Hud()
    hud.begin_recording()
    hud.elapsed_text = lambda: "0:12"  # type: ignore[method-assign]
    hud.set_preview("Доброе утро! Начинаем запись совещания.")
    bands = []
    for index in range(120):
        level = 0.35 + 0.45 * abs(math.sin(index / 7.0)) * (0.6 + 0.4 * abs(math.sin(index / 2.3)))
        bands.append((max(0.02, level * 0.35), min(1.0, level)))
    hud.append_bands(bands)
    return hud


def render_hud(hud: Hud, path: Path) -> None:
    width = (WIDTH + PAD * 2) * SCALE
    height = (HEIGHT + PAD * 2) * SCALE
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    gradient = QLinearGradient(0, 0, 0, height)
    gradient.setColorAt(0.0, QColor("#191c22"))
    gradient.setColorAt(1.0, QColor("#0d0f13"))
    painter.fillRect(QRectF(0, 0, width, height), gradient)
    painter.scale(SCALE, SCALE)
    painter.translate(PAD, PAD)
    hud.render(painter, QPoint(0, 0))
    painter.end()
    image.save(str(path))


def render_settings(app: QApplication, path: Path) -> None:  # noqa: ARG001
    cfg = Config(
        hotkey="Meta+Alt+D",
        model_name="large-v3-turbo",
        dictionary_words=("Kubernetes", "ChargeBee", "PostgreSQL"),
        dictionary_threshold=0.18,
    )
    dialog = SettingsDialog(cfg, ServerManager(cfg))
    dialog.resize(600, 680)
    pixmap = dialog.grab()
    pixmap.save(str(path))


def main() -> int:
    app = QApplication.instance() or QApplication([])
    render_hud(prepare_hud(app), ROOT / "docs" / "screenshot-hud.png")
    render_settings(app, ROOT / "docs" / "screenshot-settings.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
