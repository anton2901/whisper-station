"""Конфигурация: TOML в ~/.config/whisper-station/config.toml.

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

from .paths import config_file, legacy_config_file

log = logging.getLogger(__name__)

DEFAULT_HOTKEY = "Meta+Alt+D"
# Потолок записи: 30 минут. Сервер принимает до 64 МБ (~34 мин PCM16 16 кГц),
# а в памяти это ~58 МБ — с запасом.
MAX_RECORD_SECONDS = 1800.0
# Словарь — пост-коррекция текста, поэтому список не может быть произвольным:
# ограничиваем число терминов и их длину, чтобы вставка оставалась быстрой.
MAX_DICTIONARY_WORDS = 200
MAX_WORD_LENGTH = 64
INSERT_MODES = ("paste", "type", "clipboard")
PASTE_SHORTCUTS = ("ctrl+v", "ctrl+shift+v")
HOTKEY_MODES = ("toggle", "press")
AUDIO_BACKENDS = ("auto", "parec", "pw-record")
LANGUAGES = ("ru", "en", "auto")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

# Секция TOML -> {ключ в файле: поле Config}. Порядок важен для записи.
SECTIONS: dict[str, dict[str, str]] = {
    "hotkey": {"toggle": "hotkey", "mode": "hotkey_mode"},
    "preview": {"live": "preview_live"},
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
    "dictionary": {
        "words": "dictionary_words",
        "threshold": "dictionary_threshold",
    },
    "text": {
        "remove_fillers": "remove_fillers",
        "collapse_stutters": "collapse_stutters",
        "trailing_space": "trailing_space",
        "fillers": "fillers",
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
        "mode": "toggle (нажал-нажал) или press (удержание, push-to-talk)",
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
    "dictionary": {
        "words": 'свои термины и имена: ["Kubernetes", "ChargeBee"] — исправляются после распознавания',
        "threshold": "допустимое расхождение при нечётком совпадении, 0…1 (0 — только точные)",
    },
    "text": {
        "remove_fillers": "убирать «ээ», «ммм», «uh», «hmm» из готового текста",
        "collapse_stutters": "схлопывать повторы «я я я» в одно слово",
        "trailing_space": "добавлять пробел в конце — чтобы диктовки не слипались",
        "fillers": "свой список филлеров; пусто — встроенный",
    },
    "audio": {
        "backend": "auto, parec или pw-record",
        "device": "@DEFAULT_SOURCE@ или имя источника PipeWire",
        "min_seconds": "записи короче — не отправлять на распознавание",
        "max_seconds": "защитный предел длительности записи",
    },
    "preview": {
        "live": "живой предпросмотр распознавания в HUD",
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
    hotkey_mode: str = "toggle"
    preview_live: bool = True
    language: str = "ru"
    server_url: str = "http://127.0.0.1:8765"
    server_command: str = ""
    server_autostart: bool = True
    insert_mode: str = "paste"
    restore_clipboard: bool = False
    restore_delay_ms: int = 1500
    paste_shortcut: str = "ctrl+v"
    dictionary_words: tuple[str, ...] = ()
    dictionary_threshold: float = 0.18
    remove_fillers: bool = True
    collapse_stutters: bool = True
    trailing_space: bool = False
    fillers: tuple[str, ...] = ()
    audio_backend: str = "auto"
    audio_device: str = "@DEFAULT_SOURCE@"
    min_seconds: float = 0.35
    max_seconds: float = 300.0
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
        elif isinstance(default, tuple):
            if isinstance(value, list):
                items = [item for item in value if isinstance(item, str)]
                if len(items) != len(value):
                    log.warning(
                        "config: в %s не только строки, нестроковые значения пропущены",
                        key,
                    )
                return tuple(items)
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


def _clean_words(
    words: tuple[str, ...],
    label: str,
    *,
    limit: int = MAX_DICTIONARY_WORDS,
) -> tuple[str, ...]:
    """Обрезать пробелы, убрать пустые и одинаковые (без учёта регистра) слова."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in words:
        word = " ".join(str(raw).split()).strip()
        if not word:
            continue
        if len(word) > MAX_WORD_LENGTH:
            log.warning("config: %s: слово длиннее %d символов пропущено", label, MAX_WORD_LENGTH)
            continue
        key = word.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(word)
        if len(cleaned) >= limit:
            log.warning("config: %s: больше %d слов, остальные пропущены", label, limit)
            break
    return tuple(cleaned)


def _validate(cfg: Config) -> Config:
    changes: dict[str, Any] = {}

    words = _clean_words(cfg.dictionary_words, "dictionary.words")
    if words != cfg.dictionary_words:
        changes["dictionary_words"] = words
    fillers = _clean_words(cfg.fillers, "text.fillers", limit=100)
    if fillers != cfg.fillers:
        changes["fillers"] = fillers
    if not 0.0 <= cfg.dictionary_threshold <= 1.0:
        log.warning(
            "config: порог словаря %.2f вне 0…1, беру 0.18", cfg.dictionary_threshold
        )
        changes["dictionary_threshold"] = 0.18

    if cfg.hotkey_mode not in HOTKEY_MODES:
        log.warning("config: неизвестный режим хоткея %r, беру toggle", cfg.hotkey_mode)
        changes["hotkey_mode"] = "toggle"
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
    if cfg.max_seconds > MAX_RECORD_SECONDS:
        log.warning(
            "config: max_seconds=%.0f больше предела, ограничиваю %.0f",
            cfg.max_seconds,
            MAX_RECORD_SECONDS,
        )
        changes["max_seconds"] = MAX_RECORD_SECONDS
    if cfg.restore_delay_ms < 0:
        changes["restore_delay_ms"] = 0
    return cfg.with_changes(**changes) if changes else cfg


def load(path: Path | None = None) -> Config:
    """Прочитать конфиг; отсутствие файла — это нормально (берём умолчания)."""
    explicit = path is not None
    path = path or config_file()
    cfg = Config()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        legacy = legacy_config_file()
        if not explicit and legacy.is_file():
            log.info("config: переношу настройки из %s", legacy)
            migrated = load(legacy)
            save(migrated)
            return migrated
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
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def dumps(cfg: Config) -> str:
    """Сериализовать конфиг в TOML с комментариями."""
    by_field = {f.name: getattr(cfg, f.name) for f in fields(Config)}
    lines = ["# Конфигурация whisper-station. Правки применяются при перезапуске."]
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
        Path.home() / ".local" / "share" / "whisper-station" / "run.sh",
        Path.home() / ".config" / "whisper-station" / "run.sh",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None
