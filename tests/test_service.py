"""Тесты сервиса распознавания: /health и запуск по требованию."""

from __future__ import annotations

import http.server
import json
import os
import threading
import unittest
from unittest import mock

from whisper_station import service
from whisper_station.config import Config
from whisper_station.service import ServerManager, ServerStatus, health
from whisper_station.stt import ServerUnavailable


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

    def test_spawn_sets_own_parent_pid(self) -> None:
        cfg = Config(server_command="/bin/true")
        manager = ServerManager(cfg)
        captured: dict[str, object] = {}

        class FakeProc:
            pid = 1
            returncode = None

            def poll(self) -> None:
                return None

            def terminate(self) -> None:
                self.returncode = 0

            def wait(self, timeout: float | None = None) -> int:
                return 0

        def fake_popen(argv, **kwargs):  # noqa: ANN001, ANN003
            captured["env"] = kwargs.get("env")
            return FakeProc()

        with mock.patch.object(service.subprocess, "Popen", fake_popen):
            manager.spawn()
            manager.stop_owned()
        env = captured.get("env") or {}
        self.assertEqual(env.get("WHISPER_PARENT_PID"), str(os.getpid()))

    def test_loading_server_is_not_spawned_twice(self) -> None:
        cfg = Config(server_url="http://127.0.0.1:9")
        manager = ServerManager(cfg)
        loading = ServerStatus(False, error="loading: модель загружается", model="m")
        with mock.patch.object(service, "health", return_value=loading):
            with mock.patch.object(manager, "spawn") as spawn:
                with self.assertRaises(ServerUnavailable):
                    manager.ensure(timeout=0.3)
        spawn.assert_not_called()

    def test_status_describe(self) -> None:
        self.assertIn("cuda", ServerStatus(ok=True, device="cuda", model="m").describe())
        self.assertIn("недоступен", ServerStatus(ok=False, error="нет").describe())


class SpawnPlanTest(unittest.TestCase):
    def test_builtin_plan_passes_model_settings(self) -> None:
        cfg = Config(
            model_name="small",
            model_device="cpu",
            model_compute="int8",
            model_threads=4,
            server_url="http://127.0.0.1:9999",
        )
        manager = ServerManager(cfg)
        with mock.patch.object(service.server_env, "is_installed", return_value=True):
            plan = manager.plan()
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.argv[1:], ["-m", "whisper_station.server"])
        self.assertEqual(plan.env["WHISPER_MODEL"], "small")
        self.assertEqual(plan.env["WHISPER_DEVICE"], "cpu")
        self.assertEqual(plan.env["WHISPER_COMPUTE"], "int8")
        self.assertEqual(plan.env["WHISPER_THREADS"], "4")
        self.assertEqual(plan.env["WHISPER_PORT"], "9999")
        self.assertEqual(plan.env["WHISPER_PARENT_PID"], str(os.getpid()))
        self.assertIn(str(service.app_root()), plan.env["PYTHONPATH"])

    def test_custom_command_wins_over_builtin(self) -> None:
        cfg = Config(server_command="/bin/true")
        with mock.patch.object(service.server_env, "is_installed", return_value=True):
            plan = ServerManager(cfg).plan()
        assert plan is not None
        self.assertEqual(plan.argv, ["/bin/true"])
        self.assertNotIn("WHISPER_MODEL", plan.env)

    def test_plan_adds_cuda_libraries(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            lib = (
                Path(tmp) / "server-venv" / "lib" / "python3.12" / "site-packages"
                / "nvidia" / "cublas" / "lib"
            )
            lib.mkdir(parents=True)
            with mock.patch.object(service.server_env.paths, "data_dir", return_value=Path(tmp)):
                with mock.patch.object(service.server_env, "is_installed", return_value=True):
                    with mock.patch.object(service.server_env, "cuda_enabled", return_value=True):
                        plan = ServerManager(Config()).plan()
        assert plan is not None
        self.assertIn(str(lib), plan.env["LD_LIBRARY_PATH"])

    def test_plan_none_without_server(self) -> None:
        with mock.patch.object(service.server_env, "is_installed", return_value=False):
            with mock.patch.object(service, "find_server_command", return_value=None):
                self.assertIsNone(ServerManager(Config()).plan())

    def test_legacy_run_sh_used_as_fallback(self) -> None:
        with mock.patch.object(service.server_env, "is_installed", return_value=False):
            with mock.patch.object(service, "find_server_command", return_value="/opt/run.sh"):
                plan = ServerManager(Config()).plan()
        assert plan is not None
        self.assertEqual(plan.argv, ["/opt/run.sh"])

    def test_spawn_after_plan_uses_env(self) -> None:
        cfg = Config(model_name="base", server_url="http://127.0.0.1:9998")
        manager = ServerManager(cfg)
        captured: dict[str, object] = {}

        class FakeProc:
            pid = 1
            returncode = None

            def poll(self) -> None:
                return None

            def terminate(self) -> None:
                self.returncode = 0

            def wait(self, timeout: float | None = None) -> int:
                return 0

        def fake_popen(argv, **kwargs):  # noqa: ANN001, ANN003
            captured["argv"] = argv
            captured["env"] = kwargs.get("env")
            return FakeProc()

        with mock.patch.object(service.server_env, "is_installed", return_value=True):
            with mock.patch.object(service.subprocess, "Popen", fake_popen):
                manager.spawn()
                manager.stop_owned()
        env = captured.get("env") or {}
        self.assertEqual(env.get("WHISPER_MODEL"), "base")
        self.assertEqual(captured["argv"][1:], ["-m", "whisper_station.server"])


if __name__ == "__main__":
    unittest.main()
