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


def data_home() -> Path:
    return _env_path("XDG_DATA_HOME", Path.home() / ".local" / "share")


def data_dir() -> Path:
    return data_home() / APP_NAME


def runtime_dir() -> Path:
    return _env_path("XDG_RUNTIME_DIR", Path("/tmp"))


def config_dir() -> Path:
    return config_home() / APP_NAME


def config_file() -> Path:
    return config_dir() / "config.toml"


def legacy_config_file() -> Path:
    """Файл настроек под прежним именем приложения (до переименования)."""
    return config_home() / "whisper-dictate" / "config.toml"


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


def server_venv_dir() -> Path:
    """Отдельное окружение сервера: faster-whisper не тянем в системный Python."""
    return data_dir() / "server-venv"


def server_python() -> Path:
    return server_venv_dir() / "bin" / "python"


def models_dir() -> Path:
    return data_dir() / "models"


def ensure_dirs() -> None:
    """Создать каталоги состояния; сокет живёт в runtime-каталоге."""
    for path in (config_dir(), state_dir()):
        path.mkdir(parents=True, exist_ok=True)
