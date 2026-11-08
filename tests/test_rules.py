"""Тесты правила KWin: координаты HUD, INI-правка и запись в kwinrulesrc."""

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


class RuleIdsTest(unittest.TestCase):
    def test_parse(self) -> None:
        self.assertEqual(rules.rule_ids(""), [])
        self.assertEqual(rules.rule_ids("1"), [1])
        self.assertEqual(rules.rule_ids("1,2, 3"), [1, 2, 3])
        self.assertEqual(rules.rule_ids("abc,5"), [5])


class IniTest(unittest.TestCase):
    def test_parse_sections(self) -> None:
        lines = ["[General]", "rules=7", "", "[7]", "wmclass=firefox", "# comment", "position=5,5"]
        sections = rules.parse_sections(lines)
        self.assertEqual(sections["General"]["rules"], "7")
        self.assertEqual(sections["7"]["wmclass"], "firefox")
        self.assertEqual(sections["7"]["position"], "5,5")

    def test_set_and_replace(self) -> None:
        lines = ["[7]", "wmclass=firefox"]
        lines = rules._set_in_section(lines, "7", "wmclass", "kate")
        self.assertEqual(lines, ["[7]", "wmclass=kate"])

    def test_new_section_appended(self) -> None:
        lines = rules._set_in_section(["[General]", "rules="], "991001", "wmclass", "x")
        self.assertIn("[991001]", lines)
        self.assertIn("wmclass=x", lines)


class RuleFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / "kwinrulesrc"
        patcher = mock.patch.object(rules, "reload_kwin", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_creates_rule(self) -> None:
        self.assertTrue(rules.ensure_rule(1540, 40, config=self.config))
        text = self.config.read_text(encoding="utf-8")
        self.assertIn(f"[{rules.RULE_ID}]", text)
        self.assertIn("position=1540,40", text)
        self.assertIn("wmclass=whisper-dictate", text)
        self.assertIn("positionrule=2", text)
        self.assertTrue(rules.rule_present(config=self.config))

    def test_keeps_foreign_content(self) -> None:
        self.config.write_text(
            "# чужой комментарий\n[General]\nrules=7\n\n[7]\nwmclass=firefox\nposition=5,5\n",
            encoding="utf-8",
        )
        self.assertTrue(rules.ensure_rule(100, 20, config=self.config))
        text = self.config.read_text(encoding="utf-8")
        self.assertIn("wmclass=firefox", text)
        self.assertIn("# чужой комментарий", text)
        sections = rules.parse_sections(text.splitlines())
        self.assertEqual(sections["7"]["wmclass"], "firefox")
        self.assertEqual(sections[str(rules.RULE_ID)]["position"], "100,20")

    def test_update_does_not_duplicate(self) -> None:
        rules.ensure_rule(10, 10, config=self.config)
        rules.ensure_rule(20, 30, config=self.config)
        text = self.config.read_text(encoding="utf-8")
        self.assertEqual(text.count("position="), 1)
        self.assertEqual(text.count(f"[{rules.RULE_ID}]"), 1)

    def test_remove_rule(self) -> None:
        rules.ensure_rule(10, 10, config=self.config)
        self.assertTrue(rules.remove_rule(config=self.config))
        self.assertFalse(rules.rule_present(config=self.config))
        self.assertFalse(rules.remove_rule(config=self.config))


if __name__ == "__main__":
    unittest.main()
