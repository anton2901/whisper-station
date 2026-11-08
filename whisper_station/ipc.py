"""IPC между CLI и демоном: UNIX-сокет в XDG_RUNTIME_DIR."""

from __future__ import annotations

import json
import logging
import socket

from .paths import ipc_socket

log = logging.getLogger(__name__)


def send(command: str, timeout: float = 15.0) -> str | None:
    """Отправить команду демону. None — демон не отвечает."""
    socket_path = ipc_socket()
    if not socket_path.exists():
        return None
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(str(socket_path))
    except OSError:
        client.close()
        return None
    try:
        client.sendall((command + "\n").encode("utf-8"))
        chunks: list[bytes] = []
        while True:
            data = client.recv(65536)
            if not data:
                break
            chunks.append(data)
            if b"\n" in data:
                break
        return b"".join(chunks).decode("utf-8", "replace").strip()
    except OSError:
        return None
    finally:
        client.close()


def status(timeout: float = 2.0) -> dict | None:
    """Живой ли демон: возвращает его статус или None."""
    reply = send("status", timeout=timeout)
    if reply is None:
        return None
    try:
        data = json.loads(reply)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and data.get("daemon") else None


def socket_exists() -> bool:
    return ipc_socket().exists()


def listening(timeout: float = 0.3) -> bool:
    """Кто-то принимает соединения на нашем сокете."""
    socket_path = ipc_socket()
    if not socket_path.exists():
        return False
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(timeout)
    try:
        probe.connect(str(socket_path))
    except OSError:
        return False
    finally:
        probe.close()
    return True
