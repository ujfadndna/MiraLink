#!/usr/bin/env bash
set -euo pipefail

APP_USER="${APP_USER:-miralink}"
APP_ROOT="${APP_ROOT:-/opt/miralink}"
ENV_FILE="${ENV_FILE:-$APP_ROOT/deploy.env}"
BUILD_DIR="${BUILD_DIR:-$APP_ROOT/build}"
BACKEND_DIR="${BACKEND_DIR:-$APP_ROOT/backend}"
SIGNALLING_DIR="${SIGNALLING_DIR:-$APP_ROOT/signalling}"
LOG_DIR="${LOG_DIR:-$APP_ROOT/logs}"
VENV_DIR="${VENV_DIR:-$APP_ROOT/.venv}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "Please run as root: sudo bash deploy/cloud/setup.sh"
    exit 1
  fi
}

create_user() {
  if ! id "$APP_USER" >/dev/null 2>&1; then
    useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
  fi
}

install_packages() {
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    apt-get install -y python3 python3-venv python3-pip xvfb curl
  else
    echo "apt-get not found. Please install python3, python3-venv, pip, xvfb and curl manually."
  fi
}

create_directories() {
  mkdir -p "$APP_ROOT" "$BUILD_DIR" "$BACKEND_DIR" "$SIGNALLING_DIR" "$LOG_DIR"
  chown -R "$APP_USER:$APP_USER" "$APP_ROOT"
}

create_env_file() {
  if [ ! -f "$ENV_FILE" ]; then
    cat >"$ENV_FILE" <<'ENV'
# MiraLink cloud deployment environment.
# Replace all placeholder values before exposing the service publicly.
ANTHROPIC_API_KEY=your_api_key_here
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
TURN_URLS=turn:your-turn-server:3478?transport=udp,turn:your-turn-server:3478?transport=tcp
TURN_USERNAME=miralink
TURN_CREDENTIAL=<turn-credential>
TURN_PASSWORD=<turn-password>
PORT=8080
BACKEND_WS=ws://127.0.0.1:8100/ws/avatar
ICE_TRANSPORT_POLICY=all
ENV
    chmod 600 "$ENV_FILE"
    chown "$APP_USER:$APP_USER" "$ENV_FILE"
  fi
}

create_xvfb_service() {
  cat >"$SYSTEMD_DIR/xvfb.service" <<'SERVICE'
[Unit]
Description=X virtual framebuffer on display :99
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SERVICE
}

install_systemd_units() {
  cp "$SCRIPT_DIR/backend.service" "$SYSTEMD_DIR/miralink-backend.service"
  cp "$SCRIPT_DIR/signalling.service" "$SYSTEMD_DIR/miralink-signalling.service"
  cp "$SCRIPT_DIR/unity.service" "$SYSTEMD_DIR/miralink-unity.service"
  systemctl daemon-reload
}

install_python_deps() {
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    python3 -m venv "$VENV_DIR"
  fi
  "$VENV_DIR/bin/pip" install -U pip
  if [ -f "$BACKEND_DIR/requirements.txt" ]; then
    "$VENV_DIR/bin/pip" install -r "$BACKEND_DIR/requirements.txt"
  else
    echo "Warning: $BACKEND_DIR/requirements.txt not found. Upload backend/ before starting backend."
  fi
  chown -R "$APP_USER:$APP_USER" "$VENV_DIR"
}

start_services() {
  systemctl enable --now xvfb.service
  systemctl enable --now miralink-backend.service
  systemctl enable --now miralink-signalling.service

  if [ -x "$BUILD_DIR/MiraLink.x86_64" ]; then
    systemctl enable --now miralink-unity.service
  else
    echo "Warning: $BUILD_DIR/MiraLink.x86_64 not found or not executable. Upload the Unity build, chmod +x it, then run:"
    echo "  systemctl enable --now miralink-unity.service"
  fi
}

print_summary() {
  echo
  echo "MiraLink cloud setup summary"
  echo "APP_ROOT: $APP_ROOT"
  echo "ENV_FILE: $ENV_FILE"
  echo "Logs: $LOG_DIR"
  echo
  systemctl --no-pager --full status xvfb.service miralink-backend.service miralink-signalling.service miralink-unity.service || true
  echo
  echo "Health checks:"
  curl -fsS http://127.0.0.1:8100/health || true
  echo
  curl -fsS "http://127.0.0.1:${PORT:-8080}/health" || true
  echo
}

require_root
create_user
install_packages
create_directories
create_env_file
install_python_deps
create_xvfb_service
install_systemd_units
start_services
print_summary
