#!/usr/bin/env python3
"""Cloud E2E smoke test for the HerUnity avatar WebSocket pipeline.

Checks the remote services over SSH, forwards remote localhost:8100 to a local
port, sends a small avatar conversation over WebSocket, and prints a pass/fail
summary with audio and animation counts.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import select
import socket
import socketserver
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import paramiko

try:
    import websocket
except ImportError:  # pragma: no cover - exercised only on missing dependency
    websocket = None


HOST = os.environ.get("CLOUD_SSH_HOST", "")
PORT = int(os.environ.get("CLOUD_SSH_PORT", "0"))
USER = os.environ.get("CLOUD_SSH_USER", "root")
PW = os.environ.get("CLOUD_SSH_PASSWORD", "")

REMOTE_BACKEND_HOST = "127.0.0.1"
REMOTE_BACKEND_PORT = 8100
REMOTE_SIGNALLING_PORT = 7860
DEFAULT_LOCAL_PORT = 18100

EXPECTED_TYPES = {
    "session.started",
    "state.change",
    "turn.start",
    "audio.chunk",
    "animation.packet",
    "turn.end",
}


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class WsResult:
    ok: bool
    session_id: str | None = None
    received_types: set[str] = field(default_factory=set)
    message_count: int = 0
    audio_chunks: int = 0
    audio_bytes: int = 0
    animation_packets: int = 0
    errors: list[str] = field(default_factory=list)


class ForwardServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_cls: type[socketserver.BaseRequestHandler],
        ssh_transport: paramiko.Transport,
        remote_host: str,
        remote_port: int,
    ) -> None:
        super().__init__(server_address, handler_cls)
        self.ssh_transport = ssh_transport
        self.remote_host = remote_host
        self.remote_port = remote_port


class ForwardHandler(socketserver.BaseRequestHandler):
    request: socket.socket
    server: ForwardServer

    def handle(self) -> None:
        peer_host, peer_port = self.request.getpeername()
        try:
            channel = self.server.ssh_transport.open_channel(
                "direct-tcpip",
                (self.server.remote_host, self.server.remote_port),
                (peer_host, peer_port),
            )
        except Exception as exc:
            print(f"[FAIL] SSH tunnel open_channel failed: {exc}")
            return

        if channel is None:
            print("[FAIL] SSH tunnel open_channel returned no channel")
            return

        try:
            while True:
                readable, _, _ = select.select([self.request, channel], [], [], 10)
                if self.request in readable:
                    data = self.request.recv(65535)
                    if not data:
                        break
                    channel.sendall(data)
                if channel in readable:
                    data = channel.recv(65535)
                    if not data:
                        break
                    self.request.sendall(data)
        finally:
            channel.close()
            self.request.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a cloud E2E test against the HerUnity avatar WebSocket.",
    )
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--user", default=USER)
    parser.add_argument("--password", default=PW)
    parser.add_argument("--local-port", type=int, default=DEFAULT_LOCAL_PORT)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--text", default="你好")
    parser.add_argument("--avatar-id", default="test_001")
    parser.add_argument("--language", default="zh")
    parser.add_argument(
        "--skip-signalling-log",
        action="store_true",
        help="Skip the optional signalling log activity check.",
    )
    return parser.parse_args()


def connect_ssh(args: argparse.Namespace) -> paramiko.SSHClient:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        args.host,
        port=args.port,
        username=args.user,
        password=args.password,
        timeout=20,
        banner_timeout=20,
        auth_timeout=20,
    )
    transport = ssh.get_transport()
    if transport:
        transport.set_keepalive(15)
    return ssh


def run_ssh(ssh: paramiko.SSHClient, command: str, timeout: int = 15) -> tuple[int, str, str]:
    stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
    stdin.close()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    code = stdout.channel.recv_exit_status()
    return code, out, err


def compact(text: str, limit: int = 240) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def check_remote_services(ssh: paramiko.SSHClient) -> list[CheckResult]:
    checks: list[tuple[str, str]] = [
        (
            "backend health :8100",
            "curl -fsS --max-time 5 http://127.0.0.1:8100/health",
        ),
        (
            "signalling HTTP :7860",
            "curl -sS --max-time 5 -o /tmp/e2e_signalling_body -w 'HTTP %{http_code}' http://127.0.0.1:7860/ "
            "&& printf ' ' && head -c 220 /tmp/e2e_signalling_body",
        ),
        (
            "Unity process",
            "pgrep -a -f 'HerUnity\\.x86_64' | grep -v -E 'pgrep|bash -c|sh -c' | head -5",
        ),
    ]

    results: list[CheckResult] = []
    for name, command in checks:
        code, out, err = run_ssh(ssh, command)
        detail = compact(out or err)
        results.append(CheckResult(name=name, ok=code == 0 and bool(out), detail=detail))
    return results


def find_free_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])


def start_port_forward(
    transport: paramiko.Transport,
    local_port: int,
) -> tuple[ForwardServer, threading.Thread, int]:
    bind_port = find_free_port(local_port)
    server = ForwardServer(
        ("127.0.0.1", bind_port),
        ForwardHandler,
        transport,
        REMOTE_BACKEND_HOST,
        REMOTE_BACKEND_PORT,
    )
    thread = threading.Thread(target=server.serve_forever, name="ssh-port-forward", daemon=True)
    thread.start()
    return server, thread, bind_port


def recv_json(ws: Any, timeout: float) -> dict[str, Any]:
    ws.settimeout(timeout)
    raw = ws.recv()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    return json.loads(raw)


def run_ws_test(
    local_port: int,
    timeout: float,
    text: str,
    avatar_id: str,
    language: str,
) -> WsResult:
    if websocket is None:
        return WsResult(
            ok=False,
            errors=[
                "Missing dependency: websocket-client. Install with: "
                "python -m pip install websocket-client"
            ],
        )

    url = f"ws://127.0.0.1:{local_port}/ws/avatar"
    result = WsResult(ok=False)

    try:
        ws = websocket.create_connection(url, timeout=10)
    except Exception as exc:
        result.errors.append(f"WebSocket connect failed: {exc}")
        return result

    try:
        ws.send(json.dumps({"type": "session.start", "avatar_id": avatar_id, "language": language}))

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not result.session_id:
            msg = recv_json(ws, max(0.1, min(5.0, deadline - time.monotonic())))
            record_message(result, msg)
            if msg.get("type") == "session.started":
                result.session_id = msg.get("session_id")
            elif msg.get("type") == "error":
                result.errors.append(f"Backend error before session: {msg.get('message', msg)}")

        if not result.session_id:
            result.errors.append("Did not receive session.started with session_id")
            return result

        ws.send(
            json.dumps(
                {
                    "type": "turn.submit_text",
                    "session_id": result.session_id,
                    "text": text,
                },
                ensure_ascii=False,
            )
        )

        deadline = time.monotonic() + timeout
        saw_turn_end = False
        while time.monotonic() < deadline:
            try:
                msg = recv_json(ws, max(0.1, min(5.0, deadline - time.monotonic())))
            except TimeoutError:
                break
            except websocket.WebSocketTimeoutException:
                break

            record_message(result, msg)
            msg_type = msg.get("type")
            if msg_type == "error":
                result.errors.append(f"Backend error: {msg.get('message', msg)}")
            if msg_type == "turn.end":
                saw_turn_end = True
                break

        missing = EXPECTED_TYPES - result.received_types
        if missing:
            result.errors.append(f"Missing expected message types: {', '.join(sorted(missing))}")
        if not saw_turn_end:
            result.errors.append("Did not receive turn.end before timeout")
        if result.audio_bytes <= 0:
            result.errors.append("Received no TTS audio bytes")
        if result.animation_packets <= 0:
            result.errors.append("Received no animation packets")

        result.ok = not result.errors
        return result
    finally:
        try:
            ws.close()
        except Exception:
            pass


def record_message(result: WsResult, msg: dict[str, Any]) -> None:
    msg_type = str(msg.get("type", ""))
    if msg_type:
        result.received_types.add(msg_type)
    result.message_count += 1

    if msg_type == "audio.chunk":
        result.audio_chunks += 1
        payload = msg.get("base64") or ""
        try:
            result.audio_bytes += len(base64.b64decode(payload, validate=False))
        except Exception:
            result.errors.append(f"Invalid audio.chunk base64 at seq={msg.get('seq')}")
    elif msg_type == "animation.packet":
        result.animation_packets += 1


def check_signalling_log(ssh: paramiko.SSHClient) -> CheckResult:
    command = r"""
set -o pipefail
files="/data/logs/signalling.log /data/signalling.log /tmp/signalling.log"
found=0
matches=""
for f in $files; do
  if [ -f "$f" ]; then
    found=1
    m=$(tail -200 "$f" | grep -Ei 'Unity streamer connected|streamer connected|webrtc|peer|offer|answer|ice|connected' || true)
    if [ -n "$m" ]; then
      matches="${matches}== $f ==\n${m}\n"
    fi
  fi
done
if [ "$found" -eq 0 ] || [ -z "$matches" ]; then
  j=$(journalctl -u signalling --no-pager -n 200 2>/dev/null | grep -Ei 'Unity streamer connected|streamer connected|webrtc|peer|offer|answer|ice|connected' || true)
  if [ -n "$j" ]; then
    matches="${matches}== journalctl -u signalling ==\n${j}\n"
  fi
fi
printf "%b" "$matches"
"""
    code, out, err = run_ssh(ssh, command, timeout=20)
    detail = compact(out or err or "no signalling log activity found")
    ok = code == 0 and bool(out.strip())
    return CheckResult(name="signalling log WebRTC activity", ok=ok, detail=detail)


def print_check_results(results: list[CheckResult]) -> None:
    print("\nRemote service checks")
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        suffix = f" - {result.detail}" if result.detail else ""
        print(f"[{status}] {result.name}{suffix}")


def print_ws_result(result: WsResult) -> None:
    print("\nWebSocket pipeline")
    print(f"[{'PASS' if result.ok else 'FAIL'}] avatar WebSocket E2E")
    print(f"  session_id: {result.session_id or '(none)'}")
    print(f"  messages: {result.message_count}")
    print(f"  received types: {', '.join(sorted(result.received_types)) or '(none)'}")
    print(f"  audio chunks: {result.audio_chunks}")
    print(f"  TTS audio bytes: {result.audio_bytes}")
    print(f"  animation packets: {result.animation_packets}")
    for error in result.errors:
        print(f"  error: {error}")


def main() -> int:
    args = parse_args()
    print(f"Connecting to {args.user}@{args.host}:{args.port} ...")

    ssh: paramiko.SSHClient | None = None
    forward_server: ForwardServer | None = None
    exit_code = 1

    try:
        ssh = connect_ssh(args)
        print("[PASS] SSH connected")

        service_results = check_remote_services(ssh)
        print_check_results(service_results)

        transport = ssh.get_transport()
        if transport is None or not transport.is_active():
            raise RuntimeError("SSH transport is not active")

        forward_server, _, local_port = start_port_forward(transport, args.local_port)
        print(
            f"\n[PASS] SSH tunnel listening: "
            f"127.0.0.1:{local_port} -> remote {REMOTE_BACKEND_HOST}:{REMOTE_BACKEND_PORT}"
        )

        ws_result = run_ws_test(
            local_port=local_port,
            timeout=args.timeout,
            text=args.text,
            avatar_id=args.avatar_id,
            language=args.language,
        )
        print_ws_result(ws_result)

        log_result: CheckResult | None = None
        if not args.skip_signalling_log:
            log_result = check_signalling_log(ssh)
            print("\nSignalling log")
            status = "PASS" if log_result.ok else "WARN"
            print(f"[{status}] {log_result.name} - {log_result.detail}")

        service_ok = all(result.ok for result in service_results)
        exit_code = 0 if service_ok and ws_result.ok else 1

        print("\nSummary")
        print(f"  services: {'PASS' if service_ok else 'FAIL'}")
        print(f"  websocket: {'PASS' if ws_result.ok else 'FAIL'}")
        if log_result is not None:
            print(f"  signalling log: {'PASS' if log_result.ok else 'WARN'}")
        print(f"  overall: {'PASS' if exit_code == 0 else 'FAIL'}")
        return exit_code
    except Exception as exc:
        print(f"\n[FAIL] E2E test crashed: {exc}")
        return 1
    finally:
        if forward_server is not None:
            forward_server.shutdown()
            forward_server.server_close()
        if ssh is not None:
            ssh.close()


if __name__ == "__main__":
    sys.exit(main())
