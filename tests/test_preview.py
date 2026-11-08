"""Тесты живого предпросмотра: только HUD, без вставки и буфера."""

from __future__ import annotations

import unittest
from unittest import mock

from PySide6.QtCore import QCoreApplication

from whisper_station import preview as preview_module
from whisper_station.config import Config
from whisper_station.controller import Controller
from whisper_station.preview import Preview


class FakeServer:
    def ensure(self, **_kwargs):  # noqa: ANN003
        raise AssertionError("сервер не должен запускаться")


class FakeRecorder:
    def __init__(self, captured: int = 4000) -> None:
        self.bytes_captured = captured

    def snapshot(self, _seconds: float) -> bytes:
        return b"\x00\x00" * 100


class PreviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_work_emits_text(self) -> None:
        preview = Preview(Config())
        got: list[str] = []
        preview.text_ready.connect(got.append)
        result = type("T", (), {"text": "привет", "elapsed_ms": 10})()
        with mock.patch.object(preview_module, "transcribe", return_value=result):
            preview._work(b"\x00\x00" * 100)
        self.assertEqual(got, ["привет"])

    def test_work_swallows_errors(self) -> None:
        preview = Preview(Config())
        with mock.patch.object(preview_module, "transcribe", side_effect=preview_module.SttError("нет")):
            preview._work(b"")  # не должно падать
        preview.end()

    def test_tick_without_recorder_is_silent(self) -> None:
        preview = Preview(Config())
        preview._tick()
        self.assertFalse(preview.active)

    def test_begin_and_end(self) -> None:
        preview = Preview(Config())
        preview.begin(FakeRecorder())
        self.assertTrue(preview.active)
        preview.end()
        self.assertFalse(preview.active)

    def test_controller_cancel_stops_preview(self) -> None:
        controller = Controller(Config(), FakeServer())
        calls: list[str] = []
        fake = type("P", (), {"end": lambda self: calls.append("end"),
                              "begin": lambda self, _r: calls.append("begin"),
                              "cfg": None})()
        controller._preview = fake
        controller.cancel()
        self.assertEqual(calls, ["end"])


if __name__ == "__main__":
    unittest.main()
