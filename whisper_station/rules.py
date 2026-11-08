"""Позиционирование HUD на KWin через правило окна.

Wayland не позволяет клиенту двигать свои окна: `move()` игнорируется
композитором, а KWin размещает новые окна сам (часто по центру экрана).
Единственный штатный способ задать позицию — правило KWin (`kwinrulesrc`).
Правило видно и удаляется в System Settings → Window Rules.

Файл правим сами, без `kreadconfig6`/`kwriteconfig6`: эти утилиты при каждом
вызове трогают собственный `kreadconfig6rc` и, если его не удаётся записать,
показывают модальный диалог — а мы вызывали их по разу на ключ при каждом
старте приложения. Формат kwinrulesrc — обычный INI, нам нужна одна секция.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

APP_ID = "whisper-station"
HUD_TITLE = "Whisper Station HUD"
RULE_ID = 991001
CONFIG_NAME = "kwinrulesrc"

HUD_WIDTH = 480   # должно совпадать с hud.WIDTH
HUD_HEIGHT = 64   # должно совпадать с hud.HEIGHT
MARGIN_TOP = 72   # ниже верхней панели Plasma, чтобы не срабатывало автоскрытие

RULE_KEYS = (
    ("Description", "Whisper Station HUD (ставит само приложение)"),
    ("wmclass", APP_ID),
    ("wmclasscomplete", "false"),
    ("wmclassmatch", "1"),
    ("title", HUD_TITLE),
    ("titlematch", "2"),
    ("positionrule", "2"),  # Apply: KWin ставит HUD при появлении
)


def hud_position(screen_x: int, screen_y: int, screen_width: int) -> tuple[int, int]:
    """Координаты верхнего центра экрана для HUD."""
    x = screen_x + max(0, (screen_width - HUD_WIDTH) // 2)
    return x, screen_y + MARGIN_TOP


def available() -> bool:
    """Наличие утилиты перезагрузки конфига KWin (необязательна)."""
    return shutil.which("qdbus6") is not None


def rule_ids(raw: str) -> list[int]:
    """Разобрать список id правил из [General] rules."""
    ids: list[int] = []
    for chunk in raw.replace(" ", "").split(","):
        if chunk.isdigit():
            ids.append(int(chunk))
    return ids


# --- минимальный INI ----------------------------------------------------
def parse_sections(lines: list[str]) -> dict[str, dict[str, str]]:
    """Разобрать INI в {секция: {ключ: значение}} (порядок и комментарии не нужны)."""
    sections: dict[str, dict[str, str]] = {}
    current = ""
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1]
            sections.setdefault(current, {})
            continue
        if "=" in stripped and current:
            key, _, value = stripped.partition("=")
            sections[current][key.strip()] = value.strip()
    return sections


def read_config(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []


def _set_in_section(lines: list[str], section: str, key: str, value: str) -> list[str]:
    """Вставить/обновить ключ в секции, сохранив остальной файл как есть."""
    header = f"[{section}]"
    out: list[str] = []
    inside = False
    found_section = False
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if inside and not replaced:
                out.append(f"{key}={value}")
                replaced = True
            inside = stripped == header
            if inside:
                found_section = True
            out.append(line)
            continue
        if inside and not replaced:
            name = stripped.partition("=")[0].strip()
            if name == key and "=" in stripped:
                out.append(f"{key}={value}")
                replaced = True
                continue
        out.append(line)
    if inside and not replaced:
        out.append(f"{key}={value}")
        replaced = True
    if not found_section:
        if out and out[-1].strip():
            out.append("")
        out.append(header)
        out.append(f"{key}={value}")
    return out


def _remove_section(lines: list[str], section: str) -> list[str]:
    header = f"[{section}]"
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            skipping = stripped == header
            if skipping:
                continue
        if not skipping:
            out.append(line)
    return out


def write_config(path: Path, lines: list[str]) -> bool:
    """Атомарно записать файл рядом с оригиналом."""
    text = "\n".join(lines).rstrip("\n") + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".kwinrules-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, path)
    except OSError as exc:
        log.warning("rules: не смог записать %s: %s", path, exc)
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        return False
    return True


# --- правило HUD --------------------------------------------------------
def ensure_rule(x: int, y: int, config: Path | None = None) -> bool:
    """Создать/обновить правило, ставящее HUD в точку (x, y)."""
    config = config or Path.home() / ".config" / CONFIG_NAME
    lines = read_config(config)

    lines = _set_in_section(lines, "General", "rules", str(RULE_ID))
    lines = _set_in_section(lines, "General", "count", "1")
    for key, value in RULE_KEYS:
        lines = _set_in_section(lines, str(RULE_ID), key, value)
    lines = _set_in_section(lines, str(RULE_ID), "position", f"{x},{y}")

    if not write_config(config, lines):
        return False
    reload_kwin()
    log.info("rules: HUD закреплён в %s,%s (правило %s)", x, y, RULE_ID)
    return True


def remove_rule(config: Path | None = None) -> bool:
    """Убрать наше правило из файла."""
    config = config or Path.home() / ".config" / CONFIG_NAME
    if not config.exists():
        return False
    lines = read_config(config)
    sections = parse_sections(lines)
    if str(RULE_ID) not in sections:
        return False
    lines = _remove_section(lines, str(RULE_ID))
    lines = _set_in_section(lines, "General", "rules", "")
    lines = _set_in_section(lines, "General", "count", str(max(0, len(sections) - 2)))
    if not write_config(config, lines):
        return False
    reload_kwin()
    log.info("rules: правило HUD удалено")
    return True


def rule_present(config: Path | None = None) -> bool:
    config = config or Path.home() / ".config" / CONFIG_NAME
    return str(RULE_ID) in parse_sections(read_config(config))


def reload_kwin() -> None:
    """Попросить KWin перечитать конфигурацию."""
    exe = shutil.which("qdbus6")
    if not exe:
        return
    try:
        subprocess.run(  # noqa: S603 - фиксированные аргументы
            [exe, "org.kde.KWin", "/KWin", "org.kde.KWin.reconfigure"],
            capture_output=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("rules: reconfigure не удался: %s", exc)
