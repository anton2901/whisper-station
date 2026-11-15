"""Тесты хоткея: кодирование комбинаций, action id, разбор ответа демона."""

from __future__ import annotations

import unittest
from unittest import mock

from whisper_station.hotkey import (
    ActionId,
    GlobalHotkey,
    HotkeyError,
    _first_key,
    int_to_shortcut,
    kglobalaccel_available,
    shortcut_to_int,
)


class ShortcutEncodingTest(unittest.TestCase):
    def test_meta_alt_d(self) -> None:
        self.assertEqual(shortcut_to_int("Meta+Alt+D"), 402653252)

    def test_roundtrip(self) -> None:
        for sequence in ("Meta+Alt+D", "Alt+M", "Ctrl+Shift+S", "Meta+V"):
            with self.subTest(sequence=sequence):
                self.assertEqual(int_to_shortcut(shortcut_to_int(sequence)), sequence)

    def test_empty_raises(self) -> None:
        with self.assertRaises(HotkeyError):
            shortcut_to_int("")

    def test_garbage_raises(self) -> None:
        with self.assertRaises(HotkeyError):
            shortcut_to_int("Не комбинация")


class ActionIdTest(unittest.TestCase):
    def test_order_matches_kglobalaccel(self) -> None:
        action = ActionId("whisper-station", "toggle", "Whisper Station", "Диктовка")
        self.assertEqual(
            action.as_list(),
            ["whisper-station", "toggle", "Whisper Station", "Диктовка"],
        )


class FirstKeyTest(unittest.TestCase):
    def test_extracts_non_zero(self) -> None:
        self.assertEqual(_first_key([((402653252, 0, 0, 0),)]), 402653252)

    def test_empty_and_zero(self) -> None:
        self.assertIsNone(_first_key([]))
        self.assertIsNone(_first_key([((0, 0, 0, 0),)]))

    def test_garbage(self) -> None:
        self.assertIsNone(_first_key("ерунда"))


class MatchTest(unittest.TestCase):
    def setUp(self) -> None:
        from whisper_station.hotkey import GlobalHotkey

        self.hk = GlobalHotkey(lambda: None)

    def test_accepts_own_component(self) -> None:
        self.assertTrue(self.hk._match(("whisper-station", "toggle", 1)))

    def test_accepts_legacy_component(self) -> None:
        self.assertTrue(self.hk._match(("whisper-dictate", "toggle", 1)))

    def test_rejects_foreign_component(self) -> None:
        self.assertFalse(self.hk._match(("kwin", "toggle", 1)))

    def test_rejects_other_action(self) -> None:
        self.assertFalse(self.hk._match(("whisper-station", "other", 1)))


class GlobalHotkeyTest(unittest.TestCase):
    def test_bad_sequence_raises_and_stops(self) -> None:
        hotkey = GlobalHotkey(lambda: None)
        with self.assertRaises(HotkeyError):
            hotkey.start("", timeout=5.0)
        hotkey.stop()
        self.assertFalse(hotkey.active)

    def test_bad_sequence_checked_before_dbus(self) -> None:
        hotkey = GlobalHotkey(lambda: None)
        try:
            import dbus
        except ImportError:
            self.skipTest("нет dbus-python")
        with mock.patch.object(dbus, "SessionBus", side_effect=AssertionError("bus touched")):
            with self.assertRaises(HotkeyError):
                hotkey.start("")
        hotkey.stop()

    def test_missing_session_bus_is_hotkey_error(self) -> None:
        hotkey = GlobalHotkey(lambda: None)
        try:
            import dbus
        except ImportError:
            self.skipTest("нет dbus-python")
        with mock.patch.object(dbus, "SessionBus", side_effect=RuntimeError("no session bus")):
            with self.assertRaises(HotkeyError) as ctx:
                hotkey.start("Meta+Alt+D")
        self.assertIn("D-Bus", str(ctx.exception))

    def test_availability_is_bool(self) -> None:
        self.assertIsInstance(kglobalaccel_available(), bool)


if __name__ == "__main__":
    unittest.main()
