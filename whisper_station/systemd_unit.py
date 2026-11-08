"""Установка демона как user-юнита systemd.

Юнит живёт в ~/.config/systemd/user и не требует root. Он удобнее autostart
файла: `systemctl --user status`, логи в journalctl и перезапуск при падении.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import APP_NAME

log = logging.getLogger(__name__)

UNIT_NAME = f"{APP_NAME}.service"


def unit_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(base) / "systemd" / "user" / UNIT_NAME


def resolve_exec() -> tuple[str, str | None]:
    """Команда запуска демона: установленный бинарь или текущий Python."""
    installed = shutil.which(APP_NAME)
    if installed:
        return f"{installed} daemon", None
    repo = Path(__file__).resolve().parent.parent
    return f"{sys.executable} -m whisper_station daemon", f"PYTHONPATH={repo}"


def unit_text(exec_start: str, environment: str | None = None) -> str:
    env_line = f"Environment={environment}\n" if environment else ""
    return f"""[Unit]
Description={APP_NAME}: локальная диктовка
Documentation=file:/usr/share/doc/{APP_NAME}/README.md
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart={exec_start}
{env_line}Restart=on-failure
RestartSec=2
TimeoutStopSec=10

[Install]
WantedBy=graphical-session.target
"""


def install() -> Path:
    """Записать файл юнита под текущую установку."""
    exec_start, environment = resolve_exec()
    path = unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit_text(exec_start, environment), encoding="utf-8")
    log.info("systemd: юнит записан %s", path)
    return path


def _systemctl(*args: str, timeout: float = 15.0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - фиксированные аргументы
        ["systemctl", "--user", *args],
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def enable() -> bool:
    """Установить юнит, включить и запустить его."""
    install()
    reload_result = _systemctl("daemon-reload")
    if reload_result.returncode != 0:
        log.warning("systemd: daemon-reload вернул %s", reload_result.returncode)
        return False
    result = _systemctl("enable", "--now", UNIT_NAME)
    if result.returncode != 0:
        log.warning(
            "systemd: enable вернул %s: %s",
            result.returncode,
            result.stderr.decode("utf-8", "replace").strip(),
        )
        return False
    return True


def disable() -> bool:
    """Остановить, выключить и удалить файл юнита."""
    _systemctl("disable", "--now", UNIT_NAME)
    path = unit_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    _systemctl("daemon-reload")
    log.info("systemd: юнит выключен")
    return True


def is_active() -> bool:
    return _systemctl("is-active", UNIT_NAME).returncode == 0


def is_enabled() -> bool:
    return _systemctl("is-enabled", UNIT_NAME).returncode == 0
