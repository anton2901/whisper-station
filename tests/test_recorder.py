"""Тесты записи: WAV-обёртка, полосы осциллограммы, процесс записи (заглушка)."""

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
    pcm_bands,
    pcm_to_wav,
    wav_duration,
)

FAKE_RECORDER = """#!/bin/sh
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

    def test_pcm_bands_shape_and_range(self) -> None:
        pcm = (1000).to_bytes(2, "little", signed=True) * 1600
        bands = pcm_bands(pcm, count=16)
        self.assertEqual(len(bands), 16)
        for low, high in bands:
            self.assertLessEqual(low, high)
            self.assertGreaterEqual(low, -1.0)
            self.assertLessEqual(high, 1.0)
        self.assertAlmostEqual(bands[0][1], 1000 / 32768, places=4)

    def test_pcm_bands_keeps_negative_peaks(self) -> None:
        pcm = (-20000).to_bytes(2, "little", signed=True) * 800
        bands = pcm_bands(pcm, count=4)
        self.assertLess(bands[0][0], -0.5)

    def test_pcm_bands_empty(self) -> None:
        self.assertEqual(pcm_bands(b""), [])


class RecorderProcessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ("parec", "pw-record"):
            fake = self.root / name
            fake.write_text(FAKE_RECORDER, encoding="utf-8")
            fake.chmod(0o755)
        self._old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{self.root}{os.pathsep}{self._old_path}"
        self.addCleanup(lambda: os.environ.__setitem__("PATH", self._old_path))

    def test_prefers_pw_record(self) -> None:
        recorder = Recorder(Config(audio_backend="auto"))
        self.assertEqual(recorder.resolve_backend(), "pw-record")

    def test_records_and_wraps_wav(self) -> None:
        recorder = Recorder(Config(audio_backend="parec"))
        recorder.start()
        time.sleep(0.4)
        wav = recorder.stop()
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertGreater(wav_duration(wav), 0.15)
        self.assertLess(wav_duration(wav), 2.0)
        self.assertFalse(recorder.running)

    def test_wave_callback_receives_bands(self) -> None:
        waves: list[list[tuple[float, float]]] = []
        recorder = Recorder(Config(audio_backend="parec"), on_wave=waves.append)
        recorder.start()
        time.sleep(0.35)
        recorder.stop()
        self.assertTrue(waves, "осциллограмма не получила ни одной полосы")
        self.assertTrue(all(len(bands) > 0 for bands in waves))

    def test_cancel_discards(self) -> None:
        recorder = Recorder(Config(audio_backend="parec"))
        recorder.start()
        time.sleep(0.2)
        recorder.cancel()
        self.assertFalse(recorder.running)
        with self.assertRaises(RecorderError):
            recorder.stop()

    def test_stop_without_start_raises(self) -> None:
        with self.assertRaises(RecorderError):
            Recorder(Config(audio_backend="parec")).stop()

    def test_missing_backend_raises(self) -> None:
        recorder = Recorder(Config(audio_backend="нет-такого-бинаря"))
        with self.assertRaises(RecorderError):
            recorder.start()

    def test_failed_process_raises(self) -> None:
        broken = self.root / "parec"
        broken.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        broken.chmod(0o755)
        recorder = Recorder(Config(audio_backend="parec"))
        recorder.start()
        time.sleep(0.2)
        with self.assertRaises(RecorderError):
            recorder.stop()

    def test_silent_process_returns_empty_wav(self) -> None:
        silent = self.root / "parec"
        silent.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        silent.chmod(0o755)
        recorder = Recorder(Config(audio_backend="parec"))
        recorder.start()
        time.sleep(0.2)
        wav = recorder.stop()
        self.assertEqual(wav_duration(wav), 0.0)


if __name__ == "__main__":
    unittest.main()
