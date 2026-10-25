#!/usr/bin/env bash
# Acto 3 - Rojo/Naranja. Tres reportes JalRekha Volunteer simultaneos corroboran lectura JalRekha Node.
# Inyecta VolunteerReport sinteticos con severity controlada para escalada determinista.
# Esperado: fused level=red, score>=0.82, local_alarm_triggered=true.
set -euo pipefail

API="${API:-http://127.0.0.1:8000}"
SITE="${SITE:-puente-arroyo-01}"

inject_vol() {
  local name="$1"; local role="$2"; local text="$3"; local sev="$4"; local cat="$5"; local road="$6"; local homes="$7"
  curl -sS -X POST "$API/api/demo/inject-volunteer-report" \
    -H "Content-Type: application/json" \
    -d "{
      \"site_id\": \"$SITE\",
      \"reporter_name\": \"$name\",
      \"reporter_role\": \"$role\",
      \"transcript_text\": \"$text\",
      \"severity_score\": $sev,
      \"water_level_category\": \"$cat\",
      \"trend\": \"rising\",
      \"road_status\": \"$road\",
      \"homes_affected\": $homes,
      \"urgency\": \"critical\",
      \"summary\": \"$text\"
    }" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); a=d['alert']; print(f\"  -> level={a['level']} score={a['score']} trigger={a['trigger_source']} alarm={a['local_alarm_triggered']}\")"
}

echo "[Acto 3] Tres reportes JalRekha Volunteer simultaneos a $SITE..."
echo "  R1 (vecino puente):"
inject_vol "Vecino Lopez" "ciudadano" "El agua paso la marca del puente." 0.78 "high" "open" false
sleep 1
echo "  R2 (esquina plaza):"
inject_vol "Voluntario Sosa" "brigadista" "Se taparon las calles, intransitable en la esquina de la plaza." 0.74 "high" "blocked" false
sleep 1
echo "  R3 (apagon sincroniza):"
inject_vol "Vecina Diaz" "ciudadano" "El agua esta entrando a las casas, hay familias evacuadas." 0.88 "critical" "blocked" true

echo ""
echo "[Acto 4a] Decision trace SINAGIR-ready..."
ALERT_JSON=$(curl -sS "$API/api/alerts")
ALERT=$(echo "$ALERT_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); a=[x for x in d if x['site_id']=='$SITE'][0]; print(a['id'])")
echo "  Alert id: $ALERT"
curl -sS -X POST "$API/api/alerts/$ALERT/export-sinagir" > /tmp/sinagir_${ALERT}.json
python3 -m json.tool < /tmp/sinagir_${ALERT}.json | head -30 || true
echo "  (full: /tmp/sinagir_${ALERT}.json)"

echo ""
echo "[Acto 4b] Emitiendo CAP v1.2 XML institucional..."
SITE_META=$(echo "$ALERT_JSON" | python3 -c "
import json,sys
d=json.load(sys.stdin)
a=[x for x in d if x['site_id']=='$SITE'][0]
sev_map={'red':'severe','orange':'severe','yellow':'moderate','green':'minor'}
print(json.dumps({
  'site_id': a['site_id'],
  'lat': -32.9468,
  'lon': -60.6393,
  'severity': sev_map.get(a['level'],'minor'),
  'headline': f\"Alerta {a['level'].upper()} en {a['site_id']}\",
  'summary': a['summary'],
  'instruction': 'Activar protocolo de Defensa Civil y evacuar zonas anegadas.',
  'areaDesc': a['site_id'],
}))")
curl -sS -X POST "$API/cap/emit" \
  -H "Content-Type: application/json" \
  -d "$SITE_META" -o "/tmp/cap_alert_${ALERT}.xml"
echo "  CAP XML -> /tmp/cap_alert_${ALERT}.xml"
head -c 900 "/tmp/cap_alert_${ALERT}.xml"; echo "..."
