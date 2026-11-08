"""Запись микрофона через parec/pw-record в WAV 16 кГц моно PCM16."""

from __future__ import annotations

import array
import io
import logging
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import wave
from collections.abc import Callable
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
CHANNELS = 1
CHUNK_BYTES = 3200  # 100 мс


class RecorderError(RuntimeError):
    """Микрофон недоступен или процесс записи завершился с ошибкой."""


def pcm_to_wav(
    pcm: bytes,
    rate: int = SAMPLE_RATE,
    channels: int = CHANNELS,
    width: int = SAMPLE_WIDTH,
) -> bytes:
    """Обернуть сырой PCM в контейнер WAV (заголовок считается по размеру)."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    return buffer.getvalue()


def pcm_bands(pcm: bytes, count: int = 16) -> list[tuple[float, float]]:
    """Разбить кусок PCM на полосы (min, max) в диапазоне −1..1 — для осциллограммы."""
    usable = len(pcm) - (len(pcm) % 2)
    if usable <= 0:
        return []
    samples = array.array("h")
    samples.frombytes(pcm[:usable])
    step = max(1, len(samples) // count)
    bands: list[tuple[float, float]] = []
    for start in range(0, len(samples) - step + 1, step):
        piece = samples[start : start + step]
        if not piece:
            break
        bands.append((max(-1.0, min(piece) / 32768.0), min(1.0, max(piece) / 32768.0)))
    return bands


class Recorder:
    """Процесс записи с чтением stdout в отдельном потоке."""

    def __init__(
        self,
        cfg: Config,
        on_wave: Callable[[list[tuple[float, float]]], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self.on_wave = on_wave
        self._proc: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._buffer = bytearray()
        self._started_at = 0.0
        self._stderr: tempfile.NamedTemporaryFile[bytes] | None = None
        self._lock = threading.Lock()

    # --- состояние -----------------------------------------------------
    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def snapshot(self, max_seconds: float = 20.0) -> bytes:
        """Последние N секунд сырого PCM — для живого предпросмотра."""
        limit = int(max_seconds * SAMPLE_RATE * SAMPLE_WIDTH)
        with self._lock:
            data = bytes(self._buffer)
        return data[-limit:] if limit > 0 else data

    @property
    def bytes_captured(self) -> int:
        with self._lock:
            return len(self._buffer)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._started_at if self._started_at else 0.0

    # --- бэкенд ---------------------------------------------------------
    def resolve_backend(self) -> str:
        if self.cfg.audio_backend != "auto":
            if shutil.which(self.cfg.audio_backend) is None:
                raise RecorderError(f"{self.cfg.audio_backend} не найден в PATH")
            return self.cfg.audio_backend
        # pw-record первым: parec на PipeWire молчит, если stdout — pipe.
        for candidate in ("pw-record", "parec"):
            if shutil.which(candidate):
                return candidate
        raise RecorderError("Не найден ни parec, ни pw-record: записи не будет")

    def command(self, backend: str) -> list[str]:
        if backend == "parec":
            return [
                "parec",
                "--raw",
                "--format=s16le",
                f"--rate={SAMPLE_RATE}",
                f"--channels={CHANNELS}",
                "--device",
                self.cfg.audio_device,
            ]
        args = [
            "pw-record",
            # --raw обязателен: иначе pw-record пишет контейнер .snd (AU)
            # с float32, и в модель уходит шум вместо речи.
            "--raw",
            "--format=s16",
            f"--rate={SAMPLE_RATE}",
            f"--channels={CHANNELS}",
        ]
        device = self.cfg.audio_device
        if device and not device.startswith("@"):
            args += ["--target", device]
        args.append("-")
        return args

    # --- запись ---------------------------------------------------------
    def start(self) -> None:
        if self.running:
            raise RecorderError("Запись уже идёт")
        backend = self.resolve_backend()
        command = self.command(backend)
        self._buffer = bytearray()
        self._stderr = tempfile.NamedTemporaryFile(prefix="whisper-station-", suffix=".log")
        log.info("recorder: старт %s", " ".join(command))
        try:
            self._proc = subprocess.Popen(  # noqa: S603 - фиксированные аргументы
                command,
                stdout=subprocess.PIPE,
                stderr=self._stderr,
                stdin=subprocess.DEVNULL,
                bufsize=0,
            )
        except OSError as exc:
            raise RecorderError(f"Не удалось запустить {backend}: {exc}") from exc
        self._started_at = time.monotonic()
        self._thread = threading.Thread(target=self._read_loop, name="recorder-reader", daemon=True)
        self._thread.start()

    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        stream = proc.stdout
        try:
            while True:
                chunk = stream.read(CHUNK_BYTES)
                if not chunk:
                    break
                with self._lock:
                    self._buffer += chunk
                if self.on_wave is not None:
                    try:
                        self.on_wave(pcm_bands(chunk))
                    except Exception:  # noqa: BLE001
                        log.debug("recorder: on_wave упал", exc_info=True)
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def _terminate(self) -> int:
        proc, self._proc = self._proc, None
        if proc is None:
            return 0
        if proc.poll() is None:
            try:
                proc.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass
        try:
            returncode = proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            log.warning("recorder: процесс не вышел по SIGINT, убиваю")
            proc.kill()
            returncode = proc.wait(timeout=1.0)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        return returncode

    def read_stderr(self) -> str:
        if self._stderr is None:
            return ""
        try:
            self._stderr.flush()
            self._stderr.seek(0)
            return self._stderr.read().decode("utf-8", "replace").strip()
        except (OSError, ValueError):
            return ""

    def stop(self) -> bytes:
        """Остановить запись и вернуть WAV. Пустой результат — ошибка записи."""
        if self._proc is None:
            raise RecorderError("Запись не запущена")
        returncode = self._terminate()
        with self._lock:
            raw = bytes(self._buffer)
        stderr = self.read_stderr()
        self._cleanup()
        if not raw:
            if returncode not in (0, -signal.SIGINT, 130):
                detail = f": {stderr[-400:]}" if stderr else ""
                raise RecorderError(f"Микрофон не дал данных (код {returncode}){detail}")
            log.warning("recorder: за запись не пришло ни одного сэмпла")
            return pcm_to_wav(b"")
        if returncode not in (0, -signal.SIGINT, 130) and len(raw) < CHUNK_BYTES:
            raise RecorderError(
                f"Запись прервалась (код {returncode})"
                + (f": {stderr[-400:]}" if stderr else "")
            )
        log.info("recorder: стоп, %.2f с, %d байт PCM", len(raw) / SAMPLE_WIDTH / SAMPLE_RATE, len(raw))
        return pcm_to_wav(raw)

    def cancel(self) -> None:
        """Прервать запись, ничего не отдавая."""
        if self._proc is None:
            return
        self._terminate()
        self._cleanup()
        with self._lock:
            self._buffer = bytearray()
        log.info("recorder: запись отменена")

    def _cleanup(self) -> None:
        if self._stderr is not None:
            try:
                self._stderr.close()
            except OSError:
                pass
            self._stderr = None
        self._started_at = 0.0


def available_backends() -> list[str]:
    return [name for name in ("parec", "pw-record") if shutil.which(name)]


def default_device_name() -> str:
    return "@DEFAULT_SOURCE@"


def wav_duration(wav: bytes) -> float:
    """Длительность WAV в секундах (0.0 для битого файла)."""
    try:
        with wave.open(io.BytesIO(wav), "rb") as handle:
            frames, rate = handle.getnframes(), handle.getframerate()
    except (wave.Error, EOFError):
        return 0.0
    return frames / rate if rate else 0.0


def normalize_pcm(wav: bytes, target: float = 0.6, max_gain: float = 10.0) -> bytes:
    """Поднять тихую запись до нормального уровня (без клиппинга).

    Микрофон в PipeWire часто пишет с низким уровнем (пик 0.004–0.05),
    и Whisper на таком звуке «додумывает» текст. Усиление до 0.6 по пику
    делает речь отчётливой.
    """
    try:
        with wave.open(io.BytesIO(wav), "rb") as handle:
            params = handle.getparams()
            frames = handle.readframes(handle.getnframes())
    except (wave.Error, EOFError):
        return wav
    usable = len(frames) - (len(frames) % 2)
    if usable <= 0:
        return wav
    samples = array.array("h")
    samples.frombytes(frames[:usable])
    peak = max((abs(value) for value in samples), default=0)
    if peak == 0:
        return wav
    gain = min(max_gain, target * 32768 / peak)
    if gain <= 1.05:
        return wav
    scaled = array.array("h", (max(-32768, min(32767, int(value * gain))) for value in samples))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setparams(params)
        handle.writeframes(scaled.tobytes())
    return buffer.getvalue()


def wav_peak(wav: bytes) -> float:
    """Пиковая амплитуда записи 0..1 (0 — цифровая тишина)."""
    try:
        with wave.open(io.BytesIO(wav), "rb") as handle:
            frames = handle.readframes(handle.getnframes())
    except (wave.Error, EOFError):
        return 0.0
    usable = len(frames) - (len(frames) % 2)
    if usable <= 0:
        return 0.0
    samples = array.array("h")
    samples.frombytes(frames[:usable])
    return max((abs(value) for value in samples), default=0) / 32768.0


def looks_like_wav(data: bytes) -> bool:
    return data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def write_debug_copy(wav: bytes, path: Path) -> None:
    """Сохранить запись на диск — только при включённом DEBUG."""
    path.write_bytes(wav)
    log.debug("recorder: отладочная копия в %s", path)
