"""Каталог моделей Whisper, которые ставит whisper-station.

Модели — CT2-сборки из HuggingFace, их читает faster-whisper. Размер — сколько
занимает каталог модели на диске, а не вес скачивания. Оценки сделаны для
float16 на GPU; на CPU int8 модель занимает столько же, но считает медленнее.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    """Одна модель: короткое имя, репозиторий, размер и подсказка для UI."""

    name: str
    repo: str
    size_mb: int
    quality: int
    speed: str
    note: str

    @property
    def size_gb(self) -> float:
        return round(self.size_mb / 1024, 1)

    def describe(self) -> str:
        """Строка для настроек и `model list`."""
        return f"{self.name} — {self.size_label}, {self.speed}: {self.note}"

    @property
    def size_label(self) -> str:
        if self.size_mb >= 1024:
            return f"{self.size_gb:.1f} ГБ"
        return f"{self.size_mb} МБ"


# Порядок — от самой лёгкой к самой тяжёлой: так удобнее выбирать в списке.
CATALOG: tuple[ModelInfo, ...] = (
    ModelInfo(
        name="tiny",
        repo="Systran/faster-whisper-tiny",
        size_mb=75,
        quality=1,
        speed="мгновенно",
        note="черновики, слабые машины",
    ),
    ModelInfo(
        name="base",
        repo="Systran/faster-whisper-base",
        size_mb=145,
        quality=2,
        speed="очень быстро",
        note="простая речь",
    ),
    ModelInfo(
        name="small",
        repo="Systran/faster-whisper-small",
        size_mb=484,
        quality=3,
        speed="быстро",
        note="разумный выбор для CPU",
    ),
    ModelInfo(
        name="medium",
        repo="Systran/faster-whisper-medium",
        size_mb=1536,
        quality=4,
        speed="средне",
        note="если CPU справляется",
    ),
    ModelInfo(
        name="large-v3-turbo",
        repo="mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        size_mb=1600,
        quality=5,
        speed="быстро для своего размера",
        note="лучший выбор для GPU",
    ),
    ModelInfo(
        name="large-v3",
        repo="Systran/faster-whisper-large-v3",
        size_mb=3100,
        quality=5,
        speed="медленно",
        note="максимум качества, нужна память",
    ),
)

BY_NAME: dict[str, ModelInfo] = {info.name: info for info in CATALOG}

DEFAULT_MODEL = "large-v3-turbo"
CPU_MODEL = "small"
GPU_MODEL = "large-v3-turbo"


def get(name: str) -> ModelInfo | None:
    return BY_NAME.get(name.strip())


def names() -> tuple[str, ...]:
    return tuple(info.name for info in CATALOG)


def default_name(device: str = "auto") -> str:
    """Что предложить по умолчанию: без GPU тяжёлая модель только мешает."""
    if device == "cuda":
        return GPU_MODEL
    if device == "cpu":
        return CPU_MODEL
    return DEFAULT_MODEL


def detect_device() -> str:
    """Есть ли рабочая CUDA.

    В окружении сервера отвечает ctranslate2 (он и грузит модель), в окружении
    приложения его нет — тогда смотрим на драйвер через nvidia-smi.
    """
    try:
        import ctranslate2

        if int(ctranslate2.get_cuda_device_count()) > 0:
            return "cuda"
        return "cpu"
    except Exception:  # noqa: BLE001 - пакета нет, проверим драйвер
        pass
    try:
        probe = subprocess.run(  # noqa: S603 - фиксированные аргументы
            ["nvidia-smi", "-L"], capture_output=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return "cpu"
    if probe.returncode == 0 and b"GPU" in probe.stdout:
        return "cuda"
    return "cpu"

