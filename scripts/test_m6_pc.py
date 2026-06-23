"""M6 PC 测试脚本

模拟 Unity Avatar 客户端 + 手机 sensor 页面，验证 M6 链路：
sensor.event -> /ws/sensor -> SensorReactionEngine -> _handle_sensor_reaction -> /ws/avatar

用法：
1. 启动后端：uvicorn app.main:app --host 0.0.0.0 --port 8100
2. 运行：python scripts/test_m6_pc.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import websockets

BACKEND_WS = "ws://127.0.0.1:8100"


async def avatar_client(session_id_holder: dict, messages: list) -> None:
    """模拟 Unity Avatar，连接 /ws/avatar。"""
    async with websockets.connect(f"{BACKEND_WS}/ws/avatar") as ws:
        await ws.send(json.dumps({"type": "session.start", "avatar_id": "vrm_female_001", "language": "zh"}))
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
            except asyncio.TimeoutError:
                messages.append({"type": "timeout", "note": "avatar client idle timeout"})
                break
            data = json.loads(msg)
            messages.append(data)
            if data.get("type") == "session.started":
                session_id_holder["id"] = data["session_id"]
                print(f"[Avatar] session started: {data['session_id']}")
            elif data.get("type") == "turn.start":
                print(f"[Avatar] turn.start emotion={data.get('emotion')} act={data.get('dialogue_act')}")
            elif data.get("type") == "turn.end":
                print(f"[Avatar] turn.end {data.get('turn_id')}")
                # 收到一次完整 sensor reaction 后退出
                break
            elif data.get("type") == "error":
                print(f"[Avatar] error: {data.get('message')}")
                break


async def sensor_client(session_id: str) -> None:
    """模拟手机 sensor_controller.html，连接 /ws/sensor。"""
    async with websockets.connect(f"{BACKEND_WS}/ws/sensor") as ws:
        await ws.send(json.dumps({"type": "sensor.bind", "session_id": session_id}))
        bound = await ws.recv()
        print(f"[Sensor] {bound}")

        event = {
            "type": "sensor.event",
            "session_id": session_id,
            "event": "pickup",
            "zone": None,
            "value": {"beta": 75.0, "gamma": 5.0, "confidence": 0.95, "simulated": True},
            "timestamp_ms": 0,
        }
        await ws.send(json.dumps(event))
        print(f"[Sensor] sent pickup event")
        # 等待后端处理完成
        await asyncio.sleep(0.5)


async def main() -> int:
    session_id_holder: dict = {}
    messages: list = []

    avatar_task = asyncio.create_task(avatar_client(session_id_holder, messages))
    # 等待 session 创建
    for _ in range(50):
        await asyncio.sleep(0.1)
        if session_id_holder.get("id"):
            break
    else:
        print("ERROR: avatar session not started in time")
        avatar_task.cancel()
        return 1

    await sensor_client(session_id_holder["id"])
    await avatar_task

    # 简单断言
    types = {m.get("type") for m in messages}
    required = {"session.started", "state.change", "turn.start", "audio.chunk", "animation.packet", "turn.end"}
    missing = required - types
    if missing:
        print(f"FAIL: missing message types: {missing}")
        return 1

    turn_starts = [m for m in messages if m.get("type") == "turn.start"]
    if not turn_starts or turn_starts[0].get("dialogue_act") != "sensor_reaction":
        print("FAIL: expected sensor_reaction turn")
        return 1

    print("PASS: M6 sensor -> avatar E2E works on PC")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
