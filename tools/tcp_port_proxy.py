"""Simple TCP port proxy used for local runtime port bridging."""
from __future__ import annotations

import os
import select
import socket
import socketserver


class ThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def pipe(left: socket.socket, right: socket.socket) -> None:
    try:
        while True:
            readable, _, _ = select.select([left, right], [], [])
            if left in readable:
                data = left.recv(16384)
                if not data:
                    break
                right.sendall(data)
            if right in readable:
                data = right.recv(16384)
                if not data:
                    break
                left.sendall(data)
    finally:
        left.close()
        right.close()


def make_handler(target_host: str, target_port: int):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            try:
                upstream = socket.create_connection((target_host, target_port), timeout=10)
            except OSError as exc:
                print(f"connect target failed: {exc}", flush=True)
                return

            pipe(self.request, upstream)

    return Handler


def main() -> None:
    listen_host = os.environ.get("TCP_PROXY_LISTEN_HOST", "127.0.0.1")
    listen_port = int(os.environ.get("TCP_PROXY_LISTEN_PORT", "0"))
    target_host = os.environ["TCP_PROXY_TARGET_HOST"]
    target_port = int(os.environ["TCP_PROXY_TARGET_PORT"])
    if listen_port <= 0:
        raise RuntimeError("TCP_PROXY_LISTEN_PORT must be positive")

    server = ThreadingTCPServer(
        (listen_host, listen_port),
        make_handler(target_host, target_port),
    )
    print(
        f"TCP proxy {listen_host}:{listen_port} -> {target_host}:{target_port}",
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
