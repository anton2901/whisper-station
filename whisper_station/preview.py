"""Живой предпросмотр распознавания в HUD (эксперимент, по умолчанию выключен).

Пока идёт запись, раз в полтора секунды отправляем в Whisper последние
секунды аудио и показываем растущий текст внутри HUD. Целевое окно,
буфер обмена и вставка этого модуля не касаются: финальный текст по-прежнему
появляется у пользователя только после остановки записи.

Выключить: `[preview] live = false` (или галочка в настройках).
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QTimer, Signal

from .config import Config
from .recorder import Recorder, pcm_to_wav
from .stt import SttError, transcribe

log = logging.getLogger(__name__)

INTERVAL_MS = 1200
MAX_SECONDS = 15.0
TIMEOUT = 20.0


class Preview(QObject):
    """Периодическое распознавание накопленного аудио — только для HUD."""

    text_ready = Signal(str)

    def __init__(self, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self._recorder: Recorder | None = None
        self._busy = False
        self._text = ""
        self._timer = QTimer(self)
        self._timer.setInterval(INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    @property
    def active(self) -> bool:
        return self._recorder is not None

    def begin(self, recorder: Recorder) -> None:
        self._recorder = recorder
        self._busy = False
        self._text = ""
        self._timer.start()

    def end(self) -> None:
        self._timer.stop()
        self._text = ""
        self._recorder = None
        self._busy = False

    def _tick(self) -> None:
        recorder = self._recorder
        if recorder is None or self._busy:
            return
        if recorder.bytes_captured == 0:
            return
        self._busy = True
        pcm = recorder.snapshot(MAX_SECONDS)
        log.debug("preview: запрос, %.1f с аудио", len(pcm) / 2 / 16000)
        threading.Thread(target=self._work, args=(pcm,), daemon=True).start()

    def _work(self, pcm: bytes) -> None:
        try:
            result = transcribe(
                pcm_to_wav(pcm), self.cfg, timeout=TIMEOUT, retries=0
            )
            text = result.text.strip()
            # Отбрасываем только «обрезанный» ответ (он — префикс прежнего):
            # так строка не прыгает назад, но и не замирает на устаревшем тексте.
            if text and not (self._text and self._text.startswith(text)):
                self._text = text
                self.text_ready.emit(text)
        except SttError as exc:
            log.debug("preview: %s", exc)
        except Exception:  # noqa: BLE001 - предпросмотр не должен ломать запись
            log.debug("preview: ошибка", exc_info=True)
        finally:
            self._busy = False
