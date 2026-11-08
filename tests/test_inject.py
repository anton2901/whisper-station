"""Тесты вставки: буфер, Ctrl+V, восстановление буфера и запасные пути."""

from __future__ import annotations

import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from whisper_station import inject
from whisper_station.config import Config

FAKE_WL_COPY = """#!/bin/sh
if [ "$1" = "--clear" ]; then : > "$FAKE_CLIP_FILE"; exit 0; fi
cat > "$FAKE_CLIP_FILE"
"""
FAKE_WL_PASTE = """#!/bin/sh
[ -f "$FAKE_CLIP_FILE" ] && cat "$FAKE_CLIP_FILE"
exit 0
"""
FAKE_YDOTOOL = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_YDOTOOL_LOG"
exit 0
"""


class InjectTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name, script in (
            ("wl-copy", FAKE_WL_COPY),
            ("wl-paste", FAKE_WL_PASTE),
            ("ydotool", FAKE_YDOTOOL),
        ):
            path = self.root / name
            path.write_text(script, encoding="utf-8")
            path.chmod(0o755)
        self.clip = self.root / "clipboard.txt"
        self.log = self.root / "ydotool.log"
        # Настоящий слушающий UNIX-сокет: ensure_ydotoold проверяет живость.
        self.socket = self.root / "yd.sock"
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(self.socket))
        self.listener.listen(1)
        self.addCleanup(self.listener.close)
        env = {
            "PATH": f"{self.root}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_CLIP_FILE": str(self.clip),
            "FAKE_YDOTOOL_LOG": str(self.log),
            "YDOTOOL_SOCKET": str(self.socket),
        }
        patcher = mock.patch.dict(os.environ, env, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def cfg(self, **changes) -> Config:
        return Config(restore_delay_ms=0, **changes)

    def ydotool_calls(self) -> str:
        return self.log.read_text(encoding="utf-8") if self.log.exists() else ""

    def test_paste_mode_pastes_and_restores(self) -> None:
        self.clip.write_text("старое", encoding="utf-8")
        result = inject.inject_text(
            "новый текст", self.cfg(insert_mode="paste", restore_clipboard=True)
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.method, "paste")
        self.assertIn("key 29:1 47:1 47:0 29:0", self.ydotool_calls())
        self.assertEqual(self.clip.read_text(encoding="utf-8"), "старое")

    def test_clipboard_mode_does_not_type(self) -> None:
        result = inject.inject_text("только буфер", self.cfg(insert_mode="clipboard"))
        self.assertTrue(result.ok)
        self.assertEqual(result.method, "clipboard")
        self.assertEqual(self.clip.read_text(encoding="utf-8"), "только буфер")
        self.assertEqual(self.ydotool_calls(), "")

    def test_restore_disabled_keeps_new_text(self) -> None:
        self.clip.write_text("старое", encoding="utf-8")
        inject.inject_text(
            "новый", self.cfg(insert_mode="paste", restore_clipboard=False)
        )
        self.assertEqual(self.clip.read_text(encoding="utf-8"), "новый")

    def test_terminal_shortcut(self) -> None:
        result = inject.inject_text(
            "в терминал", self.cfg(insert_mode="paste", paste_shortcut="ctrl+shift+v")
        )
        self.assertTrue(result.ok)
        self.assertIn("key 29:1 42:1 47:1 47:0 42:0 29:0", self.ydotool_calls())

    def test_type_mode(self) -> None:
        result = inject.inject_text(
            "по буквам", self.cfg(insert_mode="type", restore_clipboard=False)
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.method, "type")
        self.assertIn("type --delay 12 по буквам", self.ydotool_calls())

    def test_falls_back_to_clipboard_without_ydotoold(self) -> None:
        with mock.patch.object(inject, "ensure_ydotoold", side_effect=inject.InjectError("нет uinput")):
            result = inject.inject_text("текст", self.cfg(insert_mode="paste"))
        self.assertFalse(result.ok)
        self.assertEqual(result.method, "clipboard")
        self.assertIn("буфере", result.detail)
        self.assertEqual(self.clip.read_text(encoding="utf-8"), "текст")

    def test_falls_back_when_ydotool_fails(self) -> None:
        failing = self.root / "ydotool"
        failing.write_text("#!/bin/sh\necho boom >&2\nexit 1\n", encoding="utf-8")
        failing.chmod(0o755)
        result = inject.inject_text("текст", self.cfg(insert_mode="paste"))
        self.assertFalse(result.ok)
        self.assertIn("boom", result.detail)

    def test_empty_text_is_rejected(self) -> None:
        result = inject.inject_text("", self.cfg())
        self.assertFalse(result.ok)
        self.assertEqual(result.method, "none")

    def test_cyrillic_survives_utf8(self) -> None:
        inject.inject_text("Привет, мир!", self.cfg(insert_mode="clipboard"))
        self.assertEqual(self.clip.read_text(encoding="utf-8"), "Привет, мир!")

    def test_clipboard_get_empty_when_missing(self) -> None:
        self.clip.unlink(missing_ok=True)
        self.assertEqual(inject.clipboard_get(), "")

    def test_check_environment_shape(self) -> None:
        info = inject.check_environment()
        for key in ("wayland", "wl_clipboard", "ydotool", "uinput", "runtime_dir"):
            self.assertIn(key, info)


if __name__ == "__main__":
    unittest.main()
