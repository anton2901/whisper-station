"""Звуковые сигналы старта и остановки записи.

Основной путь — `canberra-gtk-play` (libcanberra, звуки темы KDE). Если его нет,
падаем на системный звонок Qt.
"""

from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger(__name__)

# События freedesktop: message — мягкий сигнал, complete — завершение.
EVENTS = {"start": "message", "stop": "complete"}


def available() -> bool:
    return shutil.which("canberra-gtk-play") is not None


def command(kind: str) -> list[str] | None:
    event = EVENTS.get(kind)
    if event is None or not available():
        return None
    return ["canberra-gtk-play", "-i", event]


def play(kind: str) -> None:
    """Проиграть сигнал; ошибки не пробрасываются — звук не критичен."""
    argv = command(kind)
    if argv is not None:
        try:
            subprocess.Popen(  # noqa: S603 - фиксированные аргументы
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            return
        except OSError as exc:
            log.debug("sounds: canberra-gtk-play не запустился: %s", exc)
    try:
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance()
        # Без GUI-приложения статический beep() роняет процесс — проверяем явно.
        if isinstance(application, QApplication):
            application.beep()
    except Exception:  # noqa: BLE001 - звонок не должен ломать запись
        log.debug("sounds: системный звонок недоступен", exc_info=True)
