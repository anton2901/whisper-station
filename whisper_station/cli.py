"""Командная строка: управление демоном, разовое распознавание, диагностика."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import APP_NAME, APP_TITLE, __version__
from . import autostart as autostart_mod
from . import paths
from . import ipc
from .config import DEFAULT_HOTKEY, Config, dumps, load, save
from .logsetup import configure as configure_logging
from .recorder import available_backends, looks_like_wav
from .service import ServerManager, ServerStatus, health
from .stt import SttError, transcribe

DAEMON_COMMANDS = (
    "toggle",
    "start",
    "stop",
    "cancel",
    "repaste",
    "settings",
    "quit",
    "status",
)
START_TIMEOUT = 15.0


# --- IPC ----------------------------------------------------------------
def send_command(command: str, timeout: float = 15.0) -> str | None:
    """Тонкая обёртка над ipc.send (удобно подменять в тестах)."""
    return ipc.send(command, timeout)


def spawn_daemon() -> None:
    installed = shutil.which(APP_NAME)
    if installed:
        command = [installed, "daemon"]
        env = None
    else:
        command = [sys.executable, "-m", "whisper_station", "daemon"]
        env = dict(os.environ)
        source_root = str(Path(__file__).resolve().parent.parent)
        env["PYTHONPATH"] = source_root + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
        )
    subprocess.Popen(  # noqa: S603 - сами себя запускаем
        command,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def ensure_daemon(timeout: float = START_TIMEOUT) -> bool:
    if ipc.status() is not None:
        return True
    spawn_daemon()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ipc.status() is not None:
            return True
        time.sleep(0.2)
    return False


# --- команды ------------------------------------------------------------
def cmd_transcribe(args: argparse.Namespace, cfg: Config) -> int:
    path = Path(args.file).expanduser()
    if not path.is_file():
        print(f"{APP_NAME}: файл не найден: {path}", file=sys.stderr)
        return 1
    payload = path.read_bytes()
    if not looks_like_wav(payload):
        print(
            f"{APP_NAME}: нужен WAV 16 кГц моно PCM16, а {path.name} — не WAV",
            file=sys.stderr,
        )
        return 1
    if args.language:
        cfg = cfg.with_changes(language=args.language)
    try:
        result = transcribe(payload, cfg, filename=path.name)
    except SttError as exc:
        print(f"{APP_NAME}: {exc}", file=sys.stderr)
        return 1
    print(result.text)
    return 0 if result.text.strip() else 2


def cmd_status(cfg: Config) -> int:
    reply = ipc.status(timeout=3.0)
    if reply is not None:
        print(json.dumps(reply, ensure_ascii=False, indent=2))
        return 0
    status = health(cfg.server_url)
    print(
        json.dumps(
            {
                "daemon": False,
                "server": {
                    "ok": status.ok,
                    "model": status.model,
                    "device": status.device,
                    "error": status.error,
                },
                "config": str(paths.config_file()),
                "log": str(paths.log_file()),
                "version": __version__,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if status.ok else 1


def cmd_doctor(cfg: Config) -> int:
    from . import catalog, models, server_env
    from .hotkey import kglobalaccel_available, shortcut_to_int
    from .inject import check_environment
    from .textproc import describe_rules

    env = check_environment()
    server = health(cfg.server_url)
    session_type = os.environ.get("XDG_SESSION_TYPE", "?")
    manager = ServerManager(cfg)
    command = manager.command()
    kga = kglobalaccel_available()
    env_ok = server_env.is_installed()
    model_ok = models.is_installed(cfg.model_name)
    rows: list[tuple[str, str, bool]] = [
        ("сессия", f"{env['desktop'] or '?'} / {session_type}", bool(env["wayland"])),
        ("аудио", ", ".join(available_backends()) or "нет parec/pw-record", bool(available_backends())),
        ("буфер", "wl-copy/wl-paste" if env["wl_clipboard"] else "не найден", bool(env["wl_clipboard"])),
        ("ydotool", "найден" if env["ydotool"] else "не найден", bool(env["ydotool"])),
        ("uinput", "доступен на запись" if env["uinput"] else "нет доступа", bool(env["uinput"])),
        (
            "ydotoold",
            str(env["ydotoold_socket"] or ("поднимется при вставке" if env["uinput"] else "нет")),
            bool(env["ydotoold_socket"]) or bool(env["uinput"]),
        ),
        ("kglobalaccel", "есть" if kga else "нет", kga),
        ("сервер", server.describe(), server.ok),
        ("устройство", f"в конфиге {cfg.model_device}, детект {catalog.detect_device()}", True),
        ("команда сервера", command or "не найдена", bool(command)),
        (
            "окружение",
            "faster-whisper " + (server_env.faster_whisper_version() or "?")
            if env_ok
            else "не установлено — whisper-station server install",
            env_ok or server.ok or bool(command),
        ),
        (
            "модель",
            _model_row_text(cfg.model_name, model_ok, server),
            model_ok or server.ok,
        ),
        ("текст", describe_rules(cfg), True),
        ("конфиг", str(paths.config_file()), paths.config_file().parent.exists()),
        ("лог", str(paths.log_file()), paths.log_file().parent.exists()),
    ]
    try:
        shortcut_to_int(cfg.hotkey)
        hotkey_ok, hotkey_text = True, cfg.hotkey
    except Exception as exc:  # noqa: BLE001 - в диагностике показываем причину
        hotkey_ok, hotkey_text = False, f"{cfg.hotkey} ({exc})"
    rows.insert(1, ("хоткей", hotkey_text, hotkey_ok))

    width = max(len(name) for name, _, _ in rows)
    failures = 0
    for name, value, ok in rows:
        mark = "ok  " if ok else "--  "
        if not ok:
            failures += 1
        print(f"{mark}{name:<{width}}  {value}")
    print()
    if failures:
        print(f"{failures} пункт(ов) требуют внимания. Лог: {paths.log_file()}")
        return 1
    print(f"Всё необходимое на месте. Хоткей: {cfg.hotkey if cfg.hotkey else DEFAULT_HOTKEY}")
    return 0


def _model_row_text(name: str, downloaded: bool, server: ServerStatus) -> str:
    """Строка doctor про модель: своя на диске, чужая у сервера или нет совсем."""
    if downloaded:
        return f"{name}: скачана"
    if server.ok:
        return f"{name}: у сервера ({server.model or '?'} на {server.device or '?'})"
    return f"{name}: не скачана — whisper-station model download --yes"


def cmd_config(args: argparse.Namespace, cfg: Config) -> int:
    path = paths.config_file()
    if args.edit:
        editor = os.environ.get("EDITOR") or "xdg-open"
        return subprocess.call([editor, str(path)])  # noqa: S603 - редактор пользователя
    print(path)
    if args.show or not path.exists():
        print()
        print(dumps(cfg), end="")
    return 0


def cmd_model(args: argparse.Namespace, cfg: Config) -> int:
    from . import catalog, models, server_env

    if args.action == "list":
        installed = set(models.installed_names())
        for info in catalog.CATALOG:
            mark = "✓" if info.name in installed else " "
            current = "*" if info.name == cfg.model_name else " "
            print(f"{mark}{current} {info.describe()}")
        print()
        print(f"каталог: {models.models_dir()}")
        print(f"в конфиге: {cfg.model_name}, устройство: {cfg.model_device}")
        if not server_env.is_installed():
            print("сервер не установлен: whisper-station server install")
        return 0

    if args.action == "status":
        info = models.status()
        print(
            json.dumps(
                {
                    "path": str(info["path"]),
                    "exists": info["exists"],
                    "installed": info["installed"],
                    "sizes": {name: size for name, size in info["sizes"].items()},
                    "total_mb": round(int(info["size_bytes"]) / 1_048_576, 1),
                    "configured": cfg.model_name,
                    "device": cfg.model_device,
                    "server_installed": server_env.is_installed(),
                    "python": str(models.python_with_hub() or "нет с huggingface_hub"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    name = (args.name or cfg.model_name).strip()
    if args.action == "remove":
        if not args.yes:
            print(f"Удалит {name} из {models.models_dir()}. Повторите с --yes")
            return 1
        if models.remove(name):
            print(f"удалено: {name}")
            return 0
        print(f"{name} и так нет")
        return 0

    # download
    if not args.yes:
        try:
            repo = models.repo_of(name)
        except models.ModelError as exc:
            print(f"{APP_NAME}: {exc}", file=sys.stderr)
            return 1
        size = catalog.get(name).size_label if catalog.get(name) else "?"
        print(f"Скачает {name} ({size}, {repo}) в {models.models_dir()}")
        print("Повторите с --yes, если это то, что нужно")
        return 1
    problem = models.check_space(name)
    if problem:
        print(f"{APP_NAME}: {problem}", file=sys.stderr)
        return 1
    try:
        if args.repo:
            models.download_repo(args.repo, models.model_path(name))
        else:
            models.download(name)
    except models.ModelError as exc:
        print(f"{APP_NAME}: {exc}", file=sys.stderr)
        return 1
    print(f"модель {name} в {models.model_path(name)}")
    return 0


def cmd_server(args: argparse.Namespace, cfg: Config) -> int:
    from . import models, server_env

    if args.action == "status":
        print(
            json.dumps(
                {
                    "installed": server_env.is_installed(),
                    "cuda": server_env.cuda_enabled(),
                    "venv": str(server_env.venv_dir()),
                    "python": str(server_env.python()),
                    "faster_whisper": server_env.faster_whisper_version(),
                    "size_mb": round(server_env.venv_size() / 1_048_576, 1),
                    "model": cfg.model_name,
                    "model_downloaded": models.is_installed(cfg.model_name),
                    "device": cfg.model_device,
                    "command": ServerManager(cfg).command(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.action == "install":
        if server_env.is_installed() and not args.force:
            if args.cuda and not server_env.cuda_enabled():
                print("Добавляю cuBLAS/cuDNN в готовое окружение (~1.4 ГБ)")
                try:
                    server_env.install_cuda()
                except server_env.InstallError as exc:
                    print(f"{APP_NAME}: {exc}", file=sys.stderr)
                    return 1
                print("готово: CUDA-библиотеки на месте")
                return 0
            print(
                f"окружение сервера уже есть: faster-whisper "
                f"{server_env.faster_whisper_version() or '?'} ({server_env.python()})"
            )
            print("переустановить: whisper-station server install --force")
            return 0
        if args.cuda:
            print("С CUDA: дополнительно cuBLAS/cuDNN из колёс NVIDIA (~1.4 ГБ)")
        print(f"Ставлю окружение сервера в {server_env.venv_dir()} — это пара минут")
        try:
            version = server_env.install(args.python, force=args.force, cuda=args.cuda)
        except server_env.InstallError as exc:
            print(f"{APP_NAME}: {exc}", file=sys.stderr)
            return 1
        print(f"готово: faster-whisper {version}")
        print(f"дальше: whisper-station model download --name {cfg.model_name} --yes")
        return 0

    if args.action == "uninstall":
        if not args.yes:
            print(f"Удалит {server_env.venv_dir()} (модели останутся). Повторите с --yes")
            return 1
        server_env.remove()
        print("окружение сервера удалено")
        return 0

    # start
    manager = ServerManager(cfg)
    if not manager.builtin_ready() and not cfg.server_command.strip():
        print(
            f"{APP_NAME}: нет сервера. Сначала: whisper-station server install",
            file=sys.stderr,
        )
        return 1
    try:
        status = manager.ensure(timeout=180.0)
    except Exception as exc:  # noqa: BLE001 - текст показываем как есть
        print(f"{APP_NAME}: {exc}", file=sys.stderr)
        return 1
    print(f"сервер отвечает: {status.describe()}")
    return 0



def cmd_systemd(args: argparse.Namespace, cfg: Config) -> int:
    from . import systemd_unit

    if args.action == "status":
        print(
            json.dumps(
                {
                    "unit": str(systemd_unit.unit_path()),
                    "enabled": systemd_unit.is_enabled(),
                    "active": systemd_unit.is_active(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.action == "install":
        print(systemd_unit.install())
        return 0
    if args.action == "enable":
        if ipc.status() is not None:
            # Освобождаем место: дальше демоном управляет systemd.
            ipc.send("quit")
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and ipc.status() is not None:
                time.sleep(0.2)
        if not systemd_unit.enable():
            print(f"{APP_NAME}: не удалось включить юнит", file=sys.stderr)
            return 1
        autostart_mod.disable()
        save(cfg.with_changes(autostart=False))
        print(f"юнит включён: {systemd_unit.unit_path()}")
        print("автозапуск через ~/.config/autostart отключён, чтобы не было двух копий")
        return 0
    systemd_unit.disable()
    print("юнит выключен")
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    path = paths.log_file()
    if args.open:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        return subprocess.call(["xdg-open", str(path)])  # noqa: S603
    print(path)
    return 0


def cmd_autostart(args: argparse.Namespace) -> int:
    if args.action == "on":
        print(autostart_mod.enable())
        return 0
    if args.action == "off":
        autostart_mod.disable()
        return 0
    print("on" if autostart_mod.is_enabled() else "off")
    return 0


def cmd_service(args: argparse.Namespace, cfg: Config) -> int:
    if args.action == "status":
        status = health(cfg.server_url)
        print(json.dumps(status.__dict__, ensure_ascii=False, indent=2))
        return 0 if status.ok else 1
    manager = ServerManager(cfg)
    try:
        status = manager.ensure(timeout=180.0)
    except Exception as exc:  # noqa: BLE001 - текст показываем как есть
        print(f"{APP_NAME}: {exc}", file=sys.stderr)
        return 1
    print(f"сервер отвечает: {status.describe()}")
    return 0


# --- разбор аргументов --------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=f"{APP_TITLE}: локальная диктовка (Wayland, KDE Plasma 6)",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    sub = parser.add_subparsers(dest="command")

    daemon = sub.add_parser("daemon", help="запустить демон с иконкой в трее")
    daemon.set_defaults(func=lambda _args, cfg: _run_daemon())

    for name, help_text in (
        ("toggle", "начать/остановить запись"),
        ("start", "начать запись"),
        ("stop", "остановить запись и вставить текст"),
        ("cancel", "отменить запись без вставки"),
        ("repaste", "вставить последний распознанный текст"),
        ("settings", "открыть настройки"),
        ("quit", "завершить демон"),
    ):
        sub.add_parser(name, help=help_text).set_defaults(func=_daemon_command(name))

    sub.add_parser("status", help="состояние демона и сервера").set_defaults(func=_status_command)

    transcribe_parser = sub.add_parser("transcribe", help="распознать WAV-файл")
    transcribe_parser.add_argument("file", help="путь к WAV 16 кГц моно")
    transcribe_parser.add_argument("--language", help="ru, en или auto")
    transcribe_parser.set_defaults(func=cmd_transcribe)

    sub.add_parser("doctor", help="проверить окружение").set_defaults(func=lambda _a, cfg: cmd_doctor(cfg))

    config_parser = sub.add_parser("config", help="показать или открыть конфиг")
    config_parser.add_argument("--show", action="store_true", help="напечатать содержимое")
    config_parser.add_argument("--edit", action="store_true", help="открыть в редакторе")
    config_parser.set_defaults(func=cmd_config)

    log_parser = sub.add_parser("log", help="путь к логу")
    log_parser.add_argument("--open", action="store_true", help="открыть лог")
    log_parser.set_defaults(func=lambda args, _cfg: cmd_log(args))

    autostart_parser = sub.add_parser("autostart", help="автозапуск при входе")
    autostart_parser.add_argument("action", choices=("on", "off", "status"))
    autostart_parser.set_defaults(func=lambda args, _cfg: cmd_autostart(args))

    model_parser = sub.add_parser("model", help="модель Whisper: каталог, скачивание, удаление")
    model_parser.add_argument("action", choices=("list", "status", "download", "remove"))
    model_parser.add_argument("--name", help="имя модели из каталога")
    model_parser.add_argument("--repo", help="свой репозиторий HuggingFace")
    model_parser.add_argument(
        "--yes", action="store_true", help="подтвердить скачивание или удаление"
    )
    model_parser.set_defaults(func=cmd_model)

    server_parser = sub.add_parser("server", help="встроенный сервер распознавания")
    server_parser.add_argument("action", choices=("install", "status", "start", "uninstall"))
    server_parser.add_argument("--python", help="Python для venv (по умолчанию текущий)")
    server_parser.add_argument("--force", action="store_true", help="пересоздать окружение")
    server_parser.add_argument(
        "--cuda", action="store_true", help="поставить cuBLAS/cuDNN для NVIDIA (~1.4 ГБ)"
    )
    server_parser.add_argument("--yes", action="store_true", help="подтвердить удаление")
    server_parser.set_defaults(func=cmd_server)

    systemd_parser = sub.add_parser("systemd", help="user-юнит systemd вместо autostart")
    systemd_parser.add_argument("action", choices=("install", "enable", "disable", "status"))
    systemd_parser.set_defaults(func=cmd_systemd)

    service_parser = sub.add_parser("service", help="локальный сервер распознавания")
    service_parser.add_argument("action", choices=("status", "start"))
    service_parser.set_defaults(func=cmd_service)

    return parser


def _run_daemon() -> int:
    from .app import run

    return run(load())


def _daemon_command(name: str):
    def handler(_args: argparse.Namespace, _cfg: Config) -> int:
        if not ensure_daemon():
            print(f"{APP_NAME}: демон не запустился, смотрите {paths.log_file()}", file=sys.stderr)
            return 1
        reply = send_command(name)
        if reply is None:
            print(f"{APP_NAME}: демон не ответил", file=sys.stderr)
            return 1
        if reply.startswith("error"):
            print(f"{APP_NAME}: {reply}", file=sys.stderr)
            return 1
        return 0

    return handler


def _status_command(_args: argparse.Namespace, cfg: Config) -> int:
    return cmd_status(cfg)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    cfg = load()
    configure_logging(cfg.log_level, file=args.command == "daemon")
    try:
        return int(args.func(args, cfg))
    except KeyboardInterrupt:
        return 130
