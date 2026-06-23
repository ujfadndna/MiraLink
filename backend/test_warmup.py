from __future__ import annotations

import asyncio

import httpx
import pytest

from app.config import settings
from app.schemas import SynthesizeRequest
from app.services import warmup


def _reset_warmup_status() -> None:
    warmup._STATUS.enabled = True
    warmup._STATUS.status = "pending"
    warmup._STATUS.started_at = None
    warmup._STATUS.finished_at = None
    warmup._STATUS.errors.clear()
    warmup._STATUS.steps.clear()


def test_cloud_asr_warmup_uses_health_until_loaded(monkeypatch):
    _reset_warmup_status()
    monkeypatch.setattr(settings, "asr_backend", "cloud_whisper")
    monkeypatch.setattr(settings, "cloud_asr_api_url", "http://asr.local")
    monkeypatch.setattr(settings, "warmup_timeout_sec", 2.0)

    calls: list[str] = []

    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def get(self, url: str) -> httpx.Response:
            calls.append(url)
            return httpx.Response(200, json={"loaded": True, "loading": False}, request=httpx.Request("GET", url))

    monkeypatch.setattr(warmup.httpx, "AsyncClient", FakeAsyncClient)

    asyncio.run(warmup._warmup_asr())

    assert calls == ["http://asr.local/health"]
    assert warmup._STATUS.steps["asr"] == "ok"
    assert warmup._STATUS.errors == []


def test_tts_warmup_invokes_configured_backend(monkeypatch):
    _reset_warmup_status()
    monkeypatch.setattr(settings, "tts_backend", "indextts")
    monkeypatch.setattr(settings, "warmup_text", "你好")
    seen: list[SynthesizeRequest] = []

    def fake_run_tts(req: SynthesizeRequest):
        seen.append(req)
        return object()

    monkeypatch.setattr(warmup, "run_tts", fake_run_tts)

    asyncio.run(warmup._warmup_tts())

    assert seen and seen[0].text == "你好"
    assert warmup._STATUS.steps["tts"] == "ok"
    assert warmup._STATUS.errors == []


def test_warmup_timeout_records_error(monkeypatch):
    _reset_warmup_status()
    monkeypatch.setattr(settings, "warmup_timeout_sec", 0.01)

    async def slow_warmup() -> None:
        await asyncio.sleep(1.0)

    monkeypatch.setattr(warmup, "_run_warmup", slow_warmup)

    asyncio.run(warmup._run_with_timeout())

    assert warmup._STATUS.status == "timeout"
    assert warmup._STATUS.finished_at
    assert any("timeout" in error for error in warmup._STATUS.errors)


def test_warmup_records_step_errors(monkeypatch):
    _reset_warmup_status()
    monkeypatch.setattr(settings, "tts_backend", "indextts")

    def failing_run_tts(_req: SynthesizeRequest):
        raise RuntimeError("boom")

    monkeypatch.setattr(warmup, "run_tts", failing_run_tts)

    asyncio.run(warmup._warmup_tts())

    assert warmup._STATUS.steps["tts"] == "error"
    assert any("tts warmup failed" in error and "boom" in error for error in warmup._STATUS.errors)
