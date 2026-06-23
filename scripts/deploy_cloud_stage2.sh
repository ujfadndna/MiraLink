#!/usr/bin/env bash
# One-time cloud server setup for Pixel Streaming (Stage 2)
set -e

echo "[1/3] Installing system dependencies..."
apt-get update -y
apt-get install -y xvfb nodejs npm coturn

echo "[2/3] Setting up Pixel Streaming signalling server..."
PS_SIGNAL_DIR=/data/pixelstreaming-signalling
mkdir -p "$PS_SIGNAL_DIR"

# After Unity Pixel Streaming package is installed on your dev machine,
# the signalling server source is at:
#   Library/PackageCache/com.unity.pixelstreaming@<version>/SignallingWebServer/
# Copy that directory to the cloud machine and run: npm install && node cirrus.js
# Alternatively, use the npm package below as a fallback:
cd "$PS_SIGNAL_DIR"
cat > package.json <<'PKGJSON'
{
  "name": "ps-signalling",
  "version": "1.0.0",
  "dependencies": {
    "ws": "^8.0.0"
  }
}
PKGJSON
npm install

echo "[3/3] Creating log directory..."
mkdir -p /data/logs

echo "Stage 2 setup complete."
echo "Next steps:"
echo "  1. Upload Unity Linux build to /data/MiraLink-Build/"
echo "  2. Copy SignallingWebServer/ from Unity package to /data/pixelstreaming-signalling/"
echo "  3. Run: bash scripts/start_ps.sh"
