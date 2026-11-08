"""Тесты конфигурации: умолчания, round-trip, защита от мусора."""

from __future__ import annotations

import tempfile
import unittest
from unittest import mock
from pathlib import Path

from whisper_station import config as cfgmod


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

    def test_migrates_config_from_old_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "whisper-dictate"
            legacy.mkdir()
            (legacy / "config.toml").write_text('[hotkey]\ntoggle = "Alt+M"\n', encoding="utf-8")
            with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp}):
                cfg = cfgmod.load()
                new_file = Path(tmp) / "whisper-station" / "config.toml"
                self.assertTrue(new_file.is_file())
        self.assertEqual(cfg.hotkey, "Alt+M")

    def test_preview_live_default_and_parsing(self) -> None:
        self.assertFalse(cfgmod.Config().preview_live)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text("[preview]\nlive = true\n", encoding="utf-8")
            self.assertTrue(cfgmod.load(path).preview_live)

    def test_hotkey_mode_default_and_validation(self) -> None:
        self.assertEqual(cfgmod.Config().hotkey_mode, "toggle")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text('[hotkey]\nmode = "hold"\n', encoding="utf-8")
            self.assertEqual(cfgmod.load(path).hotkey_mode, "toggle")

    def test_paste_shortcut_default_and_validation(self) -> None:
        self.assertEqual(cfgmod.Config().paste_shortcut, "ctrl+v")
        self.assertFalse(cfgmod.Config().restore_clipboard)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text('[insert]\npaste_shortcut = "cmd+v"\n', encoding="utf-8")
            cfg = cfgmod.load(path)
        self.assertEqual(cfg.paste_shortcut, "ctrl+v")

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
