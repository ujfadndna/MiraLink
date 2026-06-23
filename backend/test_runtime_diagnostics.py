from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import asr as asr_module
from app.services import tts as tts_module
from app.services import warmup as warmup_module


def _fresh_runtime_settings(env_overrides: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("TTS_BACKEND", None)
    env.pop("INDEXTTS_API_URL", None)
    env.pop("ASR_BACKEND", None)
    env.pop("CLOUD_ASR_API_URL", None)
    if env_overrides:
        env.update(env_overrides)

    code = (
        "import json; "
        "import app.main; "
        "from app.config import settings; "
        "print(json.dumps({"
        "'tts_backend': settings.tts_backend, "
        "'indextts_api_url': settings.indextts_api_url, "
        "'asr_backend': settings.asr_backend, "
        "'cloud_asr_api_url': settings.cloud_asr_api_url"
        "}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).parent,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_backend_env_file_provides_demo_tts_backend():
    runtime = _fresh_runtime_settings()

    assert runtime["tts_backend"] == "indextts"
    assert runtime["indextts_api_url"] == "http://127.0.0.1:9001"
    assert runtime["asr_backend"] == "mock"


def test_process_env_overrides_backend_env_file():
    runtime = _fresh_runtime_settings({
        "TTS_BACKEND": "indextts",
        "INDEXTTS_API_URL": "http://127.0.0.1:9001",
        "ASR_BACKEND": "cloud_whisper",
        "CLOUD_ASR_API_URL": "http://127.0.0.1:9002",
    })

    assert runtime == {
        "tts_backend": "indextts",
        "indextts_api_url": "http://127.0.0.1:9001",
        "asr_backend": "cloud_whisper",
        "cloud_asr_api_url": "http://127.0.0.1:9002",
    }


def test_runtime_diagnostics_hides_stale_asr_result_from_other_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "asr_backend", "mock")
    monkeypatch.setattr(settings, "cloud_asr_api_url", "")
    monkeypatch.setattr(settings, "workspace_dir", tmp_path)
    monkeypatch.setattr(tts_module._RUNTIME_STATUS, "last_elapsed_ms", None)
    monkeypatch.setattr(tts_module._RUNTIME_STATUS, "last_backend", "")
    monkeypatch.setattr(warmup_module._STATUS, "enabled", False)
    monkeypatch.setattr(warmup_module._STATUS, "status", "disabled")
    monkeypatch.setattr(warmup_module._STATUS, "started_at", None)
    monkeypatch.setattr(warmup_module._STATUS, "finished_at", None)
    warmup_module._STATUS.errors.clear()
    warmup_module._STATUS.steps.clear()
    monkeypatch.setattr(asr_module._RUNTIME_STATUS, "last_text", "今天晚饭吃什么")
    monkeypatch.setattr(asr_module._RUNTIME_STATUS, "last_elapsed_ms", 42.0)
    monkeypatch.setattr(asr_module._RUNTIME_STATUS, "last_backend", "cloud_whisper")
    monkeypatch.setattr(tts_module._RUNTIME_STATUS, "last_elapsed_ms", 123.4567)
    monkeypatch.setattr(tts_module._RUNTIME_STATUS, "last_backend", "mock")
    monkeypatch.setattr(warmup_module._STATUS, "enabled", True)
    monkeypatch.setattr(warmup_module._STATUS, "status", "complete")
    monkeypatch.setattr(warmup_module._STATUS, "started_at", "2026-06-23T00:00:00+00:00")
    monkeypatch.setattr(warmup_module._STATUS, "finished_at", "2026-06-23T00:00:01+00:00")
    warmup_module._STATUS.errors.clear()
    warmup_module._STATUS.steps.clear()

    response = TestClient(app).get("/api/v1/diagnostics/runtime")
    assert response.status_code == 200
    payload = response.json()

    assert payload["asr_backend"] == "mock"
    assert payload["last_asr_text_tail"] == ""
    assert payload["last_asr_elapsed_ms"] is None
    assert payload["last_asr_backend"] == ""
    assert payload["last_tts_elapsed_ms"] == 123.457
    assert payload["last_tts_backend"] == "mock"
    assert payload["warmup_enabled"] is True
    assert payload["warmup_status"] == "complete"
    assert payload["warmup_errors"] == []


def test_runtime_diagnostics_mock_mode_has_no_sensitive_config(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "tts_backend", "mock")
    monkeypatch.setattr(settings, "tts_sample_rate", 24000)
    monkeypatch.setattr(settings, "indextts_api_url", "")
    monkeypatch.setattr(settings, "asr_backend", "mock")
    monkeypatch.setattr(settings, "cloud_asr_api_url", "")
    monkeypatch.setattr(settings, "workspace_dir", tmp_path)
    monkeypatch.setattr(tts_module._RUNTIME_STATUS, "last_elapsed_ms", None)
    monkeypatch.setattr(tts_module._RUNTIME_STATUS, "last_backend", "")
    monkeypatch.setattr(warmup_module._STATUS, "enabled", False)
    monkeypatch.setattr(warmup_module._STATUS, "status", "disabled")
    monkeypatch.setattr(warmup_module._STATUS, "started_at", None)
    monkeypatch.setattr(warmup_module._STATUS, "finished_at", None)
    warmup_module._STATUS.errors.clear()
    warmup_module._STATUS.steps.clear()

    wav_dir = tmp_path / "audio" / "aud_mocktest"
    wav_dir.mkdir(parents=True)
    sample_rate = 24000
    duration_sec = 0.5
    t = np.arange(int(sample_rate * duration_sec), dtype=np.float32) / sample_rate
    waveform = (0.02 * np.sin(2.0 * math.pi * 220.0 * t)).astype(np.float32)
    sf.write(str(wav_dir / "tts.wav"), waveform, sample_rate)

    response = TestClient(app).get("/api/v1/diagnostics/runtime")
    assert response.status_code == 200
    payload = response.json()

    assert payload["tts_backend"] == "mock"
    assert payload["tts_sample_rate"] == 24000
    assert payload["indextts_api_configured"] is False
    assert payload["indextts_http_timeout_sec"] == 240.0
    assert payload["asr_backend"] == "mock"
    assert payload["cloud_asr_configured"] is False
    assert payload["call_barge_in_enabled"] is False
    assert payload["last_asr_text_tail"] == ""
    assert payload["last_asr_elapsed_ms"] is None
    assert payload["last_asr_backend"] == ""
    assert payload["last_tts_elapsed_ms"] is None
    assert payload["last_tts_backend"] == ""
    assert payload["warmup_enabled"] is False
    assert payload["warmup_status"] == "disabled"
    assert payload["warmup_errors"] == []
    assert payload["recent_tts_wavs"][0]["path_tail"] == "audio/aud_mocktest/tts.wav"
    assert payload["recent_tts_wavs"][0]["sample_rate"] == 24000
    assert payload["recent_tts_wavs"][0]["suspected_mock_tone"] is True

    serialized = json.dumps(payload, ensure_ascii=False).lower()
    assert "api_key" not in serialized
    assert "password" not in serialized
    assert "secret" not in serialized
    assert "sk-" not in serialized
    assert "127.0.0.1:9001" not in serialized


def test_runtime_diagnostics_indextts_mode_reports_configuration_flag(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "tts_backend", "indextts")
    monkeypatch.setattr(settings, "indextts_api_url", "http://127.0.0.1:9001")
    monkeypatch.setattr(settings, "asr_backend", "cloud_whisper")
    monkeypatch.setattr(settings, "cloud_asr_api_url", "http://127.0.0.1:9002")
    monkeypatch.setattr(settings, "workspace_dir", tmp_path)
    monkeypatch.setattr(tts_module._RUNTIME_STATUS, "last_elapsed_ms", 789.1)
    monkeypatch.setattr(tts_module._RUNTIME_STATUS, "last_backend", "indextts")
    monkeypatch.setattr(warmup_module._STATUS, "enabled", True)
    monkeypatch.setattr(warmup_module._STATUS, "status", "running")
    monkeypatch.setattr(warmup_module._STATUS, "started_at", "2026-06-23T00:00:00+00:00")
    monkeypatch.setattr(warmup_module._STATUS, "finished_at", None)
    warmup_module._STATUS.errors.clear()
    warmup_module._STATUS.steps.clear()
    warmup_module._STATUS.steps["tts"] = "ok"

    response = TestClient(app).get("/api/v1/diagnostics/runtime")
    assert response.status_code == 200
    payload = response.json()

    assert payload["tts_backend"] == "indextts"
    assert payload["indextts_api_configured"] is True
    assert payload["indextts_http_timeout_sec"] == 240.0
    assert payload["asr_backend"] == "cloud_whisper"
    assert payload["cloud_asr_configured"] is True
    assert "call_barge_in_enabled" in payload
    assert payload["last_tts_elapsed_ms"] == 789.1
    assert payload["last_tts_backend"] == "indextts"
    assert payload["warmup_enabled"] is True
    assert payload["warmup_status"] == "running"
    assert payload["warmup_steps"] == {"tts": "ok"}
    assert payload["recent_tts_wavs"] == []
    assert "indextts_api_url" not in payload
    assert "cloud_asr_api_url" not in payload

    serialized = json.dumps(payload, ensure_ascii=False).lower()
    assert "127.0.0.1:9001" not in serialized
    assert "127.0.0.1:9002" not in serialized
