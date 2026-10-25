# Backend

FastAPI service for the JalRekha backend.

## Key services

- Gemma-first fixed-camera multimodal assessment through `NodeAssessmentEngine`
- temporal frame extraction with ffmpeg and Pillow optimization; no OpenCV in the JalRekha Node visual decision path
- persisted audit artifact packs for node analyses
- volunteer report parsing through a local Gemma-compatible endpoint with rule fallback
- live hydromet snapshots from Open-Meteo
- fused alert scoring and SQLite sync replication
- bundled sample clip analysis for the USGS Silverado demo site

## Runtime defaults

The fixed JalRekha Node now defaults to a Raspberry Pi 8 GB multimodal demo profile and an
embedded LiteRT-LM runtime:

Install system ffmpeg before running video capture or sample-clip analysis:

```bash
sudo apt-get install -y ffmpeg
```

```bash
JALREKHA_NODE_PROFILE=raspberry-pi-8gb-multimodal-demo
JALREKHA_DATA_DIR=/mnt/jalrekha/data
JALREKHA_NODE_PROVIDER=litert
JALREKHA_NODE_MODEL_PATH=/mnt/jalrekha/data/models/gemma-4-E2B-it.litertlm
JALREKHA_NODE_BACKEND=gpu
JALREKHA_NODE_MULTIMODAL_BACKEND=cpu
JALREKHA_NODE_MULTIMODAL_VISION_BACKEND=cpu
JALREKHA_NODE_CACHE_DIR=/mnt/jalrekha/data/litert-cache
JALREKHA_NODE_ENABLE_SPECULATIVE_DECODING=true
JALREKHA_NODE_MAX_OUTPUT_TOKENS=1024
JALREKHA_NODE_MULTIMODAL_MAX_OUTPUT_TOKENS=2048
JALREKHA_MULTIMODAL_ENABLED=true
JALREKHA_MULTIMODAL_VERIFIER_ENABLED=false
JALREKHA_MULTIMODAL_MODEL=gemma-4-E2B-it.litertlm
JALREKHA_MULTIMODAL_MAX_FRAMES=1
JALREKHA_MULTIMODAL_FRAME_SAMPLE_SECONDS=300
JALREKHA_MULTIMODAL_IMAGE_MAX_SIDE=512
JALREKHA_MULTIMODAL_NUM_CTX=1024
JALREKHA_MAX_CURATED_FRAMES=1
JALREKHA_ARTIFACT_RETENTION_DAYS=3
```

For this profile, JalRekha Node prepares one optimized frame and attempts Gemma 4
multimodal through LiteRT-LM. On the measured Raspberry Pi 5 setup, text and
reasoning smoke inference work with `gpu` and speculative
decoding enabled. The GPU vision path fails on the software WebGPU stack, but
one-image LiteRT multimodal smoke succeeds on the Pi with the CPU multimodal
engine and a 2048-token engine budget. With 1024 or fewer multimodal tokens the
image path can fail before inference because the vision patches exceed the
token cap.
The full sample-node endpoint was also exercised on the Pi and returned
`runner.mode=litert-multimodal-temporal`, `assessment_mode=gemma4-multimodal-v1`,
and `frames_analyzed=1`. Treat this endpoint result as the full JalRekha Node P1
evidence; treat `scripts/litert_smoke.py --image` as a one-image runtime smoke.

`/api/settings/runtime` exposes `p1_runtime_ready=true` when the LiteRT provider
and model are ready. That is a readiness signal, not proof that an JalRekha Node
analysis completed; use `runner.mode=litert-multimodal-temporal` from an
analysis response for evidence.
The Raspberry Pi 16 GB / workstation profile
uses the same path with more frames and context through
`../scripts/run_node_pi16_multimodal_prod.sh`. JalRekha Volunteer is treated as a
separate user/volunteer node and is not sized by this Raspberry Pi fixed-node
profile.

For local development only, the fixed node can still use Ollama by setting
`JALREKHA_NODE_PROVIDER=ollama`. That path is explicit dev mode only; LiteRT
never falls back to Ollama automatically in production.

The Pi fixed-node scripts set `JALREKHA_LLM_ENABLED=false` by default so the
fixed JalRekha Node profile stays LiteRT-only. If the same backend is reused for a
full integrated JalRekha Volunteer demo, explicitly re-enable and configure the development
Gemma endpoint for report structuring; that does not change which JalRekha Node
node inference counts for P1.

Download the model once before the first real run:

```bash
export REPO_DIR=/opt/jalrekha
cd "$REPO_DIR/backend"
python -m pip install -e .[dev]
cd ..
python scripts/fetch_litert_model.py
python scripts/fetch_demo_assets.py
python scripts/litert_smoke.py
```

Use `../scripts/node_guard.py` on the Pi to record short clips from
`JALREKHA_CAMERA_SOURCE` and submit them to `/api/node/analyze` on a fixed
interval. The backend extracts the configured number of frames and sends them
directly to Gemma 4 multimodal.

## Core node-assessment contract

The fixed-node pipeline now produces a node assessment package centered on:

- `assessment_level`
- `assessment_score`
- `temporal_summary`
- `reasoning_summary`
- `reasoning_steps`
- `critical_evidence`
- `runner_name`
- `runner_mode`
- `fallback_used`
- audit artifact references

The external API surface remains stable; these fields are added to the existing node-analysis responses.

## Seed and tests

```bash
PYTHONPATH=src python -m jalrekha.scripts.seed
PYTHONPATH=src pytest -q
```
