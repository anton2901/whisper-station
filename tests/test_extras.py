"""Тесты звуковых сигналов, systemd-юнита и работы с моделью."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from whisper_station import models, sounds, systemd_unit


class SoundsTest(unittest.TestCase):
    def test_uses_generated_files(self) -> None:
        command = sounds.command("start")
        self.assertIsNotNone(command)
        self.assertIn(command[0], sounds.PLAYERS)
        self.assertTrue(command[1].endswith("start.wav"))
        self.assertTrue(sounds.command("stop")[1].endswith("stop.wav"))
        self.assertIsNone(sounds.command("unknown"))

    def test_files_exist_in_repo(self) -> None:
        for kind in ("start", "stop"):
            path = sounds.sound_file(kind)
            self.assertIsNotNone(path, kind)
            self.assertGreater(path.stat().st_size, 1000)

    def test_falls_back_to_canberra_event(self) -> None:
        with mock.patch.object(sounds, "sound_file", return_value=None):
            with mock.patch.object(sounds.shutil, "which", return_value="/usr/bin/canberra-gtk-play"):
                command = sounds.command("stop")
        self.assertEqual(command[:2], ["canberra-gtk-play", "-i"])
        self.assertEqual(command[2], "complete")

    def test_play_does_not_raise(self) -> None:
        with mock.patch.object(sounds, "command", return_value=None):
            sounds.play("start")  # звонок Qt или тишина, но без исключения


class SystemdTest(unittest.TestCase):
    def test_unit_text(self) -> None:
        text = systemd_unit.unit_text("/usr/bin/whisper-station daemon", "PYTHONPATH=/opt/app")
        self.assertIn("ExecStart=/usr/bin/whisper-station daemon", text)
        self.assertIn("Environment=PYTHONPATH=/opt/app", text)
        self.assertIn("Restart=on-failure", text)
        self.assertIn("WantedBy=graphical-session.target", text)

    def test_resolve_exec_has_daemon(self) -> None:
        command, _environment = systemd_unit.resolve_exec()
        self.assertIn("daemon", command)

    def test_install_writes_user_unit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp}):
                path = systemd_unit.install()
                self.assertTrue(path.is_file())
                self.assertIn("[Service]", path.read_text(encoding="utf-8"))
                self.assertTrue(str(path).startswith(tmp))


class ModelsTest(unittest.TestCase):
    def test_status_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict("os.environ", {"WHISPER_STATION_MODELS": tmp}):
                info = models.status()
        self.assertTrue(info["exists"])
        self.assertEqual(info["installed"], [])
        self.assertEqual(info["files"], 0)

    def test_status_counts_installed_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "small"
            root.mkdir()
            (root / "model.bin").write_bytes(b"x" * 1024)
            with mock.patch.dict("os.environ", {"WHISPER_STATION_MODELS": tmp}):
                info = models.status()
                resolved = models.resolve("small")
        self.assertEqual(info["installed"], ["small"])
        self.assertEqual(info["sizes"]["small"], 1024)
        self.assertEqual(info["size_bytes"], 1024)
        self.assertEqual(resolved, str(root))

    def test_resolve_missing_model_uses_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict("os.environ", {"WHISPER_STATION_MODELS": tmp}):
                self.assertEqual(models.resolve("small"), "small")
                self.assertFalse(models.is_installed("small"))

    def test_unknown_model_raises(self) -> None:
        with self.assertRaises(models.ModelError):
            models.repo_of("huge-v9")

    def test_legacy_env_is_honoured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict("os.environ", {"WHISPER_DICTATE_MODELS": tmp}):
                self.assertEqual(models.models_dir(), Path(tmp))

    def test_download_script(self) -> None:
        script = models.download_script("owner/repo", Path("/tmp/models"))
        self.assertIn("snapshot_download", script)
        self.assertIn("owner/repo", script)
        self.assertIn("/tmp/models", script)

    def test_download_without_hub_raises(self) -> None:
        with mock.patch.object(models, "python_with_hub", return_value=None):
            with self.assertRaises(models.ModelError):
                models.download()

    def test_download_reports_missing_model_bin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict("os.environ", {"WHISPER_STATION_MODELS": tmp}):
                with mock.patch.object(models, "python_with_hub", return_value=Path("/bin/true")):
                    with mock.patch.object(models, "_run_download", return_value=0):
                        with self.assertRaises(models.ModelError):
                            models.download("small")

    def test_download_can_be_cancelled(self) -> None:
        import threading

        cancel = threading.Event()
        cancel.set()

        class FakeProc:
            def poll(self) -> None:
                return None

            def terminate(self) -> None:
                pass

            def wait(self, timeout: float | None = None) -> int:
                return 0

        with mock.patch.object(models.subprocess, "Popen", return_value=FakeProc()):
            with self.assertRaises(models.ModelError) as ctx:
                models._run_download(["/bin/true"], cancel)
        self.assertIn("отменена", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
