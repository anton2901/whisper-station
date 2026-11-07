"""Тесты CLI: разбор аргументов, IPC, разовые команды."""

from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from whisper_dictate import cli, ipc
from whisper_dictate.config import Config


class ParserTest(unittest.TestCase):
    def test_daemon_commands_parse(self) -> None:
        parser = cli.build_parser()
        for name in cli.DAEMON_COMMANDS:
            with self.subTest(command=name):
                args = parser.parse_args([name])
                self.assertTrue(callable(args.func))

    def test_transcribe_arguments(self) -> None:
        args = cli.build_parser().parse_args(
            ["transcribe", "sample.wav", "--language", "en"]
        )
        self.assertEqual(args.file, "sample.wav")
        self.assertEqual(args.language, "en")

    def test_autostart_choices(self) -> None:
        for action in ("on", "off", "status"):
            args = cli.build_parser().parse_args(["autostart", action])
            self.assertEqual(args.action, action)

    def test_service_choices(self) -> None:
        args = cli.build_parser().parse_args(["service", "status"])
        self.assertEqual(args.action, "status")


class SendCommandTest(unittest.TestCase):
    def test_returns_none_without_socket(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "нет.sock"
            with mock.patch.object(ipc, "ipc_socket", return_value=missing):
                self.assertIsNone(cli.send_command("status"))


class TranscribeCommandTest(unittest.TestCase):
    def test_missing_file(self) -> None:
        args = argparse.Namespace(file="/не/существует.wav", language=None)
        self.assertEqual(cli.cmd_transcribe(args, Config()), 1)

    def test_not_a_wav(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "file.wav"
            path.write_text("это не wav", encoding="utf-8")
            args = argparse.Namespace(file=str(path), language=None)
            self.assertEqual(cli.cmd_transcribe(args, Config()), 1)


class MainTest(unittest.TestCase):
    def test_version_exits_zero(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            cli.main(["--version"])
        self.assertEqual(ctx.exception.code, 0)

    def test_no_command_prints_help(self) -> None:
        self.assertEqual(cli.main([]), 0)


class StatusTest(unittest.TestCase):
    def test_status_without_daemon(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "нет.sock"
            with mock.patch.object(ipc, "ipc_socket", return_value=missing):
                self.assertIn(cli.cmd_status(Config(server_url="http://127.0.0.1:9")), (0, 1))


if __name__ == "__main__":
    unittest.main()
