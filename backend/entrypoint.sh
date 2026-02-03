#!/bin/bash
set -e

# Start system DBus daemon
dbus-daemon --system --fork

# Start Chromium headless
chromium \
    --headless=new \
    --disable-gpu \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-software-rasterizer \
    --disable-extensions \
    --disable-notifications \
    --disable-component-update \
    --remote-debugging-address=127.0.0.1 \
    --remote-debugging-port=9222 &

# Wait until Chromium CDP is ready
until curl -s http://127.0.0.1:9222/json/version >/dev/null; do
    sleep 0.5
done
echo "Chromium ready!"

# Start FastAPI
uvicorn main:api --host 0.0.0.0 --port 5002
