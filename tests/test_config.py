"""Тесты конфигурации: умолчания, round-trip, защита от мусора."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from whisper_dictate import config as cfgmod


class ConfigDefaultsTest(unittest.TestCase):
    def test_missing_file_uses_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = cfgmod.load(Path(tmp) / "config.toml")
        self.assertEqual(cfg.hotkey, cfgmod.DEFAULT_HOTKEY)
        self.assertEqual(cfg.insert_mode, "paste")
        self.assertEqual(cfg.language, "ru")
        self.assertTrue(cfg.server_autostart)

    def test_broken_toml_uses_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text("[hotkey\ntoggle = ", encoding="utf-8")
            cfg = cfgmod.load(path)
        self.assertEqual(cfg.hotkey, cfgmod.DEFAULT_HOTKEY)

    def test_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            original = cfgmod.Config(
                hotkey="Alt+M",
                language="en",
                server_url="http://127.0.0.1:9000",
                insert_mode="type",
                restore_clipboard=False,
                restore_delay_ms=100,
                min_seconds=0.5,
                max_seconds=30.0,
                beep=False,
                autostart=True,
            )
            cfgmod.save(original, path)
            loaded = cfgmod.load(path)
        self.assertEqual(loaded.hotkey, "Alt+M")
        self.assertEqual(loaded.language, "en")
        self.assertEqual(loaded.server_url, "http://127.0.0.1:9000")
        self.assertEqual(loaded.insert_mode, "type")
        self.assertFalse(loaded.restore_clipboard)
        self.assertEqual(loaded.restore_delay_ms, 100)
        self.assertAlmostEqual(loaded.min_seconds, 0.5)
        self.assertAlmostEqual(loaded.max_seconds, 30.0)
        self.assertFalse(loaded.beep)
        self.assertTrue(loaded.autostart)

    def test_invalid_values_fall_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                "[insert]\nmode = \"teleport\"\n[transcribe]\n"
                "server_url = \"http://example.com:8765\"\n[audio]\nbackend = \"alsa\"\n",
                encoding="utf-8",
            )
            cfg = cfgmod.load(path)
        self.assertEqual(cfg.insert_mode, "paste")
        self.assertEqual(cfg.server_url, "http://127.0.0.1:8765")
        self.assertEqual(cfg.audio_backend, "auto")

    def test_wrong_types_fall_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                "[hotkey]\ntoggle = 42\n[audio]\nmax_seconds = \"много\"\n[ui]\nbeep = \"да\"\n",
                encoding="utf-8",
            )
            cfg = cfgmod.load(path)
        self.assertEqual(cfg.hotkey, cfgmod.DEFAULT_HOTKEY)
        self.assertEqual(cfg.max_seconds, 120.0)
        self.assertTrue(cfg.beep)

    def test_dumps_has_sections_and_comments(self) -> None:
        text = cfgmod.dumps(cfgmod.Config())
        for section in cfgmod.SECTIONS:
            self.assertIn(f"[{section}]", text)
        self.assertIn("# глобальный хоткей", text)
        self.assertIn('toggle = "Meta+Alt+D"', text)

    def test_loopback_only(self) -> None:
        self.assertTrue(cfgmod.is_loopback_url("http://127.0.0.1:8765"))
        self.assertTrue(cfgmod.is_loopback_url("http://localhost:8765"))
        self.assertFalse(cfgmod.is_loopback_url("http://192.168.1.2:8765"))
        self.assertFalse(cfgmod.is_loopback_url("https://example.com"))
        self.assertFalse(cfgmod.is_loopback_url("не url"))

    def test_with_changes_does_not_mutate(self) -> None:
        base = cfgmod.Config()
        changed = base.with_changes(language="en")
        self.assertEqual(base.language, "ru")
        self.assertEqual(changed.language, "en")


if __name__ == "__main__":
    unittest.main()
