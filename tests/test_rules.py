"""Тесты правила KWin: координаты HUD, список правил, запись в kwinrulesrc."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from whisper_dictate import rules


class PositionTest(unittest.TestCase):
    def test_centered_top(self) -> None:
        x, y = rules.hud_position(0, 0, 3440)
        self.assertEqual(x, (3440 - rules.HUD_WIDTH) // 2)
        self.assertEqual(y, rules.MARGIN_TOP)

    def test_second_screen_offset(self) -> None:
        x, _ = rules.hud_position(3440, 0, 1920)
        self.assertEqual(x, 3440 + (1920 - rules.HUD_WIDTH) // 2)

    def test_screen_narrower_than_hud(self) -> None:
        x, _ = rules.hud_position(0, 0, 200)
        self.assertEqual(x, 0)


class SizeTest(unittest.TestCase):
    def test_matches_hud_size(self) -> None:
        from whisper_dictate import hud

        self.assertEqual(rules.HUD_WIDTH, hud.WIDTH)
        self.assertEqual(rules.HUD_HEIGHT, hud.HEIGHT)


class RuleIdsTest(unittest.TestCase):
    def test_parse(self) -> None:
        self.assertEqual(rules.rule_ids(""), [])
        self.assertEqual(rules.rule_ids("1"), [1])
        self.assertEqual(rules.rule_ids("1,2, 3"), [1, 2, 3])
        self.assertEqual(rules.rule_ids("abc,5"), [5])


class RuleFileTest(unittest.TestCase):
    def setUp(self) -> None:
        if not rules.available():
            self.skipTest("kwriteconfig6/kreadconfig6 недоступны")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / "kwinrulesrc"
        patcher = mock.patch.object(rules, "reload_kwin", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_creates_rule(self) -> None:
        self.assertTrue(rules.ensure_rule(1540, 40, config=self.config))
        text = self.config.read_text(encoding="utf-8")
        self.assertIn(str(rules.RULE_ID), text)
        self.assertIn("position=1540,40", text)
        self.assertIn("wmclass=whisper-dictate", text)
        self.assertIn("positionrule=2", text)
        self.assertTrue(rules.rule_present(config=self.config))

    def test_keeps_foreign_rules(self) -> None:
        self.config.write_text(
            "[General]\ncount=1\nrules=7\n\n[7]\nwmclass=firefox\nposition=5,5\n",
            encoding="utf-8",
        )
        self.assertTrue(rules.ensure_rule(100, 20, config=self.config))
        text = self.config.read_text(encoding="utf-8")
        self.assertIn("wmclass=firefox", text)
        self.assertEqual(rules.rule_ids(rules._kread(self.config, "General", "rules")), [7, rules.RULE_ID])

    def test_remove_rule(self) -> None:
        rules.ensure_rule(10, 10, config=self.config)
        self.assertTrue(rules.remove_rule(config=self.config))
        self.assertFalse(rules.rule_present(config=self.config))
        self.assertFalse(rules.remove_rule(config=self.config))

    def test_update_existing_rule(self) -> None:
        rules.ensure_rule(10, 10, config=self.config)
        rules.ensure_rule(20, 30, config=self.config)
        text = self.config.read_text(encoding="utf-8")
        self.assertIn("position=20,30", text)
        self.assertEqual(text.count(str(rules.RULE_ID)), text.count(str(rules.RULE_ID)))
        self.assertEqual(len(rules.rule_ids(rules._kread(self.config, "General", "rules"))), 1)


if __name__ == "__main__":
    unittest.main()
