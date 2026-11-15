"""Модели Whisper: каталог, наличие на диске и скачивание.

Модели хранятся одним каталогом на приложение (`~/.local/share/whisper-station/
models/<имя>`); встроенный сервер читает их оттуда, а не из чужого окружения.
Скачивание — только по явной команде пользователя, через huggingface_hub,
который живёт в окружении сервера.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import catalog, paths
from .config import find_server_command

log = logging.getLogger(__name__)

# Имена переменных: старую (WHISPER_DICTATE_MODELS) поддерживаем для миграции.
ENV_MODELS = "WHISPER_STATION_MODELS"
ENV_MODELS_LEGACY = "WHISPER_DICTATE_MODELS"


class ModelError(RuntimeError):
    """Скачать модель не удалось (нет инструментов или процесс упал)."""


def models_dir() -> Path:
    for variable in (ENV_MODELS, ENV_MODELS_LEGACY):
        override = os.environ.get(variable, "").strip()
        if override:
            return Path(override).expanduser()
    return paths.models_dir()


def model_path(name: str) -> Path:
    return models_dir() / name


def repo_of(name: str) -> str:
    info = catalog.get(name)
    if info is None:
        raise ModelError(f"Неизвестная модель {name!r}. Доступны: {', '.join(catalog.names())}")
    return info.repo


def is_installed(name: str) -> bool:
    path = model_path(name)
    return (path / "model.bin").is_file()


def installed_names() -> tuple[str, ...]:
    return tuple(info.name for info in catalog.CATALOG if is_installed(info.name))


def dir_size(path: Path) -> int:
    total = 0
    if not path.is_dir():
        return 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def status() -> dict[str, object]:
    """Что лежит в каталоге моделей: список установленных и занятое место."""
    path = models_dir()
    installed = installed_names()
    sizes = {name: dir_size(model_path(name)) for name in installed}
    return {
        "path": path,
        "exists": path.is_dir(),
        "installed": list(installed),
        "sizes": sizes,
        "size_bytes": sum(sizes.values()),
        "files": sum(1 for item in path.rglob("*") if item.is_file()) if path.is_dir() else 0,
    }


def resolve(name: str) -> str:
    """Что передать faster-whisper: локальный каталог, если модель уже скачана."""
    if is_installed(name):
        return str(model_path(name))
    return name


def remove(name: str) -> bool:
    """Удалить модель с диска. True — если что-то удалили."""
    path = model_path(name)
    if not path.exists():
        return False
    shutil.rmtree(path)
    log.info("models: удалена %s (%s)", name, path)
    return True


# --- поиск Python с huggingface_hub -------------------------------------
def legacy_server_python() -> Path | None:
    """Python окружения старого сервера (run.sh), если он ещё используется."""
    command = find_server_command()
    if not command:
        return None
    candidate = Path(command).parent / ".venv" / "bin" / "python"
    return candidate if candidate.is_file() else None


def python_with_hub() -> Path | None:
    """Первый интерпретатор, в котором импортируется huggingface_hub.

    Порядок: наше окружение сервера (там же живёт faster-whisper), Python
    приложения, окружение старого run.sh.
    """
    candidates = [paths.server_python(), Path(sys.executable), legacy_server_python()]
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate is None or candidate in seen or not candidate.is_file():
            continue
        seen.add(candidate)
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


def check_space(name: str) -> str | None:
    """Проверить место на диске; None — всё в порядке."""
    info = catalog.get(name)
    if info is None:
        return None
    target = models_dir()
    try:
        free = shutil.disk_usage(target if target.exists() else target.parent).free
    except OSError:
        return None
    needed = info.size_mb * 1024 * 1024
    if free < needed * 1.1:
        return (
            f"Для {name} нужно ~{info.size_label}, свободно {free / 1024**3:.1f} ГБ. "
            "Освободите место или выберите модель поменьше."
        )
    return None


def _run_download(argv: list[str], cancel: threading.Event | None) -> int:
    """Запустить загрузку и ждать её, умея отменить."""
    log.info("models: %s", " ".join(argv))
    process = subprocess.Popen(argv)  # noqa: S603 - аргументы собирает код
    while True:
        code = process.poll()
        if code is not None:
            return code
        if cancel is not None and cancel.is_set():
            log.info("models: отмена загрузки")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise ModelError("Загрузка отменена")
        time.sleep(0.2)


def download(
    name: str = catalog.DEFAULT_MODEL,
    target: Path | None = None,
    cancel: threading.Event | None = None,
) -> int:
    """Скачать модель по имени из каталога. Возвращает код возврата процесса."""
    repo = repo_of(name)
    python = python_with_hub()
    if python is None:
        raise ModelError(
            "Не нашёл Python с huggingface_hub: выполните whisper-station server install"
        )
    destination = target or model_path(name)
    destination.mkdir(parents=True, exist_ok=True)
    log.info("models: качаю %s (%s) в %s через %s", name, repo, destination, python)
    code = _run_download([str(python), "-c", download_script(repo, destination)], cancel)
    if code != 0:
        raise ModelError(f"Загрузка {name} завершилась с кодом {code}")
    if not is_installed(name):
        raise ModelError(
            f"Загрузка {name} прошла, но {destination / 'model.bin'} не появился: "
            "проверьте вывод выше"
        )
    log.info("models: готово, %s занимает %.0f МБ", name, dir_size(destination) / 1024**2)
    return code


def download_repo(repo: str, target: Path, cancel: threading.Event | None = None) -> int:
    """Скачать произвольный репозиторий HuggingFace (аргумент --repo)."""
    python = python_with_hub()
    if python is None:
        raise ModelError(
            "Не нашёл Python с huggingface_hub: выполните whisper-station server install"
        )
    target.mkdir(parents=True, exist_ok=True)
    code = _run_download([str(python), "-c", download_script(repo, target)], cancel)
    if code != 0:
        raise ModelError(f"Загрузка {repo} завершилась с кодом {code}")
    return code
