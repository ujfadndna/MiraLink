from __future__ import annotations

import httpx
import pytest

from app.config import settings
from app.services.asr import CloudWhisperAsr


def test_cloud_whisper_transcribe_returns_text(monkeypatch):
    monkeypatch.setattr(settings, "cloud_asr_api_url", "http://asr.local")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "http://asr.local/asr"
        content_type = request.headers["content-type"]
        assert "multipart/form-data" in content_type
        body = request.read()
        assert b'name="language"' in body
        assert b"zh" in body
        assert b'name="file"; filename="audio.wav"' in body
        return httpx.Response(200, json={"text": "今天天气怎么样", "language": "zh", "elapsed_ms": 12.3})

    monkeypatch.setattr(httpx, "post", httpx.Client(transport=httpx.MockTransport(handler)).post)

    text = CloudWhisperAsr().transcribe(b"\x00\x00" * 1600, 16000, "zh")

    assert text == "今天天气怎么样"


def test_cloud_whisper_requires_api_url(monkeypatch):
    monkeypatch.setattr(settings, "cloud_asr_api_url", "")

    with pytest.raises(RuntimeError, match="CLOUD_ASR_API_URL is not configured"):
        CloudWhisperAsr().transcribe(b"\x00\x00" * 1600, 16000, "zh")


def test_cloud_whisper_reports_http_failure(monkeypatch):
    monkeypatch.setattr(settings, "cloud_asr_api_url", "http://asr.local")
    monkeypatch.setattr(
        httpx,
        "post",
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500, text="boom"))).post,
    )

    with pytest.raises(RuntimeError, match="Cloud Whisper ASR HTTP failed: status=500"):
        CloudWhisperAsr().transcribe(b"\x00\x00" * 1600, 16000, "zh")


def test_cloud_whisper_reports_missing_text(monkeypatch):
    monkeypatch.setattr(settings, "cloud_asr_api_url", "http://asr.local")
    monkeypatch.setattr(
        httpx,
        "post",
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"language": "zh"}))).post,
    )

    with pytest.raises(RuntimeError, match="missing required field 'text'"):
        CloudWhisperAsr().transcribe(b"\x00\x00" * 1600, 16000, "zh")


def test_cloud_whisper_reports_empty_text(monkeypatch):
    monkeypatch.setattr(settings, "cloud_asr_api_url", "http://asr.local")
    monkeypatch.setattr(
        httpx,
        "post",
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"text": "  "}))).post,
    )

    with pytest.raises(RuntimeError, match="returned empty text"):
        CloudWhisperAsr().transcribe(b"\x00\x00" * 1600, 16000, "zh")
