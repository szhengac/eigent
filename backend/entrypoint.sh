#!/bin/bash
set -e

# Ensure DBus runtime directory exists
mkdir -p /run/dbus

# Start system DBus daemon (ignore failure if already running)
dbus-daemon --system --fork || true

# Start headless Google Chrome
google-chrome-stable \
  --headless=new \
  --no-sandbox \
  --disable-dev-shm-usage \
  --disable-gpu \
  --disable-software-rasterizer \
  --user-data-dir=/tmp/chrome-data \
  --disable-extensions \
  --disable-notifications \
  --disable-component-update \
  --disable-background-networking \
  --disable-sync \
  --disable-default-apps \
  --disable-translate \
  --disable-domain-reliability \
  --disable-client-side-phishing-detection \
  --disable-breakpad \
  --disable-hang-monitor \
  --disable-features=Translate,MediaRouter,OptimizationHints,ChromeWhatsNewUI,CloudMessaging \
  --metrics-recording-only \
  --no-first-run \
  --no-default-browser-check \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  >/dev/null 2>&1 &

# Wait until Chrome CDP is ready
until curl -sf http://127.0.0.1:9222/json/version >/dev/null; do
  sleep 0.3
done
echo "Chrome CDP ready"

# Start FastAPI (Python 3.12 for asyncio.TaskGroup support)
exec python3.12 -m uvicorn main:api --host 0.0.0.0 --port 5002
