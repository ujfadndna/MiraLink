"""Local HTTPS/WSS gateway for mobile call testing.

Serves frontend files on https://0.0.0.0:8443 and proxies WebSockets:
  /ws/call, /ws/sensor, /ws/avatar -> FastAPI backend :8100
  other websocket paths             -> RenderStreaming signalling :8080
"""
from __future__ import annotations

import asyncio
import datetime as dt
import ipaddress
import json
import mimetypes
import os
import socket
import ssl
from pathlib import Path
from urllib.parse import urlsplit

import websockets
from websockets import Headers, Response


ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get("HTTPS_GATEWAY_PORT", "8443"))
BACKEND_WS_BASE = os.environ.get("BACKEND_WS_BASE", "ws://127.0.0.1:8100")
SIGNAL_WS_BASE = os.environ.get("SIGNAL_WS_BASE", "ws://127.0.0.1:8080")
TURN_URLS = [url.strip() for url in os.environ.get("TURN_URLS", "").split(",") if url.strip()]
TURN_USERNAME = os.environ.get("TURN_USERNAME", "")
TURN_CREDENTIAL = os.environ.get("TURN_CREDENTIAL", "")
ICE_TRANSPORT_POLICY = os.environ.get("ICE_TRANSPORT_POLICY", "relay" if TURN_URLS else "all")
CERT_DIR = ROOT / "workspace" / "certs"
CERT_FILE = Path(os.environ.get("HTTPS_GATEWAY_CERT", CERT_DIR / "local-gateway.crt"))
KEY_FILE = Path(os.environ.get("HTTPS_GATEWAY_KEY", CERT_DIR / "local-gateway.key"))

ICE_SERVERS = [{"urls": "stun:stun.l.google.com:19302"}]
if TURN_URLS and TURN_USERNAME and TURN_CREDENTIAL:
    ICE_SERVERS.append(
        {
            "urls": TURN_URLS if len(TURN_URLS) > 1 else TURN_URLS[0],
            "username": TURN_USERNAME,
            "credential": TURN_CREDENTIAL,
        }
    )


async def process_request(connection, request):
    upgrade = request.headers.get("Upgrade", "")
    if upgrade.lower() == "websocket":
        return None

    path = urlsplit(request.path).path
    if path in {"", "/"}:
        return _redirect("/frontend/avatar_touch.html")
    if path == "/health":
        return _response(200, b'{"status":"ok"}', "application/json; charset=utf-8")

    file_path = _safe_file_path(path)
    if file_path is None or not file_path.is_file():
        return _response(404, b"not found", "text/plain; charset=utf-8")

    if file_path == (ROOT / "frontend" / "avatar_touch.html").resolve():
        return _response(200, _render_avatar_html(file_path), "text/html; charset=utf-8")

    content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    return _response(200, file_path.read_bytes(), content_type)


async def handle_ws(client_ws):
    source_path = client_ws.request.path if hasattr(client_ws, "request") else "/"
    parsed = urlsplit(source_path)
    if parsed.path in {"/ws/call", "/ws/sensor", "/ws/avatar"}:
        target = f"{BACKEND_WS_BASE}{source_path}"
    else:
        target = f"{SIGNAL_WS_BASE}{source_path}"

    print(f"[proxy] {source_path} -> {target}")
    try:
        async with websockets.connect(target, max_size=None) as upstream_ws:
            async def client_to_upstream():
                async for message in client_ws:
                    await upstream_ws.send(message)

            async def upstream_to_client():
                async for message in upstream_ws:
                    await client_ws.send(message)

            await asyncio.gather(client_to_upstream(), upstream_to_client())
    except Exception as exc:
        print(f"[proxy] closed {source_path}: {exc}")


def _safe_file_path(path: str) -> Path | None:
    rel = path.lstrip("/")
    if not rel:
        return ROOT / "frontend" / "avatar_touch.html"

    candidate = (ROOT / rel).resolve()
    allowed_roots = [(ROOT / "frontend").resolve(), (ROOT / "assets").resolve()]
    if any(candidate == root or root in candidate.parents for root in allowed_roots):
        return candidate
    return None


def _render_avatar_html(file_path: Path) -> bytes:
    html = file_path.read_text(encoding="utf-8")
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


def _response(status: int, body: bytes, content_type: str) -> Response:
    headers = Headers()
    headers["Content-Type"] = content_type
    headers["Content-Length"] = str(len(body))
    headers["Cache-Control"] = "no-store"
    return Response(status, "OK" if status < 400 else "ERROR", headers, body)


def _redirect(location: str) -> Response:
    headers = Headers()
    headers["Location"] = location
    headers["Content-Length"] = "0"
    return Response(302, "Found", headers, b"")


def _ssl_context() -> ssl.SSLContext:
    _ensure_cert()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(CERT_FILE), str(KEY_FILE))
    return context


def _ensure_cert() -> None:
    if CERT_FILE.is_file() and KEY_FILE.is_file():
        return

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError as exc:
        raise RuntimeError(
            "The local HTTPS gateway needs cryptography to create a self-signed certificate. "
            "Install it or set HTTPS_GATEWAY_CERT/HTTPS_GATEWAY_KEY to existing PEM files."
        ) from exc

    CERT_DIR.mkdir(parents=True, exist_ok=True)
    lan_ip = _lan_ip()

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "HerUnity Local Gateway"),
    ])
    san_entries: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    if lan_ip:
        san_entries.append(x509.IPAddress(ipaddress.ip_address(lan_ip)))

    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .sign(key, hashes.SHA256())
    )

    KEY_FILE.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    CERT_FILE.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return ""
    finally:
        sock.close()


async def main() -> None:
    lan_ip = _lan_ip() or "<电脑局域网IP>"
    context = _ssl_context()
    await websockets.serve(
        handle_ws,
        "0.0.0.0",
        PORT,
        process_request=process_request,
        ssl=context,
        max_size=None,
    )
    print(f"Ready https://{lan_ip}:{PORT}/frontend/avatar_touch.html")
    print("Android Chrome must trust/accept the self-signed certificate before microphone access works.")
    print(f"Backend WS: {BACKEND_WS_BASE}  Signalling WS: {SIGNAL_WS_BASE}")
    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
