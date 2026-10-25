#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

pkill -f "uvicorn jalrekha.main:app" 2>/dev/null || true
sleep 2
cd "${REPO_ROOT}/backend"
mkdir -p data
rm -f data/edge.db data/central.db data/jalrekha.db
PYTHONPATH=src python3 -m jalrekha.scripts.seed
nohup env JALREKHA_ENABLE_DEMO_INJECT=1 PYTHONPATH=src python3 -m uvicorn jalrekha.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &
sleep 6
echo "---health---"
curl -sS http://127.0.0.1:8000/api/health || curl -sS http://127.0.0.1:8000/api/runtime/health || echo no_health
echo ""
echo "---ACTO 1 verde---"
bash "${SCRIPT_DIR}/01_volunteer_verde.sh"
sleep 2
echo "---ACTO 2 amarillo---"
bash "${SCRIPT_DIR}/02_node_amarillo.sh"
sleep 2
echo "---ACTO 3 rojo---"
bash "${SCRIPT_DIR}/03_fusion_rojo.sh"
