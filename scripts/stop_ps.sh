#!/usr/bin/env bash
# Stop all Pixel Streaming stack processes
echo "Stopping Pixel Streaming stack..."
pkill -f "MiraLink.x86_64" 2>/dev/null && echo "  Unity stopped"       || echo "  Unity was not running"
pkill -f "cirrus.js"         2>/dev/null && echo "  Signalling stopped"  || echo "  Signalling was not running"
pkill -f "turnserver"        2>/dev/null && echo "  coturn stopped"      || echo "  coturn was not running"
pkill -f "Xvfb :99"         2>/dev/null && echo "  Xvfb stopped"        || echo "  Xvfb was not running"
echo "Done."
