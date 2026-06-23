"""WebSocket 端点：/ws/avatar。接收文本，通过 Agent 生成回复，TTS + 流式音频 + 动画包。"""
from __future__ import annotations

import base64
import asyncio
import logging
from datetime import datetime, timezone

import numpy as np
import soundfile as sf
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import storage
from app.config import settings
from app.schemas import AgentResponse, AvatarInteractionCommand, SynthesizeRequest
from app.services.agent import get_agent
from app.services.asr import transcribe_async
from app.services.avatar_intent import (
    action_ack_text,
    apply_avatar_action,
    avatar_action_gesture_event,
    parse_avatar_action_intent,
)
from app.services.gesture import compute_gesture_events
from app.services.memory import get_memory
from app.services.tts import run_tts
from app.services.tts_async import run_tts_async
from app.services.viseme import compute_viseme_curve
from app.routers.sensor_clients import forward_avatar_anchors, publish_avatar_session
from app.routers.sessions import append_turn, get_or_create_session

router = APIRouter()
_logger = logging.getLogger(__name__)

# Global registry: session_id -> active avatar WebSocket.
# Populated by avatar_ws on session.start, cleared on disconnect.
# Used by sensor_ws to push sensor reactions to the avatar channel.
_avatar_ws_registry: dict[str, WebSocket] = {}


def active_avatar_session_id() -> str:
    """Return the newest session with a currently connected avatar WebSocket."""
    if not _avatar_ws_registry:
        return ""
    return next(reversed(_avatar_ws_registry))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _generate_response_with_action(text: str, agent_text: str, session_id: str) -> AgentResponse:
    action = parse_avatar_action_intent(text)
    if action is not None and agent_text == text:
        response = AgentResponse(
            reply_text=action_ack_text(action),
            emotion=action.emotion or "neutral",
            dialogue_act="avatar_action",
            avatar_action=action,
        )
        try:
            get_memory().update_after_turn(session_id, text, response.reply_text, response.emotion)
        except Exception:
            pass
        return response

    agent = get_agent()
    response = await asyncio.wait_for(
        agent.generate(agent_text, session_id),
        timeout=max(0.1, settings.agent_response_timeout_sec),
    )
    return apply_avatar_action(response, action)


def _avatar_action_dict(command: AvatarInteractionCommand | None) -> dict | None:
    return command.model_dump(mode="json") if command is not None else None


def _gesture_event_dicts(reply_text: str, tts_result, emotion: str, action: AvatarInteractionCommand | None) -> list[dict]:
    gesture_events = compute_gesture_events(reply_text, tts_result, emotion)
    explicit_event = avatar_action_gesture_event(action)
    if explicit_event is not None:
        gesture_events.insert(0, explicit_event)
    return [event.model_dump(mode="json") for event in gesture_events]


async def _run_turn_tts(ws: WebSocket, req: SynthesizeRequest, timeout_sec: float):
    try:
        return await run_tts_async(req, timeout_sec, runner=run_tts)
    except TimeoutError:
        await ws.send_json({"type": "error", "message": f"TTS timeout after {timeout_sec:.1f}s"})
        await ws.send_json({"type": "state.change", "state": "idle", "detail": "TTS 超时，已恢复"})
        return None
    except Exception as exc:
        await ws.send_json({"type": "error", "message": f"TTS failed: {exc}"})
        await ws.send_json({"type": "state.change", "state": "idle", "detail": "TTS 失败，已恢复"})
        return None


@router.websocket("/ws/avatar")
async def avatar_ws(ws: WebSocket):
    await ws.accept()
    _logger.info("WebSocket connected")

    current_session_id: str | None = None
    auto_start_task: asyncio.Task | None = None

    async def ensure_session_started(data: dict | None = None) -> str:
        nonlocal current_session_id
        if current_session_id and _avatar_ws_registry.get(current_session_id) is ws:
            return current_session_id
        current_session_id = await _handle_session_start(ws, data or {})
        _avatar_ws_registry[current_session_id] = ws
        await publish_avatar_session(current_session_id)
        return current_session_id

    async def auto_start_session_after_delay() -> None:
        try:
            await asyncio.sleep(max(0.0, settings.avatar_auto_start_session_sec))
            if not current_session_id:
                await ensure_session_started({
                    "avatar_id": "vrm_female_001",
                    "language": "zh",
                    "auto": True,
                })
                _logger.info("auto-started avatar session: %s", current_session_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            _logger.exception("avatar auto session start failed")

    try:
        auto_start_task = asyncio.create_task(auto_start_session_after_delay())
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "session.start":
                if auto_start_task and not auto_start_task.done():
                    auto_start_task.cancel()
                await ensure_session_started(data)

            elif msg_type == "turn.submit_text":
                text = data.get("text", "").strip()
                session_id = data.get("session_id", current_session_id or "")
                if not text:
                    await ws.send_json({"type": "error", "message": "text is empty"})
                    continue
                if not session_id:
                    await ws.send_json({"type": "error", "message": "no active session — send session.start first"})
                    continue
                await _handle_turn(ws, text, session_id)

            elif msg_type == "turn.submit_text_stream":
                text = data.get("text", "").strip()
                session_id = data.get("session_id", current_session_id or "")
                if not text:
                    await ws.send_json({"type": "error", "message": "text is empty"})
                    continue
                if not session_id:
                    await ws.send_json({"type": "error", "message": "no active session — send session.start first"})
                    continue
                await _handle_turn_stream(ws, text, session_id)

            elif msg_type == "turn.submit_audio":
                audio_b64 = data.get("base64", "")
                sample_rate = data.get("sample_rate", 16000)
                session_id = data.get("session_id", current_session_id or "")
                if not audio_b64:
                    await ws.send_json({"type": "error", "message": "base64 audio is empty"})
                    continue
                if not session_id:
                    await ws.send_json({"type": "error", "message": "no active session — send session.start first"})
                    continue
                await _handle_audio_turn(ws, audio_b64, sample_rate, session_id)

            elif msg_type == "avatar.anchors":
                session_id = data.get("session_id", current_session_id or "")
                if not session_id:
                    await ws.send_json({"type": "error", "message": "no active session — send session.start first"})
                    continue

                data["session_id"] = session_id
                forwarded = await forward_avatar_anchors(data)
                _logger.debug("avatar anchors: session=%s forwarded=%s", session_id, forwarded)

            else:
                await ws.send_json({"type": "error", "message": f"unknown type: {msg_type}"})

    except WebSocketDisconnect:
        if current_session_id:
            _avatar_ws_registry.pop(current_session_id, None)
        _logger.info("WebSocket disconnected")
    except Exception as exc:
        _logger.exception("WebSocket error")
        try:
            await ws.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        if auto_start_task and not auto_start_task.done():
            auto_start_task.cancel()


async def _handle_session_start(ws: WebSocket, data: dict) -> str:
    avatar_id = data.get("avatar_id", "default")
    language = data.get("language", "zh")
    session_id = storage.new_id("sess")
    get_or_create_session(session_id, avatar_id, language)
    await ws.send_json({"type": "session.started", "session_id": session_id})
    await ws.send_json({"type": "state.change", "state": "idle", "detail": "会话已创建"})
    _logger.info("session started: %s", session_id)
    return session_id


async def _handle_audio_turn(ws: WebSocket, audio_b64: str, sample_rate: int, session_id: str):
    await ws.send_json({"type": "state.change", "state": "listening", "detail": "ASR 识别中..."})
    try:
        audio_bytes = base64.b64decode(audio_b64)
        text = await transcribe_async(audio_bytes, sample_rate, "zh")
    except Exception as exc:
        _logger.exception("ASR failed")
        await ws.send_json({"type": "error", "message": f"ASR failed: {exc}"})
        await ws.send_json({"type": "state.change", "state": "idle", "detail": "ASR 失败"})
        return
    await ws.send_json({"type": "asr.result", "text": text})
    if not text.strip():
        await ws.send_json({"type": "state.change", "state": "idle", "detail": "未识别到语音"})
        return
    await _handle_turn(ws, text, session_id)


async def _handle_turn(ws: WebSocket, text: str, session_id: str):
    turn_id = storage.new_id("turn")
    agent_text = text
    streak_before: int | None = None

    # 1. Agent 思考中
    await ws.send_json({"type": "state.change", "state": "thinking", "detail": "Agent 正在生成回复..."})

    try:
        streak_before = get_memory().load(session_id).streak_days
    except Exception:
        pass

    # M9: additive relationship prompts before generation. Memory failures must not block the turn.
    try:
        should_greet, greeting_text = get_memory().check_daily_greeting(session_id)
        if should_greet and greeting_text:
            await ws.send_json({"type": "state.change", "state": "thinking", "detail": greeting_text})
            _logger.info("daily greeting for %s: %s", session_id, greeting_text)
    except Exception:
        pass

    try:
        should_push, gap_text = get_memory().check_gap_push(session_id)
        if should_push and gap_text:
            agent_text = f"【系统提示：{gap_text} 请自然融入回复，不要说明这是系统提示。】\n用户说：{text}"
            _logger.info("gap push hint for %s: %s", session_id, gap_text)
    except Exception:
        pass

    # 2. Agent 生成回复
    try:
        response = await _generate_response_with_action(text, agent_text, session_id)
    except TimeoutError:
        await ws.send_json({"type": "error", "message": f"Agent timeout after {settings.agent_response_timeout_sec:.1f}s"})
        await ws.send_json({"type": "state.change", "state": "idle", "detail": "Agent 超时，已恢复"})
        return
    except Exception as exc:
        await ws.send_json({"type": "error", "message": f"Agent failed: {exc}"})
        await ws.send_json({"type": "state.change", "state": "idle", "detail": "Agent 失败，已恢复"})
        return

    try:
        state = get_memory().load(session_id)
        unlock_text = get_memory().get_streak_unlock(state.streak_days)
        if unlock_text and state.streak_days != streak_before:
            response.reply_text = f"{response.reply_text}\n{unlock_text}"
            _logger.info("streak unlock for %s: %s", session_id, unlock_text)
    except Exception:
        pass

    _logger.info(
        "turn %s: user=%r → reply=%r emotion=%s act=%s",
        turn_id, text, response.reply_text, response.emotion, response.dialogue_act,
    )

    # 3. TTS 生成
    if not response.reply_text.strip():
        await ws.send_json({"type": "error", "message": "Agent returned empty reply"})
        await ws.send_json({"type": "state.change", "state": "idle", "detail": "空回复，已恢复"})
        return

    await ws.send_json({"type": "state.change", "state": "speaking", "detail": "TTS 生成语音中..."})

    tts_result = await _run_turn_tts(ws, SynthesizeRequest(
        text=response.reply_text,
        emotion=response.emotion,
    ), settings.tts_turn_timeout_sec)
    if tts_result is None:
        return

    # 4. Viseme 曲线 + 手势事件
    viseme_curve = compute_viseme_curve(tts_result)
    gesture_event_dicts = _gesture_event_dicts(response.reply_text, tts_result, response.emotion, response.avatar_action)

    # 5. 读取音频 PCM 并通知 turn 开始（带情绪标签、手势事件和长度元数据）
    audio_data, sr = sf.read(tts_result.audio_path, dtype="int16")
    if audio_data.ndim > 1:
        audio_data = audio_data[:, 0]  # mono
    total_samples = len(audio_data)
    duration_ms = (total_samples / float(sr) * 1000.0) if sr else tts_result.duration_ms

    await ws.send_json({
        "type": "turn.start",
        "turn_id": turn_id,
        "emotion": response.emotion,
        "dialogue_act": response.dialogue_act,
        "gesture_events": gesture_event_dicts,
        "duration_ms": duration_ms,
        "sample_rate": int(sr),
        "total_samples": total_samples,
        "avatar_action": _avatar_action_dict(response.avatar_action),
    })

    # 6. 分块发送
    chunk_samples = int(settings.ws_chunk_duration_ms * sr / 1000)
    seq = 0
    frame_idx = 0

    for offset in range(0, total_samples, chunk_samples):
        chunk = audio_data[offset: offset + chunk_samples]
        chunk_b64 = base64.b64encode(chunk.tobytes()).decode("ascii")

        await ws.send_json({
            "type": "audio.chunk",
            "turn_id": turn_id,
            "seq": seq,
            "sample_rate": sr,
            "base64": chunk_b64,
        })

        # Animation packet
        chunk_start_ms = offset / sr * 1000
        chunk_end_ms = (offset + len(chunk)) / sr * 1000

        blendshapes: dict[str, float] = {}
        if frame_idx < len(viseme_curve.frames):
            frame = viseme_curve.frames[frame_idx]
            blendshapes = frame.weights
            frame_idx += 1

        await ws.send_json({
            "type": "animation.packet",
            "turn_id": turn_id,
            "seq": seq,
            "start_ms": chunk_start_ms,
            "end_ms": chunk_end_ms,
            "blendshapes": blendshapes,
        })

        seq += 1

    # 8. 结束
    await ws.send_json({"type": "turn.end", "turn_id": turn_id})
    await ws.send_json({"type": "state.change", "state": "idle", "detail": "就绪"})

    # 9. 记录 turn 到 session
    append_turn(session_id, {
        "turn_id": turn_id,
        "user_text": text,
        "reply_text": response.reply_text,
        "emotion": response.emotion,
        "dialogue_act": response.dialogue_act,
        "created_at": _now_iso(),
    })


async def _handle_turn_stream(ws: WebSocket, text: str, session_id: str) -> None:
    """流式 turn：token 级别推送，降低首字延迟。"""
    agent = get_agent()
    turn_id = storage.new_id("turn")
    agent_text = text
    avatar_action = parse_avatar_action_intent(text)
    streak_before: int | None = None

    await ws.send_json({"type": "state.change", "state": "thinking", "detail": "Agent 正在生成回复..."})

    try:
        streak_before = get_memory().load(session_id).streak_days
    except Exception:
        pass

    # M9: additive relationship prompts
    try:
        should_greet, greeting_text = get_memory().check_daily_greeting(session_id)
        if should_greet and greeting_text:
            await ws.send_json({"type": "state.change", "state": "thinking", "detail": greeting_text})
            _logger.info("daily greeting for %s: %s", session_id, greeting_text)
    except Exception:
        pass

    try:
        should_push, gap_text = get_memory().check_gap_push(session_id)
        if should_push and gap_text:
            agent_text = f"【系统提示：{gap_text} 请自然融入回复，不要说明这是系统提示。】\n用户说：{text}"
            _logger.info("gap push hint for %s: %s", session_id, gap_text)
    except Exception:
        pass

    accumulated = ""
    emotion = "neutral"
    dialogue_act = "unknown"
    if avatar_action is not None and agent_text == text:
        accumulated = action_ack_text(avatar_action)
        emotion = avatar_action.emotion or "neutral"
        dialogue_act = "avatar_action"
        await ws.send_json({
            "type": "stream.token",
            "token": accumulated,
            "accumulated_text": accumulated,
            "is_final": True,
        })
        try:
            get_memory().update_after_turn(session_id, text, accumulated, emotion)
        except Exception:
            pass
    else:
        # Stream tokens from agent
        try:
            async for event in agent.generate_stream(agent_text, session_id):
                accumulated = event.accumulated_text
                await ws.send_json({
                    "type": "stream.token",
                    "token": event.token,
                    "accumulated_text": event.accumulated_text,
                    "is_final": event.is_final,
                })
                if event.is_final:
                    emotion = event.emotion
                    dialogue_act = event.dialogue_act
        except Exception as exc:
            await ws.send_json({"type": "error", "message": f"Agent failed: {exc}"})
            await ws.send_json({"type": "state.change", "state": "idle"})
            return

    reply_text = accumulated
    if avatar_action is not None:
        if not reply_text.strip():
            reply_text = action_ack_text(avatar_action)
        emotion = avatar_action.emotion or emotion
        dialogue_act = "avatar_action"

    try:
        state = get_memory().load(session_id)
        unlock_text = get_memory().get_streak_unlock(state.streak_days)
        if unlock_text and state.streak_days != streak_before:
            reply_text = f"{reply_text}\n{unlock_text}"
            _logger.info("streak unlock for %s: %s", session_id, unlock_text)
    except Exception:
        pass

    _logger.info(
        "turn %s: user=%r → reply=%r emotion=%s act=%s",
        turn_id, text, reply_text, emotion, dialogue_act,
    )

    # TTS
    if not reply_text.strip():
        await ws.send_json({"type": "error", "message": "Agent returned empty reply"})
        await ws.send_json({"type": "state.change", "state": "idle", "detail": "空回复，已恢复"})
        return

    await ws.send_json({"type": "state.change", "state": "speaking", "detail": "TTS 生成语音中..."})
    tts_result = await _run_turn_tts(ws, SynthesizeRequest(
        text=reply_text,
        emotion=emotion,
    ), settings.tts_turn_timeout_sec)
    if tts_result is None:
        return

    # Viseme + gesture
    viseme_curve = compute_viseme_curve(tts_result)
    gesture_event_dicts = _gesture_event_dicts(reply_text, tts_result, emotion, avatar_action)

    audio_data, sr = sf.read(tts_result.audio_path, dtype="int16")
    if audio_data.ndim > 1:
        audio_data = audio_data[:, 0]
    total_samples = len(audio_data)
    duration_ms = (total_samples / float(sr) * 1000.0) if sr else tts_result.duration_ms

    await ws.send_json({
        "type": "turn.start",
        "turn_id": turn_id,
        "emotion": emotion,
        "dialogue_act": dialogue_act,
        "gesture_events": gesture_event_dicts,
        "duration_ms": duration_ms,
        "sample_rate": int(sr),
        "total_samples": total_samples,
        "avatar_action": _avatar_action_dict(avatar_action),
    })

    # Audio chunks
    chunk_samples = int(settings.ws_chunk_duration_ms * sr / 1000)
    seq = 0
    frame_idx = 0

    for offset in range(0, total_samples, chunk_samples):
        chunk = audio_data[offset: offset + chunk_samples]
        chunk_b64 = base64.b64encode(chunk.tobytes()).decode("ascii")

        await ws.send_json({
            "type": "audio.chunk",
            "turn_id": turn_id,
            "seq": seq,
            "sample_rate": sr,
            "base64": chunk_b64,
        })

        chunk_start_ms = offset / sr * 1000
        chunk_end_ms = (offset + len(chunk)) / sr * 1000

        blendshapes: dict[str, float] = {}
        if frame_idx < len(viseme_curve.frames):
            frame = viseme_curve.frames[frame_idx]
            blendshapes = frame.weights
            frame_idx += 1

        await ws.send_json({
            "type": "animation.packet",
            "turn_id": turn_id,
            "seq": seq,
            "start_ms": chunk_start_ms,
            "end_ms": chunk_end_ms,
            "blendshapes": blendshapes,
        })

        seq += 1

    await ws.send_json({"type": "turn.end", "turn_id": turn_id})
    await ws.send_json({"type": "state.change", "state": "idle", "detail": "就绪"})

    append_turn(session_id, {
        "turn_id": turn_id,
        "user_text": text,
        "reply_text": reply_text,
        "emotion": emotion,
        "dialogue_act": dialogue_act,
        "created_at": _now_iso(),
    })


async def _handle_sensor_reaction(
    ws: WebSocket,
    reply_text: str,
    emotion: str,
    session_id: str,
) -> None:
    """Push a sensor-triggered reaction directly to TTS, skipping the Agent step."""
    turn_id = storage.new_id("turn")

    await ws.send_json({"type": "state.change", "state": "speaking", "detail": "sensor reaction..."})

    if not reply_text.strip():
        await ws.send_json({"type": "error", "message": "empty sensor reply"})
        await ws.send_json({"type": "state.change", "state": "idle", "detail": "empty reply"})
        return

    tts_result = await _run_turn_tts(ws, SynthesizeRequest(
        text=reply_text,
        emotion=emotion,
    ), settings.tts_turn_timeout_sec)
    if tts_result is None:
        return

    viseme_curve = compute_viseme_curve(tts_result)
    gesture_event_dicts = _gesture_event_dicts(reply_text, tts_result, emotion, None)

    audio_data, sr = sf.read(tts_result.audio_path, dtype="int16")
    if audio_data.ndim > 1:
        audio_data = audio_data[:, 0]
    total_samples = len(audio_data)
    duration_ms = (total_samples / float(sr) * 1000.0) if sr else tts_result.duration_ms

    await ws.send_json({
        "type": "turn.start",
        "turn_id": turn_id,
        "emotion": emotion,
        "dialogue_act": "sensor_reaction",
        "gesture_events": gesture_event_dicts,
        "duration_ms": duration_ms,
        "sample_rate": int(sr),
        "total_samples": total_samples,
    })

    chunk_samples = int(settings.ws_chunk_duration_ms * sr / 1000)
    seq = 0
    frame_idx = 0

    for offset in range(0, total_samples, chunk_samples):
        chunk = audio_data[offset: offset + chunk_samples]
        chunk_b64 = base64.b64encode(chunk.tobytes()).decode("ascii")

        await ws.send_json({
            "type": "audio.chunk",
            "turn_id": turn_id,
            "seq": seq,
            "sample_rate": sr,
            "base64": chunk_b64,
        })

        chunk_start_ms = offset / sr * 1000
        chunk_end_ms = (offset + len(chunk)) / sr * 1000

        blendshapes: dict[str, float] = {}
        if frame_idx < len(viseme_curve.frames):
            frame = viseme_curve.frames[frame_idx]
            blendshapes = frame.weights
            frame_idx += 1

        await ws.send_json({
            "type": "animation.packet",
            "turn_id": turn_id,
            "seq": seq,
            "start_ms": chunk_start_ms,
            "end_ms": chunk_end_ms,
            "blendshapes": blendshapes,
        })

        seq += 1

    await ws.send_json({"type": "turn.end", "turn_id": turn_id})
    await ws.send_json({"type": "state.change", "state": "idle", "detail": "ready"})

    append_turn(session_id, {
        "turn_id": turn_id,
        "user_text": f"[sensor:{emotion}]",
        "reply_text": reply_text,
        "emotion": emotion,
        "dialogue_act": "sensor_reaction",
        "created_at": _now_iso(),
    })
    try:
        get_memory().update_after_turn(session_id, f"[sensor:{emotion}]", reply_text, emotion)
    except Exception:
        pass
