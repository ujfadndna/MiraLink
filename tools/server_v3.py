"""HerUnity public gateway: static ASR UI, backend WS proxy, and WebRTC signalling."""
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import websockets
from websockets import Headers, Response


PORT = int(os.environ.get("PORT", "80"))
BACKEND_WS = os.environ.get("BACKEND_WS", "ws://127.0.0.1:8100/ws/avatar")
BACKEND_WS_BASE = os.environ.get("BACKEND_WS_BASE", "")
TURN_URLS = [url.strip() for url in os.environ.get("TURN_URLS", "").split(",") if url.strip()]
TURN_USERNAME = os.environ.get("TURN_USERNAME", "")
TURN_CREDENTIAL = os.environ.get("TURN_CREDENTIAL", "")
ICE_TRANSPORT_POLICY = os.environ.get("ICE_TRANSPORT_POLICY", "relay" if TURN_URLS else "all")

SCRIPT_DIR = Path(__file__).resolve().parent
FRONTEND_DIR_CANDIDATES = [
    SCRIPT_DIR / "frontend",
    SCRIPT_DIR.parent / "frontend",
]

ICE_SERVERS = [{"urls": "stun:stun.l.google.com:19302"}]
if TURN_URLS and TURN_USERNAME and TURN_CREDENTIAL:
    ICE_SERVERS.append(
        {
            "urls": TURN_URLS if len(TURN_URLS) > 1 else TURN_URLS[0],
            "username": TURN_USERNAME,
            "credential": TURN_CREDENTIAL,
        }
    )

streamer = None
active_viewer = None
active_viewer_id = None


def _frontend_dir() -> Path:
    for candidate in FRONTEND_DIR_CANDIDATES:
        if (candidate / "avatar_touch.html").is_file():
            return candidate
    return FRONTEND_DIR_CANDIDATES[0]


def _response(status: int, body: bytes, content_type: str) -> Response:
    headers = Headers()
    headers["Content-Type"] = content_type
    headers["Content-Length"] = str(len(body))
    headers["Cache-Control"] = "no-store"
    return Response(status, "OK" if status < 400 else "ERROR", headers, body)


def _render_avatar_html() -> bytes:
    avatar_path = _frontend_dir() / "avatar_touch.html"
    if not avatar_path.is_file():
        return b"frontend/avatar_touch.html is missing"

    html = avatar_path.read_text(encoding="utf-8")
    defaults = {
        "iceTransportPolicy": ICE_TRANSPORT_POLICY,
        "iceServers": ICE_SERVERS,
    }
    injection = (
        "<script>"
        "window.HERUNITY_SERVER_DEFAULTS="
        + json.dumps(defaults, ensure_ascii=False, separators=(",", ":"))
        + ";</script>\n"
    )
    marker = '<script>\n"use strict";'
    if marker in html:
        html = html.replace(marker, injection + marker, 1)
    else:
        html = html.replace("</head>", injection + "</head>", 1)
    return html.encode("utf-8")


def _safe_static_file(path: str) -> Path | None:
    if not path.startswith("/frontend/"):
        return None
    rel = path.removeprefix("/frontend/")
    candidate = (_frontend_dir() / rel).resolve()
    frontend_root = _frontend_dir().resolve()
    if candidate == frontend_root or frontend_root in candidate.parents:
        return candidate
    return None


async def process_request(connection, request):
    del connection
    upgrade = request.headers.get("Upgrade", "")
    if upgrade.lower() == "websocket":
        return None

    parsed = urlparse(request.path)
    path = parsed.path
    if path == "/health":
        return _response(200, b'{"status":"ok"}', "application/json; charset=utf-8")

    if path in {"", "/", "/frontend/avatar_touch.html"}:
        data = _render_avatar_html()
        status = 200 if (_frontend_dir() / "avatar_touch.html").is_file() else 500
        content_type = "text/html; charset=utf-8" if status == 200 else "text/plain; charset=utf-8"
        return _response(status, data, content_type)

    static_file = _safe_static_file(path)
    if static_file is None or not static_file.is_file():
        return _response(404, b"not found", "text/plain; charset=utf-8")

    content_type = mimetypes.guess_type(str(static_file))[0] or "application/octet-stream"
    return _response(200, static_file.read_bytes(), content_type)


def _backend_target(parsed) -> str:
    if parsed.path == "/ws/avatar":
        target = BACKEND_WS
    elif BACKEND_WS_BASE:
        target = BACKEND_WS_BASE.rstrip("/") + parsed.path
    else:
        target = BACKEND_WS.rsplit("/", 1)[0] + "/" + parsed.path.rsplit("/", 1)[-1]
    if parsed.query:
        target += "?" + parsed.query
    return target


async def _proxy_backend(ws, parsed) -> None:
    target = _backend_target(parsed)
    print(f"[+]backend_proxy {parsed.path} -> {target}")
    try:
        async with websockets.connect(target, max_size=None) as backend:
            async def client_to_backend():
                async for msg in ws:
                    await backend.send(msg)

            async def backend_to_client():
                async for msg in backend:
                    await ws.send(msg)

            tasks = [
                asyncio.create_task(client_to_backend()),
                asyncio.create_task(backend_to_client()),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
    except Exception as exc:
        print(f"backend proxy err {parsed.path}: {exc}")


async def handle_ws(ws):
    global streamer, active_viewer, active_viewer_id
    path = ws.request.path if hasattr(ws, "request") else "/"
    parsed = urlparse(path)
    query = parse_qs(parsed.query)
    role = query.get("role", [""])[0]
    allow_replace = query.get("replace", ["0"])[0] in ("1", "true", "yes")

    if parsed.path in ("/ws/avatar", "/ws/sensor", "/ws/call"):
        await _proxy_backend(ws, parsed)
        return

    if role != "viewer":
        if streamer and streamer != ws:
            try:
                await streamer.close()
            except Exception:
                pass
        streamer = ws
        print("[+]streamer (Unity)")
        if active_viewer:
            try:
                await streamer.send(
                    json.dumps(
                        {
                            "type": "connect",
                            "connectionId": active_viewer_id,
                            "polite": False,
                        }
                    )
                )
                print(f"[streamer] connect active viewer {active_viewer_id}")
            except Exception as exc:
                print(f"connect active viewer {active_viewer_id} err: {exc}")
        try:
            async for msg in ws:
                if active_viewer:
                    try:
                        await active_viewer.send(msg)
                    except Exception as exc:
                        print(f"forward to viewer {active_viewer_id} err: {exc}")
        except Exception as exc:
            print(f"streamer err: {exc}")
        finally:
            if streamer == ws:
                streamer = None
            print("[-]streamer")
    else:
        cid = uuid.uuid4().hex[:8]
        old_viewer = active_viewer
        old_viewer_id = active_viewer_id
        if old_viewer and old_viewer != ws:
            if not allow_replace:
                print(f"[viewer] reject {cid}; active viewer {old_viewer_id}")
                try:
                    await ws.send(json.dumps({"type": "error", "message": "active viewer already connected"}))
                except Exception:
                    pass
                try:
                    await ws.close(code=4001, reason="active viewer already connected")
                except Exception:
                    pass
                return
            print(f"[viewer] replacing {old_viewer_id} with {cid}")
            active_viewer = None
            active_viewer_id = None
            if streamer:
                try:
                    await streamer.send(json.dumps({"type": "disconnect", "connectionId": old_viewer_id}))
                except Exception as exc:
                    print(f"disconnect old viewer {old_viewer_id} err: {exc}")
            try:
                await old_viewer.close(code=4000, reason="replaced by new viewer")
            except Exception as exc:
                print(f"close old viewer {old_viewer_id} err: {exc}")

        active_viewer = ws
        active_viewer_id = cid
        print(f"[+]viewer {cid} (active)")
        await ws.send(json.dumps({"type": "welcome", "connectionId": cid}))
        connect_msg = json.dumps(
            {
                "type": "connect",
                "connectionId": cid,
                "polite": False,
            }
        )
        if streamer:
            try:
                await streamer.send(connect_msg)
            except Exception:
                pass
        try:
            async for msg in ws:
                if active_viewer != ws:
                    print(f"drop stale viewer {cid} msg")
                    continue
                if streamer:
                    try:
                        await streamer.send(msg)
                    except Exception:
                        pass
        except Exception as exc:
            print(f"viewer {cid} err: {exc}")
        finally:
            is_active = active_viewer == ws
            if is_active:
                active_viewer = None
                active_viewer_id = None
            if streamer and is_active:
                try:
                    await streamer.send(json.dumps({"type": "disconnect", "connectionId": cid}))
                except Exception:
                    pass
            print(f"[-]viewer {cid}" + (" active" if is_active else " stale"))


async def main():
    await websockets.serve(
        handle_ws,
        "0.0.0.0",
        PORT,
        process_request=process_request,
        max_size=None,
    )
    frontend_status = "ok" if (_frontend_dir() / "avatar_touch.html").is_file() else "missing"
    print(f"Ready :{PORT} frontend={frontend_status} icePolicy={ICE_TRANSPORT_POLICY}")
    await asyncio.Future()


asyncio.run(main())
