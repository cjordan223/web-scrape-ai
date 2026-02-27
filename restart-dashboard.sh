#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_DIR="$ROOT_DIR/dashboard/web"
BACKEND_DIR="$ROOT_DIR/dashboard/backend"
VENV_PY="$ROOT_DIR/venv/bin/python"
SERVICE_LABEL="com.jobscraper.dashboard"
SERVICE_ID="gui/$(id -u)/$SERVICE_LABEL"

echo "[1/4] Building dashboard web bundle..."
cd "$WEB_DIR"
npm run build

echo "[2/4] Restarting backend..."
if launchctl print "$SERVICE_ID" >/dev/null 2>&1; then
  launchctl kickstart -k "$SERVICE_ID"
else
  # Fallback: no launchd service loaded, restart manual process.
  if lsof -tiTCP:8899 -sTCP:LISTEN >/dev/null 2>&1; then
    lsof -tiTCP:8899 -sTCP:LISTEN | xargs kill || true
    sleep 1
  fi
  nohup "$VENV_PY" "$BACKEND_DIR/server.py" > /tmp/dashboard-backend.log 2>&1 &
fi

echo "[3/4] Waiting for backend health..."
for _ in {1..15}; do
  if curl -fsS --max-time 2 "http://127.0.0.1:8899/api/overview" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "[4/4] Verifying listener..."
lsof -nP -iTCP:8899 -sTCP:LISTEN
echo "Dashboard restart complete: http://192.168.1.19:8899"
