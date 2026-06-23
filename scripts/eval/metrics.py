"""Aggregate metrics for M5 backend evaluation results."""
from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
TESTSET_PATH = EVAL_DIR / "testset.json"
RESULTS_DIR = EVAL_DIR / "results"
METRICS_PATH = RESULTS_DIR / "metrics.json"
VERSIONS = ("V0", "V1", "V2")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_results(version: str) -> list[dict[str, Any]]:
    version_dir = RESULTS_DIR / version
    if not version_dir.exists():
        return []
    return [_load_json(path) for path in sorted(version_dir.glob("*.json"))]


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isfinite(number):
        return number
    return None


def _audio_duration(result: dict[str, Any]) -> float | None:
    return _finite(result.get("audio", {}).get("duration_ms"))


def _viseme_covered(result: dict[str, Any]) -> float | None:
    viseme = result.get("viseme", {})
    covered = _finite(viseme.get("covered_ms"))
    if covered is not None:
        return covered
    return _finite(viseme.get("duration_ms"))


def _stress_times(result: dict[str, Any]) -> list[float]:
    """Return known or proxy emphasis times.

    Current MockTTS has only character-level phoneme intervals, not stress or
    prosody markers. Until real prosody arrives, use chunk boundaries from
    phoneme interval starts/ends as the documented proxy.
    """
    audio = result.get("audio", {})
    times: list[float] = []
    for key in ("stress_times_ms", "emphasis_times_ms"):
        values = audio.get(key)
        if isinstance(values, list):
            times.extend(v for v in (_finite(x) for x in values) if v is not None)
    if times:
        return sorted(times)

    for interval in audio.get("phoneme_intervals", []):
        start = _finite(interval.get("start_ms"))
        end = _finite(interval.get("end_ms"))
        if start is not None:
            times.append(start)
        if end is not None:
            times.append(end)
    return sorted(set(times))


def _nearest_error_ms(value: float, candidates: list[float]) -> float | None:
    if not candidates:
        return None
    return min(abs(value - candidate) for candidate in candidates)


def _gesture_timing_errors(results: list[dict[str, Any]]) -> list[float]:
    errors: list[float] = []
    for result in results:
        if not result.get("ok"):
            continue
        stress_times = _stress_times(result)
        for event in result.get("gesture_events", []):
            apex = _finite(event.get("apex_ms"))
            if apex is None:
                continue
            err = _nearest_error_ms(apex, stress_times)
            if err is not None:
                errors.append(err)
    return errors


def _emotion_consistency(results: list[dict[str, Any]], expected_by_id: dict[str, str]) -> float | None:
    checked = 0
    matched = 0
    for result in results:
        expected = expected_by_id.get(str(result.get("id", "")))
        if not result.get("ok") or not expected:
            continue
        checked += 1
        if str(result.get("emotion", "")).lower() == expected.lower():
            matched += 1
    if checked == 0:
        return None
    return matched / checked


def _category_breakdown(results: list[dict[str, Any]], expected_by_id: dict[str, str]) -> dict[str, Any]:
    by_category: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        by_category.setdefault(str(result.get("category", "unknown")), []).append(result)

    breakdown: dict[str, Any] = {}
    for category, items in sorted(by_category.items()):
        ok_items = [item for item in items if item.get("ok")]
        breakdown[category] = {
            "cases": len(items),
            "ok": len(ok_items),
            "error_count": len(items) - len(ok_items),
            "emotion_consistency": _emotion_consistency(items, expected_by_id),
            "gesture_events": sum(len(item.get("gesture_events", [])) for item in ok_items),
        }
    return breakdown


def compute_metrics() -> dict[str, Any]:
    testset = _load_json(TESTSET_PATH)
    expected_by_id = {
        str(case.get("id", "")): str(case.get("expected_emotion", ""))
        for case in testset
        if case.get("expected_emotion")
    }

    output: dict[str, Any] = {}
    for version in VERSIONS:
        results = _load_results(version)
        ok_results = [result for result in results if result.get("ok")]

        lip_offsets = []
        for result in ok_results:
            if result.get("viseme", {}).get("frame_count", 0) <= 0:
                continue
            audio_duration = _audio_duration(result)
            viseme_covered = _viseme_covered(result)
            if audio_duration is None or viseme_covered is None:
                continue
            lip_offsets.append(viseme_covered - audio_duration)

        gesture_events = [
            event
            for result in ok_results
            for event in result.get("gesture_events", [])
        ]
        gesture_types = [
            str(event.get("type") or event.get("gesture_name") or event.get("anchor_type"))
            for event in gesture_events
            if (event.get("type") or event.get("gesture_name") or event.get("anchor_type"))
        ]
        timing_errors = _gesture_timing_errors(ok_results) if version == "V2" else []

        output[version] = {
            "case_count": len(results),
            "ok_count": len(ok_results),
            "error_count": len(results) - len(ok_results),
            "lip_offset_ms": {
                "mean": mean(lip_offsets) if lip_offsets else None,
                "abs_mean": mean(abs(x) for x in lip_offsets) if lip_offsets else None,
                "sample_count": len(lip_offsets),
            },
            "gesture_timing_error": {
                "mean_ms": mean(timing_errors) if timing_errors else None,
                "sample_count": len(timing_errors),
                "note": (
                    "V2 only. Uses nearest explicit stress/emphasis time when present; "
                    "otherwise nearest phoneme chunk boundary proxy."
                ),
            },
            "gesture_diversity": {
                "unique_types": len(set(gesture_types)),
                "total_events": len(gesture_types),
                "ratio": (len(set(gesture_types)) / len(gesture_types)) if gesture_types else None,
            },
            "emotion_consistency": _emotion_consistency(ok_results, expected_by_id),
            "fps": None,
            "fps_note": "N/A: frame rate is not measurable in this in-process backend harness.",
            "by_category": _category_breakdown(results, expected_by_id),
        }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main() -> int:
    metrics = compute_metrics()
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"Wrote {METRICS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
