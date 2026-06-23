"""TTS 服务。Mock 实现生成占位音频 + 均匀音素时间戳。"""
from __future__ import annotations

import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
import numpy as np
import soundfile as sf

from app import storage
from app.config import settings
from app.schemas import AudioWithTimestamps, PhonemeInterval, SynthesizeRequest
from app.services.base import get_backend, register

_SEC_PER_CHAR = 0.18
_SEC_PER_WORD = 0.30
_MIN_DURATION = 0.5
_TONE_HZ = 220.0
_TONE_AMP = 0.02
_logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TtsRuntimeStatus:
    last_elapsed_ms: float | None = None
    last_backend: str = ""


_RUNTIME_STATUS = TtsRuntimeStatus()


class TTSBackend(ABC):
    @abstractmethod
    def run(self, req: SynthesizeRequest) -> AudioWithTimestamps:
        ...


def _is_chinese(language: str) -> bool:
    return language.lower().startswith("zh")


def _tokenize(text: str, language: str) -> list[str]:
    if _is_chinese(language):
        return [c for c in text if not c.isspace()]
    return [w for w in re.split(r"\s+", text.strip()) if w]


def _estimate_duration(tokens: list[str], language: str, speed: float) -> float:
    per = _SEC_PER_CHAR if _is_chinese(language) else _SEC_PER_WORD
    speed = speed if speed > 0 else 1.0
    return max(len(tokens) * per / speed, _MIN_DURATION)


def _build_phoneme_intervals(tokens: list[str], duration_ms: float) -> list[PhonemeInterval]:
    if not tokens or duration_ms <= 0:
        return []
    n = len(tokens)
    intervals: list[PhonemeInterval] = []
    for i, tok in enumerate(tokens):
        start = i * duration_ms / n
        end = (i + 1) * duration_ms / n
        intervals.append(PhonemeInterval(phoneme=tok, start_ms=start, end_ms=end))
    return intervals


@register("tts", "mock")
class MockTTS(TTSBackend):
    def run(self, req: SynthesizeRequest) -> AudioWithTimestamps:
        sample_rate = settings.tts_sample_rate
        audio_id = storage.new_id("aud")

        tokens = _tokenize(req.text, req.language)
        duration_sec = _estimate_duration(tokens, req.language, req.speed)
        duration_ms = duration_sec * 1000.0

        # 生成占位波形
        num_samples = int(round(duration_sec * sample_rate))
        t = np.arange(num_samples, dtype=np.float32) / sample_rate
        waveform = (_TONE_AMP * np.sin(2.0 * np.pi * _TONE_HZ * t)).astype(np.float32)

        out_dir = storage.audio_dir(audio_id)
        wav_path = out_dir / "tts.wav"
        sf.write(str(wav_path), waveform, sample_rate)

        phoneme_intervals = _build_phoneme_intervals(tokens, duration_ms)

        return AudioWithTimestamps(
            audio_id=audio_id,
            audio_path=str(wav_path),
            duration_ms=duration_ms,
            sample_rate=sample_rate,
            phoneme_intervals=phoneme_intervals,
            phoneme_fallback=True,
        )


@register("tts", "indextts")
class IndexTTS2Backend(TTSBackend):
    """IndexTTS2 后端。通过 HTTP API 调用远程 IndexTTS2 服务。"""

    def run(self, req: SynthesizeRequest) -> AudioWithTimestamps:
        api_url = settings.indextts_api_url
        if not api_url:
            raise RuntimeError("INDEXTTS_API_URL is not configured")
        api_url = api_url.rstrip("/")
        timeout_sec = max(float(settings.indextts_http_timeout_sec), 1.0)

        # 调用 IndexTTS2 HTTP API
        try:
            resp = httpx.post(
                f"{api_url}/tts",
                json={
                    "text": req.text,
                    "language": req.language,
                    "speaker_id": req.speaker_id,
                    "emotion": req.emotion,
                    "speed": req.speed,
                },
                timeout=timeout_sec,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text[:300]
            raise RuntimeError(f"IndexTTS2 HTTP failed: status={status} body={body!r}") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"IndexTTS2 HTTP failed: {exc}") from exc

        try:
            result = resp.json()
        except ValueError as exc:
            raise RuntimeError("IndexTTS2 response JSON parse failed") from exc
        if not isinstance(result, dict):
            raise RuntimeError(f"IndexTTS2 response JSON must be an object; got {type(result).__name__}")

        # 下载 WAV 文件
        audio_url = result.get("audio_url")
        if not audio_url:
            keys = sorted(str(key) for key in result.keys())
            raise RuntimeError(f"IndexTTS2 response missing required field 'audio_url'; keys={keys}")

        try:
            audio_resp = httpx.get(audio_url, timeout=timeout_sec)
            audio_resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text[:300]
            raise RuntimeError(f"IndexTTS2 WAV download failed: status={status} body={body!r}") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"IndexTTS2 WAV download failed: {exc}") from exc

        # 保存 WAV 到本地
        audio_id = storage.new_id("aud")
        out_dir = storage.audio_dir(audio_id)
        wav_path = out_dir / "tts.wav"
        wav_path.write_bytes(audio_resp.content)

        # 读取音频元数据
        try:
            data, sample_rate = sf.read(str(wav_path), dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)
            duration_ms = len(data) / sample_rate * 1000.0
        except Exception as exc:
            raise RuntimeError(f"IndexTTS2 WAV parse failed: path={wav_path.name} error={exc}") from exc

        # 构建 phoneme intervals（从 API 响应获取，fallback 到均匀分布）
        phoneme_intervals = []
        raw_phonemes = result.get("phoneme_intervals", [])
        phoneme_fallback = False
        if raw_phonemes:
            phoneme_intervals = [
                PhonemeInterval(
                    phoneme=str(p.get("phoneme", "")),
                    start_ms=float(p.get("start_ms", 0.0)),
                    end_ms=float(p.get("end_ms", 0.0)),
                )
                for p in raw_phonemes
            ]
        else:
            tokens = _tokenize(req.text, req.language)
            phoneme_intervals = _build_phoneme_intervals(tokens, duration_ms)
            phoneme_fallback = True

        return AudioWithTimestamps(
            audio_id=audio_id,
            audio_path=str(wav_path),
            duration_ms=duration_ms,
            sample_rate=int(sample_rate),
            phoneme_intervals=phoneme_intervals,
            phoneme_fallback=phoneme_fallback,
        )


def run_tts(req: SynthesizeRequest) -> AudioWithTimestamps:
    backend = settings.tts_backend
    started = time.perf_counter()
    result = get_backend("tts", backend)().run(req)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    _RUNTIME_STATUS.last_elapsed_ms = elapsed_ms
    _RUNTIME_STATUS.last_backend = backend
    _logger.info(
        "TTS complete: backend=%s audio_path=%s sample_rate=%s duration_ms=%.1f phoneme_fallback=%s elapsed_ms=%.1f",
        backend,
        result.audio_path,
        result.sample_rate,
        result.duration_ms,
        result.phoneme_fallback,
        elapsed_ms,
    )
    return result


def get_tts_runtime_status(active_backend: str | None = None) -> dict[str, object]:
    if active_backend and _RUNTIME_STATUS.last_backend != active_backend:
        return {
            "last_tts_elapsed_ms": None,
            "last_tts_backend": "",
        }

    return {
        "last_tts_elapsed_ms": (
            round(_RUNTIME_STATUS.last_elapsed_ms, 3)
            if _RUNTIME_STATUS.last_elapsed_ms is not None
            else None
        ),
        "last_tts_backend": _RUNTIME_STATUS.last_backend,
    }
