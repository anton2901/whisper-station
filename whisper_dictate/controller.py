"""Состояния диктовки: idle → starting → recording → transcribing → idle."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from .config import Config
from .inject import inject_text
from .recorder import Recorder, RecorderError, normalize_pcm, wav_duration, wav_peak
from .service import ServerManager, ServerStatus
from .stt import SttError, is_probable_hallucination, transcribe

log = logging.getLogger(__name__)

IDLE = "idle"

# Короче этого удержание считаем случайным тапом и просто отменяем запись.
MIN_HOLD_SECONDS = 0.35
# Пик ниже — цифровая тишина (шум комнаты на этой машине ~0.004).
SILENCE_PEAK = 0.008
# Пик ниже этого — запись тихая: подозрительные фразы отбрасываем.
WEAK_PEAK = 0.05
STARTING = "starting"
RECORDING = "recording"
TRANSCRIBING = "transcribing"


class Controller(QObject):
    """Управляет записью, распознаванием и вставкой. Вся работа с Qt — в главном потоке."""

    state_changed = Signal(str)
    wave_changed = Signal(object)  # полосы осциллограммы (min, max)
    server_status = Signal(object)
    notify_requested = Signal(str, str, str)  # заголовок, текст, важность

    _server_ready = Signal(object)
    _server_failed = Signal(str)
    _transcribed = Signal(str, int)
    _transcribe_failed = Signal(str)

    def __init__(self, cfg: Config, server: ServerManager, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.server = server
        self.state = IDLE
        self._hud = None
        self._recorder: Recorder | None = None
        self._generation = 0
        self._last_peak = 1.0
        self._max_timer = QTimer(self)
        self._max_timer.setSingleShot(True)
        self._max_timer.timeout.connect(self.stop)

        queued = Qt.ConnectionType.QueuedConnection
        self._server_ready.connect(self._on_server_ready, queued)
        self._server_failed.connect(self._on_error, queued)
        self._transcribed.connect(self._on_transcribed, queued)
        self._transcribe_failed.connect(self._on_error, queued)

    # --- подключение UI -------------------------------------------------
    def set_hud(self, hud) -> None:
        self._hud = hud

    # --- команды --------------------------------------------------------
    def toggle(self) -> None:
        if self.state == IDLE:
            self.start()
        elif self.state == RECORDING:
            self.stop()

    def start(self) -> None:
        if self.state != IDLE:
            log.debug("controller: start проигнорирован в состоянии %s", self.state)
            return
        self._generation += 1
        generation = self._generation
        self._set_state(STARTING)
        threading.Thread(
            target=self._prepare, args=(generation,), name="whisper-prepare", daemon=True
        ).start()

    def press_start(self) -> None:
        """Push-to-talk: клавиша нажата — начинаем запись."""
        if self.state == IDLE:
            self.start()

    def press_stop(self) -> None:
        """Push-to-talk: клавиша отпущена — останавливаем и распознаём."""
        if self.state == STARTING:
            # Отпустили раньше, чем поднялся сервер: отменяем запуск.
            self.cancel()
            return
        if self.state != RECORDING:
            return
        if self._recorder is not None and self._recorder.elapsed < MIN_HOLD_SECONDS:
            log.info("controller: удержание %.2f с — отменяю", self._recorder.elapsed)
            self.cancel()
            return
        self.stop()

    def stop(self) -> None:
        if self.state != RECORDING:
            return
        self._max_timer.stop()
        recorder, self._recorder = self._recorder, None
        self._set_state(TRANSCRIBING)
        if self._hud is not None:
            self._hud.begin_transcribing()
        if recorder is None:
            self._set_state(IDLE)
            return
        try:
            wav = recorder.stop()
        except RecorderError as exc:
            self._on_error(str(exc))
            return
        duration = wav_duration(wav)
        if duration < 0.25:
            # Быстрый двойной тап по хоткею — это не ошибка, молчим.
            if self._hud is not None:
                self._hud.finish()
            self._set_state(IDLE)
            log.info("controller: запись %.2f с, слишком коротко — пропускаю", duration)
            return
        peak = wav_peak(wav)
        self._last_peak = peak
        if peak < SILENCE_PEAK:
            if self._hud is not None:
                self._hud.finish()
            self._set_state(IDLE)
            log.info(
                "controller: тишина (пик %.4f, %.2f с) — распознавание не запускаю",
                peak,
                duration,
            )
            if duration >= 1.0:
                self.notify_requested.emit(
                    "Ничего не слышно",
                    "Микрофон молчит — проверьте, не выключен ли он",
                    "low",
                )
            return
        if duration < self.cfg.min_seconds:
            if self._hud is not None:
                self._hud.finish()
            self._set_state(IDLE)
            self.notify_requested.emit(
                "Слишком короткая запись",
                f"Записано {duration:.2f} с — нажмите и говорите дольше",
                "low",
            )
            return
        wav = normalize_pcm(wav)
        self._beep()
        generation = self._generation
        threading.Thread(
            target=self._run_transcription,
            args=(wav, generation),
            name="whisper-transcribe",
            daemon=True,
        ).start()

    def cancel(self) -> None:
        self._generation += 1
        self._max_timer.stop()
        recorder, self._recorder = self._recorder, None
        if recorder is not None:
            try:
                recorder.cancel()
            except Exception:  # noqa: BLE001 - отмена не должна падать
                log.debug("controller: cancel упал", exc_info=True)
        if self._hud is not None:
            self._hud.finish()
        self._set_state(IDLE)
        log.info("controller: отменено")

    def shutdown(self) -> None:
        self.cancel()

    # --- фоновые шаги ---------------------------------------------------
    def _prepare(self, generation: int) -> None:
        try:
            status = self.server.ensure(timeout=90.0)
        except Exception as exc:  # noqa: BLE001 - показываем текст пользователю
            self._server_failed.emit(str(exc))
            return
        if generation != self._generation:
            return
        self._server_ready.emit(status)

    def _run_transcription(self, wav: bytes, generation: int) -> None:
        try:
            result = transcribe(wav, self.cfg)
        except SttError as exc:
            self._transcribe_failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - сеть/парсер
            self._transcribe_failed.emit(f"Неожиданная ошибка распознавания: {exc}")
            return
        if generation != self._generation:
            return
        self._transcribed.emit(result.text, result.elapsed_ms)

    # --- слоты ----------------------------------------------------------
    def _on_server_ready(self, status: ServerStatus) -> None:
        if self.state != STARTING:
            return
        self.server_status.emit(status)
        recorder = Recorder(self.cfg, on_wave=self.wave_changed.emit)
        try:
            recorder.start()
        except RecorderError as exc:
            self._on_error(str(exc))
            return
        self._recorder = recorder
        self._max_timer.start(int(self.cfg.max_seconds * 1000))
        self._set_state(RECORDING)
        self._beep()
        if self._hud is not None and self.cfg.show_hud:
            self._hud.begin_recording()
        log.info("controller: запись началась")

    def _on_transcribed(self, text: str, elapsed_ms: int) -> None:
        if self.state != TRANSCRIBING:
            return
        if self._hud is not None:
            self._hud.finish()
        if text.strip() and is_probable_hallucination(text) and self._last_peak < WEAK_PEAK:
            log.info("controller: отбросил галлюцинацию Whisper: %r", text[:80])
            text = ""
        if not text.strip():
            self._set_state(IDLE)
            self.notify_requested.emit(
                "Ничего не распознано",
                "Похоже, была тишина — попробуйте ещё раз",
                "low",
            )
            return
        log.info("controller: распознано за %d мс", elapsed_ms)
        result = inject_text(text, self.cfg)
        self._set_state(IDLE)
        if result.ok:
            log.info("controller: вставлено (%s)", result.method)
            return
        self.notify_requested.emit("Текст в буфере обмена", result.detail, "normal")

    def _on_error(self, message: str) -> None:
        if self._hud is not None:
            self._hud.finish()
        self._set_state(IDLE)
        log.error("controller: %s", message)
        self.notify_requested.emit("Ошибка диктовки", message, "critical")

    # --- служебное ------------------------------------------------------
    def _set_state(self, state: str) -> None:
        if state == self.state:
            return
        self.state = state
        self.state_changed.emit(state)

    def _beep(self) -> None:
        if not self.cfg.beep:
            return
        try:
            from PySide6.QtWidgets import QApplication

            QApplication.beep()
        except Exception:  # noqa: BLE001 - сигнал не критичен
            log.debug("controller: beep недоступен", exc_info=True)
