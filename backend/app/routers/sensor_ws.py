from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from time import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.routers.ws import _avatar_ws_registry, _handle_audio_turn, _handle_sensor_reaction
from app.routers.sensor_clients import bind_sensor_ws, latest_avatar_session_id, unbind_sensor_ws
from app.services.sensor import SensorReactionEngine

router = APIRouter()
_logger = logging.getLogger(__name__)
_engine = SensorReactionEngine()
_session_speaking: dict[str, bool] = defaultdict(bool)


@router.websocket("/ws/sensor")
async def sensor_ws(ws: WebSocket):
    await ws.accept()
    _logger.info("sensor WebSocket connected")
    bound_session_id: str | None = None

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "sensor.bind":
                requested_session_id = str(data.get("session_id", "") or "").strip()
                bound_session_id = requested_session_id or latest_avatar_session_id()
                if not bound_session_id:
                    bind_sensor_ws("", ws)
                    await ws.send_json({
                        "type": "sensor.waiting_session",
                        "message": "waiting for avatar session",
                    })
                else:
                    bind_sensor_ws(bound_session_id, ws)
                    await ws.send_json({
                        "type": "sensor.bound",
                        "session_id": bound_session_id,
                        "auto": not requested_session_id,
                    })
                    _logger.info("sensor bound to session: %s auto=%s", bound_session_id, not requested_session_id)

            elif msg_type == "sensor.event":
                event = data.get("event", "")
                session_id = data.get("session_id", bound_session_id or "") or bound_session_id or latest_avatar_session_id()

                if not session_id:
                    bind_sensor_ws("", ws)
                    await ws.send_json({"type": "error", "message": "no avatar session yet - waiting for Unity session.start"})
                    continue
                if not bound_session_id:
                    bound_session_id = session_id
                    bind_sensor_ws(bound_session_id, ws)
                if not event:
                    await ws.send_json({"type": "error", "message": "event field is required"})
                    continue

                await _handle_sensor_event(ws, data, event, session_id)

            elif msg_type == "sensor.audio":
                audio_b64 = data.get("base64", "")
                sample_rate = data.get("sample_rate", 16000)
                session_id = data.get("session_id", bound_session_id or "")

                if not session_id:
                    await ws.send_json({"type": "error", "message": "no session bound - send sensor.bind first"})
                    continue
                if not audio_b64:
                    await ws.send_json({"type": "error", "message": "base64 audio is empty"})
                    continue

                await _handle_sensor_audio(ws, audio_b64, sample_rate, session_id)

            else:
                await ws.send_json({"type": "error", "message": f"unknown type: {msg_type}"})

    except WebSocketDisconnect:
        _logger.info("sensor WebSocket disconnected")
    except Exception as exc:
        _logger.exception("sensor WebSocket error")
        try:
            await ws.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        unbind_sensor_ws(ws, bound_session_id)


async def _handle_sensor_event(ws: WebSocket, data: dict, event: str, session_id: str) -> None:
    value = data.get("value") if isinstance(data.get("value"), dict) else {}
    zone = _extract_zone(data, value)
    feedback_spec = _engine.feedback_for_event(event, zone=zone, value=value)
    normalized_event = _engine.normalize_event(event)
    received_ms = _epoch_ms()
    timestamp_ms = _safe_int(data.get("timestamp_ms", 0))
    latency_ms = max(0, received_ms - timestamp_ms) if timestamp_ms > 0 else 0

    if feedback_spec is None:
        await ws.send_json({
            "type": "sensor.ack",
            "session_id": session_id,
            "event": normalized_event or event,
            "accepted": False,
            "latency_ms": latency_ms,
            "reason": f"unknown event: {event}",
        })
        _logger.warning("unknown sensor event: session=%s event=%s", session_id, event)
        return

    avatar_ws = _avatar_ws_registry.get(session_id)
    if avatar_ws is None:
        await ws.send_json({"type": "error", "message": f"no avatar session for {session_id}"})
        return

    can_forward, retry_after_ms = _engine.can_forward(feedback_spec.event, session_id)
    if not can_forward:
        await ws.send_json({
            "type": "sensor.ack",
            "session_id": session_id,
            "event": feedback_spec.event,
            "accepted": False,
            "latency_ms": latency_ms,
            "reason": "rate_limited",
            "retry_after_ms": retry_after_ms,
        })
        _logger.debug(
            "rate-limited sensor event: session=%s event=%s retry_after=%sms",
            session_id,
            feedback_spec.event,
            retry_after_ms,
        )
        return

    feedback = {
        "type": "sensor.feedback",
        "session_id": session_id,
        "event": feedback_spec.event,
        "zone": zone,
        "value": value,
        "timestamp_ms": timestamp_ms,
        "received_ms": received_ms,
        "latency_ms": latency_ms,
        "emotion": feedback_spec.emotion,
        "jd_state": "Reacting",
        "energy_delta": feedback_spec.energy_delta,
        "affinity_delta": feedback_spec.affinity_delta,
        "score_delta": feedback_spec.score_delta,
        "feedback_tags": feedback_spec.feedback_tags,
        "command": feedback_spec.command.as_dict(),
    }

    try:
        await avatar_ws.send_json(feedback)
    except Exception as exc:
        _logger.warning("failed to forward sensor feedback: session=%s event=%s error=%s", session_id, event, exc)
        await ws.send_json({"type": "error", "message": f"avatar websocket unavailable for {session_id}"})
        return

    await ws.send_json({
        "type": "sensor.ack",
        "session_id": session_id,
        "event": feedback_spec.event,
        "accepted": True,
        "latency_ms": latency_ms,
        "reason": "",
    })
    _logger.info(
        "sensor feedback: session=%s event=%s latency=%sms emotion=%s",
        session_id,
        feedback_spec.event,
        latency_ms,
        feedback_spec.emotion,
    )

    diagnostic = bool(data.get("diagnostic")) or bool(value.get("diagnostic"))
    if diagnostic:
        _logger.debug("sensor voice reaction %s for session %s skipped (diagnostic)", feedback_spec.event, session_id)
    elif feedback_spec.should_voice and _engine.can_react(feedback_spec.event, session_id):
        asyncio.create_task(_run_optional_sensor_reaction(avatar_ws, feedback_spec.event, session_id))
    elif feedback_spec.should_voice:
        _logger.debug("sensor voice reaction %s for session %s skipped (cooldown)", feedback_spec.event, session_id)


async def _run_optional_sensor_reaction(avatar_ws: WebSocket, event: str, session_id: str) -> None:
    if _session_speaking[session_id]:
        _logger.debug("sensor voice reaction %s for session %s skipped (avatar speaking)", event, session_id)
        return

    _session_speaking[session_id] = True
    try:
        reply_text, emotion = _engine.react(event, session_id)
        _logger.info("sensor reaction: session=%s event=%s emotion=%s text=%r", session_id, event, emotion, reply_text)
        await _handle_sensor_reaction(avatar_ws, reply_text, emotion, session_id)
    except Exception:
        _logger.exception("sensor voice reaction failed: session=%s event=%s", session_id, event)
    finally:
        _session_speaking[session_id] = False


async def _handle_sensor_audio(ws: WebSocket, audio_b64: str, sample_rate: int, session_id: str) -> None:
    avatar_ws = _avatar_ws_registry.get(session_id)
    if avatar_ws is None:
        await ws.send_json({"type": "error", "message": f"no avatar session for {session_id}"})
        return

    _logger.info("sensor audio turn: session=%s sample_rate=%s", session_id, sample_rate)
    await _handle_audio_turn(avatar_ws, audio_b64, sample_rate, session_id)
    await ws.send_json({"type": "audio.received", "session_id": session_id})


def _epoch_ms() -> int:
    return int(time() * 1000)


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _extract_zone(data: dict, value: dict) -> str | None:
    raw = data.get("zone")
    if raw is None:
        raw = value.get("visual_zone")
    if raw is None:
        raw = value.get("zone")
    zone = str(raw or "").strip().lower()
    return zone or None
