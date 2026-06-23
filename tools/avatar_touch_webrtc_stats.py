"""Sample avatar_touch WebRTC stats and a video pixel snapshot.

The command writes a JSON report and PNG screenshot to workspace/run by default.
It reads workspace/run/turn_credential.txt when a TURN credential is needed so
sampling URLs stay aligned with the runtime credential used by the start script.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "workspace" / "run"
DEFAULT_TURN_URLS = os.environ.get("TURN_URLS", "")
DEFAULT_TURN_USERNAME = os.environ.get("TURN_USERNAME", "")

PROFILES: dict[str, dict[str, float]] = {
    "baseline": {"min_fps": 7.0, "width": 240, "height": 426},
    "phone_stable": {"min_fps": 10.0, "width": 360, "height": 640},
    "clear": {"min_fps": 10.0, "width": 540, "height": 960},
    "high_fps": {"min_fps": 10.0, "width": 540, "height": 960},
}


def turn_credential_path() -> Path:
    return RUN_DIR / "turn_credential.txt"


def read_turn_credential(required: bool) -> str:
    path = turn_credential_path()
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    if required:
        raise RuntimeError(f"TURN credential file missing: {path}")
    return ""


def mask_url(url: str) -> str:
    parts = urlsplit(url)
    pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in {"turn_credential", "credential"}:
            pairs.append((key, "<redacted>"))
        else:
            pairs.append((key, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))


def with_query(url: str, additions: dict[str, str]) -> str:
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    merged = dict(pairs)
    for key, value in additions.items():
        if value != "":
            merged[key] = value
    query = urlencode(merged)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def default_url(args: argparse.Namespace) -> str:
    host = args.host
    return f"https://{host}:{args.gateway_port}/frontend/avatar_touch.html"


def build_url(args: argparse.Namespace) -> str:
    url = args.url or default_url(args)
    credential = args.turn_credential or read_turn_credential(required=args.ice_policy == "relay")
    additions = {
        "autostart": "1",
        "session": "auto",
        "debug": "1" if args.debug else "",
        "ice_policy": args.ice_policy,
        "turn": args.turn_urls,
        "turn_username": args.turn_username,
        "turn_credential": credential,
    }
    if args.no_turn:
        additions.pop("turn", None)
        additions.pop("turn_username", None)
        additions.pop("turn_credential", None)
    return with_query(url, additions)


def safe_label(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("_") or "current"


def first_video_inbound(stats: list[dict[str, Any]]) -> dict[str, Any] | None:
    for report in stats:
        if report.get("type") == "inbound-rtp" and (
            report.get("kind") == "video" or report.get("mediaType") == "video"
        ):
            return report
    return None


def candidate_pairs(stats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [report for report in stats if report.get("type") == "candidate-pair"]


def public_stats(report: dict[str, Any] | None) -> dict[str, Any]:
    if not report:
        return {}
    keys = [
        "id",
        "timestamp",
        "type",
        "kind",
        "mediaType",
        "ssrc",
        "jitter",
        "packetsLost",
        "packetsReceived",
        "bytesReceived",
        "framesDecoded",
        "framesDropped",
        "framesPerSecond",
        "framesReceived",
        "freezeCount",
        "frameWidth",
        "frameHeight",
        "keyFramesDecoded",
        "nackCount",
        "pauseCount",
        "pliCount",
        "totalFreezesDuration",
        "totalInterFrameDelay",
        "totalPausesDuration",
    ]
    return {key: report[key] for key in keys if key in report}


def public_pair(report: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "id",
        "timestamp",
        "type",
        "state",
        "nominated",
        "writable",
        "bytesReceived",
        "bytesSent",
        "packetsReceived",
        "packetsSent",
        "currentRoundTripTime",
        "availableOutgoingBitrate",
    ]
    return {key: report[key] for key in keys if key in report}


def sample_page(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """async () => {
          const video = document.getElementById('unity-video') || document.querySelector('video');
          const pc = window.videoPc || null;
          let reports = [];
          if (pc && pc.getStats) {
            const stats = await pc.getStats();
            stats.forEach((value) => reports.push(JSON.parse(JSON.stringify(value))));
          }
          const pixel = { nonBlackRatio: 0, brightRatio: 0, avg: 0, error: '' };
          if (video && video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0) {
            const canvas = document.createElement('canvas');
            canvas.width = 160;
            canvas.height = 284;
            const ctx = canvas.getContext('2d', { willReadFrequently: true });
            try {
              ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
              const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
              let nonBlack = 0, bright = 0, total = 0;
              for (let i = 0; i < data.length; i += 4) {
                const y = (data[i] + data[i + 1] + data[i + 2]) / 3;
                total += y;
                if (y > 8) nonBlack += 1;
                if (y > 80) bright += 1;
              }
              const count = data.length / 4;
              pixel.nonBlackRatio = nonBlack / count;
              pixel.brightRatio = bright / count;
              pixel.avg = total / count;
            } catch (err) {
              pixel.error = err && err.message ? err.message : String(err);
            }
          }
          return {
            t: performance.now(),
            video: video ? {
              readyState: video.readyState,
              videoWidth: video.videoWidth || 0,
              videoHeight: video.videoHeight || 0,
              currentTime: video.currentTime || 0,
              paused: video.paused
            } : null,
            pc: pc ? {
              connectionState: pc.connectionState,
              iceConnectionState: pc.iceConnectionState,
              signalingState: pc.signalingState,
              iceGatheringState: pc.iceGatheringState
            } : null,
            reports,
            pixel,
            debugText: (document.getElementById('debug-layer') || {}).innerText || ''
          };
        }"""
    )


def wait_until_connected(page: Page, timeout_ms: int) -> None:
    page.wait_for_function(
        """() => {
          const video = document.getElementById('unity-video') || document.querySelector('video');
          const pc = window.videoPc || null;
          return !!(video && pc && video.readyState >= 2 && video.videoWidth > 0 &&
                    (pc.connectionState === 'connected' || pc.iceConnectionState === 'connected' ||
                     pc.iceConnectionState === 'completed'));
        }""",
        timeout=timeout_ms,
    )


def summarize(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    inbound_before = first_video_inbound(before["reports"])
    inbound_after = first_video_inbound(after["reports"])
    duration = max(0.001, (after["t"] - before["t"]) / 1000.0)
    frames_decoded_delta = int((inbound_after or {}).get("framesDecoded", 0) or 0) - int(
        (inbound_before or {}).get("framesDecoded", 0) or 0
    )
    frames_dropped_delta = int((inbound_after or {}).get("framesDropped", 0) or 0) - int(
        (inbound_before or {}).get("framesDropped", 0) or 0
    )
    bytes_delta = int((inbound_after or {}).get("bytesReceived", 0) or 0) - int(
        (inbound_before or {}).get("bytesReceived", 0) or 0
    )
    fps_decoded = frames_decoded_delta / duration
    bitrate_kbps = bytes_delta * 8 / duration / 1000
    return {
        "duration_sec": duration,
        "fps_decoded": fps_decoded,
        "frames_decoded_delta": frames_decoded_delta,
        "frames_dropped_delta": frames_dropped_delta,
        "frames_dropped_ratio": frames_dropped_delta / max(1, frames_decoded_delta + frames_dropped_delta),
        "bitrate_kbps": bitrate_kbps,
        "packets_lost": int((inbound_after or {}).get("packetsLost", 0) or 0),
        "jitter": float((inbound_after or {}).get("jitter", 0) or 0),
        "framesPerSecond_after": (inbound_after or {}).get("framesPerSecond"),
        "freezeCount": int((inbound_after or {}).get("freezeCount", 0) or 0),
        "frameWidth": (inbound_after or {}).get("frameWidth") or (after.get("video") or {}).get("videoWidth"),
        "frameHeight": (inbound_after or {}).get("frameHeight") or (after.get("video") or {}).get("videoHeight"),
        "pc": after.get("pc"),
        "video": after.get("video"),
        "pixel": after.get("pixel"),
    }


def validate(summary: dict[str, Any], profile: str, min_fps: float | None) -> list[str]:
    failures: list[str] = []
    pc = summary.get("pc") or {}
    video = summary.get("video") or {}
    pixel = summary.get("pixel") or {}
    threshold = min_fps if min_fps is not None else PROFILES.get(profile, PROFILES["phone_stable"])["min_fps"]
    if pc.get("connectionState") != "connected":
        failures.append(f"connectionState={pc.get('connectionState')!r}")
    if pc.get("iceConnectionState") not in {"connected", "completed"}:
        failures.append(f"iceConnectionState={pc.get('iceConnectionState')!r}")
    if int(video.get("readyState") or 0) != 4:
        failures.append(f"video.readyState={video.get('readyState')!r}")
    if int(video.get("videoWidth") or 0) <= 0 or int(video.get("videoHeight") or 0) <= 0:
        failures.append(f"video dimensions={video.get('videoWidth')}x{video.get('videoHeight')}")
    if float(pixel.get("nonBlackRatio") or 0) <= 0.2:
        failures.append(f"nonBlackRatio={pixel.get('nonBlackRatio')!r}")
    if int(summary.get("packets_lost") or 0) > 2:
        failures.append(f"packets_lost={summary.get('packets_lost')}")
    if float(summary.get("frames_dropped_ratio") or 0) >= 0.05:
        failures.append(f"framesDropped ratio={summary.get('frames_dropped_ratio'):.3f}")
    if float(summary.get("fps_decoded") or 0) < threshold:
        failures.append(f"fps_decoded={summary.get('fps_decoded'):.2f} < {threshold:.2f}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--gateway-port", type=int, default=8443)
    parser.add_argument("--label", default="current")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="")
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--connect-timeout", type=float, default=20.0)
    parser.add_argument("--ice-policy", default="relay")
    parser.add_argument("--turn-urls", default=DEFAULT_TURN_URLS)
    parser.add_argument("--turn-username", default=DEFAULT_TURN_USERNAME)
    parser.add_argument("--turn-credential", default="")
    parser.add_argument("--no-turn", action="store_true")
    parser.add_argument("--debug", action="store_true", default=True)
    parser.add_argument("--output-dir", default=str(RUN_DIR))
    parser.add_argument("--min-fps", type=float, default=None)
    parser.add_argument("--viewport-width", type=int, default=390)
    parser.add_argument("--viewport-height", type=int, default=844)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    label = safe_label(args.label or args.profile or "current")
    json_path = output_dir / f"avatar_touch_stats_{label}.json"
    png_path = output_dir / f"avatar_touch_stats_{label}.png"
    profile = args.profile or label if (args.profile or label) in PROFILES else "phone_stable"
    url = build_url(args)

    console_messages: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        context = browser.new_context(
            ignore_https_errors=True,
            viewport={"width": args.viewport_width, "height": args.viewport_height},
            is_mobile=args.viewport_width <= 480,
            has_touch=args.viewport_width <= 480,
        )
        page = context.new_page()
        page.on("console", lambda msg: console_messages.append(f"{msg.type}: {msg.text}"))
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        try:
            wait_until_connected(page, int(args.connect_timeout * 1000))
        except PlaywrightTimeoutError:
            pass
        before = sample_page(page)
        time.sleep(max(0.1, args.duration))
        after = sample_page(page)
        page.screenshot(path=str(png_path), full_page=True)
        browser.close()

    summary = summarize(before, after)
    failures = validate(summary, profile, args.min_fps)
    result = {
        "url": mask_url(url),
        "profile": profile,
        "label": label,
        "passed": not failures,
        "failures": failures,
        "before": {
            **{key: before.get(key) for key in ["t", "video", "pc", "pixel", "debugText"]},
            "inbound": public_stats(first_video_inbound(before["reports"])),
            "candidatePairs": [public_pair(pair) for pair in candidate_pairs(before["reports"])],
        },
        "after": {
            **{key: after.get(key) for key in ["t", "video", "pc", "pixel", "debugText"]},
            "inbound": public_stats(first_video_inbound(after["reports"])),
            "candidatePairs": [public_pair(pair) for pair in candidate_pairs(after["reports"])],
        },
        "summary": summary,
        "console": console_messages[-50:],
        "outputs": {
            "json": str(json_path),
            "png": str(png_path),
        },
    }
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "failures": failures, "summary": summary, "json": str(json_path), "png": str(png_path)}, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
