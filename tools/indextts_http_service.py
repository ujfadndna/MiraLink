from __future__ import annotations

import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import soundfile as sf
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from indextts.infer_v2 import IndexTTS2
from indextts.utils.model_download import ensure_models_available


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


MODEL_DIR = Path(os.environ.get("INDEXTTS_MODEL_DIR", "checkpoints"))
CFG_PATH = Path(os.environ.get("INDEXTTS_CFG_PATH", str(MODEL_DIR / "config.yaml")))
OUTPUT_DIR = Path(os.environ.get("INDEXTTS_OUTPUT_DIR", "outputs/api"))
DEFAULT_PROMPT_WAV = os.environ.get("INDEXTTS_PROMPT_WAV", "examples/voice_01.wav")
USE_FP16 = _env_bool("INDEXTTS_FP16", True)
USE_CUDA_KERNEL = _env_bool("INDEXTTS_CUDA_KERNEL", False)
USE_DEEPSPEED = _env_bool("INDEXTTS_DEEPSPEED", False)
WARMUP_ON_START = _env_bool("INDEXTTS_WARMUP_ON_START", True)
WARMUP_TEXT = os.environ.get("INDEXTTS_WARMUP_TEXT", "你好")

_tts: IndexTTS2 | None = None
_tts_lock = threading.Lock()
_started_at = time.time()
_status_lock = threading.Lock()
_warmup_status: dict[str, Any] = {
    "enabled": WARMUP_ON_START,
    "status": "pending" if WARMUP_ON_START else "disabled",
    "started_at": None,
    "finished_at": None,
    "error": "",
    "elapsed_ms": None,
}
_last_tts_elapsed_ms: float | None = None


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=800)
    language: str = "zh"
    speaker_id: str | None = "default"
    emotion: str | None = None
    speed: float = 1.0


def _emotion_kwargs(emotion: str | None) -> dict[str, Any]:
    if not emotion:
        return {}
    key = emotion.strip().lower()
    vectors = {
        "happy": [0.7, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "joy": [0.7, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "angry": [0.0, 0.7, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "sad": [0.0, 0.0, 0.7, 0.0, 0.0, 0.0, 0.0, 0.0],
        "fear": [0.0, 0.0, 0.0, 0.7, 0.0, 0.0, 0.0, 0.0],
        "disgust": [0.0, 0.0, 0.0, 0.0, 0.7, 0.0, 0.0, 0.0],
        "surprise": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.7, 0.0],
        "calm": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.7],
    }
    vector = vectors.get(key)
    if vector is None:
        return {}
    return {"emo_vector": vector, "emo_alpha": 0.65}


def _load_tts() -> IndexTTS2:
    global _tts
    if _tts is not None:
        return _tts

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    aux_paths = ensure_models_available(str(MODEL_DIR))
    _tts = IndexTTS2(
        cfg_path=str(CFG_PATH),
        model_dir=str(MODEL_DIR),
        use_fp16=USE_FP16,
        use_cuda_kernel=USE_CUDA_KERNEL,
        use_deepspeed=USE_DEEPSPEED,
        aux_paths=aux_paths,
    )
    return _tts


def _infer_to_path(tts: IndexTTS2, text: str, output_path: Path, emotion: str | None = None) -> None:
    tts.infer(
        spk_audio_prompt=DEFAULT_PROMPT_WAV,
        text=text,
        output_path=str(output_path),
        verbose=False,
        max_text_tokens_per_segment=80,
        **_emotion_kwargs(emotion),
    )


def _run_warmup() -> None:
    if not WARMUP_ON_START:
        return

    warmup_path = OUTPUT_DIR / f"warmup_{uuid.uuid4().hex}.wav"
    started = time.perf_counter()
    with _status_lock:
        _warmup_status.update({
            "status": "running",
            "started_at": time.time(),
            "finished_at": None,
            "error": "",
            "elapsed_ms": None,
        })

    try:
        with _tts_lock:
            tts = _load_tts()
            _infer_to_path(tts, WARMUP_TEXT or "你好", warmup_path)
        info = sf.info(str(warmup_path))
        if info.frames <= 0:
            raise RuntimeError("warmup produced an empty wav")
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        with _status_lock:
            _warmup_status.update({
                "status": "complete",
                "finished_at": time.time(),
                "elapsed_ms": elapsed_ms,
            })
    except Exception as exc:
        with _status_lock:
            _warmup_status.update({
                "status": "error",
                "finished_at": time.time(),
                "error": f"{type(exc).__name__}: {exc}",
            })
    finally:
        if warmup_path.exists():
            try:
                warmup_path.unlink()
            except OSError:
                pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    with _tts_lock:
        _load_tts()
    if WARMUP_ON_START:
        threading.Thread(target=_run_warmup, name="indextts-warmup", daemon=True).start()
    yield


app = FastAPI(title="MiraLink IndexTTS2 Service", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, Any]:
    with _status_lock:
        warmup = dict(_warmup_status)
    return {
        "ok": _tts is not None,
        "model_dir": str(MODEL_DIR),
        "prompt_wav": DEFAULT_PROMPT_WAV,
        "uptime_sec": round(time.time() - _started_at, 3),
        "warmup": warmup,
        "last_tts_elapsed_ms": _last_tts_elapsed_ms,
    }


@app.post("/tts")
def synthesize(req: TTSRequest, request: Request) -> dict[str, Any]:
    global _last_tts_elapsed_ms
    filename = f"{uuid.uuid4().hex}.wav"
    output_path = OUTPUT_DIR / filename
    started = time.perf_counter()

    try:
        with _tts_lock:
            tts = _load_tts()
            _infer_to_path(tts, req.text, output_path, req.emotion)
    except Exception as exc:
        if output_path.exists():
            output_path.unlink()
        raise HTTPException(status_code=500, detail=f"IndexTTS2 inference failed: {exc}") from exc

    if not output_path.exists() or output_path.stat().st_size <= 44:
        raise HTTPException(status_code=500, detail="IndexTTS2 did not produce a valid wav file")

    info = sf.info(str(output_path))
    audio_url = str(request.url_for("get_file", filename=filename))
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    _last_tts_elapsed_ms = elapsed_ms
    return {
        "audio_url": audio_url,
        "phoneme_intervals": [],
        "duration_ms": round(info.duration * 1000.0, 3),
        "sample_rate": info.samplerate,
        "elapsed_ms": elapsed_ms,
    }


@app.get("/files/{filename}", name="get_file")
def get_file(filename: str) -> FileResponse:
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=404, detail="not found")
    path = OUTPUT_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, media_type="audio/wav", filename=filename)
