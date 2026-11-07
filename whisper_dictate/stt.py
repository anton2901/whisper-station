"""HTTP-клиент локального Whisper-сервера (OpenAI-совместимый эндпоинт).

Зависимостей нет: multipart собираем руками, отправляем через urllib.
Ходим только на loopback-адреса — это проверяется до запроса.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass

from .config import Config, is_loopback_url

log = logging.getLogger(__name__)

ENDPOINT = "/v1/audio/transcriptions"


class SttError(RuntimeError):
    """Распознавание не удалось; текст исключения показывается пользователю."""


class ServerUnavailable(SttError):
    """Сервер не отвечает (не запущен / порт закрыт)."""


@dataclass(frozen=True)
class Transcript:
    text: str
    elapsed_ms: int


def build_multipart(
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
    boundary: str,
) -> bytes:
    """Собрать тело multipart/form-data.

    files: имя поля -> (имя файла, содержимое, content-type).
    """
    out = bytearray()
    for name, value in fields.items():
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += str(value).encode() + b"\r\n"
    for name, (filename, payload, content_type) in files.items():
        out += f"--{boundary}\r\n".encode()
        out += (
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
        ).encode()
        out += f"Content-Type: {content_type}\r\n\r\n".encode()
        out += payload + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out)


def _post(url: str, body: bytes, content_type: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": content_type, "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - loopback only
        return response.read()


def _parse(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text
        value = data.get("text") if isinstance(data, dict) else None
        return str(value).strip() if value is not None else ""
    return text


def transcribe(
    wav: bytes,
    cfg: Config,
    *,
    filename: str = "audio.wav",
    timeout: float = 90.0,
    retries: int = 1,
) -> Transcript:
    """Отправить WAV (16 кГц, моно, PCM16) и вернуть распознанный текст."""
    if not is_loopback_url(cfg.server_url):
        raise SttError(f"Адрес {cfg.server_url} не локальный — отправка запрещена")

    boundary = f"----whisper-dictate-{uuid.uuid4().hex}"
    body = build_multipart(
        fields={"language": cfg.language, "response_format": "json"},
        files={"file": (filename, wav, "audio/wav")},
        boundary=boundary,
    )
    url = cfg.server_url.rstrip("/") + ENDPOINT
    content_type = f"multipart/form-data; boundary={boundary}"

    started = time.monotonic()
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            payload = _post(url, body, content_type, timeout)
            return Transcript(
                text=_parse(payload),
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace").strip()[:300]
            except Exception:  # noqa: BLE001 - диагностика не должна падать
                pass
            last_error = SttError(f"Сервер ответил HTTP {exc.code}: {detail or exc.reason}")
            if exc.code < 500:
                raise last_error from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            last_error = ServerUnavailable(
                f"Сервер распознавания не отвечает ({reason}). "
                "Проверьте сервис и адрес в настройках."
            )
        except (TimeoutError, OSError) as exc:
            last_error = SttError(f"Ошибка связи с сервером: {exc}")

        if attempt < retries:
            log.warning("transcribe: попытка %d не удалась (%s), повтор", attempt + 1, last_error)
            time.sleep(0.4)

    assert last_error is not None
    raise last_error
