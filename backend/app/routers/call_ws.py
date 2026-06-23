"""Continuous mobile call WebSocket: /ws/call."""
from __future__ import annotations

import asyncio
import base64
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import soundfile as sf
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import storage
from app.config import settings
from app.routers.sensor_clients import latest_avatar_session_id
from app.routers.sessions import append_turn, get_or_create_session
from app.routers.ws import _avatar_ws_registry, active_avatar_session_id
from app.schemas import AgentResponse, SynthesizeRequest
from app.services.agent import get_agent
from app.services.avatar_intent import (
    action_ack_text,
    apply_avatar_action,
    avatar_action_gesture_event,
    parse_avatar_action_intent,
)
from app.services.call_vad import RmsVadBuffer, VadEvent
from app.services.gesture import compute_gesture_events
from app.services.memory import get_memory
from app.services.tts import run_tts
from app.services.tts_async import run_tts_async
from app.services.viseme import compute_viseme_curve
from app.services.asr import transcribe_async

router = APIRouter()
_logger = logging.getLogger(__name__)

_CALL_SAMPLE_RATE = 16000
_BARGE_IN_MS = 300.0
_AVATAR_WAIT_POLL_SEC = 0.1


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _wait_for_active_avatar_session(timeout_sec: float) -> str:
    deadline = asyncio.get_running_loop().time() + max(0.0, timeout_sec)
    while True:
        session_id = active_avatar_session_id()
        if session_id:
            return session_id
        if asyncio.get_running_loop().time() >= deadline:
            return ""
        await asyncio.sleep(_AVATAR_WAIT_POLL_SEC)


async def _send_phone_optional(session: "CallSession", payload: dict) -> None:
    try:
        await session.send_phone(payload)
    except Exception as exc:
        _logger.debug(
            "failed to send optional phone payload: session=%s type=%s error=%s",
            session.session_id,
            payload.get("type"),
            exc,
        )


@dataclass(slots=True)
class CallSession:
    phone_ws: WebSocket
    session_id: str = ""
    avatar_id: str = "vrm_female_001"
    language: str = "zh"
    state: str = "idle"
    vad: RmsVadBuffer = field(default_factory=lambda: RmsVadBuffer(sample_rate=_CALL_SAMPLE_RATE))
    response_task: asyncio.Task | None = None
    utterance_task: asyncio.Task | None = None
    current_turn_id: str = ""
    phone_send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    avatar_send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send_phone(self, payload: dict) -> None:
        async with self.phone_send_lock:
            await self.phone_ws.send_json(payload)

    async def set_state(self, state: str, detail: str = "") -> None:
        self.state = state
        await self.send_phone({"type": "call.state", "state": state, "detail": detail})
        avatar_ws = self.avatar_ws()
        if avatar_ws is not None:
            try:
                async with self.avatar_send_lock:
                    await avatar_ws.send_json({"type": "state.change", "state": state, "detail": detail})
            except Exception as exc:
                _logger.debug("failed to forward call state to avatar: session=%s error=%s", self.session_id, exc)

    async def send_error(self, message: str, recoverable: bool = True) -> None:
        _logger.warning("call error: session=%s recoverable=%s message=%s", self.session_id, recoverable, message)
        await self.send_phone({"type": "call.error", "message": message, "recoverable": recoverable})

    def avatar_ws(self) -> WebSocket | None:
        return _avatar_ws_registry.get(self.session_id)

    async def send_avatar(self, payload: dict) -> None:
        avatar_ws = self.avatar_ws()
        if avatar_ws is None:
            raise RuntimeError(f"no avatar websocket for session {self.session_id}")
        async with self.avatar_send_lock:
            await avatar_ws.send_json(payload)

    async def cancel_response(self, reason: str = "barge_in") -> None:
        turn_id = self.current_turn_id
        task = self.response_task
        if task and not task.done():
            task.cancel()
        if turn_id:
            try:
                await self.send_avatar({"type": "turn.cancel", "turn_id": turn_id, "reason": reason})
            except Exception as exc:
                _logger.warning("failed to send turn.cancel: session=%s turn=%s error=%s", self.session_id, turn_id, exc)
        self.current_turn_id = ""
        await self.set_state("listening", "interrupted")

    async def close(self) -> None:
        for task in (self.response_task, self.utterance_task):
            if task and not task.done():
                task.cancel()
        if self.current_turn_id:
            try:
                await self.send_avatar({"type": "turn.cancel", "turn_id": self.current_turn_id, "reason": "call_closed"})
            except Exception:
                pass


@router.websocket("/ws/call")
async def call_ws(ws: WebSocket):
    await ws.accept()
    session = CallSession(phone_ws=ws)
    _logger.info("call WebSocket connected")

    try:
        while True:
            data = await ws.receive_json()
            msg_type = str(data.get("type", ""))

            if msg_type == "call.start":
                await _handle_call_start(session, data)
            elif msg_type == "call.audio":
                await _handle_call_audio(session, data)
            elif msg_type == "call.interrupt":
                await session.cancel_response(str(data.get("reason") or "client_interrupt"))
            elif msg_type == "call.stop":
                await session.close()
                session.vad.reset()
                await session.set_state("idle", "call stopped")
                break
            else:
                await session.send_error(f"unknown type: {msg_type}", recoverable=True)

    except WebSocketDisconnect:
        _logger.info("call WebSocket disconnected")
    except Exception as exc:
        _logger.exception("call WebSocket error")
        try:
            await session.send_error(str(exc), recoverable=False)
        except Exception:
            pass
    finally:
        await session.close()


async def _handle_call_start(session: CallSession, data: dict) -> None:
    sample_rate = int(data.get("sample_rate") or _CALL_SAMPLE_RATE)
    if sample_rate != _CALL_SAMPLE_RATE:
        await session.send_error("call.audio only accepts PCM int16 mono 16kHz", recoverable=False)
        await session.set_state("error", "invalid sample rate")
        return

    requested_session = str(data.get("session_id") or "").strip()
    active_session = active_avatar_session_id()
    if requested_session and requested_session in _avatar_ws_registry:
        session.session_id = requested_session
    else:
        if not active_session:
            active_session = await _wait_for_active_avatar_session(settings.call_avatar_wait_sec)
        if requested_session:
            _logger.info(
                "call requested avatar session is not active; using active session instead: requested=%s active=%s",
                requested_session,
                active_session or "<none>",
            )
        if not active_session:
            await session.send_error("avatar websocket is not active; wait for Unity to reconnect and start again", recoverable=True)
            await session.set_state("error", "avatar unavailable")
            return
        session.session_id = active_session
    session.avatar_id = str(data.get("avatar_id") or "vrm_female_001")
    session.language = str(data.get("language") or "zh")
    session.current_turn_id = ""
    session.vad.reset()
    get_or_create_session(session.session_id, session.avatar_id, session.language)

    await session.send_phone({"type": "call.started", "session_id": session.session_id})
    await session.set_state("listening")
    _logger.info("call started: session=%s avatar=%s language=%s", session.session_id, session.avatar_id, session.language)


async def _handle_call_audio(session: CallSession, data: dict) -> None:
    if not session.session_id:
        await session.send_error("send call.start before call.audio", recoverable=True)
        return

    pcm_b64 = str(data.get("pcm_b64") or "")
    if not pcm_b64:
        await session.send_error("call.audio pcm_b64 is empty", recoverable=True)
        return

    try:
        pcm = base64.b64decode(pcm_b64, validate=True)
        if (
            not settings.call_barge_in_enabled
            and session.response_task
            and not session.response_task.done()
            and session.state == "speaking"
        ):
            session.vad.reset()
            return
        events = session.vad.accept_chunk(pcm)
    except Exception as exc:
        await session.send_error(f"invalid PCM chunk: {exc}", recoverable=True)
        return

    if (
        settings.call_barge_in_enabled
        and session.response_task
        and not session.response_task.done()
        and session.state == "speaking"
        and session.vad.current_voiced_ms >= _BARGE_IN_MS
    ):
        await session.cancel_response("barge_in")

    for event in events:
        if event.type == "speech_start":
            if session.state == "listening":
                await session.set_state("user_speaking")
        elif event.type == "speech_discarded":
            _logger.debug(
                "call VAD discarded: session=%s duration=%.1f speech=%.1f rms=%.4f",
                session.session_id,
                event.duration_ms,
                event.speech_ms,
                event.rms,
            )
            if session.state in {"user_speaking", "listening"}:
                await session.set_state("listening")
        elif event.type == "utterance":
            await _submit_utterance(session, event)


async def _submit_utterance(session: CallSession, event: VadEvent) -> None:
    if session.utterance_task and not session.utterance_task.done():
        _logger.info("call utterance dropped while previous utterance is processing: session=%s", session.session_id)
        return

    session.utterance_task = asyncio.create_task(_process_utterance(session, event.pcm))


async def _process_utterance(session: CallSession, pcm: bytes) -> None:
    try:
        await session.set_state("asr", "recognizing")
        text = await transcribe_async(pcm, _CALL_SAMPLE_RATE, session.language)
        await session.send_phone({"type": "asr.final", "text": text})
        if not text.strip():
            await session.set_state("listening", "empty asr")
            return

        await session.set_state("thinking", "agent")
        try:
            should_greet, greeting_text = get_memory().check_daily_greeting(session.session_id)
            if should_greet and greeting_text:
                _logger.info("daily greeting for call %s: %s", session.session_id, greeting_text)
        except Exception:
            pass

        response = await _generate_agent_response(text, session.session_id)
        await session.send_phone({
            "type": "llm.final",
            "text": response.reply_text,
            "emotion": response.emotion,
            "dialogue_act": response.dialogue_act,
        })

        if session.response_task and not session.response_task.done():
            await session.cancel_response("new_utterance")
        session.response_task = asyncio.create_task(_speak_response(session, text, response))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _logger.exception("call utterance failed")
        await session.send_error(str(exc), recoverable=True)
        await session.set_state("listening", "recovered")


async def _generate_agent_response(text: str, session_id: str) -> AgentResponse:
    avatar_action = parse_avatar_action_intent(text)
    if avatar_action is not None:
        response = AgentResponse(
            reply_text=action_ack_text(avatar_action),
            emotion=avatar_action.emotion or "neutral",
            dialogue_act="avatar_action",
            avatar_action=avatar_action,
        )
        try:
            get_memory().update_after_turn(session_id, text, response.reply_text, response.emotion)
        except Exception:
            pass
        return response

    quick = _quick_call_response(text)
    if quick is not None:
        return quick

    agent_text = text
    streak_before: int | None = None

    try:
        streak_before = get_memory().load(session_id).streak_days
    except Exception:
        pass

    try:
        should_push, gap_text = get_memory().check_gap_push(session_id)
        if should_push and gap_text:
            agent_text = f"【系统提示：{gap_text} 请自然融入回复，不要说明这是系统提示。】\n用户说：{text}"
    except Exception:
        pass

    agent = get_agent()
    try:
        response = await asyncio.wait_for(
            agent.generate(agent_text, session_id),
            timeout=max(0.1, settings.agent_response_timeout_sec),
        )
    except TimeoutError:
        raise RuntimeError(f"Agent timeout after {settings.agent_response_timeout_sec:.1f}s") from None
    except Exception as exc:
        _logger.warning("agent generate failed; falling back to mock: session=%s error=%s", session_id, exc)
        response = await get_agent("mock").generate(text, session_id)

    try:
        state = get_memory().load(session_id)
        unlock_text = get_memory().get_streak_unlock(state.streak_days)
        if unlock_text and state.streak_days != streak_before:
            response.reply_text = f"{response.reply_text}\n{unlock_text}"
    except Exception:
        pass

    response = apply_avatar_action(response, avatar_action)
    response.reply_text = _compact_call_reply(response.reply_text, settings.call_reply_max_chars)
    return response


def _quick_call_response(text: str) -> AgentResponse | None:
    normalized = re.sub(r"\s+", "", text or "").strip("，。！？,.!? ")
    if not normalized:
        return None

    if len(normalized) <= 12 and re.search(r"^(你好|您好|嗨|哈喽|hello|hi)$", normalized, re.IGNORECASE):
        return AgentResponse(
            reply_text="你好，我在。现在可以听见你说话，也可以继续和你对话。",
            emotion="happy",
            dialogue_act="greet",
        )

    if re.search(r"介绍一下你自己|你是谁|你叫什么|你是什么", normalized):
        return AgentResponse(
            reply_text="我是 MiraLink 数字人助手，可以语音对话、做口型同步，也能在 Unity 里显示表情和动作。",
            emotion="happy",
            dialogue_act="self_intro",
        )

    return None


def _compact_call_reply(text: str, max_chars: int) -> str:
    cleaned = re.sub(r"\s*\[EMOTION:\s*\w+\]\s*", "", text or "", flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\[ACT:\s*\w+\]\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if max_chars <= 0 or len(cleaned) <= max_chars:
        return cleaned

    for separator in ("。", "！", "？", ".", "!", "?"):
        index = cleaned.find(separator)
        if 0 < index + 1 <= max_chars:
            return cleaned[: index + 1].strip()

    return cleaned[:max_chars].rstrip("，,；;、 ") + "。"


async def _speak_response(session: CallSession, user_text: str, response: AgentResponse) -> None:
    turn_id = storage.new_id("turn")
    session.current_turn_id = turn_id

    try:
        if session.avatar_ws() is None:
            raise RuntimeError(f"no avatar websocket for session {session.session_id}; start Unity /ws/avatar first")
        if not response.reply_text.strip():
            await session.send_error("Agent returned empty reply", recoverable=True)
            await session.set_state("listening", "recovered")
            return

        await session.set_state("speaking", "tts")
        try:
            tts_result = await run_tts_async(SynthesizeRequest(
                text=response.reply_text,
                language=session.language,
                emotion=response.emotion,
            ), settings.call_tts_turn_timeout_sec, runner=run_tts)
        except TimeoutError:
            await session.send_error(f"TTS timeout after {settings.call_tts_turn_timeout_sec:.1f}s", recoverable=True)
            await session.set_state("listening", "recovered")
            return
        except Exception as exc:
            await session.send_error(f"TTS failed: {exc}", recoverable=True)
            await session.set_state("listening", "recovered")
            return

        viseme_curve = compute_viseme_curve(tts_result)
        gesture_events = compute_gesture_events(response.reply_text, tts_result, response.emotion)
        explicit_event = avatar_action_gesture_event(response.avatar_action)
        if explicit_event is not None:
            gesture_events.insert(0, explicit_event)
        gesture_event_dicts = [event.model_dump(mode="json") for event in gesture_events]

        audio_data, sr = sf.read(tts_result.audio_path, dtype="int16")
        if audio_data.ndim > 1:
            audio_data = audio_data[:, 0]

        total_samples = len(audio_data)
        duration_ms = (total_samples / float(sr) * 1000.0) if sr else tts_result.duration_ms

        await session.send_avatar({
            "type": "turn.start",
            "turn_id": turn_id,
            "emotion": response.emotion,
            "dialogue_act": response.dialogue_act,
            "gesture_events": gesture_event_dicts,
            "duration_ms": duration_ms,
            "sample_rate": int(sr),
            "total_samples": total_samples,
            "avatar_action": response.avatar_action.model_dump(mode="json") if response.avatar_action is not None else None,
        })
        await _send_phone_optional(session, {
            "type": "call.audio.start",
            "turn_id": turn_id,
            "sample_rate": int(sr),
            "total_samples": total_samples,
            "duration_ms": duration_ms,
        })

        chunk_samples = int(settings.ws_chunk_duration_ms * sr / 1000)
        seq = 0
        frame_idx = 0

        for offset in range(0, total_samples, chunk_samples):
            await asyncio.sleep(0)
            chunk = audio_data[offset: offset + chunk_samples]
            chunk_b64 = base64.b64encode(chunk.tobytes()).decode("ascii")
            await session.send_avatar({
                "type": "audio.chunk",
                "turn_id": turn_id,
                "seq": seq,
                "sample_rate": int(sr),
                "base64": chunk_b64,
            })
            await _send_phone_optional(session, {
                "type": "call.audio.chunk",
                "turn_id": turn_id,
                "seq": seq,
                "sample_rate": int(sr),
                "base64": chunk_b64,
            })

            chunk_start_ms = offset / sr * 1000
            chunk_end_ms = (offset + len(chunk)) / sr * 1000
            blendshapes: dict[str, float] = {}
            if frame_idx < len(viseme_curve.frames):
                blendshapes = viseme_curve.frames[frame_idx].weights
                frame_idx += 1

            await session.send_avatar({
                "type": "animation.packet",
                "turn_id": turn_id,
                "seq": seq,
                "start_ms": chunk_start_ms,
                "end_ms": chunk_end_ms,
                "blendshapes": blendshapes,
            })
            seq += 1

        await session.send_avatar({"type": "turn.end", "turn_id": turn_id})
        await _send_phone_optional(session, {"type": "call.audio.end", "turn_id": turn_id})
        await asyncio.sleep(max(0.0, tts_result.duration_ms / 1000.0))
        append_turn(session.session_id, {
            "turn_id": turn_id,
            "user_text": user_text,
            "reply_text": response.reply_text,
            "emotion": response.emotion,
            "dialogue_act": response.dialogue_act,
            "created_at": _now_iso(),
        })
        await session.set_state("listening")
    except asyncio.CancelledError:
        _logger.info("call response cancelled: session=%s turn=%s", session.session_id, turn_id)
        await _send_phone_optional(session, {"type": "call.audio.cancel", "turn_id": turn_id})
        raise
    except Exception as exc:
        _logger.exception("call response failed")
        await session.send_error(str(exc), recoverable=True)
        await session.set_state("listening", "recovered")
    finally:
        if session.current_turn_id == turn_id:
            session.current_turn_id = ""
