#!/usr/bin/env bash
# Starts the backend (FastAPI) and frontend (static UI) together.
# Frees BE_PORT/FE_PORT first if something is already bound to them.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BE_DIR="$ROOT_DIR/BE"
UI_DIR="$ROOT_DIR/UI"
VENV_DIR="$BE_DIR/.venv"

# Load .env files if present. These override any same-named vars you
# exported before invoking this script - edit the .env files, not the shell,
# if you want persistent overrides.
set -a
[ -f "$BE_DIR/.env" ] && source "$BE_DIR/.env"
[ -f "$UI_DIR/.env" ] && source "$UI_DIR/.env"
set +a

BE_HOST="${BE_HOST:-127.0.0.1}"
BE_PORT="${BE_PORT:-8000}"
FE_HOST="${FE_HOST:-127.0.0.1}"
FE_PORT="${FE_PORT:-5173}"
API_BASE_URL="${API_BASE_URL:-http://${BE_HOST}:${BE_PORT}}"
UI_ORIGINS="${UI_ORIGINS:-http://${FE_HOST}:${FE_PORT}}"

log() { printf '[start] %s\n' "$1"; }

kill_port() {
  local port="$1"
  local pids
  pids="$(lsof -ti "tcp:${port}" 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    log "Port ${port} is in use (pid: ${pids}) - stopping it"
    kill $pids 2>/dev/null || true
    sleep 1
    pids="$(lsof -ti "tcp:${port}" 2>/dev/null || true)"
    [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
  fi
}

kill_port "$BE_PORT"
kill_port "$FE_PORT"

PYTHON_BIN="${PYTHON_BIN:-python3.11}"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || PYTHON_BIN="python3"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  log "Creating BE virtualenv at ${VENV_DIR#$ROOT_DIR/}"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

if ! "$VENV_DIR/bin/python" -c "import fastapi, uvicorn, langgraph, pydantic, yaml, dotenv, prometheus_client, opentelemetry.sdk" >/dev/null 2>&1; then
  log "Installing backend dependencies"
  "$VENV_DIR/bin/pip" install -q --upgrade pip
  (cd "$BE_DIR" && "$VENV_DIR/bin/pip" install -q -e ".[dev,pdf,observability]")
fi

mkdir -p "$ROOT_DIR/data/workflows"

# Keep the FE pointed at whichever backend origin this run actually uses.
cat > "$UI_DIR/config.js" <<EOF
window.API_BASE_URL = "${API_BASE_URL}";
EOF

BE_PID=""
FE_PID=""

cleanup() {
  log "Shutting down"
  [ -n "$BE_PID" ] && kill "$BE_PID" 2>/dev/null || true
  [ -n "$FE_PID" ] && kill "$FE_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

log "Starting backend on http://${BE_HOST}:${BE_PORT}"
(
  cd "$BE_DIR"
  export UI_ORIGINS
  exec "$VENV_DIR/bin/python" -m uvicorn app.main:app --host "$BE_HOST" --port "$BE_PORT" --reload
) &
BE_PID=$!

log "Starting frontend on http://${FE_HOST}:${FE_PORT}"
(
  cd "$UI_DIR"
  exec "$PYTHON_BIN" -m http.server "$FE_PORT" --bind "$FE_HOST"
) &
FE_PID=$!

log "Backend:  http://${BE_HOST}:${BE_PORT}  (docs: http://${BE_HOST}:${BE_PORT}/docs)"
log "Frontend: http://${FE_HOST}:${FE_PORT}"
log "Press Ctrl+C to stop both."

# Portable wait-for-either (avoids bash 4's `wait -n`, absent on macOS's stock bash).
while kill -0 "$BE_PID" 2>/dev/null && kill -0 "$FE_PID" 2>/dev/null; do
  sleep 1
done

if ! kill -0 "$BE_PID" 2>/dev/null; then
  log "Backend process exited unexpectedly"
fi
if ! kill -0 "$FE_PID" 2>/dev/null; then
  log "Frontend process exited unexpectedly"
fi
