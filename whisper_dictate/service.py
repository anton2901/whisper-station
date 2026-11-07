"""Жизненный цикл локального сервера распознавания.

Правило: чужой экземпляр (запущенный DSH, вручную или systemd) не трогаем —
используем, если отвечает; запускаем свой только когда никто не слушает порт.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import Config, find_server_command
from .stt import ServerUnavailable

log = logging.getLogger(__name__)

HEALTH_TIMEOUT = 1.5
POLL_INTERVAL = 0.25


@dataclass(frozen=True)
class ServerStatus:
    ok: bool
    device: str | None = None
    model: str | None = None
    pid: int | None = None
    error: str | None = None

    def describe(self) -> str:
        if not self.ok:
            return f"сервер недоступен: {self.error or 'нет ответа'}"
        return f"{self.model or 'whisper'} на {self.device or '?'}"


def health(url: str, timeout: float = HEALTH_TIMEOUT) -> ServerStatus:
    """GET /health; любая ошибка превращается в ServerStatus(ok=False)."""
    target = url.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(target, timeout=timeout) as response:  # noqa: S310 - loopback
            payload = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return ServerStatus(False, error=str(reason))
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return ServerStatus(False, error="ответ /health не JSON")
    if not isinstance(data, dict) or data.get("status") != "ok":
        return ServerStatus(False, error=str(data)[:200])
    return ServerStatus(
        ok=True,
        device=data.get("device"),
        model=data.get("model"),
        pid=data.get("pid") if isinstance(data.get("pid"), int) else None,
    )


class ServerManager:
    """Поднимает run.sh по требованию и следит, чтобы не убить чужое."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._proc: subprocess.Popen[bytes] | None = None
        self._stderr: tempfile.NamedTemporaryFile[bytes] | None = None
        self._command: str | None = None

    # --- команда запуска ------------------------------------------------
    def command(self) -> str | None:
        if self.cfg.server_command.strip():
            return self.cfg.server_command.strip()
        return find_server_command()

    def spawn(self) -> None:
        command = self.command()
        if not command:
            raise ServerUnavailable(
                "Не нашёл команду запуска сервера. Укажите её в настройках "
                "(например, путь к run.sh) или запустите сервис вручную."
            )
        if self._proc is not None and self._proc.poll() is None:
            return
        self._command = command
        argv = shlex.split(command)
        if not argv:
            raise ServerUnavailable("Пустая команда запуска сервера")
        cwd = None
        executable = shutil.which(argv[0]) or argv[0]
        path = Path(executable)
        if path.is_file():
            cwd = str(path.parent)
        self._stderr = tempfile.NamedTemporaryFile(prefix="whisper-server-", suffix=".log")
        env = dict(os.environ)
        env.setdefault("WHISPER_PARENT_PID", str(os.getpid()))
        log.info("server: запускаю %r (cwd=%s)", command, cwd)
        try:
            self._proc = subprocess.Popen(  # noqa: S603 - команда из конфига пользователя
                argv,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=self._stderr,
                start_new_session=True,
            )
        except OSError as exc:
            raise ServerUnavailable(f"Не удалось запустить сервер: {exc}") from exc

    def ensure(
        self,
        timeout: float = 90.0,
        on_progress: Callable[[float], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> ServerStatus:
        """Дождаться живого сервера, при необходимости запустив свой."""
        status = health(self.cfg.server_url)
        if status.ok:
            log.info("server: использую уже запущенный (%s)", status.describe())
            return status
        if not self.cfg.server_autostart:
            raise ServerUnavailable(
                "Сервер распознавания не отвечает, автозапуск отключён в настройках"
            )

        self.spawn()
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            if cancelled is not None and cancelled():
                raise ServerUnavailable("Запуск сервера отменён")
            if self._proc is not None and self._proc.poll() is not None:
                detail = self.read_stderr()
                raise ServerUnavailable(
                    f"Сервер завершился с кодом {self._proc.returncode}"
                    + (f": {detail[-300:]}" if detail else "")
                )
            status = health(self.cfg.server_url)
            if status.ok:
                log.info("server: поднялся за %.1f с (%s)", time.monotonic() - started, status.describe())
                return status
            if on_progress is not None:
                on_progress(min(1.0, (time.monotonic() - started) / timeout))
            time.sleep(POLL_INTERVAL)
        raise ServerUnavailable(f"Сервер не ответил за {timeout:.0f} с")

    def read_stderr(self) -> str:
        if self._stderr is None:
            return ""
        try:
            self._stderr.flush()
            self._stderr.seek(0)
            return self._stderr.read().decode("utf-8", "replace").strip()
        except (OSError, ValueError):
            return ""

    @property
    def owned_pid(self) -> int | None:
        if self._proc is None or self._proc.poll() is not None:
            return None
        return self._proc.pid

    def stop_owned(self) -> None:
        """Остановить только тот процесс, который запустили мы сами."""
        if self._proc is None:
            return
        if self._proc.poll() is None:
            log.info("server: останавливаю собственный процесс %s", self._proc.pid)
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=2)
        self._proc = None
        if self._stderr is not None:
            try:
                self._stderr.close()
            except OSError:
                pass
            self._stderr = None
