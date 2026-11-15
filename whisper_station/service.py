"""Жизненный цикл сервера распознавания.

Правило: чужой экземпляр (запущенный вручную или systemd) не трогаем —
используем, если отвечает; запускаем свой только когда никто не слушает порт.
Свой сервер — встроенный (venv плюс faster-whisper) или команда из настроек.
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
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from . import models, server_env
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
    if not isinstance(data, dict):
        return ServerStatus(False, error=str(data)[:200])

    model = str(data["model"]) if data.get("model") else None
    device = str(data["device"]) if data.get("device") else None
    pid = data.get("pid") if isinstance(data.get("pid"), int) else None
    state = str(data.get("status") or "")
    if state != "ok":
        detail = data.get("error") or ("модель загружается" if state == "loading" else str(data)[:200])
        return ServerStatus(
            False,
            model=model,
            device=device,
            pid=pid,
            error=f"{state or 'нет статуса'}: {detail}",
        )
    return ServerStatus(ok=True, device=device, model=model, pid=pid)


def app_root() -> Path:
    """Каталог, который надо положить в PYTHONPATH для `-m whisper_station.server`."""
    return Path(__file__).resolve().parent.parent


def _url_parts(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    try:
        port = parsed.port or 8765
    except ValueError:
        port = 8765
    return host, port


@dataclass(frozen=True)
class SpawnPlan:
    """Готовая команда запуска: argv, переменные окружения, рабочий каталог."""

    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    description: str = ""

    def command_line(self) -> str:
        return " ".join(shlex.quote(part) for part in self.argv)


class ServerManager:
    """Поднимает сервер по требованию и следит, чтобы не убить чужое."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._proc: subprocess.Popen[bytes] | None = None
        self._stderr: tempfile.NamedTemporaryFile[bytes] | None = None
        self._command: str | None = None
        self._plan: SpawnPlan | None = None

    # --- что и как запускать -------------------------------------------
    def builtin_ready(self) -> bool:
        return server_env.is_installed()

    def plan(self) -> SpawnPlan | None:
        """Приоритет: своя команда → встроенный сервер → старый run.sh."""
        if self.cfg.server_command.strip():
            argv = shlex.split(self.cfg.server_command.strip())
            if not argv:
                return None
            return SpawnPlan(
                argv=argv,
                env={"WHISPER_PARENT_PID": str(os.getpid())},
                cwd=_cwd_for(argv[0]),
                description="своя команда",
            )
        if self.builtin_ready():
            host, port = _url_parts(self.cfg.server_url)
            env = {
                "WHISPER_PARENT_PID": str(os.getpid()),
                "WHISPER_HOST": host,
                "WHISPER_PORT": str(port),
                "WHISPER_MODEL": self.cfg.model_name,
                "WHISPER_DEVICE": self.cfg.model_device,
                "WHISPER_COMPUTE": self.cfg.model_compute,
                "WHISPER_THREADS": str(self.cfg.model_threads),
                "WHISPER_MODELS_DIR": str(models.models_dir()),
            }
            root = str(app_root())
            current = os.environ.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{root}{os.pathsep}{current}" if current else root
            return SpawnPlan(
                argv=[str(server_env.python()), "-m", "whisper_station.server"],
                env=env,
                cwd=root,
                description="встроенный сервер",
            )
        legacy = find_server_command()
        if not legacy:
            return None
        argv = shlex.split(legacy)
        return SpawnPlan(
            argv=argv,
            env={"WHISPER_PARENT_PID": str(os.getpid())},
            cwd=_cwd_for(argv[0]),
            description="готовый run.sh",
        )

    def command(self) -> str | None:
        """Строка для вывода в doctor/status."""
        plan = self.plan()
        return plan.command_line() if plan else None

    # --- процесс --------------------------------------------------------
    def spawn(self) -> None:
        plan = self.plan()
        if plan is None:
            raise ServerUnavailable(
                "Нет сервера распознавания: выполните `whisper-station server install` "
                "или укажите команду запуска в настройках."
            )
        if self._proc is not None and self._proc.poll() is None:
            return
        self._plan = plan
        self._command = plan.command_line()
        env = dict(os.environ)
        env.update(plan.env)
        self._stderr = tempfile.NamedTemporaryFile(prefix="whisper-server-", suffix=".log")
        log.info("server: запускаю %s (%s)", self._command, plan.description)
        try:
            self._proc = subprocess.Popen(  # noqa: S603 - команда собирается кодом
                plan.argv,
                cwd=plan.cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=self._stderr,
                start_new_session=True,
            )
        except OSError as exc:
            raise ServerUnavailable(f"Не удалось запустить сервер: {exc}") from exc

    @property
    def plan_used(self) -> SpawnPlan | None:
        return self._plan

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
        # Кто-то уже поднимает сервер (наш прошлый процесс или чужой):
        # второй экземпляр занял бы порт и упал, поэтому просто ждём.
        starting = bool(status.error) and status.error.startswith("loading")
        if not self.cfg.server_autostart and not starting:
            raise ServerUnavailable(
                "Сервер распознавания не отвечает, автозапуск отключён в настройках"
            )

        if not starting:
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
                log.info(
                    "server: поднялся за %.1f с (%s)", time.monotonic() - started, status.describe()
                )
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


def _cwd_for(executable: str) -> str | None:
    resolved = shutil.which(executable) or executable
    path = Path(resolved)
    return str(path.parent) if path.is_file() else None
