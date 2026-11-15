"""Настройки сервера из окружения.

Приложение передаёт их при запуске своего сервера; ручной запуск тоже работает:
переменные те же, что были у прежнего run.sh (WHISPER_MODEL, WHISPER_DEVICE…).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .. import paths

DEFAULT_PORT = 8765
MAX_BYTES = 64 * 1024 * 1024
DEFAULT_IDLE_SECONDS = 1800
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


class ConfigError(RuntimeError):
    """Окружение задано так, что сервер нельзя запускать."""


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}={raw!r} — не число") from exc


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    model: str = "large-v3-turbo"
    device: str = "auto"
    compute: str = ""
    threads: int = 0
    models_dir: Path = paths.models_dir()
    max_bytes: int = MAX_BYTES
    beam: int = 5
    idle_seconds: int = DEFAULT_IDLE_SECONDS
    parent_pid: int = 0

    @property
    def threads_effective(self) -> int:
        if self.threads > 0:
            return self.threads
        return max(2, (os.cpu_count() or 4) - 2)

    @classmethod
    def from_env(cls) -> "ServerConfig":
        host = os.environ.get("WHISPER_HOST", "127.0.0.1").strip() or "127.0.0.1"
        if host not in LOOPBACK_HOSTS:
            raise ConfigError(
                f"WHISPER_HOST={host!r}: сервер слушает только loopback "
                f"({', '.join(LOOPBACK_HOSTS)})"
            )
        models_raw = os.environ.get("WHISPER_MODELS_DIR", "").strip()
        return cls(
            host=host,
            port=_int("WHISPER_PORT", DEFAULT_PORT),
            model=os.environ.get("WHISPER_MODEL", "large-v3-turbo").strip() or "large-v3-turbo",
            device=(os.environ.get("WHISPER_DEVICE", "auto").strip() or "auto").lower(),
            compute=(os.environ.get("WHISPER_COMPUTE", "").strip() or "").lower(),
            threads=_int("WHISPER_THREADS", 0),
            models_dir=Path(models_raw).expanduser() if models_raw else paths.models_dir(),
            max_bytes=_int("WHISPER_MAX_BYTES", MAX_BYTES),
            beam=_int("WHISPER_BEAM", 5),
            idle_seconds=_int("WHISPER_IDLE_SECONDS", DEFAULT_IDLE_SECONDS),
            parent_pid=_int("WHISPER_PARENT_PID", 0),
        )
