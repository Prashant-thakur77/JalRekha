#!/usr/bin/env bash
# Full pipeline: kill+restart backend, reset DB, ensure frontend up, run recorder.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}/backend"
pkill -f "uvicorn jalrekha.main:app" 2>/dev/null || true
sleep 2
rm -f data/edge.db data/central.db data/jalrekha.db
PYTHONPATH=src python3 -m jalrekha.scripts.seed
nohup env JALREKHA_ENABLE_DEMO_INJECT=1 PYTHONPATH=src python3 -m uvicorn jalrekha.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &
sleep 6

# Make sure frontend is up
if ! curl -sf http://127.0.0.1:5173 > /dev/null; then
  echo "[rec] starting frontend dev server..."
  cd "${REPO_ROOT}/frontend"
  nohup npm run dev -- --host 127.0.0.1 --port 5173 > /tmp/frontend.log 2>&1 &
  sleep 8
fi

curl -sS http://127.0.0.1:8000/api/health
echo
curl -sf http://127.0.0.1:5173 > /dev/null && echo "[rec] frontend OK"

cd "${SCRIPT_DIR}"
python3 record_demo.py --out /tmp/persona_c_demo.webm
