"""Тесты встроенного сервера: multipart, WAV, HTTP-эндпоинты, окружение."""

from __future__ import annotations

import io
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
import wave
from unittest import mock

from whisper_station.config import Config
from whisper_station.recorder import pcm_to_wav
from whisper_station.server.config import ConfigError, ServerConfig
from whisper_station.server.engine import EngineLoading, Result, Segment, pick_compute
from whisper_station.server.multipart import MultipartError, boundary_of, parse
from whisper_station.server.web import Server, wav_error
from whisper_station.stt import build_multipart, transcribe

WAV = pcm_to_wav(b"\x00\x00" * 1600)


def make_wav(rate: int = 16000, channels: int = 1, width: int = 2) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(b"\x00" * 320)
    return buffer.getvalue()


class MultipartTest(unittest.TestCase):
    def test_roundtrip_with_client_builder(self) -> None:
        body = build_multipart(
            fields={"language": "ru", "response_format": "json"},
            files={"file": ("audio.wav", WAV, "audio/wav")},
            boundary="XBOUNDARY",
        )
        form = parse(body, "XBOUNDARY")
        self.assertEqual(form.fields["language"], "ru")
        self.assertEqual(form.fields["response_format"], "json")
        self.assertEqual(form.files["file"].filename, "audio.wav")
        self.assertEqual(form.files["file"].content_type, "audio/wav")
        self.assertEqual(form.files["file"].data, WAV)

    def test_empty_file_part(self) -> None:
        body = (
            b"--B\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.wav\"\r\n"
            b"Content-Type: audio/wav\r\n\r\n\r\n--B--\r\n"
        )
        form = parse(body, "B")
        self.assertEqual(form.files["file"].data, b"")

    def test_boundary_header(self) -> None:
        self.assertEqual(boundary_of("multipart/form-data; boundary=abc"), "abc")
        self.assertEqual(boundary_of('multipart/form-data; boundary="a b"'), "a b")
        with self.assertRaises(MultipartError):
            boundary_of("application/json")
        with self.assertRaises(MultipartError):
            boundary_of("multipart/form-data")


class WavTest(unittest.TestCase):
    def test_valid(self) -> None:
        self.assertIsNone(wav_error(WAV))

    def test_garbage(self) -> None:
        self.assertIn("не WAV", wav_error(b"not a wav") or "")

    def test_wrong_rate(self) -> None:
        problem = wav_error(make_wav(rate=44100))
        self.assertIn("44100", problem or "")


class CudaErrorTest(unittest.TestCase):
    def test_recognises_cuda_failures(self) -> None:
        from whisper_station.server.engine import cuda_error

        self.assertTrue(cuda_error(RuntimeError("Library libcublas.so.12 is not found")))
        self.assertTrue(cuda_error(RuntimeError("cuDNN version mismatch")))
        self.assertFalse(cuda_error(RuntimeError("invalid WAV header")))


class ComputeTest(unittest.TestCase):
    def test_auto_by_device(self) -> None:
        self.assertEqual(pick_compute("cuda", ""), "float16")
        self.assertEqual(pick_compute("cpu", ""), "int8")

    def test_float16_on_cpu_downgraded(self) -> None:
        self.assertEqual(pick_compute("cpu", "float16"), "int8")
        self.assertEqual(pick_compute("cuda", "int8_float16"), "int8_float16")


class ServerConfigTest(unittest.TestCase):
    def test_defaults(self) -> None:
        cfg = ServerConfig.from_env()
        self.assertEqual(cfg.host, "127.0.0.1")
        self.assertGreater(cfg.threads_effective, 0)

    def test_model_and_device_from_env(self) -> None:
        env = {"WHISPER_MODEL": "small", "WHISPER_DEVICE": "CUDA", "WHISPER_PORT": "9123"}
        with mock.patch.dict(os.environ, env):
            cfg = ServerConfig.from_env()
        self.assertEqual(cfg.model, "small")
        self.assertEqual(cfg.device, "cuda")
        self.assertEqual(cfg.port, 9123)

    def test_non_loopback_rejected(self) -> None:
        with mock.patch.dict(os.environ, {"WHISPER_HOST": "0.0.0.0"}):
            with self.assertRaises(ConfigError):
                ServerConfig.from_env()

    def test_bad_port(self) -> None:
        with mock.patch.dict(os.environ, {"WHISPER_PORT": "восемь"}):
            with self.assertRaises(ConfigError):
                ServerConfig.from_env()


class FakeEngine:
    """Заглушка движка: без faster-whisper и без модели."""

    def __init__(self, *, loading: bool = False, fail: bool = False) -> None:
        self.loading = loading
        self.fail = fail
        self.calls: list[tuple[str, str]] = []
        self.last_activity = 0.0

    def start(self) -> None:
        pass

    def status(self) -> dict[str, object]:
        return {"status": "loading" if self.loading else "ok", "model": "fake", "device": "cpu"}

    def transcribe(self, wav: bytes, language: str, prompt: str | None) -> Result:
        self.calls.append((language, prompt or ""))
        if self.loading:
            raise EngineLoading("модель ещё загружается")
        return Result(
            text="привет",
            language="ru",
            duration=0.1,
            segments=(Segment(0.0, 0.1, "привет"),),
        )


class HttpTest(unittest.TestCase):
    def start(self, engine: FakeEngine, **cfg_changes) -> str:
        cfg = ServerConfig(port=0, **cfg_changes)
        self.server = Server(cfg, engine)  # type: ignore[arg-type]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        return f"http://127.0.0.1:{self.server.server_port}"

    def test_health(self) -> None:
        url = self.start(FakeEngine())
        with urllib.request.urlopen(url + "/health", timeout=5) as response:
            payload = json.loads(response.read())
        self.assertEqual(payload["status"], "ok")

    def test_models(self) -> None:
        url = self.start(FakeEngine(), model="small")
        with urllib.request.urlopen(url + "/v1/models", timeout=5) as response:
            payload = json.loads(response.read())
        self.assertEqual(payload["data"][0]["id"], "small")

    def assert_http_error(self, code: int, request: str | urllib.request.Request) -> urllib.error.HTTPError:
        """Проверить код ответа и закрыть тело, чтобы не было ResourceWarning."""
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        error = ctx.exception
        error.close()
        self.assertEqual(error.code, code)
        return error

    def test_unknown_get(self) -> None:
        url = self.start(FakeEngine())
        self.assert_http_error(404, url + "/nope")

    def test_transcribe_roundtrip(self) -> None:
        engine = FakeEngine()
        url = self.start(engine)
        result = transcribe(WAV, Config(server_url=url, language="ru"))
        self.assertEqual(result.text, "привет")
        self.assertEqual(engine.calls, [("ru", "")])

    def test_prompt_is_forwarded(self) -> None:
        engine = FakeEngine()
        url = self.start(engine)
        body = build_multipart(
            fields={"language": "ru", "prompt": "Kubernetes, ChargeBee"},
            files={"file": ("audio.wav", WAV, "audio/wav")},
            boundary="B",
        )
        request = urllib.request.Request(
            url + "/v1/audio/transcriptions",
            data=body,
            headers={"Content-Type": "multipart/form-data; boundary=B"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read())
        self.assertEqual(payload["text"], "привет")
        self.assertEqual(engine.calls, [("ru", "Kubernetes, ChargeBee")])

    def test_text_format(self) -> None:
        engine = FakeEngine()
        url = self.start(engine)
        body = build_multipart(
            fields={"response_format": "text"},
            files={"file": ("audio.wav", WAV, "audio/wav")},
            boundary="B",
        )
        request = urllib.request.Request(
            url + "/v1/audio/transcriptions",
            data=body,
            headers={"Content-Type": "multipart/form-data; boundary=B"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.read().decode("utf-8"), "привет")

    def test_bad_wav_rejected(self) -> None:
        url = self.start(FakeEngine())
        body = build_multipart(
            fields={"language": "ru"},
            files={"file": ("audio.wav", b"garbage", "audio/wav")},
            boundary="B",
        )
        request = urllib.request.Request(
            url + "/v1/audio/transcriptions",
            data=body,
            headers={"Content-Type": "multipart/form-data; boundary=B"},
            method="POST",
        )
        self.assert_http_error(400, request)

    def test_too_large_audio(self) -> None:
        url = self.start(FakeEngine(), max_bytes=16)
        body = build_multipart(
            fields={"language": "ru"},
            files={"file": ("audio.wav", WAV, "audio/wav")},
            boundary="B",
        )
        request = urllib.request.Request(
            url + "/v1/audio/transcriptions",
            data=body,
            headers={"Content-Type": "multipart/form-data; boundary=B"},
            method="POST",
        )
        self.assert_http_error(413, request)

    def test_loading_gives_503(self) -> None:
        url = self.start(FakeEngine(loading=True))
        body = build_multipart(
            fields={"language": "ru"},
            files={"file": ("audio.wav", WAV, "audio/wav")},
            boundary="B",
        )
        request = urllib.request.Request(
            url + "/v1/audio/transcriptions",
            data=body,
            headers={"Content-Type": "multipart/form-data; boundary=B"},
            method="POST",
        )
        error = self.assert_http_error(503, request)
        self.assertEqual(error.headers.get("Retry-After"), "2")


if __name__ == "__main__":
    unittest.main()
