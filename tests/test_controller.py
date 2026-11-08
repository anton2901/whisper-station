"""Тесты контроллера: режим удержания (push-to-talk) и его границы."""

from __future__ import annotations

import unittest

from PySide6.QtCore import QCoreApplication

from whisper_dictate.config import Config
from whisper_dictate.controller import MIN_HOLD_SECONDS, Controller


class FakeServer:
    def ensure(self, **_kwargs):  # noqa: ANN003 - заглушка
        raise AssertionError("сервер не должен запускаться в этих тестах")


class FakeRecorder:
    def __init__(self, elapsed: float) -> None:
        self.elapsed = elapsed


class PressModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self) -> None:
        self.controller = Controller(Config(hotkey_mode="press"), FakeServer())
        self.calls: list[str] = []
        self.controller.start = lambda: self.calls.append("start")
        self.controller.stop = lambda: self.calls.append("stop")
        self.controller.cancel = lambda: self.calls.append("cancel")

    def test_press_starts_when_idle(self) -> None:
        self.controller.press_start()
        self.assertEqual(self.calls, ["start"])

    def test_press_is_ignored_while_recording(self) -> None:
        self.controller.state = "recording"
        self.controller.press_start()
        self.assertEqual(self.calls, [])

    def test_short_hold_cancels(self) -> None:
        self.controller.state = "recording"
        self.controller._recorder = FakeRecorder(MIN_HOLD_SECONDS / 3)
        self.controller.press_stop()
        self.assertEqual(self.calls, ["cancel"])

    def test_long_hold_stops(self) -> None:
        self.controller.state = "recording"
        self.controller._recorder = FakeRecorder(MIN_HOLD_SECONDS + 1)
        self.controller.press_stop()
        self.assertEqual(self.calls, ["stop"])

    def test_release_while_starting_cancels(self) -> None:
        self.controller.state = "starting"
        self.controller.press_stop()
        self.assertEqual(self.calls, ["cancel"])

    def test_release_when_idle_does_nothing(self) -> None:
        self.controller.press_stop()
        self.assertEqual(self.calls, [])

    def test_release_without_recorder_stops(self) -> None:
        self.controller.state = "recording"
        self.controller._recorder = None
        self.controller.press_stop()
        self.assertEqual(self.calls, ["stop"])


if __name__ == "__main__":
    unittest.main()
