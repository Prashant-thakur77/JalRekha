#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
LOG_DIR="$BACKEND_DIR/data/logs"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
BACKEND_PID_FILE="$LOG_DIR/backend.pid"
FRONTEND_PID_FILE="$LOG_DIR/frontend.pid"

mkdir -p "$LOG_DIR"

cleanup() {
  local exit_code=$?
  for pid_file in "$BACKEND_PID_FILE" "$FRONTEND_PID_FILE"; do
    if [[ -f "$pid_file" ]]; then
      pid="$(cat "$pid_file")"
      if kill -0 "$pid" >/dev/null 2>&1; then
        kill "$pid" >/dev/null 2>&1 || true
        wait "$pid" 2>/dev/null || true
      fi
      rm -f "$pid_file"
    fi
  done
  exit "$exit_code"
}

trap cleanup INT TERM EXIT

if [[ ! -d "$BACKEND_DIR/.venv" ]]; then
  (
    cd "$BACKEND_DIR"
    if command -v uv >/dev/null 2>&1; then
      uv venv
      source .venv/bin/activate
      uv pip install -e .[dev]
    else
      python3 -m venv .venv
      source .venv/bin/activate
      python -m pip install --upgrade pip
      python -m pip install -e .[dev]
    fi
  )
fi

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  (
    cd "$FRONTEND_DIR"
    npm install --legacy-peer-deps
  )
fi

"$ROOT_DIR/scripts/run_gemma_local.sh"

(
  cd "$BACKEND_DIR"
  PYTHONPATH=src python3 -m jalrekha.scripts.seed >/dev/null
  PYTHONPATH=src python3 -m uvicorn jalrekha.main:app --host 127.0.0.1 --port 8000 >"$BACKEND_LOG" 2>&1
) &
backend_pid=$!
echo "$backend_pid" > "$BACKEND_PID_FILE"

(
  cd "$FRONTEND_DIR"
  npm run dev -- --host 127.0.0.1 --port 5173 >"$FRONTEND_LOG" 2>&1
) &
frontend_pid=$!
echo "$frontend_pid" > "$FRONTEND_PID_FILE"

for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1 && curl -fsS http://127.0.0.1:5173 >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
  echo "Backend did not start correctly. Check $BACKEND_LOG" >&2
  exit 1
fi

if ! curl -fsS http://127.0.0.1:5173 >/dev/null 2>&1; then
  echo "Frontend did not start correctly. Check $FRONTEND_LOG" >&2
  exit 1
fi

cat <<EOM
Local stack is running.
Frontend: http://127.0.0.1:5173
Backend:  http://127.0.0.1:8000
Ollama:   http://127.0.0.1:11434/v1

Logs:
- $BACKEND_LOG
- $FRONTEND_LOG

Press Ctrl+C to stop backend and frontend.
EOM

wait "$backend_pid" "$frontend_pid"
