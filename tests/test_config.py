"""Тесты конфигурации: умолчания, round-trip, защита от мусора."""

from __future__ import annotations

import tempfile
import tomllib
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
        self.assertEqual(cfg.max_seconds, cfgmod.Config().max_seconds)
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

    def test_max_seconds_capped(self) -> None:
        self.assertEqual(cfgmod.Config().max_seconds, 300.0)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text("[audio]\nmax_seconds = 5000\n", encoding="utf-8")
            self.assertEqual(cfgmod.load(path).max_seconds, cfgmod.MAX_RECORD_SECONDS)

    def test_preview_live_default_and_parsing(self) -> None:
        self.assertTrue(cfgmod.Config().preview_live)
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


class DictionaryConfigTest(unittest.TestCase):
    def test_defaults(self) -> None:
        cfg = cfgmod.Config()
        self.assertEqual(cfg.dictionary_words, ())
        self.assertAlmostEqual(cfg.dictionary_threshold, 0.18)
        self.assertTrue(cfg.remove_fillers)
        self.assertTrue(cfg.collapse_stutters)
        self.assertFalse(cfg.trailing_space)
        self.assertEqual(cfg.fillers, ())

    def test_roundtrip_lists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            original = cfgmod.Config(
                dictionary_words=("Kubernetes", "в общем", 'say "hi"'),
                dictionary_threshold=0.3,
                remove_fillers=False,
                collapse_stutters=False,
                trailing_space=True,
                fillers=("ну", "вот"),
            )
            cfgmod.save(original, path)
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
            loaded = cfgmod.load(path)
        self.assertEqual(raw["dictionary"]["words"], ["Kubernetes", "в общем", 'say "hi"'])
        self.assertEqual(loaded.dictionary_words, original.dictionary_words)
        self.assertEqual(loaded.fillers, ("ну", "вот"))
        self.assertAlmostEqual(loaded.dictionary_threshold, 0.3)
        self.assertFalse(loaded.remove_fillers)
        self.assertFalse(loaded.collapse_stutters)
        self.assertTrue(loaded.trailing_space)

    def test_cleans_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                '[dictionary]\nwords = ["  Kubernetes  ", "", "kubernetes", "Docker"]\n',
                encoding="utf-8",
            )
            cfg = cfgmod.load(path)
        self.assertEqual(cfg.dictionary_words, ("Kubernetes", "Docker"))

    def test_skips_non_string_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text("[dictionary]\nwords = [42, \"ok\", true]\n", encoding="utf-8")
            cfg = cfgmod.load(path)
        self.assertEqual(cfg.dictionary_words, ("ok",))

    def test_non_list_words_fall_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text('[dictionary]\nwords = "Kubernetes"\n', encoding="utf-8")
            cfg = cfgmod.load(path)
        self.assertEqual(cfg.dictionary_words, ())

    def test_long_word_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            long_word = "x" * (cfgmod.MAX_WORD_LENGTH + 1)
            path.write_text(f'[dictionary]\nwords = ["{long_word}", "ok"]\n', encoding="utf-8")
            cfg = cfgmod.load(path)
        self.assertEqual(cfg.dictionary_words, ("ok",))

    def test_threshold_out_of_range_falls_back(self) -> None:
        for bad in ("5", "-1", "nan"):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.toml"
                path.write_text(f"[dictionary]\nthreshold = {bad}\n", encoding="utf-8")
                cfg = cfgmod.load(path)
                self.assertAlmostEqual(cfg.dictionary_threshold, 0.18)

    def test_zero_threshold_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text("[dictionary]\nthreshold = 0\n", encoding="utf-8")
            self.assertAlmostEqual(cfgmod.load(path).dictionary_threshold, 0.0)

    def test_dumps_is_valid_toml(self) -> None:
        text = cfgmod.dumps(cfgmod.Config(dictionary_words=("a", "b")))
        parsed = tomllib.loads(text)
        self.assertEqual(parsed["dictionary"]["words"], ["a", "b"])
        self.assertEqual(parsed["text"]["trailing_space"], False)


if __name__ == "__main__":
    unittest.main()
