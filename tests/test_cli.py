"""Тесты CLI: разбор аргументов, IPC, разовые команды."""

from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from whisper_station import cli, ipc
from whisper_station.config import Config


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


class ModelCommandTest(unittest.TestCase):
    def test_parser_has_new_actions(self) -> None:
        parser = cli.build_parser()
        for action in ("list", "status", "download", "remove"):
            args = parser.parse_args(["model", action])
            self.assertEqual(args.action, action)
        args = parser.parse_args(["server", "install"])
        self.assertEqual(args.action, "install")

    def test_list_shows_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict("os.environ", {"WHISPER_STATION_MODELS": tmp}):
                with mock.patch("builtins.print") as printed:
                    code = cli.cmd_model(argparse.Namespace(action="list", name=None), Config())
        self.assertEqual(code, 0)
        text = "\n".join(str(call.args[0]) for call in printed.call_args_list if call.args)
        self.assertIn("large-v3-turbo", text)
        self.assertIn("small", text)

    def test_download_needs_yes(self) -> None:
        with mock.patch("builtins.print"):
            code = cli.cmd_model(
                argparse.Namespace(action="download", name="small", repo=None, yes=False),
                Config(),
            )
        self.assertEqual(code, 1)

    def test_unknown_model_is_reported(self) -> None:
        with mock.patch("builtins.print"):
            code = cli.cmd_model(
                argparse.Namespace(action="download", name="huge-v9", repo=None, yes=True),
                Config(),
            )
        self.assertEqual(code, 1)

    def test_download_calls_models(self) -> None:
        from whisper_station import models

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict("os.environ", {"WHISPER_STATION_MODELS": tmp}):
                with mock.patch.object(models, "download", return_value=0) as download:
                    with mock.patch.object(models, "check_space", return_value=None):
                        with mock.patch("builtins.print"):
                            code = cli.cmd_model(
                                argparse.Namespace(
                                    action="download", name="small", repo=None, yes=True
                                ),
                                Config(model_name="small"),
                            )
        self.assertEqual(code, 0)
        download.assert_called_once_with("small")


class ServerCommandTest(unittest.TestCase):
    def test_status_reports_missing_env(self) -> None:
        from whisper_station import server_env

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict("os.environ", {"XDG_DATA_HOME": tmp}):
                with mock.patch.object(server_env, "is_installed", return_value=False):
                    with mock.patch("builtins.print") as printed:
                        code = cli.cmd_server(argparse.Namespace(action="status"), Config())
        self.assertEqual(code, 0)
        payload = printed.call_args.args[0]
        self.assertIn('"installed": false', payload)

    def test_install_reports_existing(self) -> None:
        from whisper_station import server_env

        with mock.patch.object(server_env, "is_installed", return_value=True):
            with mock.patch.object(server_env, "faster_whisper_version", return_value="1.1.0"):
                with mock.patch("builtins.print") as printed:
                    code = cli.cmd_server(
                        argparse.Namespace(action="install", python=None, force=False), Config()
                    )
        self.assertEqual(code, 0)
        text = "\n".join(str(call.args[0]) for call in printed.call_args_list if call.args)
        self.assertIn("1.1.0", text)

    def test_uninstall_needs_yes(self) -> None:
        with mock.patch("builtins.print") as printed:
            code = cli.cmd_server(argparse.Namespace(action="uninstall", yes=False), Config())
        self.assertEqual(code, 1)
        self.assertIn("--yes", str(printed.call_args.args[0]))
