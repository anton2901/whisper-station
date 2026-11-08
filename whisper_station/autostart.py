"""Автозапуск при входе: ~/.config/autostart/whisper-station.desktop."""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

from . import APP_NAME, APP_TITLE
from .paths import autostart_file

log = logging.getLogger(__name__)


def launcher_command() -> str:
    """Команда запуска демона: установленный бинарь, иначе текущий Python."""
    installed = shutil.which(APP_NAME)
    if installed:
        return installed
    return f"{sys.executable} -m whisper_station"


def desktop_entry(command: str | None = None) -> str:
    command = command or launcher_command()
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_TITLE}\n"
        "Comment=Локальная диктовка: запись, распознавание, вставка текста\n"
        f"Exec={command} daemon\n"
        f"Icon={APP_NAME}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        "X-KDE-autostart-after=panel\n"
    )


def enable(command: str | None = None) -> Path:
    path = autostart_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(desktop_entry(command), encoding="utf-8")
    path.chmod(0o644)
    log.info("autostart: включён (%s)", path)
    return path


def disable() -> None:
    path = autostart_file()
    try:
        path.unlink()
        log.info("autostart: выключен (%s)", path)
    except FileNotFoundError:
        pass


def is_enabled() -> bool:
    return autostart_file().exists()


def apply(enabled: bool, command: str | None = None) -> None:
    """Привести файл автозапуска в соответствие с флагом."""
    if enabled:
        if not os.access(autostart_file().parent, os.W_OK) and autostart_file().exists():
            log.warning("autostart: нет прав на %s", autostart_file())
            return
        enable(command)
    else:
        disable()
