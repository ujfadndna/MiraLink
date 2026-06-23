from __future__ import annotations

import importlib
import io

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient


def _wav_bytes() -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(1600, dtype=np.float32), 16000, format="WAV")
    return buffer.getvalue()


def test_health_is_lightweight(monkeypatch):
    service = importlib.import_module("tools.whisper_asr_http_service")

    def fail_gpu_info():
        raise AssertionError("/health must not query GPU state")

    monkeypatch.setattr(service, "_gpu_info", fail_gpu_info)

    response = TestClient(service.app).get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "cuda_available" not in payload
    assert "loaded" in payload
    assert "last_asr_elapsed_ms" in payload
    assert "last_error" in payload
    assert "inference_count" in payload
    assert "started_at" in payload


def test_asr_runs_transcribe_in_worker_thread(monkeypatch):
    service = importlib.import_module("tools.whisper_asr_http_service")
    called = {}

    async def fake_to_thread(func, *args):
        called["func"] = func
        called["args"] = args
        return "你好", "zh"

    monkeypatch.setattr(service.asyncio, "to_thread", fake_to_thread)

    response = TestClient(service.app).post(
        "/asr",
        data={"language": "zh"},
        files={"file": ("audio.wav", _wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 200
    assert response.json()["text"] == "你好"
    assert called["func"] is service._transcribe_sync
    assert called["args"][1] == "zh"
