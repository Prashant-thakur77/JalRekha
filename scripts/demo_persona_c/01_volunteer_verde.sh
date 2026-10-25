#!/usr/bin/env bash
# Acto 1 - Verde. JalRekha Volunteer ciudadano reporta rutina sin riesgo.
# Inyecta VolunteerReport sintetico con severity_score=0.20 (bypass parser LLM
# para escalada determinista). Esperado: fused level=green, score<0.4.
set -euo pipefail

API="${API:-http://127.0.0.1:8000}"
SITE="${SITE:-puente-arroyo-01}"

echo "[Acto 1] JalRekha Volunteer ciudadano envia reporte a $SITE..."
curl -sS -X POST "$API/api/demo/inject-volunteer-report" \
  -H "Content-Type: application/json" \
  -d '{
    "site_id": "'"$SITE"'",
    "reporter_name": "Vecino Garcia",
    "reporter_role": "ciudadano",
    "transcript_text": "Llueve fuerte pero el canal esta corriendo bien, sin riesgo.",
    "severity_score": 0.20,
    "water_level_category": "low",
    "trend": "stable",
    "road_status": "open",
    "urgency": "low",
    "summary": "Reporte rutina: canal corre normal, lluvia fuerte sin desborde."
  }' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); a=d['alert']; print(f\"  -> level={a['level']} score={a['score']} trigger={a['trigger_source']}\")"
