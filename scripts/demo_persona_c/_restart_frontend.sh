#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}/frontend"
pkill -f vite 2>/dev/null || true
pkill -f "npm run dev" 2>/dev/null || true
sleep 2
npm install --no-audit --no-fund 2>&1 | tail -5
nohup npm run dev -- --host 127.0.0.1 --port 5173 > /tmp/frontend.log 2>&1 &
sleep 12
tail -10 /tmp/frontend.log
echo "---HTTP---"
curl -sf http://127.0.0.1:5173 -o /dev/null && echo "OK" || echo "FAIL"
