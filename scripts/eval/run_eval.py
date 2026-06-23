"""M5 backend evaluation batch runner.

Runs Agent, TTS, viseme, and gesture services in-process and writes raw JSON
results per case/version under scripts/eval/results/.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.schemas import SynthesizeRequest  # noqa: E402
from app.services.agent import get_agent  # noqa: E402
from app.services.gesture import compute_gesture_events  # noqa: E402
from app.services.tts import run_tts  # noqa: E402
from app.services.viseme import compute_viseme_curve  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
TESTSET_PATH = EVAL_DIR / "testset.json"
RESULTS_DIR = EVAL_DIR / "results"
ALL_VERSIONS = ("V0", "V1", "V2")


def _model_dump(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    return {}


def _float_attr(obj: Any, names: tuple[str, ...], default: float = 0.0) -> float:
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    data = _model_dump(obj)
    for name in names:
        if name in data and data[name] is not None:
            try:
                return float(data[name])
            except (TypeError, ValueError):
                pass
    return default


def _str_attr(obj: Any, names: tuple[str, ...], default: str = "") -> str:
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return str(value)
    data = _model_dump(obj)
    for name in names:
        if data.get(name) is not None:
            return str(data[name])
    return default


def _list_attr(obj: Any, names: tuple[str, ...]) -> list[Any]:
    for name in names:
        value = getattr(obj, name, None)
        if isinstance(value, list):
            return value
    data = _model_dump(obj)
    for name in names:
        value = data.get(name)
        if isinstance(value, list):
            return value
    return []


def _frame_time(frame: Any) -> tuple[float, float]:
    return (
        _float_attr(frame, ("start_ms", "time_ms", "timestamp_ms", "start"), 0.0),
        _float_attr(frame, ("end_ms", "end", "time_ms", "timestamp_ms"), 0.0),
    )


def _viseme_summary(viseme_curve: Any | None) -> dict[str, Any]:
    if viseme_curve is None:
        return {
            "frame_count": 0,
            "covered_ms": 0.0,
            "duration_ms": None,
            "frames": [],
        }

    frames = _list_attr(viseme_curve, ("frames", "blendshape_frames"))
    serialized_frames: list[dict[str, Any]] = []
    covered_ms = 0.0
    first_start: float | None = None
    last_end: float | None = None

    for frame in frames:
        start_ms, end_ms = _frame_time(frame)
        weights = getattr(frame, "weights", None)
        if weights is None:
            weights = _model_dump(frame).get("weights", {})
        if first_start is None:
            first_start = start_ms
        last_end = max(last_end or end_ms, end_ms)
        covered_ms += max(0.0, end_ms - start_ms)
        serialized_frames.append(
            {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "weights": weights if isinstance(weights, dict) else {},
            }
        )

    if first_start is not None and last_end is not None:
        timeline_covered_ms = max(0.0, last_end - first_start)
    else:
        timeline_covered_ms = 0.0

    return {
        "frame_count": len(frames),
        "covered_ms": timeline_covered_ms or covered_ms,
        "duration_ms": _float_attr(viseme_curve, ("duration_ms", "total_ms"), 0.0),
        "frames": serialized_frames,
    }


def _phoneme_summary(tts_result: Any) -> list[dict[str, Any]]:
    intervals = _list_attr(tts_result, ("phoneme_intervals", "phonemes", "timestamps"))
    output: list[dict[str, Any]] = []
    for interval in intervals:
        output.append(
            {
                "phoneme": _str_attr(interval, ("phoneme", "text", "token"), ""),
                "start_ms": _float_attr(interval, ("start_ms", "start", "time_ms"), 0.0),
                "end_ms": _float_attr(interval, ("end_ms", "end"), 0.0),
            }
        )
    return output


def _gesture_summary(events: list[Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for event in events:
        gesture_name = _str_attr(event, ("gesture_name", "name", "type"), "")
        anchor_type = _str_attr(event, ("anchor_type", "type", "semantic_type"), "")
        start_ms = _float_attr(event, ("start_ms", "time_ms", "start"), 0.0)
        duration_ms = _float_attr(event, ("duration_ms", "duration"), 0.0)
        apex_ms = _float_attr(event, ("apex_ms", "apex_time_ms", "apex", "time_ms"), start_ms)
        output.append(
            {
                "type": gesture_name or anchor_type,
                "gesture_name": gesture_name,
                "anchor_type": anchor_type,
                "start_ms": start_ms,
                "apex_ms": apex_ms,
                "duration_ms": duration_ms,
                "end_ms": start_ms + duration_ms,
                "intensity": _float_attr(event, ("intensity", "weight"), 0.0),
            }
        )
    return output


def _audio_summary(tts_result: Any) -> dict[str, Any]:
    return {
        "audio_path": _str_attr(tts_result, ("audio_path", "path", "wav_path"), ""),
        "audio_id": _str_attr(tts_result, ("audio_id", "id"), ""),
        "duration_ms": _float_attr(tts_result, ("duration_ms", "duration", "total_ms"), 0.0),
        "sample_rate": int(_float_attr(tts_result, ("sample_rate", "sr"), 0.0)),
        "phoneme_intervals": _phoneme_summary(tts_result),
    }


def _base_result(case: dict[str, Any], version: str) -> dict[str, Any]:
    return {
        "version": version,
        "id": case.get("id", ""),
        "category": case.get("category", ""),
        "input": case.get("input", ""),
        "expected_emotion": case.get("expected_emotion"),
        "expected_acts": case.get("expected_acts", []),
        "expected_gesture_types": case.get("expected_gesture_types", []),
        "ok": False,
        "error": None,
    }


def _write_result(version: str, case_id: str, payload: dict[str, Any]) -> None:
    out_dir = RESULTS_DIR / version
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{case_id}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def _run_case_version(
    case: dict[str, Any],
    version: str,
    agent_response: Any | None = None,
    tts_result: Any | None = None,
) -> dict[str, Any]:
    result = _base_result(case, version)
    try:
        if agent_response is None:
            session_id = f"m5_eval_{version}_{case.get('id', 'case')}"
            agent_response = await get_agent().generate(str(case.get("input", "")), session_id)
        reply_text = _str_attr(agent_response, ("reply_text", "text", "content"), "")
        emotion = _str_attr(agent_response, ("emotion",), "neutral")
        dialogue_act = _str_attr(agent_response, ("dialogue_act", "act"), "unknown")

        if tts_result is None:
            tts_result = run_tts(SynthesizeRequest(text=reply_text, emotion=emotion))

        viseme_curve = None
        gesture_events: list[Any] = []
        if version in ("V1", "V2"):
            viseme_curve = compute_viseme_curve(tts_result)
        if version == "V2":
            gesture_events = compute_gesture_events(reply_text, tts_result, emotion)

        result.update(
            {
                "ok": True,
                "reply_text": reply_text,
                "emotion": emotion,
                "dialogue_act": dialogue_act,
                "audio": _audio_summary(tts_result),
                "viseme": _viseme_summary(viseme_curve),
                "gesture_events": _gesture_summary(gesture_events),
            }
        )
    except Exception as exc:  # noqa: BLE001 - eval must continue per case
        result.update(
            {
                "ok": False,
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                },
            }
        )
    return result


async def run_batch(versions: tuple[str, ...], limit: int | None) -> int:
    cases = json.loads(TESTSET_PATH.read_text(encoding="utf-8"))
    if limit is not None:
        cases = cases[:limit]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    total = len(cases) * len(versions)
    completed = 0

    for case in cases:
        case_id = str(case.get("id", "case"))
        shared_agent_response: Any | None = None
        shared_tts_result: Any | None = None

        try:
            session_id = f"m5_eval_{case_id}"
            shared_agent_response = await get_agent().generate(str(case.get("input", "")), session_id)
            reply_text = _str_attr(shared_agent_response, ("reply_text", "text", "content"), "")
            emotion = _str_attr(shared_agent_response, ("emotion",), "neutral")
            shared_tts_result = run_tts(SynthesizeRequest(text=reply_text, emotion=emotion))
        except Exception:
            shared_agent_response = None
            shared_tts_result = None

        for version in versions:
            payload = await _run_case_version(case, version, shared_agent_response, shared_tts_result)
            _write_result(version, case_id, payload)
            completed += 1
            status = "ok" if payload.get("ok") else "ERROR"
            print(f"[{completed}/{total}] {version} {case_id} {case.get('category')} {status}")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run M5 backend evaluation harness.")
    parser.add_argument(
        "--versions",
        default="V0,V1,V2",
        help="Comma-separated versions to run: V0,V1,V2",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit number of test cases.")
    return parser.parse_args()


def normalize_versions(raw: str) -> tuple[str, ...]:
    versions = tuple(v.strip().upper() for v in raw.split(",") if v.strip())
    invalid = [v for v in versions if v not in ALL_VERSIONS]
    if invalid:
        raise SystemExit(f"Invalid version(s): {', '.join(invalid)}. Use V0,V1,V2.")
    return versions or ALL_VERSIONS


def main() -> int:
    args = parse_args()
    versions = normalize_versions(args.versions)
    return asyncio.run(run_batch(versions, args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
