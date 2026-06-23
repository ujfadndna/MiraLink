"""Non-blocking runtime warmup for ASR, TTS, and optional agent state."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
import numpy as np

from app.config import settings
from app.schemas import SynthesizeRequest
from app.services.asr import transcribe_async
from app.services.tts import run_tts

_logger = logging.getLogger(__name__)
_task: asyncio.Task[None] | None = None


@dataclass(slots=True)
class WarmupStatus:
    enabled: bool = False
    status: str = "disabled"
    started_at: str | None = None
    finished_at: str | None = None
    errors: list[str] = field(default_factory=list)
    steps: dict[str, str] = field(default_factory=dict)


_STATUS = WarmupStatus()


def get_warmup_status() -> dict[str, Any]:
    return {
        "warmup_enabled": _STATUS.enabled,
        "warmup_status": _STATUS.status,
        "warmup_started_at": _STATUS.started_at,
        "warmup_finished_at": _STATUS.finished_at,
        "warmup_errors": list(_STATUS.errors),
        "warmup_steps": dict(_STATUS.steps),
    }


def schedule_warmup() -> None:
    """Schedule warmup after FastAPI startup without delaying health checks."""
    global _task

    _STATUS.enabled = bool(settings.warmup_on_start)
    _STATUS.status = "pending" if _STATUS.enabled else "disabled"
    _STATUS.started_at = None
    _STATUS.finished_at = None
    _STATUS.errors.clear()
    _STATUS.steps.clear()

    if not _STATUS.enabled:
        return

    if _task is not None and not _task.done():
        return

    _task = asyncio.create_task(_run_with_timeout())


async def _run_with_timeout() -> None:
    timeout_sec = max(float(settings.warmup_timeout_sec), 1.0)
    try:
        await asyncio.wait_for(_run_warmup(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        _record_error(f"warmup timeout after {timeout_sec:.1f}s")
        _STATUS.status = "timeout"
        _STATUS.finished_at = _now_iso()
    except Exception as exc:  # pragma: no cover - defensive task boundary
        _record_error(f"{type(exc).__name__}: {exc}")
        _STATUS.status = "error"
        _STATUS.finished_at = _now_iso()


async def _run_warmup() -> None:
    _STATUS.status = "running"
    _STATUS.started_at = _now_iso()
    _logger.info("Runtime warmup started")

    if settings.warmup_asr:
        await _warmup_asr()

    if settings.warmup_tts:
        await _warmup_tts()

    if settings.warmup_agent:
        await _warmup_agent()

    _STATUS.finished_at = _now_iso()
    _STATUS.status = "error" if _STATUS.errors else "complete"
    _logger.info("Runtime warmup finished: status=%s errors=%d", _STATUS.status, len(_STATUS.errors))


async def _warmup_asr() -> None:
    backend = settings.asr_backend.strip().lower()
    if backend == "mock":
        _STATUS.steps["asr"] = "skipped:mock"
        return

    try:
        if backend == "cloud_whisper":
            await _warmup_cloud_asr()
        elif backend == "faster_whisper":
            sample_rate = 16000
            pcm = np.zeros(int(sample_rate * 0.2), dtype=np.int16).tobytes()
            await transcribe_async(pcm, sample_rate, "zh")
        else:
            _STATUS.steps["asr"] = f"skipped:{backend}"
            return
        _STATUS.steps["asr"] = "ok"
    except Exception as exc:
        _record_error(f"asr warmup failed: {type(exc).__name__}: {exc}")
        _STATUS.steps["asr"] = "error"


async def _warmup_cloud_asr() -> None:
    api_url = settings.cloud_asr_api_url.strip().rstrip("/")
    if not api_url:
        raise RuntimeError("CLOUD_ASR_API_URL is not configured")

    timeout_sec = min(max(float(settings.warmup_timeout_sec), 1.0), 15.0)
    deadline = time.monotonic() + max(float(settings.warmup_timeout_sec), 1.0)
    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        last_payload: Any = None
        while True:
            response = await client.get(f"{api_url}/health")
            response.raise_for_status()
            last_payload = response.json()
            if isinstance(last_payload, dict):
                if last_payload.get("loaded") is True:
                    return
                if last_payload.get("loading") is False and last_payload.get("loaded") is False:
                    raise RuntimeError(f"cloud ASR not loaded: {last_payload}")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"cloud ASR did not report loaded=true: {last_payload}")
            await asyncio.sleep(1.0)


async def _warmup_tts() -> None:
    backend = settings.tts_backend.strip().lower()
    if backend == "mock":
        _STATUS.steps["tts"] = "skipped:mock"
        return

    try:
        await asyncio.to_thread(
            run_tts,
            SynthesizeRequest(text=settings.warmup_text or "你好", language="zh", emotion="neutral"),
        )
        _STATUS.steps["tts"] = "ok"
    except Exception as exc:
        _record_error(f"tts warmup failed: {type(exc).__name__}: {exc}")
        _STATUS.steps["tts"] = "error"


async def _warmup_agent() -> None:
    try:
        from app.services.agent import get_agent

        await get_agent().generate(settings.warmup_text or "你好", "warmup")
        _STATUS.steps["agent"] = "ok"
    except Exception as exc:
        _record_error(f"agent warmup failed: {type(exc).__name__}: {exc}")
        _STATUS.steps["agent"] = "error"


def _record_error(message: str) -> None:
    _logger.warning("Runtime warmup error: %s", message)
    _STATUS.errors.append(message)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
