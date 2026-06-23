"""工作区路径管理。"""
from __future__ import annotations

import uuid
from pathlib import Path

from app.config import settings

ROOT = settings.workspace_dir


def _ensure(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def audio_dir(audio_id: str) -> Path:
    return _ensure(ROOT / "audio" / audio_id)
