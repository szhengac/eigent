#!/bin/bash
set -e

# Ensure DBus runtime directory exists
mkdir -p /run/dbus

# Start system DBus daemon
dbus-daemon --system --fork

# Start headless Google Chrome with extra flags to suppress GCM/deprecated endpoint errors
google-chrome-stable \
    --headless=new \
    --disable-gpu \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-software-rasterizer \
    --disable-extensions \
    --disable-notifications \
    --disable-component-update \
    --disable-background-networking \
    --disable-sync \
    --disable-translate \
    --safebrowsing-disable-auto-update \
    --remote-debugging-address=127.0.0.1 \
    --remote-debugging-port=9222 &

# Wait until Chrome CDP is ready
until curl -s http://127.0.0.1:9222/json/version >/dev/null; do
    sleep 0.5
done
echo "Chromium ready!"

# Start FastAPI
uvicorn main:api --host 0.0.0.0 --port 5002
