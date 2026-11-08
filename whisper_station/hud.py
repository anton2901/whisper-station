"""HUD записи: компактная панель с осциллограммой уровня.

На Wayland клиент не управляет позицией окна — координаты задаёт правило KWin
(`rules.py`), поэтому здесь только размеры и отрисовка. HUD забирает фокус на
время записи: иначе не работают Esc и кнопки. Перед вставкой контроллер его
прячет, и фокус возвращается в целевое окно.
"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import QElapsedTimer, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QPushButton, QWidget

# Заголовок — маркер для правила KWin; окно настроек его не содержит.
TITLE = "Whisper Station HUD"

WIDTH = 300
HEIGHT = 68
WAVE_BARS = 84

BG = QColor(22, 22, 26, 240)
BORDER = QColor(255, 255, 255, 38)
TEXT = QColor(238, 238, 242)
MUTED = QColor(148, 150, 160)
DOT_RECORDING = QColor("#e05a4f")
DOT_BUSY = QColor("#e0b050")
WAVE_TOP = QColor(150, 220, 255, 235)
WAVE_BOTTOM = QColor(70, 130, 200, 210)
WAVE_BG = QColor(255, 255, 255, 14)
WAVE_MID = QColor(255, 255, 255, 26)
WAVE_GAIN = 2.2  # речь редко доходит до полной шкалы — растягиваем по вертикали


class Hud(QWidget):
    stop_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setWindowTitle(TITLE)
        self.setFixedSize(WIDTH, HEIGHT)

        self._state = "idle"
        self._bands: deque[tuple[float, float]] = deque(maxlen=WAVE_BARS)
        self._elapsed = QElapsedTimer()
        self._tick = QTimer(self)
        self._tick.setInterval(80)
        self._tick.timeout.connect(self.update)

        self._stop_button = QPushButton("Стоп", self)
        self._cancel_button = QPushButton("✕", self)
        for button in (self._stop_button, self._cancel_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._stop_button.setStyleSheet(
            "QPushButton { background: rgba(224,90,79,205); border: none;"
            " border-radius: 7px; color: #fff; font-size: 8.5pt; padding: 0; }"
            "QPushButton:hover { background: rgba(232,110,98,235); }"
        )
        self._cancel_button.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid rgba(255,255,255,60);"
            " border-radius: 7px; color: #d8d8de; font-size: 9pt; padding: 0; }"
            "QPushButton:hover { background: rgba(255,255,255,38); }"
        )
        self._stop_button.clicked.connect(self.stop_requested)
        self._cancel_button.clicked.connect(self.cancel_requested)
        self._layout_buttons()

    # --- состояние ------------------------------------------------------
    @property
    def state(self) -> str:
        return self._state

    def begin_recording(self) -> None:
        self._state = "recording"
        self._bands.clear()
        self._elapsed.restart()
        self._tick.start()
        self.show_hud()

    def begin_transcribing(self) -> None:
        self._state = "transcribing"
        self._tick.stop()
        self.update()

    def finish(self) -> None:
        self._tick.stop()
        self._state = "idle"
        self._bands.clear()
        self.hide()

    def show_hud(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self._place()

    def append_bands(self, bands: list[tuple[float, float]]) -> None:
        if self._state == "recording":
            self._bands.extend(bands)

    def elapsed_text(self) -> str:
        seconds = int(self._elapsed.elapsed() / 1000) if self._elapsed.isValid() else 0
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes}:{seconds:02d}"

    # --- события --------------------------------------------------------
    def _layout_buttons(self) -> None:
        self._stop_button.setGeometry(WIDTH - 12 - 50, 5, 50, 22)
        self._cancel_button.setGeometry(WIDTH - 12 - 50 - 6 - 24, 5, 24, 22)

    def _place(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2, area.top() + 72)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    # --- отрисовка ------------------------------------------------------
    def _wave_rect(self) -> QRectF:
        return QRectF(12, 28, WIDTH - 24, HEIGHT - 28 - 10)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        painter.setPen(QPen(BORDER, 1))
        painter.setBrush(BG)
        painter.drawRoundedRect(QRectF(0.5, 0.5, WIDTH - 1, HEIGHT - 1), 12, 12)

        wave = self._wave_rect()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(WAVE_BG)
        painter.drawRoundedRect(wave, 8, 8)

        painter.setClipRect(wave.adjusted(2, 2, -2, -2))
        mid = wave.center().y()
        painter.setPen(QPen(WAVE_MID, 1))
        painter.drawLine(int(wave.left()) + 4, int(mid), int(wave.right()) - 4, int(mid))
        self._paint_wave(painter, wave)
        painter.setClipping(False)

        self._paint_header(painter)
        painter.end()

    def _paint_header(self, painter: QPainter) -> None:
        dot_color = DOT_RECORDING if self._state == "recording" else DOT_BUSY
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot_color if self._state != "idle" else MUTED)
        painter.drawEllipse(QRectF(14, 11, 7, 7))

        font = QFont(self.font())
        font.setPointSizeF(10.5)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(TEXT)
        timer = self.elapsed_text()
        timer_width = painter.fontMetrics().horizontalAdvance(timer)
        painter.drawText(28, 20, timer)

        font.setBold(False)
        font.setPointSizeF(8.5)
        painter.setFont(font)
        painter.setPen(MUTED)
        label = "Распознаю…" if self._state == "transcribing" else "Запись"
        painter.drawText(28 + timer_width + 9, 20, label)

    def _paint_wave(self, painter: QPainter, wave: QRectF) -> None:
        count = len(self._bands)
        if count < 2:
            return
        half = wave.height() / 2 - 2
        step = (WIDTH - 24) / WAVE_BARS
        offset = WAVE_BARS - count
        mid = wave.center().y()

        path = QPainterPath()
        first_x = None
        for index, (_, high) in enumerate(self._bands):
            x = wave.left() + (offset + index + 0.5) * step
            y = mid - max(-1.0, min(1.0, high * WAVE_GAIN)) * half
            if index == 0:
                path.moveTo(x, y)
                first_x = x
            else:
                path.lineTo(x, y)
        for index in range(count - 1, -1, -1):
            low = self._bands[index][0]
            x = wave.left() + (offset + index + 0.5) * step
            path.lineTo(x, mid - max(-1.0, min(1.0, low * WAVE_GAIN)) * half)
        path.closeSubpath()

        gradient = QLinearGradient(0, mid - half, 0, mid + half)
        gradient.setColorAt(0.0, WAVE_TOP)
        gradient.setColorAt(1.0, WAVE_BOTTOM)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawPath(path)

        if first_x is not None:
            painter.setPen(QPen(QColor(200, 240, 255, 160), 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            top = QPainterPath()
            for index, (_, high) in enumerate(self._bands):
                x = wave.left() + (offset + index + 0.5) * step
                y = mid - max(-1.0, min(1.0, high * WAVE_GAIN)) * half
                if index == 0:
                    top.moveTo(x, y)
                else:
                    top.lineTo(x, y)
            painter.drawPath(top)
