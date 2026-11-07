"""HUD записи: маленькое окно без рамки, индикатор уровня, таймер, Стоп/Отмена.

На Wayland клиент не управляет позицией окна — KWin размещает HUD сам,
поэтому move() здесь только подсказка. HUD забирает фокус на время записи:
иначе Esc и кнопки не работают (KWin не отдаёт клавиатуру окну без фокуса).
Перед вставкой контроллер прячет HUD — и фокус возвращается в целевое окно.
"""

from __future__ import annotations

from PySide6.QtCore import QElapsedTimer, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QWidget

BG = QColor(24, 24, 28, 236)
BORDER = QColor(255, 255, 255, 44)
TEXT = QColor(236, 236, 240)
MUTED = QColor(160, 162, 170)
ACCENT = QColor("#7fb2ff")
LEVEL = QColor("#8ee08e")

# Заголовок — маркер для правила KWin; окно настроек его не содержит.
TITLE = "Whisper Dictate HUD"


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
        self.resize(360, 104)
        self.setMinimumSize(320, 96)

        self._state = "idle"
        self._level = 0.0
        self._shown_level = 0.0
        self._elapsed = QElapsedTimer()
        self._tick = QTimer(self)
        self._tick.setInterval(100)
        self._tick.timeout.connect(self._on_tick)

        self._stop_button = QPushButton("Стоп", self)
        self._cancel_button = QPushButton("Отмена", self)
        for button in (self._stop_button, self._cancel_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setStyleSheet(
                "QPushButton { background: rgba(255,255,255,26);"
                " border: 1px solid rgba(255,255,255,55); border-radius: 9px;"
                " color: #ececf0; padding: 2px 10px; font-size: 12px; }"
                "QPushButton:hover { background: rgba(255,255,255,52); }"
            )
        self._stop_button.clicked.connect(self.stop_requested)
        self._cancel_button.clicked.connect(self.cancel_requested)

    # --- состояние ------------------------------------------------------
    @property
    def state(self) -> str:
        return self._state

    def begin_recording(self) -> None:
        self._state = "recording"
        self._level = 0.0
        self._shown_level = 0.0
        self._elapsed.restart()
        self._tick.start()
        self._stop_button.setEnabled(True)
        self.show_hud()

    def begin_transcribing(self) -> None:
        self._state = "transcribing"
        self._tick.stop()
        self.set_level(0.0)
        self.update()

    def finish(self) -> None:
        self._tick.stop()
        self._state = "idle"
        self.hide()

    def show_hud(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self._place()

    def set_level(self, value: float) -> None:
        self._level = max(0.0, min(1.0, value))

    def elapsed_text(self) -> str:
        seconds = int(self._elapsed.elapsed() / 1000) if self._elapsed.isValid() else 0
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes}:{seconds:02d}"

    # --- события --------------------------------------------------------
    def _on_tick(self) -> None:
        # Атака быстрая, спад плавный: индикатор успевает за слогами речи.
        factor = 0.75 if self._level > self._shown_level else 0.28
        self._shown_level += (self._level - self._shown_level) * factor
        self._level = max(0.0, self._level - 0.04)
        self.update()

    def _place(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2, area.bottom() - self.height() - 64)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        height = 26
        width = 74
        self._stop_button.setGeometry(self.width() - width - 14, self.height() - height - 12, width, height)
        self._cancel_button.setGeometry(
            self.width() - 2 * width - 22, self.height() - height - 12, width, height
        )

    # --- отрисовка ------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(BORDER, 1))
        painter.setBrush(BG)
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 14, 14)

        title = "Распознаю…" if self._state == "transcribing" else f"Запись   {self.elapsed_text()}"
        font = QFont(self.font())
        font.setPointSizeF(10.5)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(TEXT if self._state != "transcribing" else ACCENT)
        painter.drawText(16, 26, title)

        font.setBold(False)
        font.setPointSizeF(8.5)
        painter.setFont(font)
        painter.setPen(MUTED)
        painter.drawText(16, self.height() - 14, "Esc — отмена без вставки")

        track = QRectF(16, 34, self.width() - 32, 10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 26))
        painter.drawRoundedRect(track, 5, 5)
        if self._state == "recording":
            filled = QRectF(
                track.left(),
                track.top(),
                max(6.0, track.width() * self._shown_level),
                track.height(),
            )
            painter.setBrush(LEVEL)
            painter.drawRoundedRect(filled, 5, 5)
        painter.end()
