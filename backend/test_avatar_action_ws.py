import json
import time

import numpy as np
import pytest
import soundfile as sf
from anyio import WouldBlock
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.main import app
from app.routers import call_ws as call_ws_module
from app.routers import ws as avatar_ws_module
from app.routers.ws import _avatar_ws_registry
from app.schemas import AgentResponse, AudioWithTimestamps


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
        decoded = json.loads(message["text"])
        seen.append(decoded)
        if decoded.get("type") == msg_type:
            return decoded


def _short_tts(tmp_path):
    wav_path = tmp_path / "tts.wav"
    sample_rate = 24000
    sf.write(str(wav_path), np.zeros(sample_rate // 4, dtype=np.float32), sample_rate)
    return AudioWithTimestamps(
        audio_id="aud_test",
        audio_path=str(wav_path),
        duration_ms=250.0,
        sample_rate=sample_rate,
        phoneme_intervals=[],
        phoneme_fallback=True,
    )


def test_avatar_ws_happy_action_turn_start(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "workspace_dir", tmp_path)
    monkeypatch.setattr(avatar_ws_module, "run_tts", lambda _req: _short_tts(tmp_path))
    client = TestClient(app)
    _avatar_ws_registry.clear()

    with client.websocket_connect("/ws/avatar") as ws:
        ws.send_json({"type": "session.start", "avatar_id": "vrm_female_001", "language": "zh"})
        started = ws.receive_json()
        ws.receive_json()
        ws.send_json({
            "type": "turn.submit_text",
            "session_id": started["session_id"],
            "text": "做一个开心的表情",
        })

        turn_start = _receive_until(ws, "turn.start")
        assert turn_start["emotion"] == "happy"
        assert turn_start["dialogue_act"] == "avatar_action"
        assert turn_start["avatar_action"]["emotion"] == "happy"

        audio = _receive_until(ws, "audio.chunk")
        assert audio["base64"]


def test_avatar_ws_wave_action_adds_gesture_event(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "workspace_dir", tmp_path)
    monkeypatch.setattr(avatar_ws_module, "run_tts", lambda _req: _short_tts(tmp_path))
    client = TestClient(app)
    _avatar_ws_registry.clear()

    with client.websocket_connect("/ws/avatar") as ws:
        ws.send_json({"type": "session.start", "avatar_id": "vrm_female_001", "language": "zh"})
        started = ws.receive_json()
        ws.receive_json()
        ws.send_json({
            "type": "turn.submit_text",
            "session_id": started["session_id"],
            "text": "挥挥手",
        })

        turn_start = _receive_until(ws, "turn.start")
        assert turn_start["avatar_action"]["gesture"] == "gesture_greet"
        assert any(event["gesture_name"] == "gesture_greet" for event in turn_start["gesture_events"])


def test_call_speak_response_tts_failure_recovers(monkeypatch):
    session = _FakeCallSession()
    monkeypatch.setattr(call_ws_module, "run_tts", lambda _req: (_ for _ in ()).throw(RuntimeError("tts down")))

    call_ws_module.asyncio.run(call_ws_module._speak_response(
        session,
        "你好",
        AgentResponse(reply_text="你好", emotion="happy", dialogue_act="greet"),
    ))

    assert {"type": "call.error", "message": "TTS failed: tts down", "recoverable": True} in session.phone_sent
    assert {"type": "call.state", "state": "listening", "detail": "recovered"} in session.sent
    assert not any(message.get("type") == "audio.chunk" for message in session.sent)


class _FakeCallSession:
    def __init__(self) -> None:
        self.session_id = "sess_test"
        self.language = "zh"
        self.state = "listening"
        self.current_turn_id = ""
        self.sent: list[dict] = []
        self.phone_sent: list[dict] = []

    def avatar_ws(self):
        return object()

    async def send_phone(self, payload: dict) -> None:
        self.phone_sent.append(payload)

    async def send_error(self, message: str, recoverable: bool = True) -> None:
        self.phone_sent.append({"type": "call.error", "message": message, "recoverable": recoverable})

    async def send_avatar(self, payload: dict) -> None:
        self.sent.append(payload)

    async def set_state(self, state: str, detail: str = "") -> None:
        self.state = state
        self.sent.append({"type": "call.state", "state": state, "detail": detail})
