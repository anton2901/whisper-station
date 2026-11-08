"""Живой предпросмотр распознавания в HUD.

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

INTERVAL_MS = 1800
MAX_SECONDS = 8.0
TIMEOUT = 20.0


def _words(items: list[str]) -> list[str]:
    return [item.strip(".,!?;:—-\"'«»()").lower() for item in items]


def merge_text(previous: str, fresh: str) -> str:
    """Склеить новый фрагмент с накопленным по перекрытию слов.

    Окно предпросмотра скользит, поэтому каждый ответ начинается не с начала
    фразы. Ищем максимальное перекрытие «хвост старого == начало нового» и
    дописываем только новую часть. Без перекрытия: короткий ответ считаем
    артефактом тишины и оставляем прежний текст (строка застывает).
    """
    fresh = fresh.strip()
    if not fresh:
        return previous
    if not previous:
        return fresh
    if fresh.startswith(previous):
        return fresh
    if previous.startswith(fresh):
        return previous
    old_words, new_words = previous.split(), fresh.split()
    limit = min(len(old_words), len(new_words))
    for size in range(limit, 0, -1):
        if _words(old_words[-size:]) == _words(new_words[:size]):
            return " ".join(old_words + new_words[size:])
    if len(new_words) * 2 < len(old_words):
        return previous
    return fresh


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
            merged = merge_text(self._text, result.text)
            if merged and merged != self._text:
                self._text = merged
                self.text_ready.emit(merged)
        except SttError as exc:
            log.debug("preview: %s", exc)
        except Exception:  # noqa: BLE001 - предпросмотр не должен ломать запись
            log.debug("preview: ошибка", exc_info=True)
        finally:
            self._busy = False
