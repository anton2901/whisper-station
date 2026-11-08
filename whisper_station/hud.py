"""HUD записи в стиле «станция»: широкая низкая панель с лентой осциллограммы.

На Wayland клиент не управляет позицией окна — координаты задаёт правило KWin
(`rules.py`), поэтому здесь только размеры и отрисовка. HUD забирает фокус на
время записи: иначе не работают Esc и кнопки. Перед вставкой контроллер его
прячет, и фокус возвращается в целевое окно.
"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import QElapsedTimer, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QWidget

# Заголовок — маркер для правила KWin; окно настроек его не содержит.
TITLE = "Whisper Station HUD"

WIDTH = 480
HEIGHT = 64
WAVE_BARS = 150

BG = QColor(9, 12, 20, 235)
BORDER = QColor(110, 200, 255, 90)
TEXT = QColor(234, 246, 255)
MUTED = QColor(143, 160, 184)
ACCENT = QColor(127, 208, 255)
MAGENTA = QColor(255, 159, 240)
DOT_RECORDING = QColor(224, 90, 79)
DOT_BUSY = QColor(224, 176, 80)
GRID = QColor(255, 255, 255, 10)
TICK = QColor(224, 176, 80, 60)
CENTER_LINE = QColor(255, 255, 255, 24)
WAVE_GAIN = 2.0


def _blend(first: QColor, second: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        int(first.red() + (second.red() - first.red()) * t),
        int(first.green() + (second.green() - first.green()) * t),
        int(first.blue() + (second.blue() - first.blue()) * t),
    )


def _ribbon_color(t: float) -> QColor:
    """Циан → сиреневый → маджента."""
    if t < 0.55:
        return _blend(ACCENT, QColor(150, 160, 255), t / 0.55)
    return _blend(QColor(150, 160, 255), MAGENTA, (t - 0.55) / 0.45)


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
        self._preview_text = ""
        self._bands: deque[tuple[float, float]] = deque(maxlen=WAVE_BARS)
        self._elapsed = QElapsedTimer()
        self._tick = QTimer(self)
        self._tick.setInterval(80)
        self._tick.timeout.connect(self.update)

        self._stop_button = QPushButton("Стоп", self)
        self._cancel_button = QPushButton("Отмена", self)
        for button in (self._stop_button, self._cancel_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._stop_button.setStyleSheet(
            "QPushButton { background: rgba(224,90,79,180); border: none;"
            " border-radius: 6px; color: #fff; font-size: 8.5pt; padding: 0; }"
            "QPushButton:hover { background: rgba(232,110,98,225); }"
        )
        self._cancel_button.setStyleSheet(
            "QPushButton { background: transparent; border: none;"
            " border-radius: 6px; color: #8fa0b8; font-size: 8.5pt; padding: 0; }"
            "QPushButton:hover { color: #d8e8f8; background: rgba(255,255,255,26); }"
        )
        self._stop_button.clicked.connect(self.stop_requested)
        self._cancel_button.clicked.connect(self.cancel_requested)
        self._layout_buttons()

    # --- состояние ------------------------------------------------------
    @property
    def state(self) -> str:
        return self._state

    def set_preview(self, text: str) -> None:
        """Показать живой предпросмотр распознавания (эксперимент)."""
        self._preview_text = text.strip()
        self.update()

    def begin_recording(self) -> None:
        self._state = "recording"
        self._preview_text = ""
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
        self._preview_text = ""
        self._preview_text = ""
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
        self._stop_button.setGeometry(WIDTH - 16 - 54, 20, 54, 24)
        self._cancel_button.setGeometry(WIDTH - 16 - 54 - 4 - 66, 20, 66, 24)

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
        return QRectF(148, 12, WIDTH - 148 - 160, HEIGHT - 26)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        panel = QRectF(0.5, 0.5, WIDTH - 1, HEIGHT - 1)

        painter.setPen(QPen(BORDER, 1))
        painter.setBrush(BG)
        painter.drawRoundedRect(panel, 14, 14)

        self._paint_grid(painter, panel)
        self._paint_ticks(painter, panel)

        wave = self._wave_rect()
        mid = wave.center().y()
        painter.setPen(QPen(CENTER_LINE, 1))
        painter.drawLine(
            int(wave.left()) + 2, int(mid), int(wave.right()) - 2, int(mid)
        )
        self._paint_wave(painter, wave)
        self._paint_header(painter)
        painter.end()

    def _paint_grid(self, painter: QPainter, panel: QRectF) -> None:
        painter.save()
        painter.setClipRect(panel.adjusted(1, 1, -1, -1))
        painter.setPen(QPen(GRID, 1))
        x = panel.left() + 20
        while x < panel.right() - 10:
            painter.drawLine(int(x), int(panel.top()) + 6, int(x), int(panel.bottom()) - 8)
            x += 34
        painter.restore()

    def _paint_ticks(self, painter: QPainter, panel: QRectF) -> None:
        painter.setPen(QPen(TICK, 1))
        x = panel.left() + 150
        while x < panel.right() - 150:
            painter.drawLine(int(x), int(panel.bottom()) - 5, int(x), int(panel.bottom()) - 9)
            x += 22

    def _paint_header(self, painter: QPainter) -> None:
        recording = self._state == "recording"
        dot_color = DOT_RECORDING if recording else DOT_BUSY
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot_color if self._state != "idle" else MUTED)
        painter.drawEllipse(QRectF(16, 22, 8, 8))

        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSizeF(8.5)
        painter.setFont(mono)
        painter.setPen(ACCENT)
        painter.drawText(30, 20, "REC" if recording else "…")
        painter.setFont(mono)
        painter.setPen(TEXT)
        timer_font = QFont(mono)
        timer_font.setPointSizeF(13)
        painter.setFont(timer_font)
        painter.drawText(60, 22, self.elapsed_text())

        label_font = QFont(mono)
        label_font.setPointSizeF(7.0)
        label_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
        painter.setFont(label_font)
        painter.setPen(MUTED)
        if self._preview_text:
            painter.setPen(ACCENT)
            metrics = painter.fontMetrics()
            text = metrics.elidedText(
                self._preview_text, Qt.TextElideMode.ElideRight, WIDTH - 200
            )
            painter.drawText(30, HEIGHT - 10, text)
        else:
            label = "Распознаю…" if self._state == "transcribing" else "WHISPER STATION"
            painter.setPen(MUTED)
            painter.drawText(30, HEIGHT - 10, label)


    def _paint_wave(self, painter: QPainter, wave: QRectF) -> None:
        count = len(self._bands)
        if count < 2:
            return
        half = wave.height() / 2 - 1
        step = wave.width() / WAVE_BARS
        offset = WAVE_BARS - count
        mid = wave.center().y()

        painter.save()
        painter.setClipRect(wave.adjusted(-2, -2, 2, 2))
        for index, (low, high) in enumerate(self._bands):
            x = wave.left() + (offset + index + 0.5) * step
            color = _ribbon_color(index / max(1, count - 1))
            top = mid - max(-1.0, min(1.0, high * WAVE_GAIN)) * half
            bottom = mid - max(-1.0, min(1.0, low * WAVE_GAIN)) * half
            painter.setPen(QPen(color, 1.8))
            painter.drawLine(int(x) - 3, int(top), int(x) + 3, int(top))
            faint = QColor(color)
            faint.setAlpha(120)
            painter.setPen(QPen(faint, 1.2))
            painter.drawLine(int(x) - 3, int(bottom), int(x) + 3, int(bottom))
        painter.restore()
