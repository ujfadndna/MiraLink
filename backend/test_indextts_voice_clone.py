from __future__ import annotations

import json
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

from app.config import settings
from app.schemas import SynthesizeRequest
from app.services.tts import IndexTTS2Backend


def test_indextts_request_contract_and_wav_download(monkeypatch, tmp_path):
    output_wav = tmp_path / "out.wav"
    sf.write(str(output_wav), np.zeros(4800, dtype=np.float32), 24000)

    monkeypatch.setattr(settings, "indextts_api_url", "http://tts.local")
    monkeypatch.setattr(settings, "indextts_http_timeout_sec", 123.0)
    monkeypatch.setattr(settings, "workspace_dir", tmp_path / "workspace")

    requests: list[dict] = []
    timeouts: list[object] = []

    def post_handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://tts.local/tts"
        requests.append(json.loads(request.read()))
        return httpx.Response(200, json={"audio_url": "http://tts.local/files/out.wav", "phoneme_intervals": []})

    def get_handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://tts.local/files/out.wav"
        return httpx.Response(200, content=Path(output_wav).read_bytes())

    post_client = httpx.Client(transport=httpx.MockTransport(post_handler))
    get_client = httpx.Client(transport=httpx.MockTransport(get_handler))
    def post(url, **kwargs):
        timeouts.append(("post", kwargs.get("timeout")))
        return post_client.post(url, **kwargs)

    def get(url, **kwargs):
        timeouts.append(("get", kwargs.get("timeout")))
        return get_client.get(url, **kwargs)

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "get", get)

    result = IndexTTS2Backend().run(SynthesizeRequest(text="你好", emotion="happy"))

    assert result.sample_rate == 24000
    assert result.duration_ms == 200.0
    assert Path(result.audio_path).read_bytes() == Path(output_wav).read_bytes()
    assert result.phoneme_fallback is True
    assert requests
    assert requests[0] == {
        "text": "你好",
        "language": "zh",
        "speaker_id": None,
        "emotion": "happy",
        "speed": 1.0,
    }
    assert timeouts == [("post", 123.0), ("get", 123.0)]
