#!/usr/bin/env bash
# Start the full Pixel Streaming stack on the cloud GPU server
set -e

SIGNAL_DIR=/data/pixelstreaming-signalling
BUILD_DIR=/data/MiraLink-Build
LOG_DIR=/data/logs
mkdir -p "$LOG_DIR"

echo "[1/4] Starting virtual display (Xvfb :99)..."
pkill -f "Xvfb :99" 2>/dev/null || true
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99
sleep 1

echo "[2/4] Starting coturn TURN server (port 3478)..."
pkill -f "turnserver" 2>/dev/null || true
if [ -f /etc/turnserver.conf ]; then
    turnserver -c /etc/turnserver.conf --no-auth --listening-port 3478 \
        >> "$LOG_DIR/coturn.log" 2>&1 &
else
    turnserver --no-auth --listening-port 3478 --realm miralink \
        >> "$LOG_DIR/coturn.log" 2>&1 &
fi
sleep 1

echo "[3/4] Starting Pixel Streaming signalling server (port 80 / streamer 8888)..."
pkill -f "cirrus.js" 2>/dev/null || true
cd "$SIGNAL_DIR"
node cirrus.js --HttpPort 80 --StreamerPort 8888 \
    >> "$LOG_DIR/signalling.log" 2>&1 &
sleep 2

echo "[4/4] Starting Unity headless with Pixel Streaming..."
pkill -f "MiraLink.x86_64" 2>/dev/null || true
cd "$BUILD_DIR"
DISPLAY=:99 ./MiraLink.x86_64 \
    -RenderOffscreen \
    -PixelStreamingURL ws://127.0.0.1:8888 \
    >> "$LOG_DIR/unity.log" 2>&1 &

echo ""
echo "Pixel Streaming stack is starting."
echo "  Mobile browser: http://<YOUR_SERVER_IP>:80"
echo "  Backend health: http://<YOUR_SERVER_IP>:8100/health"
echo "  Unity log:      $LOG_DIR/unity.log"
echo "  Signalling log: $LOG_DIR/signalling.log"
