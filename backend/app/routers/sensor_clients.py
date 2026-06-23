from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

_logger = logging.getLogger(__name__)

_sensor_ws_registry: dict[str, set[WebSocket]] = defaultdict(set)
_sensor_ws_sessions: dict[WebSocket, str] = {}
_unbound_sensor_ws: set[WebSocket] = set()
_latest_avatar_session_id: str = ""


def latest_avatar_session_id() -> str:
    return _latest_avatar_session_id


async def publish_avatar_session(session_id: str) -> None:
    """Remember latest avatar session and bind sensor clients waiting for auto-session."""
    global _latest_avatar_session_id
    session_id = str(session_id or "")
    if not session_id:
        return

    _latest_avatar_session_id = session_id
    waiting = list(_unbound_sensor_ws)
    for sensor_ws in waiting:
        try:
            bind_sensor_ws(session_id, sensor_ws)
            await sensor_ws.send_json({
                "type": "sensor.bound",
                "session_id": session_id,
                "auto": True,
            })
        except Exception as exc:
            _logger.warning("failed to auto-bind sensor websocket: session=%s error=%s", session_id, exc)
            unbind_sensor_ws(sensor_ws)


def bind_sensor_ws(session_id: str, ws: WebSocket) -> None:
    """Bind a sensor WebSocket to the session that should receive avatar updates."""
    session_id = str(session_id or "")
    if not session_id:
        _unbound_sensor_ws.add(ws)
        return

    _unbound_sensor_ws.discard(ws)
    previous_session_id = _sensor_ws_sessions.get(ws)
    if previous_session_id and previous_session_id != session_id:
        _sensor_ws_registry[previous_session_id].discard(ws)
        if not _sensor_ws_registry[previous_session_id]:
            _sensor_ws_registry.pop(previous_session_id, None)

    _sensor_ws_sessions[ws] = session_id
    _sensor_ws_registry[session_id].add(ws)


def unbind_sensor_ws(ws: WebSocket, session_id: str | None = None) -> None:
    """Remove a sensor WebSocket from one session, or from its tracked session."""
    _unbound_sensor_ws.discard(ws)
    tracked_session_id = session_id or _sensor_ws_sessions.pop(ws, None)
    if not tracked_session_id:
        return

    _sensor_ws_registry[tracked_session_id].discard(ws)
    if not _sensor_ws_registry[tracked_session_id]:
        _sensor_ws_registry.pop(tracked_session_id, None)

    if _sensor_ws_sessions.get(ws) == tracked_session_id:
        _sensor_ws_sessions.pop(ws, None)


async def forward_avatar_anchors(payload: dict[str, Any]) -> int:
    """Forward avatar.anchors payload to all bound sensor clients for the session."""
    session_id = str(payload.get("session_id") or "")
    if not session_id:
        return 0

    clients = list(_sensor_ws_registry.get(session_id, ()))
    if not clients:
        _logger.debug("avatar anchors dropped: no bound sensor client for %s", session_id)
        return 0

    forwarded = 0
    for sensor_ws in clients:
        try:
            await sensor_ws.send_json(payload)
            forwarded += 1
        except Exception as exc:
            _logger.warning("failed to forward avatar anchors: session=%s error=%s", session_id, exc)
            unbind_sensor_ws(sensor_ws, session_id)

    return forwarded
