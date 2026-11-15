"""Запуск встроенного сервера: `python -m whisper_station.server`.

Обычно его поднимает приложение; вручную — для отладки:
`WHISPER_MODEL=small python -m whisper_station.server`.
"""

from __future__ import annotations

import logging
import os
import sys

from .config import ConfigError, ServerConfig
from .engine import Engine
from .web import serve


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("WHISPER_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        cfg = ServerConfig.from_env()
    except ConfigError as exc:
        logging.getLogger(__name__).error("окружение: %s", exc)
        return 2
    return serve(cfg, Engine(cfg))


if __name__ == "__main__":
    sys.exit(main())
