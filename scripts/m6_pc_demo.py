"""M6 PC 演示辅助脚本

1. 启动本地 HTTP 服务器提供 frontend/sensor_controller.html
2. 模拟一个常驻 Unity Avatar 客户端，打印收到的所有消息
3. 控制台输出 session_id 和访问 URL，供浏览器测试使用

用法：
    python scripts/m6_pc_demo.py

然后在 PC 浏览器打开 http://127.0.0.1:8081/sensor_controller.html
输入 Unity HUD 上的 session_id（或本脚本打印的 session_id），点击连接，
再用页面底部的 PC 模拟按钮触发 pickup/putdown/shake 等事件。
"""
from __future__ import annotations

import asyncio
import functools
import http.server
import json
import socketserver
import sys
import threading
import websockets

BACKEND_WS = "ws://127.0.0.1:8100"
HTTP_PORT = 8081
FRONTEND_DIR = "frontend"

session_id: str | None = None


def flog(msg: str) -> None:
    print(msg, flush=True)


async def avatar_client() -> None:
    """常驻模拟 Unity Avatar 客户端。"""
    global session_id
    async with websockets.connect(f"{BACKEND_WS}/ws/avatar") as ws:
        await ws.send(json.dumps({"type": "session.start", "avatar_id": "vrm_female_001", "language": "zh"}))
        flog("[Avatar] waiting for session.started...")
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            t = data.get("type")
            if t == "session.started":
                session_id = data["session_id"]
                flog(f"[Avatar] session_id = {session_id}")
                flog(f"[HTTP] 请打开 http://127.0.0.1:{HTTP_PORT}/sensor_controller.html")
                flog(f"[HTTP] 在页面 Session ID 输入框填入: {session_id}")
            elif t == "turn.start":
                flog(f"[Avatar] turn.start emotion={data.get('emotion')} act={data.get('dialogue_act')} gestures={len(data.get('gesture_events', []))}")
            elif t == "turn.end":
                flog(f"[Avatar] turn.end {data.get('turn_id')}")
            elif t == "audio.chunk":
                flog(f"[Avatar] audio.chunk seq={data.get('seq')}")
            elif t == "animation.packet":
                flog(f"[Avatar] animation.packet seq={data.get('seq')} blendshapes={list(data.get('blendshapes', {}).keys())}")
            elif t == "error":
                flog(f"[Avatar] error: {data.get('message')}")
            else:
                flog(f"[Avatar] {t}: {json.dumps(data, ensure_ascii=False)[:120]}")


def run_http_server() -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=FRONTEND_DIR)
    with socketserver.TCPServer(("", HTTP_PORT), handler) as httpd:
        flog(f"[HTTP] serving {FRONTEND_DIR} at http://127.0.0.1:{HTTP_PORT}")
        httpd.serve_forever()


async def main() -> None:
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()
    await avatar_client()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
