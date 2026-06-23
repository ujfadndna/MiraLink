"""Generate a self-contained HTML report for M5 backend evaluation."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
METRICS_PATH = RESULTS_DIR / "metrics.json"
REPORT_PATH = RESULTS_DIR / "report.html"
VERSIONS = ("V0", "V1", "V2")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_results(version: str) -> list[dict[str, Any]]:
    version_dir = RESULTS_DIR / version
    if not version_dir.exists():
        return []
    return [_load_json(path) for path in sorted(version_dir.glob("*.json"))]


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return html.escape(str(value))


def _pct(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "N/A"


def _summary_table(metrics: dict[str, Any]) -> str:
    rows = [
        ("Cases OK / Total", lambda m: f"{m.get('ok_count', 0)} / {m.get('case_count', 0)}"),
        ("Lip Offset Mean (ms)", lambda m: _fmt(m.get("lip_offset_ms", {}).get("mean"))),
        ("Lip Offset Abs Mean (ms)", lambda m: _fmt(m.get("lip_offset_ms", {}).get("abs_mean"))),
        ("Gesture Timing Error Mean (ms)", lambda m: _fmt(m.get("gesture_timing_error", {}).get("mean_ms"))),
        ("Gesture Diversity", lambda m: _pct(m.get("gesture_diversity", {}).get("ratio"))),
        ("Gesture Events", lambda m: _fmt(m.get("gesture_diversity", {}).get("total_events"), 0)),
        ("Emotion Consistency", lambda m: _pct(m.get("emotion_consistency"))),
        ("FPS", lambda m: "N/A"),
    ]
    body = []
    for label, getter in rows:
        cells = "".join(f"<td>{getter(metrics.get(version, {}))}</td>" for version in VERSIONS)
        body.append(f"<tr><th>{html.escape(label)}</th>{cells}</tr>")
    return (
        "<table><thead><tr><th>Metric</th><th>V0 Idle</th><th>V1 Lip</th>"
        "<th>V2 SPCG Full</th></tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def _category_table(metrics: dict[str, Any]) -> str:
    categories = sorted(
        {
            category
            for version in VERSIONS
            for category in metrics.get(version, {}).get("by_category", {}).keys()
        }
    )
    rows = []
    for category in categories:
        cells = []
        for version in VERSIONS:
            data = metrics.get(version, {}).get("by_category", {}).get(category, {})
            text = (
                f"{data.get('ok', 0)}/{data.get('cases', 0)} ok, "
                f"emotion {_pct(data.get('emotion_consistency'))}, "
                f"gestures {data.get('gesture_events', 0)}"
            )
            cells.append(f"<td>{html.escape(text)}</td>")
        rows.append(f"<tr><th>{html.escape(category)}</th>{''.join(cells)}</tr>")
    return (
        "<table><thead><tr><th>Category</th><th>V0</th><th>V1</th><th>V2</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _collect_failures(results_by_version: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for version, results in results_by_version.items():
        for result in results:
            expected = result.get("expected_emotion")
            produced = result.get("emotion")
            error = result.get("error")
            mismatch = (
                result.get("ok")
                and expected
                and produced
                and str(expected).lower() != str(produced).lower()
            )
            if error or mismatch:
                failures.append(
                    {
                        "version": version,
                        "id": result.get("id", ""),
                        "category": result.get("category", ""),
                        "input": result.get("input", ""),
                        "expected": expected,
                        "produced": produced,
                        "reason": (
                            f"{error.get('type')}: {error.get('message')}"
                            if isinstance(error, dict)
                            else "emotion mismatch"
                        ),
                    }
                )
    return failures


def _failures_section(failures: list[dict[str, Any]]) -> str:
    if not failures:
        return "<p class=\"muted\">No case errors or emotion mismatches in current results.</p>"
    rows = []
    for failure in failures:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(failure['version']))}</td>"
            f"<td>{html.escape(str(failure['id']))}</td>"
            f"<td>{html.escape(str(failure['category']))}</td>"
            f"<td>{html.escape(str(failure['expected']))}</td>"
            f"<td>{html.escape(str(failure['produced']))}</td>"
            f"<td>{html.escape(str(failure['reason']))}</td>"
            f"<td>{html.escape(str(failure['input']))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Version</th><th>Case</th><th>Category</th>"
        "<th>Expected Emotion</th><th>Produced Emotion</th><th>Reason</th>"
        "<th>Input</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def generate_report() -> Path:
    metrics = _load_json(METRICS_PATH)
    results_by_version = {version: _load_results(version) for version in VERSIONS}
    failures = _collect_failures(results_by_version)

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>MiraLink M5 Backend Evaluation</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #1c2430;
      --muted: #657080;
      --line: #d9dee7;
      --accent: #1967d2;
      --accent-soft: #e8f0fe;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 32px 24px 48px;
    }}
    header {{
      margin-bottom: 24px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 28px;
      letter-spacing: 0;
    }}
    h2 {{
      margin: 28px 0 12px;
      font-size: 18px;
      letter-spacing: 0;
    }}
    p {{
      margin: 0 0 12px;
      color: var(--muted);
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      margin-bottom: 18px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 12px;
      text-align: left;
      vertical-align: top;
    }}
    thead th {{
      background: var(--accent-soft);
      color: #173b68;
      font-weight: 650;
    }}
    tbody th {{
      width: 230px;
      font-weight: 650;
    }}
    tr:last-child th, tr:last-child td {{
      border-bottom: 0;
    }}
    .muted {{
      color: var(--muted);
    }}
    .note {{
      border-left: 4px solid var(--accent);
      padding-left: 12px;
      margin-top: 12px;
    }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>MiraLink M5 Backend Evaluation</h1>
    <p>In-process comparison of V0 idle baseline, V1 lip sync, and V2 SPCG full behavior planning.</p>
  </header>

  <section class="panel">
    <h2>Summary Metrics</h2>
    {_summary_table(metrics)}
    <p class="note">Gesture timing uses explicit stress/emphasis markers when available. Current MockTTS falls back to nearest phoneme chunk boundary, so V2 timing error is a proxy until real prosody lands. FPS is not measured by this backend-only harness.</p>
  </section>

  <section class="panel">
    <h2>Per-Category Breakdown</h2>
    {_category_table(metrics)}
  </section>

  <section class="panel">
    <h2>Failures and Emotion Mismatches</h2>
    {_failures_section(failures)}
  </section>
</main>
</body>
</html>
"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html_doc, encoding="utf-8")
    return REPORT_PATH


def main() -> int:
    path = generate_report()
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
