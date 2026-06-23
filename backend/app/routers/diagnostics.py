"""Read-only runtime diagnostics."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from fastapi import APIRouter

from app.config import settings
from app.routers.ws import active_avatar_session_id
from app.services.asr import get_asr_runtime_status
from app.services.tts import get_tts_runtime_status
from app.services.warmup import get_warmup_status

router = APIRouter(prefix="/api/v1/diagnostics", tags=["diagnostics"])

_MAX_AUDIO_FILES = 5
_MAX_ANALYSIS_SAMPLES = 120_000


def _path_tail(path: Path, parts: int = 3) -> str:
    return "/".join(path.parts[-parts:])


def _estimate_dominant_frequency(data: np.ndarray, sample_rate: int) -> float | None:
    if sample_rate <= 0 or data.size < 2:
        return None

    data = data[:_MAX_ANALYSIS_SAMPLES].astype(np.float32, copy=False)
    data = data - float(np.mean(data))
    if not np.any(data):
        return None

    window = np.hanning(data.size).astype(np.float32)
    spectrum = np.fft.rfft(data * window)
    magnitudes = np.abs(spectrum)
    if magnitudes.size <= 1:
        return None

    magnitudes[0] = 0.0
    index = int(np.argmax(magnitudes))
    if magnitudes[index] <= 0:
        return None
    freqs = np.fft.rfftfreq(data.size, d=1.0 / sample_rate)
    return float(freqs[index])


def _is_suspected_mock_tone(sample_rate: int, rms: float, dominant_hz: float | None) -> bool:
    if dominant_hz is None:
        return False
    return (
        sample_rate == 24_000
        and 0.005 <= rms <= 0.03
        and 210.0 <= dominant_hz <= 230.0
    )


def _audio_metadata(path: Path) -> dict[str, Any]:
    try:
        data, sample_rate = sf.read(str(path), dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)

        duration_ms = float(data.size / sample_rate * 1000.0) if sample_rate else 0.0
        rms = float(np.sqrt(np.mean(np.square(data)))) if data.size else 0.0
        dominant_hz = _estimate_dominant_frequency(data, int(sample_rate))
        return {
            "path_tail": _path_tail(path),
            "sample_rate": int(sample_rate),
            "duration_ms": round(duration_ms, 1),
            "rms": round(rms, 6),
            "dominant_frequency_hz": round(dominant_hz, 1) if dominant_hz is not None else None,
            "suspected_mock_tone": _is_suspected_mock_tone(int(sample_rate), rms, dominant_hz),
        }
    except Exception as exc:
        return {
            "path_tail": _path_tail(path),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _recent_tts_wavs() -> list[Path]:
    audio_root = Path(settings.workspace_dir) / "audio"
    if not audio_root.exists():
        return []

    wavs = [path for path in audio_root.glob("aud_*/tts.wav") if path.is_file()]
    wavs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return wavs[:_MAX_AUDIO_FILES]


def _tail(value: str, chars: int = 12) -> str:
    return value[-chars:] if value else ""


@router.get("/runtime")
async def runtime_diagnostics() -> dict[str, Any]:
    return {
        "tts_backend": settings.tts_backend,
        "tts_sample_rate": settings.tts_sample_rate,
        "indextts_api_configured": bool(settings.indextts_api_url.strip()),
        "indextts_http_timeout_sec": settings.indextts_http_timeout_sec,
        "asr_backend": settings.asr_backend,
        "cloud_asr_configured": bool(settings.cloud_asr_api_url.strip()),
        "agent_backend": settings.agent_backend,
        "call_barge_in_enabled": settings.call_barge_in_enabled,
        "avatar_session_active": bool(active_avatar_session_id()),
        "active_avatar_session_tail": _tail(active_avatar_session_id()),
        "recent_tts_wavs": [_audio_metadata(path) for path in _recent_tts_wavs()],
        **get_tts_runtime_status(settings.tts_backend),
        **get_asr_runtime_status(settings.asr_backend),
        **get_warmup_status(),
    }
