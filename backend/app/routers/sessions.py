"""Session 管理 REST API。M2 阶段使用内存存储。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app import storage
from app.schemas import SessionCreate, SessionInfo, TurnRecord

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])
_logger = logging.getLogger(__name__)

# 内存存储（后续接入数据库）
_SESSIONS: dict[str, dict] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_session(session_id: str) -> dict:
    if session_id not in _SESSIONS:
        raise HTTPException(status_code=404, detail="session not found")
    return _SESSIONS[session_id]


def get_or_create_session(session_id: str, avatar_id: str = "default", language: str = "zh") -> dict:
    """WebSocket 侧获取或创建 session。"""
    if session_id in _SESSIONS:
        return _SESSIONS[session_id]
    session = {
        "session_id": session_id,
        "avatar_id": avatar_id,
        "language": language,
        "status": "active",
        "turns": [],
        "created_at": _now_iso(),
        "ended_at": None,
    }
    _SESSIONS[session_id] = session
    _logger.info("session created: %s", session_id)
    return session


def append_turn(session_id: str, turn: dict) -> None:
    """记录一个对话轮次。"""
    if session_id not in _SESSIONS:
        _logger.warning("append_turn for unknown session: %s", session_id)
        return
    _SESSIONS[session_id]["turns"].append(turn)


# ── REST Endpoints ──────────────────────────────────────────


@router.post("", response_model=SessionInfo)
async def create_session(body: SessionCreate):
    session_id = storage.new_id("sess")
    session = get_or_create_session(session_id, body.avatar_id, body.language)
    return _to_session_info(session)


@router.get("", response_model=list[SessionInfo])
async def list_sessions():
    return [_to_session_info(s) for s in _SESSIONS.values()]


@router.get("/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str):
    return _to_session_info(_ensure_session(session_id))


@router.delete("/{session_id}", response_model=SessionInfo)
async def end_session(session_id: str):
    session = _ensure_session(session_id)
    session["status"] = "ended"
    session["ended_at"] = _now_iso()
    _logger.info("session ended: %s", session_id)
    return _to_session_info(session)


def _to_session_info(s: dict) -> SessionInfo:
    turns = []
    for t in s.get("turns", []):
        turns.append(TurnRecord(
            turn_id=t.get("turn_id", ""),
            user_text=t.get("user_text", ""),
            reply_text=t.get("reply_text", ""),
            emotion=t.get("emotion", "neutral"),
            dialogue_act=t.get("dialogue_act", "unknown"),
            created_at=t.get("created_at", ""),
        ))
    return SessionInfo(
        session_id=s["session_id"],
        avatar_id=s.get("avatar_id", "default"),
        language=s.get("language", "zh"),
        status=s.get("status", "active"),
        turn_count=len(turns),
        turns=turns,
        created_at=s.get("created_at", ""),
        ended_at=s.get("ended_at"),
    )
