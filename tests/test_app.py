"""Тесты приложения: какие настройки требуют перезапуска сервера."""

from __future__ import annotations

import unittest

from whisper_station.app import server_settings_changed
from whisper_station.config import Config


class ServerSettingsTest(unittest.TestCase):
    def test_model_change_restarts(self) -> None:
        self.assertTrue(server_settings_changed(Config(), Config(model_name="small")))
        self.assertTrue(server_settings_changed(Config(), Config(model_device="cpu")))
        self.assertTrue(server_settings_changed(Config(), Config(model_compute="int8")))
        self.assertTrue(server_settings_changed(Config(), Config(model_threads=4)))

    def test_server_change_restarts(self) -> None:
        self.assertTrue(
            server_settings_changed(Config(), Config(server_url="http://127.0.0.1:9999"))
        )
        self.assertTrue(server_settings_changed(Config(), Config(server_command="/bin/true")))

    def test_other_settings_do_not_restart(self) -> None:
        self.assertFalse(server_settings_changed(Config(), Config()))
        self.assertFalse(server_settings_changed(Config(), Config(hotkey="Alt+M")))
        self.assertFalse(server_settings_changed(Config(), Config(language="en")))
        self.assertFalse(server_settings_changed(Config(), Config(dictionary_words=("K8s",))))


if __name__ == "__main__":
    unittest.main()
