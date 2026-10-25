# Architecture

## System shape

```text
[ Fixed Camera Clip ] ----> [ Temporal Evidence Builder ] ----> [ Gemma Assessment Runner ] ----> [ JalRekha Node Assessment Pack ]
[ Bundled USGS Clip ] ----> [ sample-node-analysis ] --------------------------------------------^
[ Volunteer PWA ] --------> [ FastAPI Backend ] -------------------------------------------------> [ edge.db ] -> [ sync queue ] -> [ central.db ]
[ Open-Meteo APIs ] ------> [ Hydromet Snapshot ]
[ Local LiteRT-LM Gemma ] -> [ JalRekha Node Assessment + Alert Reasoning ]
[ Separate JalRekha Volunteer App ] ----> [ Volunteer Reports / User Node ]
```

## Responsibilities

### JalRekha Node assessment

- input: uploaded video clip from a fixed camera or a bundled per-site sample clip
- processing:
  - sample roughly 1 FPS
  - apply the stored ROI mask
  - curate a bounded temporal frame bundle around the highest-risk window
  - preserve non-semantic hints such as motion, contrast, edge strength, and waterline ratio hints
  - hand the compact temporal evidence pack to Gemma for the actual node verdict
- output:
  - `assessment_level`
  - `assessment_score`
  - `temporal_summary`
  - `reasoning_summary`
  - `reasoning_steps`
  - `critical_evidence`
  - persisted audit artifacts

### Volunteer report flow

- input: site, operator metadata, transcript, optional photo/audio attachments
- PWA stores reports offline first in IndexedDB
- backend persists the report, structures it with local Gemma when available, and falls back to deterministic rules otherwise
- output: `VolunteerReport`, `ParsedObservation`, and a recomputed `FusedAlert`

## Backend Module Boundaries

`backend/src/jalrekha/main.py` is intentionally thin. It creates the
FastAPI app, mounts static assets, and includes routers.

- `api/routers/node.py`: fixed-camera node analysis, sample-node analysis,
  frame explanation, and JalRekha Node assessment artifact creation.
- `api/routers/volunteer.py`: volunteer report submission and report listing.
- `api/routers/sites.py`: shared site registry, calibration, and hydromet
  snapshots.
- `api/routers/alerts.py`: shared fused-alert reads, recomputation, and SINAGIR
  export.
- `api/routers/runtime.py`: health, runtime status, and connectivity toggle.
- `api/routers/sync.py`: edge-to-central queue flush.
- `api/deps.py`: shared runtime singletons such as the LLM client, JalRekha Node
  engine, image assessor, text structurer, external-data service, and sync queue
  helper.
- `api/serializers.py`: API response shaping for sites, hydromet snapshots, and
  node observations.

Team ownership guideline:

- JalRekha Node work should prefer `services/node_assessment.py`,
  `adapters/video_assessment.py`, and `api/routers/node.py`.
- JalRekha Volunteer work should prefer `services/report_structuring.py`, text adapters,
  `api/routers/volunteer.py`, and the Android/PWA report queues.
- `services/decision_engine.py`, `api/routers/alerts.py`, domain models, and
  shared docs are integration surfaces. Coordinate changes there before merging.

### Live hydromet context

- provider: Open-Meteo weather forecast API + Open-Meteo flood API
- lookup key: site latitude/longitude
- output: `HydrometSnapshot`
- used to enrich site detail pages and to boost fused risk when weather and river conditions support escalation

### Central integration and incident lifecycle

The central layer now treats JalRekha Node, JalRekha Volunteer, and hydromet records as evidence
for one operational decision. `services/decision_engine.py` evaluates a default
45 minute evidence window per site, applies temporal decay, detects
corroboration across sources, records contradictions, and emits a structured
`decision_trace` with the exact evidence IDs, weights, rules, and severity
contract used.

Severity is normalized to a 0.0-1.0 score:

- `green`: no recent operational risk evidence.
- `yellow`: incipient risk or moderate local evidence that requires monitoring.
- `orange`: high corroborated risk or one critical source that requires local preparation/action.
- `red`: severe observed risk or impact requiring immediate action.

`FusedAlert` remains the operator-facing projection. It is linked to an
`Incident` when the site has sustained yellow risk, any orange/red alert, or a
critical human report. Recomputes update the active incident instead of opening a
new incident for every alert. Incidents move through `monitoring`, `active`,
`escalated`, `stabilizing`, and `closed`.

Actuation is separated from the decision. The engine recommends siren, radio,
and app actions for orange/red alerts, records every attempt in
`ActuationRecord`, and uses incident-level idempotency so repeated recomputes do
not refire the same critical action. In production LiteRT mode,
`dispatch_actuators` asks `LiteRTNodeRuntime` for strict JSON `tool_calls`
selection and never contacts Ollama. This is structured tool selection, not a
native LiteRT function-calling API exposed by the current wrapper. If selection
returns no valid tools or omits some recommended tools, orange/red alerts use
deterministic fallback to fire the missing recommended actuators. The operational
path therefore does not depend on a complete model tool-selection response, and
tools already selected by LiteRT are not refired. Model-selected tools are
constrained to the deterministic recommended pending actuators for the alert
level.

Operator endpoints:

- `GET /api/sites/{site_id}/operator-summary`
- `GET /api/incidents/{incident_id}/timeline`
- `POST /api/incidents/{incident_id}/ack`
- `POST /api/incidents/{incident_id}/close`
- `POST /api/alerts/{alert_id}/export-sinagir`

Sync now includes queue attempts, last error, synced timestamp, partial failure
status, idempotent queue updates for the same pending entity, and
`GET /api/sync/status`.

## Runtime model contract

The fixed `JalRekha Node` node uses the embedded LiteRT-LM Python runtime for the
production Pi path. The expected artifact is
`litert-community/gemma-4-E2B-it-litert-lm` /
`gemma-4-E2B-it.litertlm`.

Default production runtime for the fixed JalRekha Node:

- LiteRT-LM package installed in the backend virtual environment
- `gemma-4-E2B-it.litertlm` stored under `$JALREKHA_DATA_DIR/models` or the
  explicit `JALREKHA_NODE_MODEL_PATH`
- `JALREKHA_NODE_PROFILE=raspberry-pi-8gb-multimodal-demo`
- `JALREKHA_DATA_DIR=/mnt/jalrekha/data` on SSD/NVMe
- `JALREKHA_NODE_PROVIDER=litert`
- `JALREKHA_NODE_BACKEND=gpu`
- `JALREKHA_NODE_MULTIMODAL_BACKEND=cpu`
- `JALREKHA_NODE_MULTIMODAL_VISION_BACKEND=cpu`
- `JALREKHA_NODE_ENABLE_SPECULATIVE_DECODING=true`
- `JALREKHA_NODE_MAX_OUTPUT_TOKENS=1024`
- `JALREKHA_NODE_MULTIMODAL_MAX_OUTPUT_TOKENS=2048`
- `JALREKHA_MAX_CURATED_FRAMES=1`
- `JALREKHA_ARTIFACT_RETENTION_DAYS=3`
- `JALREKHA_MULTIMODAL_ENABLED=true`
- `JALREKHA_MULTIMODAL_VERIFIER_ENABLED=false`
- `JALREKHA_MULTIMODAL_MODEL=gemma-4-E2B-it.litertlm`
- `JALREKHA_MULTIMODAL_MAX_FRAMES=1`
- `JALREKHA_MULTIMODAL_FRAME_SAMPLE_SECONDS=300`
- `JALREKHA_MULTIMODAL_IMAGE_MAX_SIDE=512`
- repo helper scripts: `scripts/fetch_litert_model.py`,
  `scripts/litert_smoke.py`, `scripts/run_node_pi8_multimodal_demo.sh`, and
  `scripts/run_node_pi16_multimodal_prod.sh`

Ollama is retained only for explicit development mode and JalRekha Volunteer/local
experiments. It is not an automatic production fallback for JalRekha Node; if
LiteRT-LM is unavailable, the node must report that state instead of silently
switching to Ollama.

`/api/settings/runtime` exposes `p1_runtime_ready` as a runtime readiness flag
for this LiteRT configuration. Jury-facing evidence must come from an actual
analysis response, specifically `runner.mode=litert-multimodal-temporal`.

Measured Pi 5 8 GB benchmark evidence lives in
`docs/legacy/benchmark-card.md` and `docs/legacy/e2b-e4b-ablation.md`.
Known constraints are part of the runtime contract: TTFT and decode tok/s are
not estimated because this wrapper exposes only final responses; E2B is the Pi 5
8 GB operating model; E4B GPU text/reasoning fails on this hardware with WebGPU
buffer/command errors; and the GPU text-engine reuse issue is mitigated with a
single engine-reset retry that can raise latency/RSS on the retry path.

On Raspberry Pi 8 GB, JalRekha Node is multimodal-first but sparse: ffmpeg extracts
one optimized frame and Gemma 4 performs the visual interpretation. OpenCV is not
used in the JalRekha Node decision path. The Raspberry Pi 16 GB /
workstation production profile keeps the same code path but raises frame count,
image size, context, and timeout.

`scripts/node_guard.py` is the deployable fixed-camera loop for this profile: it
records short clips from `JALREKHA_CAMERA_SOURCE`, posts them to `/api/node/analyze`,
and lets the backend extract frames and call Gemma 4 multimodal directly.

`JalRekha Volunteer` is not part of this fixed-node hardware target. It remains a separate
volunteer/user node and can run on Android/PWA/client hardware independently.

## Persistence

### edge.db

Operational local state:

- `Site`
- `SiteCalibration`
- `NodeObservation`
- `NodeAssessmentArtifact`
- `VolunteerReport`
- `ParsedObservation`
- `HydrometSnapshot`
- `FusedAlert`
- `Incident`
- `ActuationRecord`
- `SyncQueueItem`

`NodeObservation` is the compatibility-facing projection. `NodeAssessmentArtifact` stores the richer audit pack for demos and review.

### central.db

Receives synced copies of queued entities from `edge.db`.

## UI surfaces

- `Dashboard`: current alerts + site access
- `Site Detail`: hydromet refresh, reference frame preview, bundled sample analysis, upload analysis, temporal summary, runner metadata, and evidence artifacts
- `Calibration`: save ROI and threshold lines against a stored site frame
- `Report`: volunteer observation form with offline-first queueing
- `Queue`: flush locally stored reports
- `Runtime`: local Gemma endpoint + hydromet connectivity status
