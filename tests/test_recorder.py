"""Тесты записи: WAV-обёртка, уровень сигнала, процесс parec (через заглушку)."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
import wave
from io import BytesIO
from pathlib import Path

from whisper_dictate.config import Config
from whisper_dictate.recorder import (
    Recorder,
    RecorderError,
    pcm_level,
    pcm_rms,
    pcm_to_wav,
    wav_duration,
)

FAKE_PAREC = """#!/bin/sh
trap 'exit 0' INT
while true; do
  head -c 3200 /dev/zero
  sleep 0.02
done
"""


class WavHelpersTest(unittest.TestCase):
    def test_pcm_to_wav_header(self) -> None:
        wav = pcm_to_wav(b"\x00\x00" * 16000)
        with wave.open(BytesIO(wav), "rb") as handle:
            self.assertEqual(handle.getnchannels(), 1)
            self.assertEqual(handle.getsampwidth(), 2)
            self.assertEqual(handle.getframerate(), 16000)
            self.assertEqual(handle.getnframes(), 16000)

    def test_wav_duration(self) -> None:
        self.assertAlmostEqual(wav_duration(pcm_to_wav(b"\x00\x00" * 16000)), 1.0, places=2)
        self.assertEqual(wav_duration(b"not a wav"), 0.0)

    def test_pcm_rms_silence_and_signal(self) -> None:
        self.assertEqual(pcm_rms(b"\x00\x00" * 100), 0.0)
        loud = (30000).to_bytes(2, "little", signed=True) * 100
        self.assertGreater(pcm_rms(loud), 0.8)
        self.assertEqual(pcm_rms(b""), 0.0)

    def test_pcm_level_uses_db_scale(self) -> None:
        self.assertEqual(pcm_level(b"\x00\x00" * 100), 0.0)

        def constant(amplitude: int) -> bytes:
            return amplitude.to_bytes(2, "little", signed=True) * 400

        quiet = pcm_level(constant(300))  # около -41 dBFS
        normal = pcm_level(constant(3000))  # около -21 dBFS
        loud = pcm_level(constant(20000))  # около -4 dBFS
        self.assertGreater(quiet, 0.15)
        self.assertLess(quiet, 0.35)
        self.assertGreater(normal, quiet)
        self.assertGreater(normal, 0.4)
        self.assertGreater(loud, normal)
        self.assertLessEqual(loud, 1.0)


class RecorderProcessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        fake = self.root / "parec"
        fake.write_text(FAKE_PAREC, encoding="utf-8")
        fake.chmod(0o755)
        self._old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{self.root}{os.pathsep}{self._old_path}"
        self.addCleanup(lambda: os.environ.__setitem__("PATH", self._old_path))

    def cfg(self) -> Config:
        return Config(audio_backend="parec")

    def test_records_and_wraps_wav(self) -> None:
        recorder = Recorder(self.cfg())
        recorder.start()
        time.sleep(0.4)
        wav = recorder.stop()
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertGreater(wav_duration(wav), 0.15)
        self.assertLess(wav_duration(wav), 2.0)
        self.assertFalse(recorder.running)

    def test_level_callback_receives_values(self) -> None:
        levels: list[float] = []
        recorder = Recorder(self.cfg(), on_level=levels.append)
        recorder.start()
        time.sleep(0.25)
        recorder.stop()
        self.assertTrue(levels, "индикатор уровня не получил ни одного значения")
        self.assertTrue(all(0.0 <= value <= 1.0 for value in levels))

    def test_cancel_discards(self) -> None:
        recorder = Recorder(self.cfg())
        recorder.start()
        time.sleep(0.2)
        recorder.cancel()
        self.assertFalse(recorder.running)
        with self.assertRaises(RecorderError):
            recorder.stop()

    def test_stop_without_start_raises(self) -> None:
        with self.assertRaises(RecorderError):
            Recorder(self.cfg()).stop()

    def test_missing_backend_raises(self) -> None:
        recorder = Recorder(Config(audio_backend="нет-такого-бинаря"))
        with self.assertRaises(RecorderError):
            recorder.start()

    def test_empty_capture_raises(self) -> None:
        silent = self.root / "parec"
        silent.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        recorder = Recorder(self.cfg())
        recorder.start()
        time.sleep(0.2)
        with self.assertRaises(RecorderError):
            recorder.stop()


if __name__ == "__main__":
    unittest.main()
