"""Модель Whisper: проверка наличия и скачивание по явной команде.

Приложение — только клиент: чтобы распознавание работало, рядом должен быть
совместимый сервер. Эта команда готовит каталог с моделью для такого сервера;
ничего не качает без подтверждения пользователя.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from . import APP_NAME
from .config import find_server_command

log = logging.getLogger(__name__)

DEFAULT_REPO = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
class ModelError(RuntimeError):
    """Скачать модель не удалось (нет инструментов или процесс упал)."""


DOWNLOAD_HINT = (
    "модель скачивается из HuggingFace (около 1.6 ГБ) в каталог "
    f"~/.local/share/{APP_NAME}/models"
)


def models_dir() -> Path:
    override = os.environ.get("WHISPER_DICTATE_MODELS", "").strip()
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(base) / APP_NAME / "models"


def status() -> dict[str, object]:
    path = models_dir()
    files = 0
    size = 0
    if path.is_dir():
        for item in path.rglob("*"):
            if item.is_file():
                files += 1
                try:
                    size += item.stat().st_size
                except OSError:
                    pass
    return {"path": path, "exists": path.is_dir(), "files": files, "size_bytes": size}


def server_python() -> Path | None:
    """Python окружения сервера: в нём уже есть huggingface_hub."""
    command = find_server_command()
    if not command:
        return None
    candidate = Path(command).parent / ".venv" / "bin" / "python"
    return candidate if candidate.is_file() else None


def python_with_hub() -> Path | None:
    """Первый интерпретатор, в котором импортируется huggingface_hub."""
    candidates = [server_python(), Path(sys.executable)]
    for candidate in candidates:
        if candidate is None or not candidate.is_file():
            continue
        try:
            probe = subprocess.run(  # noqa: S603 - свой интерпретатор
                [str(candidate), "-c", "import huggingface_hub"],
                capture_output=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0:
            return candidate
    return None


def download_script(repo: str, target: Path) -> str:
    return (
        "from huggingface_hub import snapshot_download\n"
        f"snapshot_download(repo_id={repo!r}, local_dir={str(target)!r})\n"
    )


def download(repo: str = DEFAULT_REPO, target: Path | None = None) -> int:
    """Скачать модель. Возвращает код возврата процесса загрузки."""
    python = python_with_hub()
    if python is None:
        raise ModelError(
            "Не нашёл Python с huggingface_hub: поставьте python-huggingface-hub "
            "или укажите сервер с готовой моделью"
        )
    destination = target or models_dir()
    destination.mkdir(parents=True, exist_ok=True)
    log.info("models: качаю %s в %s (%s)", repo, destination, python)
    result = subprocess.run(  # noqa: S603 - аргументы собирает код
        [str(python), "-c", download_script(repo, destination)],
        check=False,
    )
    if result.returncode != 0:
        raise ModelError(f"Загрузка завершилась с кодом {result.returncode}")
    log.info("models: готово, файлов %s", status()["files"])
    return result.returncode
