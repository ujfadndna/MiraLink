#!/usr/bin/env python3
"""Capture a Unity Game View screenshot and ask Claude to analyze it."""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv


PROJECT_ROOT = Path("D:/HerUnity")
ENV_PATH = PROJECT_ROOT / "backend" / ".env"
SCREENSHOT_PATH = PROJECT_ROOT / "Assets" / "Screenshots" / "analysis_capture.png"
UNITY_SKILLS_URL = "http://localhost:8090"
MODEL = "claude-haiku-4-5-20251001"
POLL_INTERVAL_SECONDS = 0.5
POLL_TIMEOUT_SECONDS = 10.0


def trigger_gameview_screenshot() -> dict:
    """Request a Game View screenshot through UnitySkills."""
    payload = {
        "filename": SCREENSHOT_PATH.name,
        "superSize": 1,
        "outputDir": "Assets/Screenshots/",
    }

    result = subprocess.run(
        [
            "curl.exe",
            "-sS",
            "-X",
            "POST",
            f"{UNITY_SKILLS_URL}/skill/gameview_screenshot",
            "-H",
            "Content-Type: application/json; charset=utf-8",
            "--data-binary",
            json.dumps(payload),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    if result.returncode != 0:
        raise RuntimeError(f"curl failed with exit code {result.returncode}: {result.stderr.strip()}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"UnitySkills returned non-JSON response: {result.stdout}") from exc

    if data.get("status") == "error":
        message = data.get("message") or data.get("error") or data
        raise RuntimeError(f"UnitySkills gameview_screenshot failed: {message}")

    result_payload = data.get("result", data)
    if isinstance(result_payload, dict) and result_payload.get("success") is False:
        raise RuntimeError(f"UnitySkills gameview_screenshot failed: {result_payload}")

    return data


def wait_for_screenshot(path: Path) -> None:
    """Poll until the screenshot exists and has readable content."""
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    last_size = -1

    while time.monotonic() <= deadline:
        if path.exists():
            size = path.stat().st_size
            if size > 0 and size == last_size:
                return
            last_size = size
        time.sleep(POLL_INTERVAL_SECONDS)

    raise TimeoutError(f"Screenshot was not written within {POLL_TIMEOUT_SECONDS:.0f}s: {path}")


def encode_png(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def analyze_image(question: str, image_base64: str) -> str:
    load_dotenv(ENV_PATH)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    base_url = os.getenv("ANTHROPIC_BASE_URL")

    if not api_key:
        raise RuntimeError(f"ANTHROPIC_API_KEY is missing from {ENV_PATH}")

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url

    client = Anthropic(**client_kwargs)
    response = client.messages.create(
        model=MODEL,
        max_tokens=800,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_base64,
                        },
                    },
                    {"type": "text", "text": question},
                ],
            }
        ],
    )

    parts = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)

    return "\n".join(parts).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture Unity Game View and ask Claude a vision question."
    )
    parser.add_argument("question", help="Question to ask about the captured screenshot.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        SCREENSHOT_PATH.unlink()
    except FileNotFoundError:
        pass

    screenshot_response = trigger_gameview_screenshot()
    try:
        wait_for_screenshot(SCREENSHOT_PATH)
    except TimeoutError as exc:
        response_json = json.dumps(screenshot_response, ensure_ascii=False)
        raise TimeoutError(f"{exc}; UnitySkills response was: {response_json}") from exc

    analysis = analyze_image(args.question, encode_png(SCREENSHOT_PATH))
    print(analysis)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
