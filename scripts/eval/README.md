# MiraLink M5 Backend Evaluation

This harness runs the M5 backend evaluation in-process. It does not require Unity, a running FastAPI server, or a WebSocket client.

## Files

- `testset.json`: Chinese test prompts covering self-introduction, explanation, enumeration, contrast, emotion, and scene pointing.
- `run_eval.py`: Async batch runner for V0, V1, and V2.
- `metrics.py`: Aggregates raw results into `results/metrics.json`.
- `report.py`: Generates a self-contained static `results/report.html`.

## Run

From the repository root:

```bash
python scripts/eval/run_eval.py
python scripts/eval/metrics.py
python scripts/eval/report.py
```

Open `scripts/eval/results/report.html` after the report step.

For a quick smoke run:

```bash
python scripts/eval/run_eval.py --limit 3
python scripts/eval/metrics.py
python scripts/eval/report.py
```

You can run selected versions:

```bash
python scripts/eval/run_eval.py --versions V1,V2 --limit 10
```

## Version Definitions

- `V0`: Agent + TTS only. No viseme curve, no gesture events.
- `V1`: Agent + TTS + viseme curve. No gesture events.
- `V2`: Agent + TTS + viseme curve + SPCG gesture events.

## Notes

The scripts add `backend/` to `sys.path` and import the existing services read-only. No backend server is started.

The current backend automatically uses `MockAgent` and `MockTTS` when no API key or GPU-backed service is configured. That makes the harness runnable on a normal development machine, but timing quality should be interpreted as a proxy.

The headline M5 comparison is `V2` gesture timing error against the `V1` lip-only baseline. In this backend-only harness, `V1` has no gesture events, so the metric is reported as N/A for V1. Once real prosody/stress data lands, the target is at least a 30% improvement for V2 timing alignment over a comparable non-SPCG gesture baseline.
