"""Тесты контроллера: режим удержания (push-to-talk) и его границы."""

from __future__ import annotations

import unittest
from unittest import mock

from PySide6.QtCore import QCoreApplication

from whisper_dictate.config import Config
from whisper_dictate.controller import MIN_HOLD_SECONDS, Controller
from whisper_dictate import controller as controller_module


class FakeServer:
    def ensure(self, **_kwargs):  # noqa: ANN003 - заглушка
        raise AssertionError("сервер не должен запускаться в этих тестах")


class FakeRecorder:
    def __init__(self, elapsed: float = 1.0, running: bool = True, captured: int = 100) -> None:
        self.elapsed = elapsed
        self.running = running
        self.bytes_captured = captured


class DeadRecorder(FakeRecorder):
    def __init__(self) -> None:
        super().__init__(running=False, captured=0)


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


class RetryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self) -> None:
        self.controller = Controller(Config(), FakeServer())
        self.controller.state = "recording"
        self.started: list[object] = []

        class FreshRecorder:
            def __init__(self, *_args, **_kwargs) -> None:
                self.running = True
                self.bytes_captured = 0
                self.elapsed = 0.0

            def start(self) -> None:
                self.started = True

        self._fresh = FreshRecorder
        self.patcher = mock.patch.object(controller_module, "Recorder", FreshRecorder)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_restarts_dead_recorder_once(self) -> None:
        self.controller._recorder = DeadRecorder()
        self.controller._check_recorder_started()
        self.assertEqual(self.controller._restarts, 1)
        self.assertIsInstance(self.controller._recorder, self._fresh)
        self.controller._recorder = DeadRecorder()
        self.controller._check_recorder_started()
        self.assertEqual(self.controller._restarts, 1, "второй перезапуск запрещён")

    def test_keeps_working_recorder(self) -> None:
        recorder = FakeRecorder(captured=10)
        self.controller._recorder = recorder
        self.controller._check_recorder_started()
        self.assertEqual(self.controller._restarts, 0)
        self.assertIs(self.controller._recorder, recorder)


class RepasteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_without_text_notifies(self) -> None:
        ctrl = Controller(Config(), FakeServer())
        messages: list[tuple] = []
        ctrl.notify_requested.connect(lambda *args: messages.append(args))
        ctrl.repaste()
        self.assertTrue(messages)
        self.assertIn("Нечего", messages[-1][0])

    def test_with_text_injects(self) -> None:
        ctrl = Controller(Config(), FakeServer())
        ctrl._last_text = "проверка"
        calls: list[str] = []
        result = type("R", (), {"ok": True, "detail": "", "method": "paste"})()
        with mock.patch.object(controller_module, "inject_text",
                               side_effect=lambda text, _cfg: (calls.append(text), result)[1]):
            ctrl.repaste()
        self.assertEqual(calls, ["проверка"])


if __name__ == "__main__":
    unittest.main()
