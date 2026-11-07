"""Тесты сервиса распознавания: /health и запуск по требованию."""

from __future__ import annotations

import http.server
import json
import threading
import unittest

from whisper_dictate.config import Config
from whisper_dictate.service import ServerManager, ServerStatus, health
from whisper_dictate.stt import ServerUnavailable


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    payload: dict[str, object] = {
        "status": "ok",
        "model": "large-v3-turbo",
        "device": "cuda",
        "pid": 123,
    }
    status = 200

    def do_GET(self) -> None:  # noqa: N802 - API http.server
        body = json.dumps(type(self).payload).encode()
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


class HealthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        _HealthHandler.payload = {"status": "ok", "model": "m", "device": "cuda", "pid": 1}
        _HealthHandler.status = 200

    def test_ok(self) -> None:
        status = health(self.url)
        self.assertTrue(status.ok)
        self.assertEqual(status.device, "cuda")
        self.assertEqual(status.pid, 1)

    def test_not_ok_status(self) -> None:
        _HealthHandler.payload = {"status": "loading", "error": "загружаюсь"}
        status = health(self.url)
        self.assertFalse(status.ok)
        self.assertIn("loading", status.error or "")

    def test_invalid_json(self) -> None:
        _HealthHandler.payload = {}
        _HealthHandler.status = 200
        status = health(self.url)
        self.assertFalse(status.ok)

    def test_dead_port(self) -> None:
        status = health("http://127.0.0.1:9", timeout=0.5)
        self.assertFalse(status.ok)
        self.assertTrue(status.error)


class ServerManagerTest(unittest.TestCase):
    def test_command_from_config(self) -> None:
        cfg = Config(server_command="/usr/local/bin/run.sh")
        self.assertEqual(ServerManager(cfg).command(), "/usr/local/bin/run.sh")

    def test_health_ok_does_not_spawn(self) -> None:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            cfg = Config(server_url=f"http://127.0.0.1:{server.server_port}")
            manager = ServerManager(cfg)
            status = manager.ensure(timeout=2.0)
            self.assertTrue(status.ok)
            self.assertIsNone(manager.owned_pid)
        finally:
            server.shutdown()
            server.server_close()

    def test_autostart_disabled_raises(self) -> None:
        cfg = Config(server_url="http://127.0.0.1:9", server_autostart=False)
        with self.assertRaises(ServerUnavailable):
            ServerManager(cfg).ensure(timeout=1.0)

    def test_missing_command_raises(self) -> None:
        cfg = Config(server_url="http://127.0.0.1:9", server_command="/nonexistent/run.sh")
        with self.assertRaises(ServerUnavailable):
            ServerManager(cfg).ensure(timeout=2.0)

    def test_status_describe(self) -> None:
        self.assertIn("cuda", ServerStatus(ok=True, device="cuda", model="m").describe())
        self.assertIn("недоступен", ServerStatus(ok=False, error="нет").describe())


if __name__ == "__main__":
    unittest.main()
