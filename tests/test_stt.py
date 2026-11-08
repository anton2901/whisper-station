"""Тесты HTTP-клиента: multipart, ответы сервера, ошибки и ретраи."""

from __future__ import annotations

import http.server
import threading
import unittest

from whisper_station.config import Config
from whisper_station.recorder import pcm_to_wav
from whisper_station.stt import SttError, ServerUnavailable, build_multipart, transcribe

WAV = pcm_to_wav(b"\x00\x00" * 1600)


class _Handler(http.server.BaseHTTPRequestHandler):
    status = 200
    body = b'{"text": "\xd0\xbf\xd1\x80\xd0\xb8\xd0\xb2\xd0\xb5\xd1\x82"}'
    calls = 0

    def do_POST(self) -> None:  # noqa: N802 - API http.server
        type(self).calls += 1
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(type(self).body)))
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, *args: object) -> None:
        pass


class SttTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        _Handler.status = 200
        _Handler.body = b'{"text": "\xd0\xbf\xd1\x80\xd0\xb8\xd0\xb2\xd0\xb5\xd1\x82"}'
        _Handler.calls = 0

    def cfg(self) -> Config:
        return Config(server_url=self.url, language="ru")

    def test_transcribes_json(self) -> None:
        result = transcribe(WAV, self.cfg())
        self.assertEqual(result.text, "привет")
        self.assertGreaterEqual(result.elapsed_ms, 0)

    def test_plain_text_response(self) -> None:
        _Handler.body = "просто текст".encode()
        self.assertEqual(transcribe(WAV, self.cfg()).text, "просто текст")

    def test_empty_body_gives_empty_text(self) -> None:
        _Handler.body = b""
        self.assertEqual(transcribe(WAV, self.cfg()).text, "")

    def test_http_500_raises_stt_error(self) -> None:
        _Handler.status = 500
        _Handler.body = b"boom"
        with self.assertRaises(SttError) as ctx:
            transcribe(WAV, self.cfg())
        self.assertIn("500", str(ctx.exception))

    def test_5xx_is_retried_once(self) -> None:
        _Handler.status = 503
        with self.assertRaises(SttError):
            transcribe(WAV, self.cfg(), retries=1)
        self.assertEqual(_Handler.calls, 2)

    def test_4xx_is_not_retried(self) -> None:
        _Handler.status = 400
        with self.assertRaises(SttError):
            transcribe(WAV, self.cfg(), retries=1)
        self.assertEqual(_Handler.calls, 1)

    def test_non_loopback_is_refused(self) -> None:
        cfg = Config(server_url="http://example.com:8765")
        with self.assertRaises(SttError):
            transcribe(WAV, cfg)
        self.assertEqual(_Handler.calls, 0)

    def test_connection_refused_is_server_unavailable(self) -> None:
        cfg = Config(server_url="http://127.0.0.1:9")
        with self.assertRaises(ServerUnavailable):
            transcribe(WAV, cfg, retries=0)


class MultipartTest(unittest.TestCase):
    def test_structure(self) -> None:
        body = build_multipart(
            {"language": "ru"},
            {"file": ("a.wav", b"RIFFdata", "audio/wav")},
            "BOUND",
        )
        self.assertIn(b"--BOUND\r\n", body)
        self.assertIn(b'name="language"', body)
        self.assertIn(b"ru", body)
        self.assertIn(b'filename="a.wav"', body)
        self.assertIn(b"Content-Type: audio/wav", body)
        self.assertIn(b"RIFFdata", body)
        self.assertTrue(body.endswith(b"--BOUND--\r\n"))

    def test_empty_parts(self) -> None:
        body = build_multipart({}, {}, "B")
        self.assertEqual(body, b"--B--\r\n")


if __name__ == "__main__":
    unittest.main()
