"""Единые пути приложения: конфиг, состояние, сокет, автозапуск."""

from __future__ import annotations

import os
from pathlib import Path

from . import APP_NAME


def _env_path(name: str, fallback: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else fallback


def config_home() -> Path:
    return _env_path("XDG_CONFIG_HOME", Path.home() / ".config")


def state_home() -> Path:
    return _env_path("XDG_STATE_HOME", Path.home() / ".local" / "state")


def runtime_dir() -> Path:
    return _env_path("XDG_RUNTIME_DIR", Path("/tmp"))


def config_dir() -> Path:
    return config_home() / APP_NAME


def config_file() -> Path:
    return config_dir() / "config.toml"


def state_dir() -> Path:
    return state_home() / APP_NAME


def log_file() -> Path:
    return state_dir() / "app.log"


def ipc_socket() -> Path:
    return runtime_dir() / f"{APP_NAME}.sock"


def ydotoold_socket() -> Path:
    return runtime_dir() / f"{APP_NAME}-ydotoold.sock"


def autostart_file() -> Path:
    return config_home() / "autostart" / f"{APP_NAME}.desktop"


def ensure_dirs() -> None:
    """Создать каталоги состояния; сокет живёт в runtime-каталоге."""
    for path in (config_dir(), state_dir()):
        path.mkdir(parents=True, exist_ok=True)
