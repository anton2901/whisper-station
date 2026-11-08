"""Версия в одном месте: модуль, pyproject и PKGBUILD должны совпадать."""

from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

from whisper_dictate import __version__

ROOT = Path(__file__).resolve().parent.parent


class VersionTest(unittest.TestCase):
    def test_pyproject_matches(self) -> None:
        with (ROOT / "pyproject.toml").open("rb") as handle:
            self.assertEqual(tomllib.load(handle)["project"]["version"], __version__)

    def test_pkgbuild_matches(self) -> None:
        text = (ROOT / "PKGBUILD").read_text(encoding="utf-8")
        match = re.search(r"^pkgver=(\S+)$", text, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), __version__)

    def test_changelog_mentions_version(self) -> None:
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## [{__version__}]", text)


if __name__ == "__main__":
    unittest.main()
