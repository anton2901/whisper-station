"""Вставка текста в активное окно Wayland.

Основной путь: wl-copy (буфер) + Ctrl+V через ydotool/uinput.
Запасные: ввод по символам (ydotool type) и «только буфер».
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .paths import runtime_dir, ydotoold_socket

log = logging.getLogger(__name__)

# KEY_LEFTCTRL=29, KEY_V=47 в кодах Linux input-event-codes.
CTRL_V_SEQUENCE = ("29:1", "47:1", "47:0", "29:0")
SOCKET_CANDIDATES = (Path("/tmp/.ydotool_socket"),)

# Собственный ydotoold: останавливаем его при выходе приложения.
_ydotoold: subprocess.Popen[bytes] | None = None
_ydotoold_stderr: object | None = None


class InjectError(RuntimeError):
    """Вставка невозможна (нет инструментов или прав)."""


@dataclass(frozen=True)
class InjectionResult:
    ok: bool
    method: str
    detail: str = ""


def _run(
    command: list[str],
    *,
    timeout: float = 10.0,
    input_bytes: bytes | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    # wl-copy демонизируется и держит унаследованные дескрипторы: с PIPE
    # subprocess.run повиснет навсегда, ожидая EOF. Пишем stderr в файл.
    with tempfile.TemporaryFile() as errors:
        completed = subprocess.run(  # noqa: S603 - аргументы фиксированы кодом
            command,
            input=input_bytes,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=errors,
            timeout=timeout,
            check=False,
            start_new_session=True,
        )
        errors.seek(0)
        stderr = errors.read()
    return subprocess.CompletedProcess(completed.args, completed.returncode, completed.stdout, stderr)


def _require(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise InjectError(f"{tool} не найден в PATH")
    return path


# --- буфер обмена -------------------------------------------------------
def clipboard_set(text: str) -> None:
    """Положить текст в буфер. wl-copy демонизируется — запускаем отвязанно."""
    _require("wl-copy")
    result = _run(["wl-copy"], input_bytes=text.encode("utf-8"))
    if result.returncode != 0:
        raise InjectError(
            f"wl-copy вернул {result.returncode}: {result.stderr.decode('utf-8', 'replace').strip()}"
        )


def clipboard_get() -> str:
    if not shutil.which("wl-paste"):
        return ""
    try:
        result = _run(["wl-paste", "--no-newline"], timeout=5.0, capture=True)
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("clipboard_get: %s", exc)
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.decode("utf-8", "replace") if result.stdout else ""


def clipboard_clear() -> None:
    if shutil.which("wl-copy"):
        _run(["wl-copy", "--clear"])


# --- ydotool ------------------------------------------------------------
def _socket_alive(path: Path) -> bool:
    """Сокет существует и кто-то слушает (защита от мусора после падения).

    ydotoold слушает SOCK_DGRAM: с SOCK_STREAM connect падает с EPROTOTYPE.
    """
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    probe.settimeout(0.2)
    try:
        probe.connect(str(path))
    except OSError:
        return False
    finally:
        probe.close()
    return True


def find_ydotoold_socket() -> Path | None:
    env_socket = os.environ.get("YDOTOOL_SOCKET", "").strip()
    candidates = [Path(env_socket)] if env_socket else []
    candidates += [*SOCKET_CANDIDATES, ydotoold_socket()]
    for candidate in candidates:
        if candidate.exists() and _socket_alive(candidate):
            return candidate
    return None


def ensure_ydotoold(timeout: float = 3.0) -> Path:
    """Найти или поднять собственный ydotoold. Права не меняются.

    На CachyOS /dev/uinput уже доступен пользователю через ACL uaccess,
    поэтому демон запускается от обычного пользователя.
    """
    existing = find_ydotoold_socket()
    if existing is not None:
        return existing
    if not shutil.which("ydotoold"):
        raise InjectError("ydotoold не найден: вставка через Ctrl+V недоступна")

    socket_path = ydotoold_socket()
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        socket_path.unlink()
    except FileNotFoundError:
        pass
    global _ydotoold, _ydotoold_stderr
    for attempt in (1, 2):
        log.info("inject: запускаю ydotoold (%s), попытка %d", socket_path, attempt)
        try:
            socket_path.unlink(missing_ok=True)
        except OSError:
            pass
        _ydotoold_stderr = tempfile.NamedTemporaryFile(
            prefix="whisper-ydotoold-", suffix=".log"
        )
        try:
            _ydotoold = subprocess.Popen(  # noqa: S603 - фиксированные аргументы
                ["ydotoold", "-p", str(socket_path), "-P", "0600"],
                stdout=subprocess.DEVNULL,
                stderr=_ydotoold_stderr,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            raise InjectError(f"Не удалось запустить ydotoold: {exc}") from exc
        if _wait_for_socket(socket_path, timeout):
            return socket_path
        if _ydotoold.poll() is None:
            break

    detail = _ydotoold_log()
    raise InjectError(
        "ydotoold не поднялся"
        + (f" ({detail})" if detail else "")
        + ". Нужен доступ к /dev/uinput (ACL uaccess, группа input или root)"
    )


def _wait_for_socket(socket_path: Path, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if socket_path.exists() and _socket_alive(socket_path):
            return True
        time.sleep(0.05)
    return False


def _ydotoold_log() -> str:
    if _ydotoold_stderr is None:
        return ""
    try:
        _ydotoold_stderr.flush()
        _ydotoold_stderr.seek(0)
        return _ydotoold_stderr.read().decode("utf-8", "replace").strip()[-300:]
    except (OSError, ValueError):
        return ""


def _pids_on_socket(socket_path: Path) -> list[int]:
    """Все ydotoold, слушающие наш сокет (могут остаться от прошлых запусков)."""
    marker = str(socket_path)
    own = {os.getpid(), os.getppid()}
    found: list[int] = []
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return found
    for entry in entries:
        if not entry.name.isdigit() or int(entry.name) in own:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        # Строгая проверка: argv[0] — именно ydotoold, путь — отдельный аргумент.
        # Иначе под нож попадает любой `bash -c "... ydotoold ..."`.
        argv = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
        if argv and Path(argv[0]).name == "ydotoold" and marker in argv:
            found.append(int(entry.name))
    return found


def stop_ydotoold() -> None:
    """Остановить ydotoold на нашем сокете (свой и подхваченный от прошлого запуска)."""
    global _ydotoold, _ydotoold_stderr
    proc, _ydotoold = _ydotoold, None
    socket_path = ydotoold_socket()
    try:
        if proc is not None and proc.poll() is None:
            log.info("inject: останавливаю собственный ydotoold")
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1)
        for pid in _pids_on_socket(socket_path):
            log.info("inject: останавливаю ydotoold с нашего сокета (pid %s)", pid)
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        for _ in range(40):
            if not _pids_on_socket(socket_path):
                break
            time.sleep(0.05)
        for pid in _pids_on_socket(socket_path):
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    finally:
        if _ydotoold_stderr is not None:
            try:
                _ydotoold_stderr.close()
            except OSError:
                pass
            _ydotoold_stderr = None
        try:
            socket_path.unlink(missing_ok=True)
        except OSError:
            pass


def _ydotool(socket_path: Path, args: list[str], timeout: float = 15.0) -> None:
    _require("ydotool")
    env = dict(os.environ, YDOTOOL_SOCKET=str(socket_path))
    result = subprocess.run(  # noqa: S603 - аргументы фиксированы кодом
        ["ydotool", *args],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise InjectError(f"ydotool {args[0]} вернул {result.returncode}: {message}")


def paste_shortcut(socket_path: Path) -> None:
    _ydotool(socket_path, ["key", *CTRL_V_SEQUENCE])


def type_text(socket_path: Path, text: str, delay_ms: int = 12) -> None:
    _ydotool(socket_path, ["type", "--delay", str(delay_ms), text])


# --- стратегии ----------------------------------------------------------
def inject_text(text: str, cfg: Config) -> InjectionResult:
    """Вставить текст согласно конфигу. Никогда не бросает: результат в объекте."""
    if not text:
        return InjectionResult(False, "none", "Пустой текст")

    try:
        if cfg.insert_mode == "clipboard":
            clipboard_set(text)
            return InjectionResult(True, "clipboard", "Текст в буфере обмена")
    except InjectError as exc:
        return InjectionResult(False, "clipboard", f"Буфер недоступен: {exc}")

    previous = None
    if cfg.restore_clipboard:
        previous = clipboard_get()

    try:
        clipboard_set(text)
    except InjectError as exc:
        return InjectionResult(False, "clipboard", f"Буфер недоступен: {exc}")

    if cfg.insert_mode == "type":
        try:
            socket_path = ensure_ydotoold()
            type_text(socket_path, text)
        except InjectError as exc:
            log.warning("inject: посимвольный ввод не удался: %s", exc)
            return InjectionResult(False, "clipboard", f"Ввод недоступен ({exc}). Текст в буфере")
        _restore_clipboard(previous, cfg.restore_delay_ms, text)
        return InjectionResult(True, "type", "")

    try:
        socket_path = ensure_ydotoold()
        paste_shortcut(socket_path)
    except InjectError as exc:
        log.warning("inject: Ctrl+V не удался: %s", exc)
        return InjectionResult(
            False, "clipboard", f"Вставка недоступна ({exc}). Текст в буфере обмена"
        )

    _restore_clipboard(previous, cfg.restore_delay_ms, text)
    return InjectionResult(True, "paste", "")


def _restore_clipboard(previous: str | None, delay_ms: int, expected: str) -> None:
    """Вернуть прежний буфер, но только если его ещё не перезаписали.

    Wayland отдаёт данные вставки асинхронно: приложение читает буфер через
    несколько сотен миллисекунд после Ctrl+V. Поэтому восстановление
    откладывается и выполняется в фоновом потоке, а не в UI-потоке.
    """
    if previous is None:
        return
    if delay_ms <= 0:
        _do_restore(previous, expected)
        return
    timer = threading.Timer(delay_ms / 1000.0, _do_restore, args=(previous, expected))
    timer.daemon = True
    timer.start()


def _do_restore(previous: str, expected: str) -> None:
    try:
        if clipboard_get() != expected:
            log.debug("inject: буфер уже изменили, восстановление пропущено")
            return
        if previous:
            clipboard_set(previous)
        else:
            clipboard_clear()
    except (InjectError, OSError, subprocess.SubprocessError) as exc:
        log.debug("inject: не удалось вернуть буфер: %s", exc)


def check_environment() -> dict[str, object]:
    """Диагностика для `whisper-dictate doctor`."""
    info: dict[str, object] = {
        "wayland": os.environ.get("XDG_SESSION_TYPE") == "wayland",
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
        "wl_clipboard": shutil.which("wl-copy") is not None,
        "ydotool": shutil.which("ydotool") is not None,
        "ydotoold_socket": str(find_ydotoold_socket() or ""),
        "runtime_dir": str(runtime_dir()),
    }
    uinput = Path("/dev/uinput")
    info["uinput"] = uinput.exists() and os.access(uinput, os.W_OK)
    return info
