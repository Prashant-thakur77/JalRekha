# P6 — SINAGIR Mapping

## Context

Argentina's **Sistema Nacional para la Gestión Integral del Riesgo y la
Protección Civil (SINAGIR)** was created by Ley 27.287/2016. Its operational
event registry is **SINAME** (Sistema Nacional de Monitoreo y Alerta
Temprana). Resolución 334/2026 approved the **Plan Nacional para la
Reducción del Riesgo de Desastres 2025-2029**, which prioritizes
hydrometeorological early-warning systems. Roughly **60% of registered
disasters in Argentina are floods** (SINAGIR annual report).

Portal: <https://www.argentina.gob.ar/sinagir/siname>.

Our product aims for **SINAGIR-compatible output** — a normalized event
payload that a provincial SINAGIR integrator can consume without schema
translation. We do *not* claim live SINAGIR API integration.

## Field mapping

| JalRekha Node `FusedAlert` field | SINAGIR / SINAME concept | Notes |
|---|---|---|
| `id` (internal int) | `external_id` | We wrap as `node-alert-{id}` to avoid collision |
| `site_id` | `evento.sitio.id` | Free-form in SINAME; our id is stable |
| `site.name` | `evento.sitio.nombre` | |
| `site.region` | `evento.sitio.provincia` | Free text today; a lookup against INDEC province codes is future work |
| `site.lat`, `site.lng` | `evento.sitio.coords` | WGS84 decimal degrees, SINAME compatible |
| `created_at` | `evento.fecha_hora` | UTC ISO-8601 |
| `level` (green/yellow/orange/red) | `evento.severidad.nivel` | SINAGIR uses verde/amarillo/naranja/rojo — direct mapping |
| `score` (0.0–1.0) | `evento.severidad.indice` | Numeric auxiliary, not in current SINAME but allowed as metadata |
| `trigger_source` (node/volunteer/hydromet/fused) | `evento.origen` | |
| `summary` | `evento.resumen` | |
| `decision_trace.rules_fired` | `evento.explicacion` | Backward-compatible export keeps this as `explanation: list[str]` |
| `decision_trace` (structured JSON) | `evento.trazabilidad` | Includes window, evidence IDs, weights, rules, and source payload summaries |
| `incident_id` | `evento.incidente.id` | Operational continuity across recomputes |
| `reasoning_summary` + `reasoning_chain` | `evento.justificacion` | SINAGIR does not mandate a structure for explanation; we expose as sub-object |
| `reasoning_model` | `evento.fuente_ai` | Metadata only; SINAGIR does not yet standardize AI provenance |
| `local_alarm_triggered` | `evento.actuacion_local` | Boolean |
| `ActuationRecord[]` | `evento.actuacion_local.records` | Siren/radio/app attempts, status, errors, timestamps |
| hazard type | `evento.tipo` = `"inundacion"` | Hardcoded for this MVP |

## What is compatible today

- Spanish level names (verde/amarillo/naranja/rojo) align with SINAGIR's
  color-coded severity.
- Coordinate system (WGS84 dd) matches SINAME's expected input.
- Timestamps are timezone-aware ISO-8601.
- Event payload carries a human-readable explanation (`explanation` +
  `reasoning_summary`) and structured trace (`decision_trace`) for audit.
- Incident and actuation records are exported alongside the alert so the payload
  can show both the decision and the operational response.

## What requires future work

- **No live SINAGIR API integration.** Our export produces JSON; a provincial
  integrator would have to POST it to their SINAGIR gateway.
- INDEC province-code normalization for `region`.
- Standardized AI provenance metadata (none exists in SINAGIR today; we ship a
  best-guess schema extension).
- Chain-of-custody / multi-party signature — future requirement from
  Plan Nacional 2025-2029 for cross-provincial events.

## Export endpoint

```
POST /api/alerts/{alert_id}/export-sinagir
```

Response (example from a red alert on `silverado-fixed-cam-usgs`):

```json
{
  "schema": "sinagir-ready-v1",
  "disclaimer": "Schema export only. Not submitted to SINAGIR production endpoints.",
  "event": {
    "external_id": "node-alert-7",
    "observed_at": "2026-04-20T15:31:52Z",
    "site": {
      "id": "silverado-fixed-cam-usgs",
      "name": "Silverado Fixed Cam (USGS)",
      "region": "Demo",
      "lat": -32.95,
      "lng": -60.64
    },
    "hazard_type": "inundacion",
    "severity": {"level": "red", "score": 0.98},
    "trigger_source": "volunteer",
    "summary": "Volunteer report: water=critical, trend=rising, road=blocked",
    "explanation": ["volunteer_mark_exceeded", "volunteer_road_cut"],
    "decision_trace": {
      "schema": "decision-trace-v2",
      "window": {"minutes": 45},
      "rules_fired": ["volunteer_mark_exceeded", "volunteer_road_cut"],
      "evidence": [{"source": "volunteer", "entity_id": 12, "weighted_score": 0.92}]
    },
    "reasoning": {
      "summary": "Alerta roja: el reporte voluntario confirma agua critica...",
      "chain": ["paso la marca critica", "ruta cortada", "escalar"],
      "model": "gemma4:e2b"
    },
    "local_actuation": {
      "siren_triggered": true,
      "records": [{"actuator_type": "trigger_alarm", "status": "success"}]
    },
    "incident": {"id": 3, "state": "escalated", "current_level": "red"},
    "origin_system": "JalRekha (edge)"
  }
}
```

## Side-by-side comparison

Our `fused-alert.schema.json` vs a minimal SINAME-equivalent:

```
shared/schemas/fused-alert.schema.json          SINAME (inferred from portal)
─────────────────────────────────────────       ─────────────────────────────
site_id              string                     evento.sitio.id          string
created_at           datetime                   evento.fecha_hora        iso8601
level                enum green|...|red         evento.severidad.nivel   enum verde|...|rojo
score                float                      (metadata)
summary              string                     evento.resumen           string
decision_trace       list[string]               evento.explicacion       list[string]
local_alarm_triggered bool                      evento.actuacion_local   bool
```
