# NadiSaathi agent, region and relief API (v1)

All routes are under `/api`. Times are ISO-8601 UTC strings. Every response is
JSON unless noted. The older routes (sites, node, reports, alerts, sync, CAP)
are unchanged; see `docs/legacy/architecture.md` (edge stack) and `docs/ARCHITECTURE.md` (cloud + agent).

Operator-only routes need the header `X-Operator-Pin: <pin>`. The PIN is
`JALREKHA_OPERATOR_PIN` on the server (default `2468` in local dev; the cloud PIN
is set from SSM Parameter Store). A wrong PIN returns 401.

## Regions and rivers

`GET /api/regions` → `RegionSummary[]`

```json
{"id": "np", "name": "Nepal", "country_code": "NP",
 "languages": [{"code": "ne", "name": "Nepali", "native_name": "नेपाली", "script": "Deva",
                "tts": {"provider": "polly", "voice": "Kajal", "engine": "neural", "language_code": "hi-IN", "note": "..."} ,
                "asr": {"provider": "whisper", "code": "ne", "note": "..."}}],
 "channels": ["sms", "voice", "cap", "siren", "telegram"],
 "authority_roles": [{"id": "ward_focal", "name": "Ward disaster focal person", "approves": ["send_sms"]}],
 "levels": [{"id": "warning", "label": {"en": "Warning", "hi": "चेतावनी", "ne": "चेतावनी"}, "color": "orange"}],
 "bounds": {"min_lon": 80.0, "max_lon": 88.3, "min_lat": 26.3, "max_lat": 30.5}}
```

`GET /api/regions/{id}` → full profile (above plus `admin_units[]`, `alert_format{}`, `agencies[]`).

`GET /api/rivers` → `[{"id": "koshi", "name": "Koshi / Kosi", "countries": ["NP", "IN"], "nodes": 5, "edges": 4}]`

`GET /api/rivers/{basin}` →

```json
{"id": "koshi", "name": "Koshi / Kosi",
 "nodes": [{"id": "chatara", "name": "Chatara", "country": "NP", "lat": 26.82, "lng": 87.16,
            "kind": "gauge|camera|barrage|village", "river": "Sapta Koshi",
            "warning_m": 5.5, "danger_m": 6.8, "agency": "DHM", "site_id": "koshi-chatara-cam" ,
            "region_id": "np", "admin_unit": "Sunsari"}],
 "edges": [{"from": "chatara", "to": "koshi_barrage", "distance_km": 42,
            "travel_time_h": {"min": 2.0, "typ": 3.0, "max": 4.5},
            "method": "estimate: distance/celerity", "source": "..."}]}
```

`GET /api/rivers/{basin}/eta?from_node=chatara&rate_m_per_h=0.6` →

```json
{"basin": "koshi", "from_node": "chatara", "computed_at": "...",
 "downstream": [{"node_id": "birpur", "name": "Birpur", "country": "IN", "region_id": "in",
                 "eta_h": {"min": 3.1, "typ": 4.6, "max": 6.8}, "path": ["chatara", "koshi_barrage", "birpur"],
                 "crosses_border": true}]}
```

## Agent

`GET /api/agent/state` → per site:

```json
[{"site_id": "koshi-chatara-cam", "mode": "normal|watch|alert|degraded", "cadence_s": 60,
  "last_stage_m": 4.21, "last_sigma_m": 0.03, "last_rate_m_per_h": 0.62, "last_quality": "ok",
  "basin": "koshi", "node_id": "chatara", "region_id": "np", "updated_at": "..."}]
```

`POST /api/agent/cycle` (multipart): `site_id` + one or more `frames` (images) →
the trace of the cycle that ran (shape below). Used by the edge box and tests.

`GET /api/agent/traces?site_id=&limit=50` → newest first:

```json
[{"trace_id": "tr_8f2c...", "site_id": "...", "cycle": 12, "started_at": "...",
  "branches": ["D4", "D5"], "summary": "Rise 0.62 m/h → cadence 60→10 s; ETA Birpur 4.6 h; SMS drafted for approval",
  "steps": 9, "scenario_run_id": "run_..."}]
```

`GET /api/agent/traces/{trace_id}` →

```json
{"trace_id": "...", "site_id": "...", "cycle": 12, "started_at": "...", "branches": ["D4"],
 "measurement": {"stage_m": 4.21, "sigma_m": 0.03, "rate_m_per_h": 0.62, "usable": true,
                 "quality": {"ok": true, "reasons": []}, "estimators": {"E1_edge": 4.20, "E2_temporal": 4.22, "E3_colour": 4.21},
                 "registration": "orb", "overlay_url": "/uploads/...png", "frame_url": "/uploads/...jpg",
                 "timings_ms": {"total": 61.2}},
 "steps": [{"i": 0, "t": "...", "kind": "tool|decision|guard|approval|fallback",
            "tool": "measure_stage", "input": {}, "output": {},
            "decision": {"branch": "D4", "reason": "rate 0.62 m/h ≥ 0.30 m/h", "before": {"cadence_s": 60}, "after": {"cadence_s": 10}},
            "latency_ms": 61.2, "cost_usd_est": 0.0, "model": null,
            "guard": {"accepted": true, "reason": "accepted"}}]}
```

Branch ids (the places where an OpenCV output changes the next action):
`D1` quality gate, `D2` registration rescue, `D3` estimator disagreement → VLM,
`D4` fast rise → cadence + ETA, `D5` projected crossing → downstream drafts,
`D6` danger + good quality → local siren, `D7` VLM contradicts CV → keep CV + human,
`D8` relief photo blocked → route board approval, `D9` falling → cadence down + all-clear proposal.

## Approvals (human in the loop)

`GET /api/approvals?status=pending|approved|rejected|all` →

```json
[{"id": 7, "created_at": "...", "status": "pending", "action": "send_sms|voice_call|publish_cap|cross_border_notify|all_clear|publish_route_status|dispatch_relief",
  "site_id": "...", "region_id": "in", "role": "ddma_control_room", "title": "Koshi rise: Birpur in ~4.6 h",
  "rationale": "...", "trace_id": "...",
  "payload": {"messages": [{"lang": "hi", "text": "...", "chars": 132, "segments": 2}],
              "audio": [{"lang": "hi", "url": "/uploads/audio/....mp3"}],
              "cap_xml": "<?xml ...", "eta": {"min": 3.1, "typ": 4.6, "max": 6.8}, "recipients": "Supaul embankment villages (role-based list)"},
  "evidence": [{"label": "Upstream stage", "value": "4.21 m ± 0.03", "source": "tr_...#2"}],
  "decided_by": null, "decided_at": null, "decision_note": null, "dispatch": null}]
```

`POST /api/approvals/{id}/decision` (header `X-Operator-Pin`):
`{"decision": "approve|reject", "operator": "Rakesh (DDMA)", "note": "", "edited_messages": [{"lang": "hi", "text": "..."}]}`
→ the updated approval. On approve the dispatch runs (SNS SMS / Polly / CAP /
stub) and `dispatch` holds `{channel: status}`.

## Scenario replays (the live demo)

`GET /api/scenarios` → `[{"id": "koshi-rise", "title": "...", "description": "...", "basin": "koshi", "label": "SCENARIO REPLAY (synthetic camera frames)", "steps": 24}]`

`POST /api/scenarios/{id}/run` body `{"speed": 1.0}` → `{"run_id": "run_...", "status": "running"}`
(runs in the background; every step is one agent cycle on real OpenCV measurements).

`GET /api/scenarios/runs/{run_id}` → `{"run_id": "...", "scenario_id": "...", "status": "running|done|failed", "step": 7, "total": 24, "trace_ids": [...], "approval_ids": [...], "error": null}`

`GET /api/sites/{id}/live` →

```json
{"site": {"id": "...", "name": "...", "region": "..."}, "warning_m": 5.5, "danger_m": 6.8,
 "latest": {"at": "...", "frame_url": "/uploads/...", "overlay_url": "/uploads/...", "stage_m": 4.21, "sigma_m": 0.03,
            "rate_m_per_h": 0.62, "quality_ok": true, "quality_reasons": [], "usable": true},
 "series": [{"t": "...", "stage_m": 4.1, "sigma_m": 0.03}],
 "agent": {"mode": "watch", "cadence_s": 10}}
```

## Relief layer

`POST /api/relief/requests` `{"text": "...", "lang": "hi|ne|en|mai|bho", "lat": 26.1, "lng": 86.9, "site_id": null, "channel": "app|sms|voice", "people": null}`
→ `{"id": 3, "need": "rescue|food|water|medical|shelter|other", "people": 6, "urgency": "critical|high|medium|low", "priority": 0.86, "duplicate_of": null, "status": "pending_approval", "parsed_by": "rules|llm"}`

`GET /api/relief/requests` → list, highest priority first.
`POST /api/relief/requests/{id}/decision` (PIN) `{"decision": "approve|reject", "operator": "...", "team": "NGO boat team 2"}`.

`POST /api/relief/photo-check` (multipart): `photo`, optional `ref_top_x, ref_top_y, ref_bottom_x, ref_bottom_y` (pixels) and `ref_height_m` (default 1.0) →
`{"water_fraction": 0.41, "waterline_y": 312, "submerged_frac": 0.55, "est_depth_m": 0.55, "depth_pm_m": 0.08, "passable": "no|yes|unknown", "confidence": 0.7, "needs_review": true, "overlay_url": "/uploads/...", "faces_blurred": 0}`

`GET /api/relief/routes` → `[{"id": "...", "name": "NH-27 Kosi bridge approach", "status": "passable|blocked|unknown", "verified": true, "updated_at": "...", "source": "approval #4"}]`
`GET /api/relief/shelters?region_id=in` → `[{"id": "...", "name": "...", "region_id": "in", "admin_unit": "Supaul", "lat": 26.1, "lng": 86.6, "capacity": 400, "occupancy": 120}]`

`GET /api/sitrep/{region_id}` → `{"region_id": "in", "generated_at": "...", "text": "...", "numbers": [{"value": "4.6 h", "label": "ETA Birpur", "source": "tr_...#5"}], "model": "template|bedrock:<id>", "fallback_used": true}`

## Evidence

`GET /api/evidence` → the headline numbers read from `eval/results/*.json`
(the same file the README tables are generated from):
`{"generated_from": ["eval/results/..."], "items": [{"key": "stage_mae_cm_full", "label": "...", "value": 8.0, "unit": "cm", "baseline": {"name": "...", "value": 74.7}, "dataset": "held-out ...", "file": "..."}]}`
