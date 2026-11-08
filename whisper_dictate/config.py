"""Конфигурация: TOML в ~/.config/whisper-dictate/config.toml.

Читаем через стандартный tomllib, пишем вручную: файл маленький и должен
оставаться читаемым человеком (комментарии, порядок секций).
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .paths import config_file

log = logging.getLogger(__name__)

DEFAULT_HOTKEY = "Meta+Alt+D"
INSERT_MODES = ("paste", "type", "clipboard")
PASTE_SHORTCUTS = ("ctrl+v", "ctrl+shift+v")
AUDIO_BACKENDS = ("auto", "parec", "pw-record")
LANGUAGES = ("ru", "en", "auto")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

# Секция TOML -> {ключ в файле: поле Config}. Порядок важен для записи.
SECTIONS: dict[str, dict[str, str]] = {
    "hotkey": {"toggle": "hotkey"},
    "transcribe": {
        "language": "language",
        "server_url": "server_url",
        "server_command": "server_command",
        "server_autostart": "server_autostart",
    },
    "insert": {
        "mode": "insert_mode",
        "restore_clipboard": "restore_clipboard",
        "restore_delay_ms": "restore_delay_ms",
        "paste_shortcut": "paste_shortcut",
    },
    "audio": {
        "backend": "audio_backend",
        "device": "audio_device",
        "min_seconds": "min_seconds",
        "max_seconds": "max_seconds",
    },
    "ui": {
        "beep": "beep",
        "show_hud": "show_hud",
        "hud_pin_top": "hud_pin_top",
        "autostart": "autostart",
        "log_level": "log_level",
    },
}

COMMENTS = {
    "hotkey": {
        "toggle": "глобальный хоткей, например Meta+Alt+D или Alt+M",
    },
    "transcribe": {
        "language": "ru, en или auto",
        "server_url": "локальный сервер распознавания (только 127.0.0.1)",
        "server_command": "команда запуска сервера; пусто — найти run.sh автоматически",
        "server_autostart": "поднимать сервер самому, если он не отвечает",
    },
    "insert": {
        "mode": "paste (буфер + Ctrl+V), type (посимвольно) или clipboard",
        "restore_clipboard": "вернуть прежнее содержимое буфера после вставки",
        "restore_delay_ms": "задержка перед восстановлением буфера, мс (Wayland отдаёт данные асинхронно)",
        "paste_shortcut": "ctrl+v для обычных окон, ctrl+shift+v для терминалов",
    },
    "audio": {
        "backend": "auto, parec или pw-record",
        "device": "@DEFAULT_SOURCE@ или имя источника PipeWire",
        "min_seconds": "записи короче — не отправлять на распознавание",
        "max_seconds": "защитный предел длительности записи",
    },
    "ui": {
        "beep": "звуковой сигнал старта и остановки",
        "show_hud": "показывать HUD во время записи",
        "hud_pin_top": "держать HUD сверху по центру (правило KWin)",
        "autostart": "запускать при входе в сессию",
        "log_level": "DEBUG, INFO, WARNING или ERROR",
    },
}


@dataclass
class Config:
    """Настройки приложения. Значения по умолчанию — рабочие для этой машины."""

    hotkey: str = DEFAULT_HOTKEY
    language: str = "ru"
    server_url: str = "http://127.0.0.1:8765"
    server_command: str = ""
    server_autostart: bool = True
    insert_mode: str = "paste"
    restore_clipboard: bool = False
    restore_delay_ms: int = 1500
    paste_shortcut: str = "ctrl+v"
    audio_backend: str = "auto"
    audio_device: str = "@DEFAULT_SOURCE@"
    min_seconds: float = 0.35
    max_seconds: float = 120.0
    beep: bool = True
    show_hud: bool = True
    hud_pin_top: bool = True
    autostart: bool = False
    log_level: str = "INFO"

    def with_changes(self, **changes: Any) -> "Config":
        return replace(self, **changes)


def is_loopback_url(url: str) -> bool:
    """Разрешены только локальные адреса: никаких внешних вызовов."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in {"127.0.0.1", "localhost", "::1"}


def _coerce(value: Any, default: Any, key: str) -> Any:
    """Привести значение из файла к типу поля; на мусор — значение по умолчанию."""
    try:
        if isinstance(default, bool):
            if isinstance(value, bool):
                return value
        elif isinstance(default, int):
            if isinstance(value, bool):
                raise TypeError
            return int(value)
        elif isinstance(default, float):
            if isinstance(value, bool):
                raise TypeError
            return float(value)
        elif isinstance(default, str):
            if isinstance(value, str):
                return value
    except (TypeError, ValueError):
        pass
    log.warning("config: некорректное значение %s=%r, беру %r", key, value, default)
    return default


def _validate(cfg: Config) -> Config:
    changes: dict[str, Any] = {}

    if cfg.paste_shortcut not in PASTE_SHORTCUTS:
        log.warning("config: неизвестное сочетание вставки %r, беру ctrl+v", cfg.paste_shortcut)
        changes["paste_shortcut"] = "ctrl+v"
    if cfg.insert_mode not in INSERT_MODES:
        log.warning("config: неизвестный режим вставки %r, беру paste", cfg.insert_mode)
        changes["insert_mode"] = "paste"
    if cfg.audio_backend not in AUDIO_BACKENDS:
        log.warning("config: неизвестный аудиобэкенд %r, беру auto", cfg.audio_backend)
        changes["audio_backend"] = "auto"
    if cfg.language not in LANGUAGES:
        log.warning("config: неизвестный язык %r, беру auto", cfg.language)
        changes["language"] = "auto"
    if cfg.log_level.upper() not in LOG_LEVELS:
        changes["log_level"] = "INFO"
    else:
        changes["log_level"] = cfg.log_level.upper()
    if not is_loopback_url(cfg.server_url):
        log.warning(
            "config: server_url %r не локальный, возвращаю 127.0.0.1:8765",
            cfg.server_url,
        )
        changes["server_url"] = "http://127.0.0.1:8765"
    if cfg.min_seconds <= 0:
        changes["min_seconds"] = 0.35
    if cfg.max_seconds <= cfg.min_seconds:
        changes["max_seconds"] = max(120.0, cfg.min_seconds * 2)
    if cfg.restore_delay_ms < 0:
        changes["restore_delay_ms"] = 0
    return cfg.with_changes(**changes) if changes else cfg


def load(path: Path | None = None) -> Config:
    """Прочитать конфиг; отсутствие файла — это нормально (берём умолчания)."""
    path = path or config_file()
    cfg = Config()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.info("config: %s не найден, использую значения по умолчанию", path)
        return cfg
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("config: не смог прочитать %s (%s), беру умолчания", path, exc)
        return cfg

    changes: dict[str, Any] = {}
    defaults = {f.name: f.default for f in fields(Config)}
    for section, mapping in SECTIONS.items():
        table = raw.get(section)
        if not isinstance(table, dict):
            continue
        for key, field_name in mapping.items():
            if key in table:
                changes[field_name] = _coerce(table[key], defaults[field_name], f"{section}.{key}")
    return _validate(replace(cfg, **changes))


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def dumps(cfg: Config) -> str:
    """Сериализовать конфиг в TOML с комментариями."""
    by_field = {f.name: getattr(cfg, f.name) for f in fields(Config)}
    lines = ["# Конфигурация whisper-dictate. Правки применяются при перезапуске."]
    for section, mapping in SECTIONS.items():
        lines.append("")
        lines.append(f"[{section}]")
        for key, field_name in mapping.items():
            comment = COMMENTS.get(section, {}).get(key)
            if comment:
                lines.append(f"# {comment}")
            lines.append(f"{key} = {_toml_value(by_field[field_name])}")
    return "\n".join(lines) + "\n"


def save(cfg: Config, path: Path | None = None) -> Path:
    path = path or config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(cfg), encoding="utf-8")
    log.info("config: записан %s", path)
    return path


def find_server_command() -> str | None:
    """Найти run.sh существующего сервиса Whisper, чтобы не качать модель заново."""
    candidates = [
        Path.home() / "Documents" / "dsh-set" / ".whisper-local" / "run.sh",
        Path.home() / ".local" / "share" / "whisper-dictate" / "run.sh",
        Path.home() / ".config" / "whisper-dictate" / "run.sh",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None
