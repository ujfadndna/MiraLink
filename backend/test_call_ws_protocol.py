import base64
import json
import math
import time

import httpx
import numpy as np
import pytest
import soundfile as sf
from anyio import WouldBlock
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.main import app
from app.routers import call_ws as call_ws_module
from app.routers.ws import _avatar_ws_registry
from app.schemas import AgentResponse, AudioWithTimestamps, PhonemeInterval
from app.services.agent import MockAgent
from app.services.viseme import compute_viseme_curve


def _tone(ms: int, amplitude: float = 0.08, sample_rate: int = 16000) -> bytes:
    count = int(sample_rate * ms / 1000)
    t = np.arange(count, dtype=np.float32) / sample_rate
    wave = np.sin(2 * math.pi * 220 * t) * amplitude
    return np.clip(wave * 32767, -32768, 32767).astype(np.int16).tobytes()


def _silence(ms: int, sample_rate: int = 16000) -> bytes:
    return np.zeros(int(sample_rate * ms / 1000), dtype=np.int16).tobytes()


def _send_pcm_chunks(ws, pcm: bytes, chunk_ms: int = 20, sample_rate: int = 16000) -> None:
    chunk_bytes = int(sample_rate * chunk_ms / 1000) * 2
    for offset in range(0, len(pcm), chunk_bytes):
        ws.send_json({
            "type": "call.audio",
            "pcm_b64": base64.b64encode(pcm[offset : offset + chunk_bytes]).decode("ascii"),
        })


def _receive_until(ws, msg_type: str, timeout_sec: float = 8.0) -> dict:
    deadline = time.monotonic() + timeout_sec
    seen: list[dict] = []
    while True:
        try:
            message = ws.portal.call(ws._send_rx.receive_nowait)
        except WouldBlock:
            if time.monotonic() > deadline:
                raise AssertionError(f"timed out waiting for {msg_type}; seen={seen}")
            time.sleep(0.01)
            continue
        if message["type"] == "websocket.close":
            raise WebSocketDisconnect(message.get("code", 1000), message.get("reason", ""))
        if "text" not in message:
            raise KeyError(f"'text' not in websocket message: {message}")
        decoded = json.loads(message["text"])
        seen.append(decoded)
        if decoded.get("type") == msg_type:
            return decoded
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {msg_type}; seen={seen}")


def test_call_start_stop_protocol():
    client = TestClient(app)
    _avatar_ws_registry.clear()

    with client.websocket_connect("/ws/avatar") as avatar_ws:
        avatar_ws.send_json({
            "type": "session.start",
            "avatar_id": "vrm_female_001",
            "language": "zh",
        })
        avatar_started = avatar_ws.receive_json()
        avatar_ws.receive_json()

        with client.websocket_connect("/ws/call") as ws:
            ws.send_json({
                "type": "call.start",
                "avatar_id": "vrm_female_001",
                "language": "zh",
                "sample_rate": 16000,
            })

            started = ws.receive_json()
            assert started == {
                "type": "call.started",
                "session_id": avatar_started["session_id"],
            }

            state = ws.receive_json()
            assert state == {"type": "call.state", "state": "listening", "detail": ""}

            ws.send_json({"type": "call.stop"})
            stopped = ws.receive_json()
            assert stopped == {"type": "call.state", "state": "idle", "detail": "call stopped"}


def test_call_start_without_avatar_returns_recoverable_error(monkeypatch):
    monkeypatch.setattr(settings, "call_avatar_wait_sec", 0.0)
    client = TestClient(app)
    _avatar_ws_registry.clear()

    with client.websocket_connect("/ws/call") as ws:
        ws.send_json({
            "type": "call.start",
            "avatar_id": "vrm_female_001",
            "language": "zh",
            "sample_rate": 16000,
        })

        error = ws.receive_json()
        assert error == {
            "type": "call.error",
            "message": "avatar websocket is not active; wait for Unity to reconnect and start again",
            "recoverable": True,
        }
        state = ws.receive_json()
        assert state == {"type": "call.state", "state": "error", "detail": "avatar unavailable"}


def test_call_start_ignores_stale_requested_session_when_avatar_is_active():
    client = TestClient(app)
    _avatar_ws_registry.clear()

    with client.websocket_connect("/ws/avatar") as avatar_ws:
        avatar_ws.send_json({
            "type": "session.start",
            "avatar_id": "vrm_female_001",
            "language": "zh",
        })
        started = avatar_ws.receive_json()
        assert started["type"] == "session.started"
        active_session_id = started["session_id"]
        avatar_ws.receive_json()

        with client.websocket_connect("/ws/call") as call_ws:
            call_ws.send_json({
                "type": "call.start",
                "session_id": "sess_stale",
                "avatar_id": "vrm_female_001",
                "language": "zh",
                "sample_rate": 16000,
            })

            call_started = call_ws.receive_json()
            assert call_started == {
                "type": "call.started",
                "session_id": active_session_id,
            }

            call_state = call_ws.receive_json()
            assert call_state == {"type": "call.state", "state": "listening", "detail": ""}

            avatar_state = avatar_ws.receive_json()
            assert avatar_state == {"type": "state.change", "state": "listening", "detail": ""}


def test_avatar_ws_auto_starts_session_when_client_does_not_send_start(monkeypatch):
    monkeypatch.setattr(settings, "avatar_auto_start_session_sec", 0.0)
    client = TestClient(app)
    _avatar_ws_registry.clear()

    with client.websocket_connect("/ws/avatar") as avatar_ws:
        started = avatar_ws.receive_json()
        assert started["type"] == "session.started"
        assert started["session_id"].startswith("sess_")
        state = avatar_ws.receive_json()
        assert state == {"type": "state.change", "state": "idle", "detail": "会话已创建"}

        with client.websocket_connect("/ws/call") as call_ws:
            call_ws.send_json({
                "type": "call.start",
                "avatar_id": "vrm_female_001",
                "language": "zh",
                "sample_rate": 16000,
            })
            call_started = call_ws.receive_json()
            assert call_started == {
                "type": "call.started",
                "session_id": started["session_id"],
            }


def test_call_ws_cloud_asr_returns_remote_text_and_enters_response_flow(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "asr_backend", "cloud_whisper")
    monkeypatch.setattr(settings, "cloud_asr_api_url", "http://asr.local")
    monkeypatch.setattr(settings, "agent_backend", "mock")
    monkeypatch.setattr(settings, "tts_backend", "mock")
    monkeypatch.setattr(settings, "workspace_dir", tmp_path)
    mock_agent = MockAgent()
    monkeypatch.setattr(call_ws_module, "get_agent", lambda backend=None: mock_agent)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://asr.local/asr"
        request.read()
        return httpx.Response(200, json={"text": "今天晚饭吃什么", "language": "zh", "elapsed_ms": 9.5})

    monkeypatch.setattr(httpx, "post", httpx.Client(transport=httpx.MockTransport(handler)).post)

    client = TestClient(app)
    _avatar_ws_registry.clear()

    with client.websocket_connect("/ws/avatar") as avatar_ws:
        avatar_ws.send_json({
            "type": "session.start",
            "avatar_id": "vrm_female_001",
            "language": "zh",
        })
        avatar_started = avatar_ws.receive_json()
        avatar_ws.receive_json()

        with client.websocket_connect("/ws/call") as call_ws:
            call_ws.send_json({
                "type": "call.start",
                "session_id": avatar_started["session_id"],
                "avatar_id": "vrm_female_001",
                "language": "zh",
                "sample_rate": 16000,
            })
            assert call_ws.receive_json()["type"] == "call.started"
            assert call_ws.receive_json()["state"] == "listening"
            assert avatar_ws.receive_json()["state"] == "listening"

            _send_pcm_chunks(call_ws, _tone(620) + _silence(760))

            asr_final = _receive_until(call_ws, "asr.final")
            assert asr_final["text"] == "今天晚饭吃什么"

            thinking = _receive_until(call_ws, "call.state")
            assert thinking["state"] in {"thinking", "speaking"}
            if thinking["state"] == "thinking":
                speaking = _receive_until(call_ws, "call.state")
                assert speaking["state"] == "speaking"


def test_call_barge_in_disabled_by_default_does_not_cancel_speaking_response(monkeypatch):
    monkeypatch.setattr(settings, "call_barge_in_enabled", False)

    session = _FakeCallSession()

    chunk = base64.b64encode(_tone(320)).decode("ascii")

    call_ws_module.asyncio.run(call_ws_module._handle_call_audio(session, {
        "type": "call.audio",
        "pcm_b64": chunk,
    }))

    assert not any(message.get("type") == "turn.cancel" for message in session.sent)
    assert session.state == "speaking"
    assert session.utterance_task is None


def test_call_barge_in_disabled_ignores_full_utterance_during_speaking(monkeypatch):
    monkeypatch.setattr(settings, "call_barge_in_enabled", False)

    session = _FakeCallSession()

    _send_pcm_chunks_to_handler(session, _tone(620) + _silence(760))

    assert not any(message.get("type") == "turn.cancel" for message in session.sent)
    assert session.state == "speaking"
    assert session.utterance_task is None


def test_call_barge_in_can_be_enabled(monkeypatch):
    monkeypatch.setattr(settings, "call_barge_in_enabled", True)

    session = _FakeCallSession()

    chunk = base64.b64encode(_tone(320)).decode("ascii")

    call_ws_module.asyncio.run(call_ws_module._handle_call_audio(session, {
        "type": "call.audio",
        "pcm_b64": chunk,
    }))

    assert {"type": "turn.cancel", "turn_id": "turn_test", "reason": "barge_in"} in session.sent
    assert session.response_task.cancelled is True


def test_call_turn_start_includes_audio_length_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "tts_backend", "mock")
    monkeypatch.setattr(settings, "workspace_dir", tmp_path)
    monkeypatch.setattr(settings, "ws_chunk_duration_ms", 80)

    session = _FakeCallSession(state="listening", response_task=None)
    monkeypatch.setattr(call_ws_module, "append_turn", lambda *_args, **_kwargs: None)

    wav_path = tmp_path / "tts.wav"
    sample_rate = 24000
    sf.write(str(wav_path), np.zeros(sample_rate * 2, dtype=np.float32), sample_rate)
    tts_result = AudioWithTimestamps(
        audio_id="aud_test",
        audio_path=str(wav_path),
        duration_ms=2000.0,
        sample_rate=sample_rate,
        phoneme_intervals=[],
        phoneme_fallback=True,
    )
    monkeypatch.setattr(call_ws_module, "run_tts", lambda _req: tts_result)

    call_ws_module.asyncio.run(call_ws_module._speak_response(
        session,
        "你好",
        AgentResponse(reply_text="你好", emotion="happy", dialogue_act="greet"),
    ))

    start = next(message for message in session.sent if message.get("type") == "turn.start")
    assert start["duration_ms"] == pytest.approx(2000.0)
    assert start["sample_rate"] == sample_rate
    assert start["total_samples"] == sample_rate * 2

    phone_start = next(message for message in session.phone_sent if message.get("type") == "call.audio.start")
    phone_chunks = [message for message in session.phone_sent if message.get("type") == "call.audio.chunk"]
    phone_end = next(message for message in session.phone_sent if message.get("type") == "call.audio.end")
    assert phone_start["turn_id"] == start["turn_id"]
    assert phone_start["sample_rate"] == sample_rate
    assert phone_start["total_samples"] == sample_rate * 2
    assert phone_chunks
    assert phone_chunks[0]["sample_rate"] == sample_rate
    assert phone_chunks[0]["base64"]
    assert phone_end["turn_id"] == start["turn_id"]

    animation_packets = [message for message in session.sent if message.get("type") == "animation.packet"]
    assert animation_packets
    assert any(packet["blendshapes"] for packet in animation_packets)
    assert any(
        any(weight > 0 for weight in packet["blendshapes"].values())
        for packet in animation_packets
    )


def test_phoneme_fallback_viseme_produces_nonzero_blendshapes():
    tts_result = AudioWithTimestamps(
        audio_id="aud_fallback",
        audio_path="unused.wav",
        duration_ms=240.0,
        sample_rate=24000,
        phoneme_intervals=[
            PhonemeInterval(phoneme="你", start_ms=0.0, end_ms=120.0),
            PhonemeInterval(phoneme="好", start_ms=120.0, end_ms=240.0),
        ],
        phoneme_fallback=True,
    )

    curve = compute_viseme_curve(tts_result)

    assert curve.frames
    assert any(frame.weights for frame in curve.frames)
    assert any(
        any(weight > 0 for weight in frame.weights.values())
        for frame in curve.frames
    )


def test_chinese_fallback_viseme_uses_distinct_mouth_channels(monkeypatch):
    monkeypatch.setattr(settings, "ws_chunk_duration_ms", 80)
    monkeypatch.setattr(settings, "viseme_smooth_window_ms", 0)
    tts_result = AudioWithTimestamps(
        audio_id="aud_viseme",
        audio_path="unused.wav",
        duration_ms=400.0,
        sample_rate=24000,
        phoneme_intervals=[
            PhonemeInterval(phoneme="你", start_ms=0.0, end_ms=80.0),
            PhonemeInterval(phoneme="好", start_ms=80.0, end_ms=160.0),
            PhonemeInterval(phoneme="我", start_ms=160.0, end_ms=240.0),
            PhonemeInterval(phoneme="不", start_ms=240.0, end_ms=320.0),
            PhonemeInterval(phoneme="饿", start_ms=320.0, end_ms=400.0),
        ],
        phoneme_fallback=True,
    )

    curve = compute_viseme_curve(tts_result)
    frames = curve.frames[:5]

    assert frames[0].weights["lip_i"] > frames[0].weights["lip_a"]
    assert frames[1].weights["lip_a"] > frames[1].weights["lip_i"]
    assert frames[2].weights["lip_o"] > 0
    assert frames[3].weights["lip_w"] > 0 or frames[3].weights["lip_u"] > 0
    assert frames[4].weights["lip_e"] > 0
    assert len({max(frame.weights, key=frame.weights.get) for frame in frames}) >= 4


def test_punctuation_viseme_is_silence_and_frames_are_complete(monkeypatch):
    monkeypatch.setattr(settings, "ws_chunk_duration_ms", 80)
    monkeypatch.setattr(settings, "viseme_smooth_window_ms", 40)
    tts_result = AudioWithTimestamps(
        audio_id="aud_pause",
        audio_path="unused.wav",
        duration_ms=240.0,
        sample_rate=24000,
        phoneme_intervals=[
            PhonemeInterval(phoneme="你", start_ms=0.0, end_ms=80.0),
            PhonemeInterval(phoneme="，", start_ms=80.0, end_ms=160.0),
            PhonemeInterval(phoneme="好", start_ms=160.0, end_ms=240.0),
        ],
        phoneme_fallback=True,
    )

    curve = compute_viseme_curve(tts_result)
    expected_channels = {"mouse_open", "lip_a", "lip_i", "lip_u", "lip_w", "lip_e", "lip_o"}

    assert curve.frames
    assert all(set(frame.weights) == expected_channels for frame in curve.frames)
    pause = next(frame for frame in curve.frames if frame.start_ms == 80.0)
    assert all(weight == 0 for weight in pause.weights.values())


def test_quick_call_response_short_greeting():
    response = call_ws_module._quick_call_response("你好")

    assert response is not None
    assert response.dialogue_act == "greet"
    assert response.emotion == "happy"
    assert len(response.reply_text) <= 40


def test_compact_call_reply_limits_long_text():
    text = "这是第一句很短的话。第二句会很长很长很长很长很长很长很长很长很长。"

    assert call_ws_module._compact_call_reply(text, 20) == "这是第一句很短的话。"
    assert len(call_ws_module._compact_call_reply("没有标点但是非常非常非常非常非常长的一句话", 12)) <= 13


class _PendingTask:
    def __init__(self) -> None:
        self.cancelled = False

    def done(self) -> bool:
        return False

    def cancel(self) -> None:
        self.cancelled = True


class _FakeCallSession:
    def __init__(self, state: str = "speaking", response_task: _PendingTask | None = None) -> None:
        self.session_id = "sess_test"
        self.language = "zh"
        self.state = state
        self.current_turn_id = "turn_test"
        self.response_task = _PendingTask() if response_task is None else response_task
        self.utterance_task = None
        self.vad = call_ws_module.RmsVadBuffer(sample_rate=16000)
        self.sent: list[dict] = []
        self.phone_sent: list[dict] = []

    def avatar_ws(self):
        return object()

    async def send_phone(self, payload: dict) -> None:
        self.phone_sent.append(payload)

    async def send_error(self, message: str, recoverable: bool = True) -> None:
        self.sent.append({"type": "call.error", "message": message, "recoverable": recoverable})

    async def send_avatar(self, payload: dict) -> None:
        self.sent.append(payload)

    async def set_state(self, state: str, detail: str = "") -> None:
        self.state = state
        self.sent.append({"type": "call.state", "state": state, "detail": detail})

    async def cancel_response(self, reason: str = "barge_in") -> None:
        task = self.response_task
        if task and not task.done():
            task.cancel()
        if self.current_turn_id:
            await self.send_avatar({"type": "turn.cancel", "turn_id": self.current_turn_id, "reason": reason})
        self.current_turn_id = ""
        await self.set_state("listening", "interrupted")


def _send_pcm_chunks_to_handler(session: _FakeCallSession, pcm: bytes, chunk_ms: int = 20) -> None:
    async def run() -> None:
        chunk_bytes = int(16000 * chunk_ms / 1000) * 2
        for offset in range(0, len(pcm), chunk_bytes):
            await call_ws_module._handle_call_audio(session, {
                "type": "call.audio",
                "pcm_b64": base64.b64encode(pcm[offset: offset + chunk_bytes]).decode("ascii"),
            })

    call_ws_module.asyncio.run(run())
