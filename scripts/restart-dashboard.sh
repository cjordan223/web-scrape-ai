#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="$ROOT_DIR/dashboard/web"
BACKEND_DIR="$ROOT_DIR/dashboard/backend"
VENV_PY="$ROOT_DIR/venv/bin/python"
SERVICE_LABEL="com.jobscraper.dashboard"
SERVICE_ID="gui/$(id -u)/$SERVICE_LABEL"

# --- SearXNG (Docker) ---
echo "[1/5] Restarting SearXNG..."
cd "$ROOT_DIR"
if docker compose ps --status running 2>/dev/null | grep -q searxng; then
  docker compose restart searxng
else
  docker compose up -d searxng
fi

# --- Frontend build ---
echo "[2/5] Building dashboard web bundle..."
cd "$WEB_DIR"
npm run build

# --- Dashboard backend ---
echo "[3/5] Restarting backend..."
if launchctl print "$SERVICE_ID" >/dev/null 2>&1; then
  launchctl kickstart -k "$SERVICE_ID"
else
  if lsof -tiTCP:8899 -sTCP:LISTEN >/dev/null 2>&1; then
    lsof -tiTCP:8899 -sTCP:LISTEN | xargs kill || true
    sleep 1
  fi
  export TEXTAILOR_SCRAPE_SCHEDULER=1
  nohup "$VENV_PY" "$BACKEND_DIR/server.py" > /tmp/dashboard-backend.log 2>&1 &
fi

# --- Health checks ---
echo "[4/5] Waiting for backend (port 8899)..."
for i in {1..15}; do
  if curl -fsS --max-time 2 "http://127.0.0.1:8899/api/overview" >/dev/null 2>&1; then
    echo "  Backend ready"
    break
  fi
  if [ "$i" -eq 15 ]; then echo "  WARNING: backend not responding after 15s"; fi
  sleep 1
done

echo "[5/5] Waiting for SearXNG (port 8888)..."
for i in {1..10}; do
  if curl -fsS --max-time 2 "http://127.0.0.1:8888/" >/dev/null 2>&1; then
    echo "  SearXNG ready"
    break
  fi
  if [ "$i" -eq 10 ]; then echo "  WARNING: SearXNG not responding after 10s"; fi
  sleep 1
done

echo ""
echo "TexTailor restart complete"
echo "  Dashboard: http://192.168.1.19:8899"
echo "  SearXNG:   http://192.168.1.19:8888"
