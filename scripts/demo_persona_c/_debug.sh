#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}/backend"
pkill -f uvicorn 2>/dev/null || true
sleep 2
rm -f data/jalrekha.db
PYTHONPATH=src python3 -m jalrekha.scripts.seed
nohup env JALREKHA_ENABLE_DEMO_INJECT=1 PYTHONPATH=src python3 -m uvicorn jalrekha.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &
sleep 6
echo "--HEALTH--"
curl -sS http://127.0.0.1:8000/api/health
echo
echo "--ACT1 raw--"
curl -sS -X POST http://127.0.0.1:8000/api/demo/inject-volunteer-report \
  -H "Content-Type: application/json" \
  -d '{"site_id":"puente-arroyo-01","reporter_name":"X","reporter_role":"ciudadano","transcript_text":"rutina","severity_score":0.20,"water_level_category":"low","trend":"stable","road_status":"open","homes_affected":false,"urgency":"low","summary":"rutina"}'
echo
echo "--ALERT FULL--"
curl -sS "http://127.0.0.1:8000/api/alerts" | python3 -m json.tool | head -80
