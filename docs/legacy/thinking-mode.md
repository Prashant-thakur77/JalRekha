# P1 — Auditable Thinking-Mode Chain

Every `FusedAlert` of level yellow/orange/red now carries a Spanish-language reasoning
block (`reasoning_summary`, `reasoning_chain`, `reasoning_model`) produced by the local
Gemma runtime. Green alerts skip the LLM; the field is populated with a rule-skip
sentence. If the configured Gemma endpoint is unreachable, a deterministic
fallback fills the block so alert emission never blocks on model availability.

Service: `backend/src/jalrekha/services/reasoning.py`
Wired in: `backend/src/jalrekha/services/decision_engine.py::recompute_site_alert`
Exposed via: `GET /api/alerts/{id}` (adds `reasoning_chain_parsed` + `decision_trace_parsed`).

## Example 1 — green (LLM skipped)

Input: no recent node, volunteer, or hydromet signals for a site.

```
level: green
score: 0.00
reasoning_model: rule-skip-green
reasoning_summary: "Nivel verde: no se supera umbral de riesgo. No se invoca Gemma."
```

No LLM call made. Latency cost: 0ms.

## Example 2 — yellow (Gemma invoked)

Inputs:
- node waterline_ratio=0.52, rise_velocity=0.08, crossed=False, confidence=0.76
- volunteer parsed: water_level_category=medium, trend=rising, road_status=caution
- hydromet: precipitation_mm=3.1, river_discharge_trend=0.6

Gemma output from a development run:

```
reasoning_model: gemma4:e2b
reasoning_summary: "Se emitio amarillo porque waterline_ratio=0.52 indica nivel
  medio y trend rising en el reporte voluntario confirma la subida. road_status
  caution y precipitacion_mm=3.1 refuerzan el riesgo sin cruzar la linea critica."
reasoning_chain:
  - "revisar waterline_ratio y rise_velocity"
  - "confirmar tendencia con reporte voluntario"
  - "ajustar por precipitacion reciente"
```

## Example 3 — red (Gemma invoked, both sources corroborating)

Inputs:
- node crossed_critical_line=True, waterline_ratio=0.84
- volunteer: water_level_category=critical, road_status=blocked, urgency=critical
- deterministic rules fired: `node=0.88`, `volunteer=0.95`, `supporting_sources=2`

Gemma output:

```
reasoning_model: gemma4:e2b
reasoning_summary: "Alerta roja: crossed_critical_line=True con waterline_ratio=0.84
  y el voluntario confirma water_level_category=critical con road_status=blocked.
  Dos fuentes coinciden, urgency=critical."
reasoning_chain:
  - "linea critica cruzada en nodo"
  - "reporte voluntario confirma"
  - "corroboracion -> escalar a rojo"
```

## Fallback example (LLM unreachable)

If the configured Gemma endpoint is down, the same red scenario yields:

```
reasoning_model: rule-fallback
reasoning_summary: "Alerta red emitida por regla local. Senales activas:
  node=0.88, volunteer=0.95, supporting_sources=2. Gemma no disponible,
  se usa resumen deterministico."
reasoning_chain: ["node=0.88", "volunteer=0.95", "supporting_sources=2"]
```

## Tests

`backend/tests/test_reasoning.py` covers:
- green skip path,
- rule-fallback when no LLM passed,
- rule-fallback when LLM returns None,
- successful LLM parse with `Cadena:` split,
- round-trip chain serialize/deserialize,
- end-to-end persistence via `POST /api/reports` → `GET /api/alerts/{id}`.

## UI

- Web: `frontend/src/pages/Dashboard.tsx` + `SiteDetail.tsx` render collapsible
  "Razonamiento de Gemma" section inside alert cards.
- Android: `android/.../ui/JalRekhaApp.kt::ReasoningPanel` renders equivalent
  collapsible inside `AlertCard`.

## Honesty note

The chain_of_thought list is a coarse surrogate extracted from Gemma's Spanish
output (either an explicit `Cadena:` line or the first 3 sentence fragments).
This is not a raw token-level trace — it is the model's own structured
explanation. The rule-based `decision_trace` list is always present alongside.
