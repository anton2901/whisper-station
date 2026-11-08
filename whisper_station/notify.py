"""Уведомления рабочего стола через notify-send."""

from __future__ import annotations

import logging
import shutil
import subprocess

from . import APP_NAME

log = logging.getLogger(__name__)

DEFAULT_ICON = "audio-input-microphone"


def available() -> bool:
    return shutil.which("notify-send") is not None


def notify(
    title: str,
    body: str,
    *,
    urgency: str = "normal",
    timeout_ms: int = 4000,
    icon: str = DEFAULT_ICON,
) -> bool:
    """Показать уведомление. False — если notify-send недоступен/не сработал."""
    if not available():
        log.warning("notify: notify-send не найден, сообщение не показано: %s", title)
        return False
    command = [
        "notify-send",
        "-a",
        APP_NAME,
        "-i",
        icon,
        "-u",
        urgency,
        "-t",
        str(timeout_ms),
        title,
        body,
    ]
    try:
        result = subprocess.run(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("notify: %s", exc)
        return False
    if result.returncode != 0:
        log.warning(
            "notify: notify-send вернул %s: %s",
            result.returncode,
            result.stderr.decode("utf-8", "replace").strip(),
        )
        return False
    return True
