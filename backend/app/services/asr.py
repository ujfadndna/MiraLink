"""ASR 服务。支持 Mock、faster-whisper 和云端 Whisper 后端。"""
from __future__ import annotations

import asyncio
import io
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
import numpy as np
import soundfile as sf

from app.config import settings
from app.services.base import get_backend, register

_logger = logging.getLogger(__name__)

_MOCK_DELAY_SEC = 0.5
_MOCK_TEXT = "你好，请介绍一下你自己"
_ASR_INSTANCES: dict[str, object] = {}
_CLOUD_ASR_TIMEOUT_SEC = 45.0


@dataclass(slots=True)
class AsrRuntimeStatus:
    last_text: str = ""
    last_elapsed_ms: float | None = None
    last_backend: str = ""


_RUNTIME_STATUS = AsrRuntimeStatus()


class AsrBackend(ABC):
    @abstractmethod
    def transcribe(self, audio_bytes: bytes, sample_rate: int, language: str) -> str:
        ...


@register("asr", "mock")
class MockAsr(AsrBackend):
    def transcribe(self, audio_bytes: bytes, sample_rate: int, language: str) -> str:
        time.sleep(_MOCK_DELAY_SEC)
        _logger.debug("MockAsr: returning fixed text, audio_bytes=%d", len(audio_bytes))
        return _MOCK_TEXT


@register("asr", "faster_whisper")
class FasterWhisperAsr(AsrBackend):
    def __init__(self) -> None:
        from faster_whisper import WhisperModel  # type: ignore[import]

        model_name = settings.asr_model
        _logger.info("Loading faster-whisper model: %s", model_name)
        device = settings.asr_device
        compute = settings.asr_compute_type
        self._model = WhisperModel(model_name, device=device, compute_type=compute)
        _logger.info("faster-whisper model loaded.")

    def transcribe(self, audio_bytes: bytes, sample_rate: int, language: str) -> str:
        buf = _pcm16_mono_to_wav(audio_bytes, sample_rate, subtype="FLOAT")

        lang = language[:2] if language else None
        segments, _ = self._model.transcribe(buf, language=lang, beam_size=5)
        text = "".join(seg.text for seg in segments).strip()
        _logger.debug("FasterWhisperAsr: transcribed=%r", text)
        return text


@register("asr", "cloud_whisper")
class CloudWhisperAsr(AsrBackend):
    """HTTP adapter for a remote faster-whisper service reached through SSH tunnel."""

    def transcribe(self, audio_bytes: bytes, sample_rate: int, language: str) -> str:
        api_url = settings.cloud_asr_api_url.strip().rstrip("/")
        if not api_url:
            raise RuntimeError("CLOUD_ASR_API_URL is not configured")

        wav = _pcm16_mono_to_wav(audio_bytes, sample_rate, subtype="PCM_16").getvalue()
        lang = (language or "zh")[:2]
        try:
            resp = httpx.post(
                f"{api_url}/asr",
                files={"file": ("audio.wav", wav, "audio/wav")},
                data={"language": lang},
                timeout=_CLOUD_ASR_TIMEOUT_SEC,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text[:300]
            raise RuntimeError(f"Cloud Whisper ASR HTTP failed: status={status} body={body!r}") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Cloud Whisper ASR HTTP failed: {exc}") from exc

        try:
            result = resp.json()
        except ValueError as exc:
            raise RuntimeError("Cloud Whisper ASR response JSON parse failed") from exc
        if not isinstance(result, dict):
            raise RuntimeError(f"Cloud Whisper ASR response JSON must be an object; got {type(result).__name__}")
        if "text" not in result:
            keys = sorted(str(key) for key in result.keys())
            raise RuntimeError(f"Cloud Whisper ASR response missing required field 'text'; keys={keys}")

        text = str(result.get("text") or "").strip()
        if not text:
            raise RuntimeError("Cloud Whisper ASR returned empty text")

        _logger.debug("CloudWhisperAsr: transcribed=%r", text)
        return text


def _pcm16_mono_to_wav(audio_bytes: bytes, sample_rate: int, subtype: str) -> io.BytesIO:
    if sample_rate <= 0:
        raise ValueError(f"sample_rate must be positive; got {sample_rate}")
    if len(audio_bytes) % 2 != 0:
        raise ValueError("PCM int16 audio length must be even")

    audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    buf = io.BytesIO()
    sf.write(buf, audio_array, sample_rate, format="WAV", subtype=subtype)
    buf.seek(0)
    return buf


def get_asr_runtime_status(active_backend: str | None = None) -> dict[str, object]:
    if active_backend and _RUNTIME_STATUS.last_backend != active_backend:
        return {
            "last_asr_text_tail": "",
            "last_asr_elapsed_ms": None,
            "last_asr_backend": "",
        }

    return {
        "last_asr_text_tail": _RUNTIME_STATUS.last_text[-80:],
        "last_asr_elapsed_ms": (
            round(_RUNTIME_STATUS.last_elapsed_ms, 3)
            if _RUNTIME_STATUS.last_elapsed_ms is not None
            else None
        ),
        "last_asr_backend": _RUNTIME_STATUS.last_backend,
    }


async def transcribe_async(audio_bytes: bytes, sample_rate: int, language: str) -> str:
    backend_name = settings.asr_backend
    if backend_name not in _ASR_INSTANCES:
        _ASR_INSTANCES[backend_name] = get_backend("asr", backend_name)()
    backend = _ASR_INSTANCES[backend_name]
    loop = asyncio.get_event_loop()
    started = time.perf_counter()
    text = await loop.run_in_executor(None, backend.transcribe, audio_bytes, sample_rate, language)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    _RUNTIME_STATUS.last_text = text
    _RUNTIME_STATUS.last_elapsed_ms = elapsed_ms
    _RUNTIME_STATUS.last_backend = backend_name
    _logger.info(
        "ASR complete: backend=%s sample_rate=%s audio_bytes=%d text=%r elapsed_ms=%.1f",
        backend_name,
        sample_rate,
        len(audio_bytes),
        text,
        elapsed_ms,
    )
    return text
