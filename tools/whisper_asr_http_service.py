from __future__ import annotations

import asyncio
import io
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import soundfile as sf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


MODEL_NAME = os.environ.get("WHISPER_ASR_MODEL", "large-v3")
DEVICE = os.environ.get("WHISPER_ASR_DEVICE", "cuda")
COMPUTE_TYPE = os.environ.get("WHISPER_ASR_COMPUTE_TYPE", "float16")
BEAM_SIZE = int(os.environ.get("WHISPER_ASR_BEAM_SIZE", "5"))
LOAD_ON_START = _env_bool("WHISPER_ASR_LOAD_ON_START", True)

_model: Any | None = None
_load_lock = threading.Lock()
_inference_lock = threading.Lock()
_status_lock = threading.Lock()
_started_at = time.time()
_load_thread: threading.Thread | None = None
_status: dict[str, Any] = {
    "loaded": False,
    "loading": False,
    "last_asr_elapsed_ms": None,
    "last_error": "",
    "inference_count": 0,
}


def _gpu_info() -> dict[str, Any]:
    try:
        import torch  # type: ignore[import]

        cuda_available = bool(torch.cuda.is_available())
        info: dict[str, Any] = {
            "cuda_available": cuda_available,
            "cuda_device_count": int(torch.cuda.device_count()) if cuda_available else 0,
        }
        if cuda_available:
            index = int(torch.cuda.current_device())
            info["cuda_current_device"] = index
            info["cuda_device_name"] = torch.cuda.get_device_name(index)
        return info
    except Exception as exc:
        return {
            "cuda_available": False,
            "gpu_info_error": f"{type(exc).__name__}: {exc}",
        }


def _set_status(**updates: Any) -> None:
    with _status_lock:
        _status.update(updates)


def _status_snapshot() -> dict[str, Any]:
    with _status_lock:
        status = dict(_status)
    status["loaded"] = _model is not None
    status["started_at"] = datetime.fromtimestamp(_started_at, timezone.utc).isoformat()
    status["started_at_epoch"] = round(_started_at, 3)
    status["uptime_sec"] = round(time.time() - _started_at, 3)
    return status


def _load_model() -> Any:
    global _model
    if _model is not None:
        return _model

    from faster_whisper import WhisperModel  # type: ignore[import]

    with _load_lock:
        if _model is None:
            _set_status(loading=True)
            try:
                _model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)
                _set_status(loaded=True, loading=False, last_error="")
            except Exception as exc:
                _set_status(loading=False, last_error=f"{type(exc).__name__}: {exc}")
                raise
    return _model


def _preload_model() -> None:
    try:
        _load_model()
    except Exception:
        pass


def _start_background_load() -> None:
    global _load_thread
    if _model is not None:
        return
    if _load_thread is not None and _load_thread.is_alive():
        return
    _load_thread = threading.Thread(target=_preload_model, name="whisper-asr-preload", daemon=True)
    _load_thread.start()


def _transcribe_sync(audio_bytes: bytes, language: str) -> tuple[str, str]:
    model = _load_model()
    with _inference_lock:
        segments, detected = model.transcribe(
            io.BytesIO(audio_bytes),
            language=(language or "zh")[:2],
            beam_size=BEAM_SIZE,
        )
        text = "".join(segment.text for segment in segments).strip()
    detected_language = getattr(detected, "language", None) or (language or "zh")[:2]
    return text, detected_language


@asynccontextmanager
async def lifespan(_: FastAPI):
    if LOAD_ON_START:
        _start_background_load()
    yield


app = FastAPI(title="HerUnity Cloud Whisper ASR Service", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "model": MODEL_NAME,
        "device": DEVICE,
        "compute_type": COMPUTE_TYPE,
        "beam_size": BEAM_SIZE,
        **_status_snapshot(),
    }


@app.get("/diagnostics/gpu")
def diagnostics_gpu() -> dict[str, Any]:
    return {
        "ok": True,
        **_status_snapshot(),
        **_gpu_info(),
    }


@app.get("/debug/gpu")
def debug_gpu() -> dict[str, Any]:
    return diagnostics_gpu()


@app.post("/asr")
async def transcribe(
    file: UploadFile = File(...),
    language: str = Form("zh"),
) -> dict[str, Any]:
    started = time.perf_counter()
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="file is empty")

    try:
        info = sf.info(io.BytesIO(audio_bytes))
        duration_ms = round(float(info.duration) * 1000.0, 3)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"WAV parse failed: {exc}") from exc

    try:
        text, detected_language = await asyncio.to_thread(_transcribe_sync, audio_bytes, language)
    except Exception as exc:
        _set_status(last_error=f"{type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail=f"Whisper inference failed: {exc}") from exc

    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    with _status_lock:
        _status["last_asr_elapsed_ms"] = elapsed_ms
        _status["last_error"] = ""
        _status["inference_count"] = int(_status.get("inference_count") or 0) + 1
    return {
        "text": text,
        "language": detected_language,
        "duration_ms": duration_ms,
        "elapsed_ms": elapsed_ms,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "whisper_asr_http_service:app",
        host=os.environ.get("WHISPER_ASR_HOST", "0.0.0.0"),
        port=int(os.environ.get("WHISPER_ASR_PORT", "9002")),
    )
