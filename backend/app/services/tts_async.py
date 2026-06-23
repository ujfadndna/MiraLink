"""Async wrappers for blocking TTS backends."""
from __future__ import annotations

import asyncio
from collections.abc import Callable

from app.schemas import AudioWithTimestamps, SynthesizeRequest
from app.services.tts import run_tts


async def run_tts_async(
    req: SynthesizeRequest,
    timeout_sec: float,
    runner: Callable[[SynthesizeRequest], AudioWithTimestamps] = run_tts,
) -> AudioWithTimestamps:
    return await asyncio.wait_for(asyncio.to_thread(runner, req), timeout=max(0.1, timeout_sec))
