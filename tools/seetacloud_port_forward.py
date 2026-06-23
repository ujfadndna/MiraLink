"""Forward TCP ports to/from a SeeTaCloud service over SSH.

Required SSH environment variables:
  SEETA_SSH_HOST, SEETA_SSH_PORT, SEETA_SSH_USER, SEETA_SSH_PASSWORD

Port environment variables:
  TUNNEL_LOCAL_HOST, TUNNEL_LOCAL_PORT, TUNNEL_REMOTE_HOST, TUNNEL_REMOTE_PORT
  TUNNEL_MODE=forward|reverse

The legacy INDEXTTS_* variables are still accepted for the IndexTTS2 tunnel.
"""
from __future__ import annotations

import os
import select
import socket
import socketserver
import threading
from dataclasses import dataclass

import paramiko


@dataclass(frozen=True)
class TunnelConfig:
    ssh_host: str
    ssh_port: int
    ssh_user: str
    ssh_password: str
    local_host: str
    local_port: int
    remote_host: str
    remote_port: int
    mode: str


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _int_env(name: str, default: str | None = None) -> int:
    raw = os.environ.get(name, default)
    if raw is None or not raw.strip():
        raise RuntimeError(f"{name} is required")
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer; got {raw!r}") from exc


def load_config() -> TunnelConfig:
    local_host = os.environ.get(
        "TUNNEL_LOCAL_HOST",
        os.environ.get("INDEXTTS_TUNNEL_HOST", "127.0.0.1"),
    )
    local_port = _int_env(
        "TUNNEL_LOCAL_PORT",
        os.environ.get("INDEXTTS_TUNNEL_PORT", "9001"),
    )
    remote_host = os.environ.get(
        "TUNNEL_REMOTE_HOST",
        os.environ.get("INDEXTTS_REMOTE_HOST", "127.0.0.1"),
    )
    remote_port = _int_env(
        "TUNNEL_REMOTE_PORT",
        os.environ.get("INDEXTTS_REMOTE_PORT", "9001"),
    )
    mode = os.environ.get("TUNNEL_MODE", "forward").strip().lower()
    if mode not in {"forward", "reverse"}:
        raise RuntimeError(f"TUNNEL_MODE must be forward or reverse; got {mode!r}")

    return TunnelConfig(
        ssh_host=_required_env("SEETA_SSH_HOST"),
        ssh_port=_int_env("SEETA_SSH_PORT"),
        ssh_user=_required_env("SEETA_SSH_USER"),
        ssh_password=_required_env("SEETA_SSH_PASSWORD"),
        local_host=local_host,
        local_port=local_port,
        remote_host=remote_host,
        remote_port=remote_port,
        mode=mode,
    )


class ForwardServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_handler(transport: paramiko.Transport, remote_host: str, remote_port: int):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            try:
                chan = transport.open_channel(
                    "direct-tcpip",
                    (remote_host, remote_port),
                    self.request.getpeername(),
                )
            except Exception as exc:
                print(f"open channel failed: {exc}")
                return
            if chan is None:
                print("open channel failed: no channel")
                return

            try:
                while True:
                    readable, _, _ = select.select([self.request, chan], [], [])
                    if self.request in readable:
                        data = self.request.recv(16384)
                        if not data:
                            break
                        chan.sendall(data)
                    if chan in readable:
                        data = chan.recv(16384)
                        if not data:
                            break
                        self.request.sendall(data)
            finally:
                chan.close()
                self.request.close()

    return Handler


def pipe_socket_to_channel(sock: socket.socket, chan: paramiko.Channel) -> None:
    try:
        while True:
            readable, _, _ = select.select([sock, chan], [], [])
            if sock in readable:
                data = sock.recv(16384)
                if not data:
                    break
                chan.sendall(data)
            if chan in readable:
                data = chan.recv(16384)
                if not data:
                    break
                sock.sendall(data)
    finally:
        chan.close()
        sock.close()


def serve_reverse(
    transport: paramiko.Transport,
    remote_host: str,
    remote_port: int,
    local_host: str,
    local_port: int,
) -> None:
    transport.request_port_forward(remote_host, remote_port)
    print(
        f"Reverse forwarding {remote_host}:{remote_port} -> "
        f"{local_host}:{local_port}"
    )
    print("Press Ctrl+C to stop.")
    try:
        while True:
            chan = transport.accept(30)
            if chan is None:
                continue
            try:
                sock = socket.create_connection((local_host, local_port), timeout=10)
            except Exception as exc:
                print(f"connect local target failed: {exc}")
                chan.close()
                continue
            threading.Thread(
                target=pipe_socket_to_channel,
                args=(sock, chan),
                daemon=True,
            ).start()
    finally:
        try:
            transport.cancel_port_forward(remote_host, remote_port)
        except Exception:
            pass


def main() -> None:
    cfg = load_config()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=cfg.ssh_host,
        port=cfg.ssh_port,
        username=cfg.ssh_user,
        password=cfg.ssh_password,
        timeout=15,
        banner_timeout=15,
        auth_timeout=15,
    )
    transport = client.get_transport()
    if transport is None:
        raise RuntimeError("SSH transport was not established")

    try:
        if cfg.mode == "reverse":
            serve_reverse(
                transport,
                cfg.remote_host,
                cfg.remote_port,
                cfg.local_host,
                cfg.local_port,
            )
            return

        server = ForwardServer(
            (cfg.local_host, cfg.local_port),
            make_handler(transport, cfg.remote_host, cfg.remote_port),
        )
        print(
            f"Forwarding {cfg.local_host}:{cfg.local_port} -> "
            f"{cfg.ssh_user}@{cfg.ssh_host}:{cfg.ssh_port} -> {cfg.remote_host}:{cfg.remote_port}"
        )
        print("Press Ctrl+C to stop.")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if "server" in locals():
            server.shutdown()
            server.server_close()
        client.close()


if __name__ == "__main__":
    main()
