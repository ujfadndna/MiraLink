"""模拟 PC 浏览器触发 M6 sensor 事件。

用法：
    python scripts/test_m6_browser_sim.py <session_id>

示例：
    python scripts/test_m6_browser_sim.py sess_777767c4
"""
from __future__ import annotations

import asyncio
import json
import sys

import websockets

BACKEND_WS = "ws://127.0.0.1:8100"


async def main(session_id: str, event: str) -> int:
    url = f"{BACKEND_WS}/ws/sensor"
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "sensor.bind", "session_id": session_id}))
        bind_resp = await ws.recv()
        print(f"[Sensor] {bind_resp}")

        payload = {
            "type": "sensor.event",
            "session_id": session_id,
            "event": event,
            "zone": None,
            "value": {"simulated": True, "confidence": 1.0},
            "timestamp_ms": 0,
        }
        await ws.send(json.dumps(payload))
        print(f"[Sensor] sent event={event}")

        # 等待后端可能的错误/确认（sensor ws 通常不回复 sensor.event）
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            print(f"[Sensor] response: {msg}")
        except asyncio.TimeoutError:
            print("[Sensor] no immediate response (expected)")

        await asyncio.sleep(1.0)
    return 0


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else ""
    evt = sys.argv[2] if len(sys.argv) > 2 else "pickup"
    if not sid:
        print("Usage: python test_m6_browser_sim.py <session_id> [event]")
        sys.exit(1)
    sys.exit(asyncio.run(main(sid, evt)))
