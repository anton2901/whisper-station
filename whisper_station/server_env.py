"""Окружение встроенного сервера: venv с faster-whisper и его установка.

faster-whisper тянет ctranslate2, av и huggingface_hub — в системный Python это
ставить нельзя. Поэтому сервер живёт в отдельном venv рядом с данными
приложения, а приложение запускает его своим интерпретатором.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from . import __version__, paths

log = logging.getLogger(__name__)

REQUIREMENTS = ("faster-whisper>=1.0,<2",)
MARKER = "install.json"
MIN_PYTHON = (3, 9)
PIP_TIMEOUT = 1800.0


class InstallError(RuntimeError):
    """Поставить окружение сервера не удалось."""


def venv_dir() -> Path:
    return paths.server_venv_dir()


def python() -> Path:
    return paths.server_python()


def marker_path() -> Path:
    return venv_dir() / MARKER


def is_installed() -> bool:
    """Готовым считаем окружение, где venv есть и установка отмечена маркером."""
    return python().is_file() and marker_path().is_file()


def installed_info() -> dict[str, object]:
    try:
        return json.loads(marker_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def faster_whisper_version() -> str | None:
    value = installed_info().get("faster_whisper")
    return str(value) if value else None


def venv_size() -> int:
    total = 0
    if not venv_dir().is_dir():
        return 0
    for item in venv_dir().rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def _check_source(source: str) -> None:
    try:
        probe = subprocess.run(  # noqa: S603 - интерпретатор выбирает пользователь
            [source, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallError(f"Не удалось запустить {source}: {exc}") from exc
    if probe.returncode != 0:
        raise InstallError(f"{source} не работает: {probe.stderr.strip()[:300]}")
    match = re.match(r"(\d+)\.(\d+)", probe.stdout.strip())
    if not match:
        raise InstallError(f"Не понял версию Python: {probe.stdout.strip()!r}")
    version = (int(match.group(1)), int(match.group(2)))
    if version < MIN_PYTHON:
        raise InstallError(
            f"Нужен Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+, у {source} — "
            f"{version[0]}.{version[1]}"
        )


def _run(argv: list[str], on_output: Callable[[str], None] | None) -> str:
    log.info("server_env: %s", " ".join(argv))
    try:
        result = subprocess.run(  # noqa: S603 - аргументы собирает код
            argv,
            capture_output=True,
            text=True,
            timeout=PIP_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallError(f"Команда не выполнилась: {exc}") from exc
    output = (result.stdout or "") + (result.stderr or "")
    if on_output is not None:
        on_output(output.strip())
    if result.returncode != 0:
        tail = "\n".join(output.strip().splitlines()[-12:])
        raise InstallError(f"{' '.join(argv[:4])}… вернул {result.returncode}:\n{tail}")
    return output


def install(
    source_python: str | None = None,
    *,
    force: bool = False,
    on_output: Callable[[str], None] | None = None,
) -> str:
    """Создать venv и поставить faster-whisper. Возвращает версию пакета."""
    source = source_python or sys.executable
    _check_source(source)
    target = venv_dir()
    if target.exists() and force:
        log.info("server_env: пересоздаю %s", target)
        shutil.rmtree(target)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InstallError(f"Не могу создать {target.parent}: {exc}") from exc
    _run([source, "-m", "venv", str(target)], on_output)

    _run(
        [
            str(python()),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            *REQUIREMENTS,
        ],
        on_output,
    )
    version = _run(
        [
            str(python()),
            "-c",
            "import faster_whisper; print(faster_whisper.__version__)",
        ],
        on_output,
    ).strip().splitlines()[-1]
    marker = {
        "app_version": __version__,
        "faster_whisper": version,
        "requirements": list(REQUIREMENTS),
        "python": str(python()),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    try:
        marker_path().write_text(
            json.dumps(marker, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise InstallError(f"Не могу записать {marker_path()}: {exc}") from exc
    log.info("server_env: готово, faster-whisper %s", version)
    return version


def remove() -> None:
    """Удалить окружение сервера (модели не трогаем)."""
    if venv_dir().exists():
        shutil.rmtree(venv_dir())
        log.info("server_env: удалено %s", venv_dir())
