"""Разбор multipart/form-data стандартной библиотекой.

`cgi` удалён в Python 3.13, а тянуть python-multipart ради одного поля с
аудио не хочется: формат простой, а тело приходит от нашего же клиента.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class MultipartError(ValueError):
    """Тело запроса не похоже на multipart/form-data."""


@dataclass(frozen=True)
class FilePart:
    filename: str
    content_type: str
    data: bytes


@dataclass
class Form:
    fields: dict[str, str] = field(default_factory=dict)
    files: dict[str, FilePart] = field(default_factory=dict)


def boundary_of(content_type: str) -> str:
    """Достать boundary из заголовка Content-Type."""
    kind, _, rest = content_type.partition(";")
    if kind.strip().lower() != "multipart/form-data":
        raise MultipartError(f"ожидался multipart/form-data, получено {kind.strip()!r}")
    for item in rest.split(";"):
        key, _, value = item.partition("=")
        if key.strip().lower() == "boundary":
            boundary = value.strip().strip('"')
            if not boundary:
                break
            return boundary
    raise MultipartError("в Content-Type нет boundary")


def _params(value: str) -> dict[str, str]:
    """Разобрать `form-data; name="file"; filename="a.wav"` в словарь."""
    pieces = value.split(";")
    params: dict[str, str] = {}
    for item in pieces[1:]:
        key, _, raw = item.partition("=")
        if not _:
            continue
        params[key.strip().lower()] = raw.strip().strip('"')
    params["_type"] = pieces[0].strip().lower()
    return params


def _headers(block: bytes) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in block.decode("utf-8", "replace").split("\r\n"):
        key, sep, value = line.partition(":")
        if sep:
            headers[key.strip().lower()] = value.strip()
    return headers


def parse(body: bytes, boundary: str) -> Form:
    """Разложить тело на текстовые поля и файлы."""
    if not boundary:
        raise MultipartError("пустой boundary")
    marker = b"--" + boundary.encode("utf-8")
    form = Form()
    for chunk in body.split(marker)[1:]:
        if chunk.startswith(b"--"):
            break
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        head, separator, data = chunk.partition(b"\r\n\r\n")
        if not separator:
            continue
        if data.endswith(b"\r\n"):
            data = data[:-2]
        headers = _headers(head)
        disposition = headers.get("content-disposition", "")
        params = _params(disposition)
        name = params.get("name")
        if not name:
            continue
        filename = params.get("filename")
        if filename is None:
            form.fields[name] = data.decode("utf-8", "replace")
        else:
            form.files[name] = FilePart(
                filename=filename,
                content_type=headers.get("content-type", "application/octet-stream"),
                data=data,
            )
    return form
