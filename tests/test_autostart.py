"""Тесты автозапуска: содержимое .desktop, включение и выключение."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from whisper_dictate import autostart


class AutostartTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "autostart" / "whisper-dictate.desktop"
        patcher = mock.patch.object(autostart, "autostart_file", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_desktop_entry(self) -> None:
        entry = autostart.desktop_entry("/usr/bin/whisper-dictate")
        self.assertIn("Exec=/usr/bin/whisper-dictate daemon", entry)
        self.assertIn("Type=Application", entry)
        self.assertIn("Icon=whisper-dictate", entry)

    def test_enable_and_disable(self) -> None:
        self.assertFalse(autostart.is_enabled())
        autostart.enable("/usr/bin/whisper-dictate")
        self.assertTrue(autostart.is_enabled())
        self.assertIn("daemon", self.path.read_text(encoding="utf-8"))
        autostart.disable()
        self.assertFalse(autostart.is_enabled())

    def test_disable_is_idempotent(self) -> None:
        autostart.disable()
        autostart.disable()
        self.assertFalse(autostart.is_enabled())

    def test_apply_follows_flag(self) -> None:
        autostart.apply(True, "/usr/bin/whisper-dictate")
        self.assertTrue(autostart.is_enabled())
        autostart.apply(False)
        self.assertFalse(autostart.is_enabled())


if __name__ == "__main__":
    unittest.main()
