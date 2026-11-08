"""Звуковые сигналы старта и остановки записи.

Свои короткие WAV (сгенерированы `tools/make_sounds.py`): мягкие низкие
тона с плавным глиссандо, без высоких обертонов. Играем через PipeWire/Pulse,
запасной путь — событие libcanberra, последний — звонок Qt.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

FILES = {"start": "start.wav", "stop": "stop.wav"}
EVENTS = {"start": "message", "stop": "complete"}

# Куда пакет ставит звуки и где они лежат в репозитории.
INSTALLED_DIR = Path("/usr/share/whisper-station/sounds")
REPO_DIR = Path(__file__).resolve().parent.parent / "packaging" / "sounds"

PLAYERS = ("pw-play", "paplay")


def sound_file(kind: str) -> Path | None:
    name = FILES.get(kind)
    if name is None:
        return None
    for directory in (INSTALLED_DIR, REPO_DIR):
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def player() -> str | None:
    for candidate in PLAYERS:
        if shutil.which(candidate):
            return candidate
    return None


def command(kind: str) -> list[str] | None:
    """Команда воспроизведения сигнала (или None, если играть нечем)."""
    path = sound_file(kind)
    chosen = player()
    if path is not None and chosen is not None:
        return [chosen, str(path)]
    event = EVENTS.get(kind)
    if event is not None and shutil.which("canberra-gtk-play"):
        return ["canberra-gtk-play", "-i", event]
    return None


def play(kind: str) -> None:
    """Проиграть сигнал; ошибки не пробрасываются — звук не критичен."""
    argv = command(kind)
    if argv is not None:
        try:
            subprocess.Popen(  # noqa: S603 - фиксированные аргументы
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            return
        except OSError as exc:
            log.debug("sounds: %s не запустился: %s", argv[0], exc)
    try:
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance()
        # Без GUI-приложения статический beep() роняет процесс — проверяем явно.
        if isinstance(application, QApplication):
            application.beep()
    except Exception:  # noqa: BLE001 - звонок не должен ломать запись
        log.debug("sounds: системный звонок недоступен", exc_info=True)
