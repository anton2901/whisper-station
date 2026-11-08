"""Логирование: файл в ~/.local/state/whisper-station/app.log + консоль в TTY."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from . import APP_NAME
from .paths import ensure_dirs, log_file

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def configure(level: str = "INFO", *, console: bool | None = None, file: bool = True) -> None:
    ensure_dirs()
    handlers: list[logging.Handler] = []
    if file:
        handlers.append(
            RotatingFileHandler(log_file(), maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        )
    if console is None:
        console = sys.stderr.isatty()
    if console:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=FORMAT,
        handlers=handlers,
        force=True,
    )
    logging.getLogger(APP_NAME).info("=== %s: %s ===", APP_NAME, " ".join(sys.argv[1:]) or "daemon")
