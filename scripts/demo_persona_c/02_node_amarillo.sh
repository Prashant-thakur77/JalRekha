#!/usr/bin/env bash
# Acto 2 — Amarillo. Camara fija detecta cota sobre linea de referencia, sin cruzar critica.
# Inyecta NodeObservation sintetica via endpoint demo (requiere JALREKHA_ENABLE_DEMO_INJECT=1).
# Esperado: fused level=yellow, score ~0.45-0.55.
set -euo pipefail

API="${API:-http://127.0.0.1:8000}"
SITE="${SITE:-puente-arroyo-01}"

echo "[Acto 2] JalRekha Node (camara fija) inyecta lectura elevada a $SITE..."
curl -sS -X POST "$API/api/demo/inject-node-observation" \
  -H "Content-Type: application/json" \
  -d '{
    "site_id": "'"$SITE"'",
    "severity_score": 0.52,
    "waterline_ratio": 0.62,
    "rise_velocity": 0.05,
    "crossed_critical_line": false,
    "confidence": 0.81,
    "assessment_level": "elevated",
    "temporal_summary": "Camara fija: cota supera linea de referencia, sin alcanzar linea critica."
  }' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); a=d['alert']; print(f\"  -> level={a['level']} score={a['score']} trigger={a['trigger_source']}\")"
