"""Read-only ICE/TURN diagnostics for the current MiraLink deployment."""
from __future__ import annotations

import argparse
import os
import socket
from typing import Iterable


DEFAULT_HOST = os.environ.get("CLOUD_SSH_HOST", "")
DEFAULT_PORT = int(os.environ.get("CLOUD_SSH_PORT", "0"))
DEFAULT_USER = "root"
DEFAULT_PAGE_HOST = os.environ.get("CLOUD_PAGE_HOST", "")
DEFAULT_PUBLIC_IP = os.environ.get("CLOUD_PUBLIC_IP", "")


def tcp_probe(host: str, port: int, timeout: float = 3.0) -> str:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return "CONNECTED"
    except OSError as exc:
        return f"BLOCKED ({exc.__class__.__name__})"


def print_tcp_probes(targets: Iterable[tuple[str, int]]) -> None:
    print("=== External TCP reachability ===")
    for host, port in targets:
        print(f"{host}:{port} -> {tcp_probe(host, port)}")


def run_remote(host: str, port: int, user: str, password: str) -> None:
    try:
        import paramiko
    except ImportError:
        print("\nparamiko not installed; skipping SSH checks")
        return

    commands = [
        "hostname && date",
        'ps aux | grep -E "MiraLink|server.py|uvicorn|turnserver|Xvfb" | grep -v grep || true',
        'ss -lntup 2>/dev/null | grep -E ":(80|3478|8100|7860)" || true',
        'test -f /etc/turnserver.conf && sed -n "1,120p" /etc/turnserver.conf || echo no-turn-conf',
        "tail -n 120 /data/logs/sig.log 2>/dev/null || true",
        "tail -n 120 /var/log/turnserver.log 2>/dev/null || tail -n 120 /tmp/turn.log 2>/dev/null || true",
    ]

    print("\n=== Remote service state ===")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        host,
        port=port,
        username=user,
        password=password,
        timeout=30,
        look_for_keys=False,
        allow_agent=False,
    )
    try:
        for command in commands:
            print(f"\n$ {command}")
            _, stdout, stderr = ssh.exec_command(command, timeout=20)
            out = stdout.read().decode("utf-8", "replace")
            err = stderr.read().decode("utf-8", "replace")
            print((out or err or "").strip()[:6000])
    finally:
        ssh.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-host", default=DEFAULT_HOST)
    parser.add_argument("--ssh-port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--ssh-user", default=DEFAULT_USER)
    parser.add_argument("--ssh-pass", default="")
    parser.add_argument("--page-host", default=DEFAULT_PAGE_HOST)
    parser.add_argument("--public-ip", default=DEFAULT_PUBLIC_IP)
    args = parser.parse_args()

    print_tcp_probes(
        [
            (args.public_ip, 80),
            (args.public_ip, 3478),
            (args.page_host, 443),
            (args.page_host, 3478),
        ]
    )

    if args.ssh_pass:
        run_remote(args.ssh_host, args.ssh_port, args.ssh_user, args.ssh_pass)
    else:
        print("\nNo --ssh-pass provided; skipped SSH checks")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
