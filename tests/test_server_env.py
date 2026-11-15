"""Тесты окружения сервера: установка venv, маркер, отказ на старом Python."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from whisper_station import server_env


class EnvTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict("os.environ", {"XDG_DATA_HOME": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_not_installed_by_default(self) -> None:
        self.assertFalse(server_env.is_installed())
        self.assertIsNone(server_env.faster_whisper_version())
        self.assertEqual(server_env.venv_size(), 0)

    def test_marker_makes_it_installed(self) -> None:
        server_env.python().parent.mkdir(parents=True)
        server_env.python().write_text("#!/bin/sh\n", encoding="utf-8")
        server_env.marker_path().write_text(
            json.dumps({"faster_whisper": "1.2.0"}), encoding="utf-8"
        )
        self.assertTrue(server_env.is_installed())
        self.assertEqual(server_env.faster_whisper_version(), "1.2.0")

    def test_broken_marker_is_tolerated(self) -> None:
        server_env.venv_dir().mkdir(parents=True)
        server_env.marker_path().write_text("{", encoding="utf-8")
        self.assertEqual(server_env.installed_info(), {})

    def test_old_python_rejected(self) -> None:
        with mock.patch.object(
            server_env.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="3.8\n", stderr=""),
        ):
            with self.assertRaises(server_env.InstallError):
                server_env._check_source("/usr/bin/python3.8")

    def test_install_runs_venv_and_pip(self) -> None:
        commands: list[list[str]] = []

        def fake_run(argv, **kwargs):  # noqa: ANN001, ANN003
            commands.append(list(argv))
            if "-m" in argv and "venv" in argv:
                (Path(argv[-1]) / "bin").mkdir(parents=True, exist_ok=True)
                (Path(argv[-1]) / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if "version_info" in argv[-1]:
                return SimpleNamespace(returncode=0, stdout="3.12\n", stderr="")
            if "faster_whisper.__version__" in argv[-1]:
                return SimpleNamespace(returncode=0, stdout="1.2.0\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with mock.patch.object(server_env.subprocess, "run", fake_run):
            version = server_env.install("/usr/bin/python3")

        self.assertEqual(version, "1.2.0")
        flat = [" ".join(cmd) for cmd in commands]
        self.assertTrue(any("venv" in cmd for cmd in flat))
        self.assertTrue(any("pip install" in cmd and "faster-whisper" in cmd for cmd in flat))
        marker = json.loads(server_env.marker_path().read_text(encoding="utf-8"))
        self.assertEqual(marker["faster_whisper"], "1.2.0")
        self.assertTrue(server_env.is_installed())

    def test_install_with_cuda_adds_nvidia_packages(self) -> None:
        commands: list[list[str]] = []

        def fake_run(argv, **kwargs):  # noqa: ANN001, ANN003
            commands.append(list(argv))
            if "venv" in argv:
                (Path(argv[-1]) / "bin").mkdir(parents=True, exist_ok=True)
                (Path(argv[-1]) / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if "version_info" in argv[-1]:
                return SimpleNamespace(returncode=0, stdout="3.12\n", stderr="")
            if "faster_whisper.__version__" in argv[-1]:
                return SimpleNamespace(returncode=0, stdout="1.2.0\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with mock.patch.object(server_env.subprocess, "run", fake_run):
            server_env.install("/usr/bin/python3", cuda=True)

        pip = " ".join(next(cmd for cmd in commands if "pip" in cmd))
        self.assertIn("nvidia-cublas-cu12", pip)
        self.assertIn("nvidia-cudnn-cu12", pip)
        marker = json.loads(server_env.marker_path().read_text(encoding="utf-8"))
        self.assertTrue(marker["cuda"])
        self.assertTrue(server_env.cuda_enabled())

    def test_install_cuda_requires_env(self) -> None:
        with self.assertRaises(server_env.InstallError):
            server_env.install_cuda()

    def test_install_cuda_updates_marker(self) -> None:
        server_env.python().parent.mkdir(parents=True)
        server_env.python().write_text("#!/bin/sh\n", encoding="utf-8")
        server_env.marker_path().write_text(
            json.dumps({"faster_whisper": "1.2.0", "requirements": ["faster-whisper>=1.0,<2"]}),
            encoding="utf-8",
        )
        with mock.patch.object(
            server_env.subprocess, "run",
            return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
        ):
            server_env.install_cuda()
        marker = json.loads(server_env.marker_path().read_text(encoding="utf-8"))
        self.assertTrue(marker["cuda"])
        self.assertTrue(any("nvidia" in item for item in marker["requirements"]))

    def test_install_failure_reports_tail(self) -> None:
        def fake_run(argv, **kwargs):  # noqa: ANN001, ANN003
            if "version_info" in argv[-1]:
                return SimpleNamespace(returncode=0, stdout="3.12\n", stderr="")
            if "venv" in argv:
                (Path(argv[-1]) / "bin").mkdir(parents=True, exist_ok=True)
                (Path(argv[-1]) / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")
                return SimpleNamespace(returncode=1, stdout="", stderr="boom line")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with mock.patch.object(server_env.subprocess, "run", fake_run):
            with self.assertRaises(server_env.InstallError) as ctx:
                server_env.install("/usr/bin/python3")
        self.assertIn("boom line", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
