#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${OLLAMA_INSTALL_DIR:-$ROOT_DIR/tools/ollama}"
BIN="$INSTALL_DIR/bin/ollama"
MODEL="${1:-${JALREKHA_LLM_MODEL:-gemma4:e2b}}"
HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
HTTP_BASE="http://$HOST"
MODELS_DIR="${OLLAMA_MODELS:-$ROOT_DIR/backend/data/ollama-models}"
LOG_DIR="$ROOT_DIR/backend/data/logs"
LOG_FILE="$LOG_DIR/ollama.log"
PID_FILE="$LOG_DIR/ollama.pid"

if [[ ! -x "$BIN" ]]; then
  "$ROOT_DIR/scripts/install_ollama_local.sh"
fi

mkdir -p "$MODELS_DIR" "$LOG_DIR"
export LD_LIBRARY_PATH="$INSTALL_DIR/lib/ollama:${LD_LIBRARY_PATH:-}"
export OLLAMA_HOST="$HOST"
export OLLAMA_MODELS="$MODELS_DIR"

if ! curl -fsS "$HTTP_BASE/api/tags" >/dev/null 2>&1; then
  echo "Starting Ollama on $HTTP_BASE"
  nohup "$BIN" serve >"$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
else
  echo "Ollama already reachable at $HTTP_BASE"
fi

for _ in $(seq 1 90); do
  if curl -fsS "$HTTP_BASE/api/tags" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS "$HTTP_BASE/api/tags" >/dev/null 2>&1; then
  echo "Ollama did not start correctly. Check $LOG_FILE" >&2
  exit 1
fi

if ! "$BIN" list | awk 'NR>1 {print $1}' | grep -Fx "$MODEL" >/dev/null 2>&1; then
  echo "Pulling model $MODEL"
  "$BIN" pull "$MODEL"
fi

cat <<EOM
Ollama is ready.
Base URL: $HTTP_BASE/v1
Model: $MODEL
Models dir: $MODELS_DIR
Log: $LOG_FILE

Export for backend:
export JALREKHA_LLM_BASE_URL=$HTTP_BASE/v1
export JALREKHA_LLM_MODEL=$MODEL
export JALREKHA_LLM_API_KEY=ollama
EOM
