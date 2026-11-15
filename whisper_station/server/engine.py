"""Движок распознавания: загрузка faster-whisper, выбор устройства, инференс.

Модель грузится один раз в фоновом потоке, чтобы `/health` отвечал сразу:
приложение ждёт статус `ok`, а не висящий HTTP-запрос.
"""

from __future__ import annotations

import io
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .config import ServerConfig

log = logging.getLogger(__name__)


CUDA_ERROR_MARKERS = ("cublas", "cudnn", "nvrtc", "cuda driver", "no cuda", "out of memory")


class EngineError(RuntimeError):
    """Распознать нельзя: модель не загрузилась."""


class EngineLoading(EngineError):
    """Модель ещё грузится — клиенту стоит повторить запрос позже."""


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Result:
    text: str
    language: str
    duration: float
    segments: tuple[Segment, ...]


def cuda_error(exc: BaseException) -> bool:
    """Похоже ли на проблему с CUDA, после которой стоит уйти на CPU."""
    text = str(exc).lower()
    return any(marker in text for marker in CUDA_ERROR_MARKERS)


def detect_device() -> str:
    """cuda, если ctranslate2 видит устройства; иначе cpu."""
    try:
        import ctranslate2

        if int(ctranslate2.get_cuda_device_count()) > 0:
            return "cuda"
    except Exception:  # noqa: BLE001 - нет пакета или драйвера — это cpu
        log.debug("engine: ctranslate2 недоступен, беру cpu", exc_info=True)
    return "cpu"


def pick_compute(device: str, requested: str) -> str:
    """Подобрать compute_type под устройство; float16 на CPU не работает."""
    if requested == "float16" and device != "cuda":
        log.warning("engine: float16 на %s не поддерживается, беру int8", device)
        return "int8"
    if requested:
        return requested
    return "float16" if device == "cuda" else "int8"


class Engine:
    """Одна модель на процесс; инференс сериализован замком."""

    def __init__(self, cfg: ServerConfig) -> None:
        self.cfg = cfg
        self._model: object | None = None
        self._ready = threading.Event()
        self._error: str | None = None
        self._fallback: str | None = None
        self._device = "cpu"
        self._compute = ""
        self._lock = threading.Lock()
        self.last_activity = time.monotonic()

    # --- загрузка -------------------------------------------------------
    def start(self) -> None:
        thread = threading.Thread(target=self._load, name="model-loader", daemon=True)
        thread.start()

    def _source(self) -> str:
        """Локальный каталог модели, если он уже скачан, иначе имя для HF."""
        local = self.cfg.models_dir / self.cfg.model
        if (local / "model.bin").is_file():
            return str(local)
        return self.cfg.model

    def _load(self) -> None:
        started = time.monotonic()
        device = self.cfg.device if self.cfg.device in {"cuda", "cpu"} else detect_device()
        compute = pick_compute(device, self.cfg.compute)
        self._device, self._compute = device, compute
        try:
            self._build(device, compute)
            self._warmup_if_gpu()
        except Exception as exc:  # noqa: BLE001 - показываем причину в /health
            if device == "cuda":
                log.warning("engine: CUDA не поднялась (%s), пробую CPU", exc)
                self._fallback = f"CUDA не поднялась ({type(exc).__name__}: {exc}); работаю на CPU"
                self._device, self._compute = "cpu", "int8"
                try:
                    self._build("cpu", "int8")
                except Exception as fallback:  # noqa: BLE001
                    self._error = f"{type(fallback).__name__}: {fallback}"
                    log.error("engine: модель не загрузилась: %s", self._error)
            else:
                self._error = f"{type(exc).__name__}: {exc}"
                log.error("engine: модель не загрузилась: %s", self._error)
        finally:
            self._ready.set()
            log.info(
                "engine: %s на %s/%s, потоки %d, %.1f с",
                self.cfg.model,
                self._device,
                self._compute,
                self.cfg.threads_effective,
                time.monotonic() - started,
            )

    def _build(self, device: str, compute: str) -> None:
        from faster_whisper import WhisperModel

        source = self._source()
        # Локальный каталог читаем без похода в HuggingFace за ревизией.
        self._model = WhisperModel(
            source,
            device=device,
            compute_type=compute,
            cpu_threads=self.cfg.threads_effective,
            download_root=str(self.cfg.models_dir),
            local_files_only=not Path(source).exists(),
        )

    def _warmup_if_gpu(self) -> None:
        """Пробный прогон только для CUDA: на CPU греть нечего, а старт дороже.

        cuBLAS/cuDNN грузятся лениво, уже на инференсе: без прогрева `/health`
        успевал сказать «ok», а первая диктовка падала с «libcublas.so.12 is
        not found».
        """
        if self._device != "cuda":
            return
        import numpy as np

        silence = np.zeros(9600, dtype=np.float32)  # 0.6 с
        with self._lock:
            segments, _info = self._model.transcribe(  # type: ignore[attr-defined]
                silence,
                language="en",
                beam_size=1,
                vad_filter=False,
                condition_on_previous_text=False,
                without_timestamps=True,
            )
            list(segments)

    def _fallback_to_cpu(self, reason: BaseException) -> None:
        log.warning("engine: %s — перезагружаю модель на CPU", reason)
        self._fallback = f"{type(reason).__name__}: {reason}; работаю на CPU"
        self._device, self._compute = "cpu", "int8"
        self._build("cpu", "int8")

    # --- состояние ------------------------------------------------------
    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    def status(self) -> dict[str, object]:
        if not self.ready:
            phase = "loading"
        elif self._model is None:
            phase = "error"
        else:
            phase = "ok"
        return {
            "status": phase,
            "model": self.cfg.model,
            "device": self._device,
            "compute_type": self._compute,
            "threads": self.cfg.threads_effective,
            "pid": os.getpid(),
            "parentPid": self.cfg.parent_pid,
            "idleSeconds": self.cfg.idle_seconds,
            "error": self._error,
            "fallback": self._fallback,
        }

    # --- инференс -------------------------------------------------------
    def transcribe(self, wav: bytes, language: str, prompt: str | None) -> Result:
        """Распознать WAV 16 кГц моно PCM16; язык auto — определить самому."""
        if not self.ready:
            raise EngineLoading("модель ещё загружается")
        if self._model is None:
            raise EngineError(self._error or "модель недоступна")

        self.last_activity = time.monotonic()
        requested = None if language.strip().lower() in {"", "auto"} else language.strip().lower()
        hint = (prompt or "").strip()[:1000] or None
        seconds = _wav_seconds(wav)
        samples = wav_samples(wav)
        started = time.monotonic()
        try:
            segments, info = self._run(samples, requested, hint)
        except Exception as exc:  # noqa: BLE001 - CUDA может отвалиться на инференсе
            if self._device != "cuda" or not cuda_error(exc):
                raise
            self._fallback_to_cpu(exc)
            segments, info = self._run(samples, requested, hint)
        collected = tuple(
            Segment(float(segment.start), float(segment.end), segment.text.strip())
            for segment in segments
        )
        text = " ".join(segment.text for segment in collected if segment.text).strip()
        log.info(
            "transcribe: %.1f с аудио, язык %s, за %.1f с, %d симв.",
            seconds,
            getattr(info, "language", "?"),
            time.monotonic() - started,
            len(text),
        )
        return Result(
            text=text,
            language=str(getattr(info, "language", "") or ""),
            duration=seconds,
            segments=collected,
        )

    def _run(self, samples, requested, hint):
        """Один вызов transcribe под замком; возвращает (segments, info)."""
        with self._lock:
            segments, info = self._model.transcribe(  # type: ignore[attr-defined]
                samples,
                language=requested,
                beam_size=self.cfg.beam,
                vad_filter=True,
                condition_on_previous_text=False,
                initial_prompt=hint,
            )
            return list(segments), info


def wav_samples(wav: bytes):
    """PCM16 16 кГц моно → float32 [-1, 1] для faster-whisper.

    Своими руками, а не через PyAV: у него меняется API, и decode_audio падает
    на несовместимой версии. Формат WAV уже проверен HTTP-слоем.
    """
    import numpy as np
    import wave

    with wave.open(io.BytesIO(wav)) as handle:
        raw = handle.readframes(handle.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def _wav_seconds(wav: bytes) -> float:
    import wave

    try:
        with wave.open(io.BytesIO(wav)) as handle:
            frames = handle.getnframes()
            rate = handle.getframerate() or 16000
        return frames / float(rate)
    except (wave.Error, EOFError):
        return 0.0
