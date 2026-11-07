"""Позиционирование HUD на KWin через правило окна.

Wayland не позволяет клиенту двигать свои окна: `move()` игнорируется
композитором, а KWin размещает новые окна сам (часто по центру экрана).
Единственный штатный способ задать позицию — правило KWin (`kwinrulesrc`).
Правило видно и удаляется в System Settings → Window Rules.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

APP_ID = "whisper-dictate"
HUD_TITLE = "Whisper Dictate HUD"
RULE_ID = 991001
CONFIG_NAME = "kwinrulesrc"

HUD_WIDTH = 300   # должно совпадать с hud.WIDTH
HUD_HEIGHT = 68   # должно совпадать с hud.HEIGHT
MARGIN_TOP = 72   # ниже верхней панели Plasma, чтобы не срабатывало автоскрытие


def hud_position(screen_x: int, screen_y: int, screen_width: int) -> tuple[int, int]:
    """Координаты верхнего центра экрана для HUD."""
    x = screen_x + max(0, (screen_width - HUD_WIDTH) // 2)
    return x, screen_y + MARGIN_TOP


def _tool(name: str) -> str | None:
    return shutil.which(name)


def available() -> bool:
    """Есть ли KDE-утилиты для правки kwinrulesrc."""
    return _tool("kwriteconfig6") is not None and _tool("kreadconfig6") is not None


def rule_ids(raw: str) -> list[int]:
    """Разобрать список id правил из [General] rules."""
    ids: list[int] = []
    for chunk in raw.replace(" ", "").split(","):
        if chunk.isdigit():
            ids.append(int(chunk))
    return ids


def _kread(config: Path, group: str, key: str) -> str:
    try:
        result = subprocess.run(  # noqa: S603 - фиксированные аргументы
            ["kreadconfig6", "--file", str(config), "--group", group, "--key", key],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("rules: kreadconfig6 упал: %s", exc)
        return ""
    return result.stdout.strip()


def _kwrite(config: Path, group: str, key: str, value: str) -> bool:
    try:
        result = subprocess.run(  # noqa: S603 - фиксированные аргументы
            [
                "kwriteconfig6",
                "--file",
                str(config),
                "--group",
                group,
                "--key",
                key,
                value,
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("rules: kwriteconfig6 упал: %s", exc)
        return False
    if result.returncode != 0:
        log.warning("rules: kwriteconfig6 вернул %s: %s", result.returncode, result.stderr.strip())
        return False
    return True


def reload_kwin() -> None:
    """Попросить KWin перечитать конфигурацию (правила читаются при map)."""
    exe = _tool("qdbus6")
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


def ensure_rule(x: int, y: int, config: Path | None = None) -> bool:
    """Создать/обновить правило, ставящее HUD в точку (x, y)."""
    if not available():
        log.warning("rules: нет kwriteconfig6/kreadconfig6 — позиция HUD останется на KWin")
        return False
    config = config or Path.home() / ".config" / CONFIG_NAME
    config.parent.mkdir(parents=True, exist_ok=True)
    config.touch(exist_ok=True)

    ids = rule_ids(_kread(config, "General", "rules"))
    if RULE_ID not in ids:
        ids.append(RULE_ID)
    if not _kwrite(config, "General", "count", str(len(ids))):
        return False
    if not _kwrite(config, "General", "rules", ",".join(str(rule) for rule in ids)):
        return False

    group = str(RULE_ID)
    values = {
        "Description": "Whisper Dictate HUD (ставит само приложение)",
        "wmclass": APP_ID,
        "wmclasscomplete": "false",
        "wmclassmatch": "1",
        "title": HUD_TITLE,
        "titlematch": "2",
        "position": f"{x},{y}",
        "positionrule": "2",  # Apply: KWin ставит HUD при появлении (Force на Wayland не работает)
    }
    for key, value in values.items():
        if not _kwrite(config, group, key, value):
            return False
    reload_kwin()
    log.info("rules: HUD закреплён в %s,%s (правило %s)", x, y, RULE_ID)
    return True


def remove_rule(config: Path | None = None) -> bool:
    """Убрать наше правило из списка (для отключённой опции)."""
    if not available():
        return False
    config = config or Path.home() / ".config" / CONFIG_NAME
    if not config.exists():
        return False
    ids = rule_ids(_kread(config, "General", "rules"))
    if RULE_ID not in ids:
        return False
    ids = [rule for rule in ids if rule != RULE_ID]
    _kwrite(config, "General", "count", str(len(ids)))
    _kwrite(config, "General", "rules", ",".join(str(rule) for rule in ids))
    reload_kwin()
    log.info("rules: правило HUD удалено")
    return True


def rule_present(config: Path | None = None) -> bool:
    if not available():
        return False
    config = config or Path.home() / ".config" / CONFIG_NAME
    if not config.exists():
        return False
    return RULE_ID in rule_ids(_kread(config, "General", "rules"))
