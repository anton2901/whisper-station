"""HTTP-слой сервера: /health, /v1/models и /v1/audio/transcriptions.

Эндпоинты повторяют то, что уже понимает клиент whisper-station, поэтому
встроенный сервер и любой OpenAI-совместимый взаимозаменяемы.
"""

from __future__ import annotations

import io
import json
import logging
import os
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .config import ServerConfig
from .engine import Engine, EngineError, EngineLoading
from .multipart import MultipartError, boundary_of, parse

log = logging.getLogger(__name__)

ENDPOINT = "/v1/audio/transcriptions"


def wav_error(data: bytes) -> str | None:
    """Проверить WAV до модели: понятная ошибка лучше стектрейса."""
    try:
        with wave.open(io.BytesIO(data)) as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
    except (wave.Error, EOFError) as exc:
        return f"не WAV: {exc}"
    if width != 2 or channels != 1 or rate != 16000:
        return (
            "ожидался WAV 16 кГц, моно, PCM16; "
            f"получено {rate} Гц, {channels} кан., {width * 8} бит"
        )
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "whisper-station"
    protocol_version = "HTTP/1.1"

    @property
    def cfg(self) -> ServerConfig:
        return self.server.cfg  # type: ignore[attr-defined]

    @property
    def engine(self) -> Engine:
        return self.server.engine  # type: ignore[attr-defined]

    # --- маршруты -------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - API http.server
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/health":
            self._json(200, self.engine.status())
        elif path in {"/v1/models", "/models"}:
            model = self.cfg.model
            self._json(200, {"object": "list", "data": [{"id": model, "object": "model"}]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - API http.server
        path = urlparse(self.path).path.rstrip("/")
        if path != ENDPOINT:
            self._json(404, {"error": "not found"})
            return
        self._transcribe()

    def _transcribe(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            self._json(400, {"error": "некорректный Content-Length"})
            return
        if length <= 0:
            self._json(411, {"error": "нужен Content-Length"})
            return
        if length > self.cfg.max_bytes + 8192:
            self._json(413, {"error": "аудио больше предела"})
            return

        body = self.rfile.read(length)
        try:
            boundary = boundary_of(self.headers.get("Content-Type", ""))
        except MultipartError as exc:
            self._json(415, {"error": str(exc)})
            return
        try:
            form = parse(body, boundary)
        except MultipartError as exc:
            self._json(400, {"error": str(exc)})
            return

        part = form.files.get("file")
        if part is None:
            self._json(400, {"error": "нет поля file с аудио"})
            return
        if len(part.data) > self.cfg.max_bytes:
            self._json(413, {"error": "аудио больше предела"})
            return
        problem = wav_error(part.data)
        if problem is not None:
            self._json(400, {"error": problem})
            return

        language = form.fields.get("language", "auto")
        prompt = form.fields.get("prompt", "")
        response_format = form.fields.get("response_format", "json").lower()
        try:
            result = self.engine.transcribe(part.data, language, prompt)
        except EngineLoading as exc:
            self._json(503, {"error": str(exc)}, {"Retry-After": "2"})
            return
        except EngineError as exc:
            self._json(503, {"error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - иначе клиент получит обрыв
            log.exception("transcribe упал")
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return

        if response_format == "text":
            self._text(200, result.text)
            return
        if response_format == "verbose_json":
            self._json(
                200,
                {
                    "text": result.text,
                    "language": result.language,
                    "duration": round(result.duration, 2),
                    "segments": [
                        {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text}
                        for s in result.segments
                    ],
                },
            )
            return
        self._json(200, {"text": result.text})

    # --- ответы ---------------------------------------------------------
    def _json(self, status: int, payload: Any, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _text(self, status: int, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - API
        log.debug("%s %s", self.address_string(), format % args)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, cfg: ServerConfig, engine: Engine) -> None:
        super().__init__((cfg.host, cfg.port), Handler)
        self.cfg = cfg
        self.engine = engine


def watch_lifetime(cfg: ServerConfig, engine: Engine, interval: float = 2.0) -> None:
    """Выйти, когда приложение-хозяин исчезло или сервер простаивает."""
    while True:
        time.sleep(interval)
        if cfg.parent_pid:
            try:
                os.kill(cfg.parent_pid, 0)
            except ProcessLookupError:
                log.info("приложение %d завершилось — останавливаюсь", cfg.parent_pid)
                os._exit(0)
            except PermissionError:
                pass
        if cfg.idle_seconds and time.monotonic() - engine.last_activity > cfg.idle_seconds:
            log.info("простой %d с — останавливаюсь", cfg.idle_seconds)
            os._exit(0)


def serve(cfg: ServerConfig, engine: Engine) -> int:
    """Поднять сервер и работать до остановки."""
    engine.start()
    threading.Thread(
        target=watch_lifetime, args=(cfg, engine), name="lifetime", daemon=True
    ).start()
    try:
        server = Server(cfg, engine)
    except OSError as exc:
        log.error("не могу занять %s:%d (%s)", cfg.host, cfg.port, exc)
        return 1
    log.info(
        "слушаю http://%s:%d, модель %s, потоков %d",
        cfg.host,
        cfg.port,
        cfg.model,
        cfg.threads_effective,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("остановлен по Ctrl+C")
    finally:
        server.server_close()
    return 0
