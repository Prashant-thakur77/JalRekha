# Raspberry Pi JalRekha Node

This guide prepares a fixed JalRekha Node camera node with Gemma 4 through
LiteRT-LM. The Raspberry Pi 8 GB profile is the minimum field/demo target; the
Raspberry Pi 16 GB / workstation profile uses the same production code path
with more frames and a larger context budget.

## Pi 8 demo profile

```bash
export JALREKHA_NODE_PROFILE=raspberry-pi-8gb-multimodal-demo
export JALREKHA_DATA_DIR=/mnt/jalrekha/data
export JALREKHA_UPLOAD_DIR=/mnt/jalrekha/data/uploads
export JALREKHA_NODE_PROVIDER=litert
export JALREKHA_NODE_MODEL_PATH=/mnt/jalrekha/data/models/gemma-4-E2B-it.litertlm
export JALREKHA_NODE_BACKEND=gpu
export JALREKHA_NODE_MULTIMODAL_BACKEND=cpu
export JALREKHA_NODE_MULTIMODAL_VISION_BACKEND=cpu
export JALREKHA_NODE_CACHE_DIR=/mnt/jalrekha/data/litert-cache
export JALREKHA_NODE_ENABLE_SPECULATIVE_DECODING=true
export JALREKHA_NODE_MAX_OUTPUT_TOKENS=1024
export JALREKHA_NODE_MULTIMODAL_MAX_OUTPUT_TOKENS=2048
export JALREKHA_MULTIMODAL_ENABLED=true
export JALREKHA_MULTIMODAL_MODEL=gemma-4-E2B-it.litertlm
export JALREKHA_MULTIMODAL_MAX_FRAMES=1
export JALREKHA_MULTIMODAL_FRAME_SAMPLE_SECONDS=300
export JALREKHA_MULTIMODAL_IMAGE_MAX_SIDE=512
export JALREKHA_MULTIMODAL_NUM_CTX=1024
export JALREKHA_MULTIMODAL_TIMEOUT_SECONDS=300
```

This mode extracts one small frame from each short clip using ffmpeg, optimizes
it with Pillow, and sends it directly to Gemma 4 multimodal. There is no OpenCV
visual analysis in this path.

Measured Raspberry Pi 5 status for this profile:

- `JALREKHA_NODE_BACKEND=gpu` works for LiteRT text inference.
- `litert-lm-api==0.11.0` is the tested Python package version.
- The expected model file is `gemma-4-E2B-it.litertlm` under
  `$JALREKHA_DATA_DIR/models` or the explicit `JALREKHA_NODE_MODEL_PATH`.
- The bundled sample clip is
  `fixtures/media/usgs_silverado_fire_2015_fixed_cam.mp4` under the repo root.
- Gemma 4 E2B GPU multimodal fails on Pi 5 because LiteRT picks Mesa
  `llvmpipe` WebGPU and the vision encoder exceeds the available buffer size.
- Gemma 4 E2B one-image multimodal succeeds on Pi 5 with
  `JALREKHA_NODE_BACKEND=gpu`, `JALREKHA_NODE_MULTIMODAL_BACKEND=cpu`,
  `JALREKHA_NODE_MULTIMODAL_VISION_BACKEND=cpu`,
  `JALREKHA_NODE_MULTIMODAL_MAX_OUTPUT_TOKENS=2048`, and speculative decoding
  enabled.
- Generic cold text smoke is real LiteRT inference but slow on this Pi:
  `elapsed_seconds=130` in the measured run.
- JalRekha Node alert reasoning text now has a Pi-short prompt. A previous measured
  Pi run with a 256-token engine produced `reasoning_model=gemma-4-E2B-it.litertlm`
  in `350.18s` with about `3120 MB` max RSS. This is real LiteRT-LM inference,
  but too slow to claim stable operational latency on Raspberry Pi 5 8 GB. The
  current text profile uses 1024 tokens; the multimodal image profile uses 2048
  tokens because LiteRT internally expands the frame to more than 2300 visual
  patches.

## Pi 16 / workstation production profile

```bash
export JALREKHA_NODE_PROFILE=raspberry-pi-16gb-multimodal-prod
export JALREKHA_MULTIMODAL_MAX_FRAMES=4
export JALREKHA_MULTIMODAL_FRAME_SAMPLE_SECONDS=60
export JALREKHA_MULTIMODAL_IMAGE_MAX_SIDE=960
export JALREKHA_MULTIMODAL_NUM_CTX=4096
export JALREKHA_MULTIMODAL_TIMEOUT_SECONDS=240
```

Use `scripts/run_node_pi16_multimodal_prod.sh` on a workstation now, and on
a 16 GB Pi later. It keeps the exact same backend flow as the Pi 8 demo, just
with more visual evidence per analysis.

## LiteRT bootstrap

From the repo root, after creating `backend/.venv`:

```bash
export REPO_DIR=/opt/jalrekha
cd "$REPO_DIR"
python3 -m venv backend/.venv
source backend/.venv/bin/activate
python -m pip install -e backend/.[dev]
python scripts/fetch_litert_model.py
python scripts/fetch_demo_assets.py
python scripts/litert_smoke.py
```

This project uses the Python API (`litert-lm-api==0.11.0`) for production node
inference. Ollama remains acceptable only as an explicit development path for
JalRekha Volunteer or local experimentation, not as the JalRekha Node production engine on the Pi.

## Reproduce measured LiteRT inference on the Pi

From the repo root:

```bash
export REPO_DIR=/opt/jalrekha
cd "$REPO_DIR"
export PYTHONPATH=$PWD/backend/src
export JALREKHA_NODE_PROVIDER=litert
export JALREKHA_NODE_MODEL_PATH=$PWD/backend/data/models/gemma-4-E2B-it.litertlm
export JALREKHA_NODE_BACKEND=gpu
export JALREKHA_NODE_CACHE_DIR=$PWD/backend/data/litert-cache
export JALREKHA_NODE_ENABLE_SPECULATIVE_DECODING=true
export JALREKHA_NODE_MAX_OUTPUT_TOKENS=1024
backend/.venv/bin/python scripts/litert_smoke.py --reasoning
```

Expected success signal:

- first JSON: `health.reachable=true`, `health.provider=litert`, `health.backend=gpu`
- second JSON: `result.model_name=gemma-4-E2B-it.litertlm`
- `benchmark.elapsed_seconds` is measured wall-clock time for the call

This command does not start or query Ollama. If LiteRT fails, the result is
`model_name=rule-fallback`; that is a failure to count as P1 evidence, not an
automatic production fallback to Ollama.

To reproduce the measured one-image LiteRT path on the Pi:

```bash
export REPO_DIR=/opt/jalrekha
cd "$REPO_DIR"
export PYTHONPATH=$PWD/backend/src
export JALREKHA_NODE_PROVIDER=litert
export JALREKHA_NODE_MODEL_PATH=$PWD/backend/data/models/gemma-4-E2B-it.litertlm
export JALREKHA_NODE_BACKEND=gpu
export JALREKHA_NODE_MULTIMODAL_BACKEND=cpu
export JALREKHA_NODE_MULTIMODAL_VISION_BACKEND=cpu
export JALREKHA_NODE_CACHE_DIR=$PWD/backend/data/litert-cache
export JALREKHA_NODE_ENABLE_SPECULATIVE_DECODING=true
export JALREKHA_NODE_MULTIMODAL_MAX_OUTPUT_TOKENS=2048
backend/.venv/bin/python scripts/litert_smoke.py --image fixtures/frames/silverado_060s.jpg
```

Expected success signal: the result JSON is `{"status":"ok","engine":"litert"}`
and LiteRT logs drafted/verified speculative tokens.

This is a one-image runtime smoke. It proves the LiteRT multimodal engine can
read an image, but it is not the full JalRekha Node endpoint proof.

## Reproduce the full JalRekha Node P1 endpoint proof

Start the backend with the Pi profile:

```bash
export REPO_DIR=/opt/jalrekha
cd "$REPO_DIR"
./scripts/run_node_pi8_multimodal_demo.sh
```

From another terminal:

```bash
curl -sf http://127.0.0.1:8000/api/settings/runtime | jq '.node | {
  provider,
  backend,
  multimodal_backend,
  multimodal_vision_backend,
  speculative_decoding,
  engine_ready,
  p1_runtime_ready,
  model_path
}'

curl -sf -X POST \
  http://127.0.0.1:8000/api/sites/silverado-fixed-cam-usgs/sample-node-analysis \
  | jq '{
    assessment_mode: .observation.assessment_mode,
    runner: .observation.runner,
    frames_analyzed: .observation.frames_analyzed,
    alert_level: .alert.level
  }'
```

Measured Raspberry Pi 5 result for the sample endpoint:

- runtime: `provider=litert`, `backend=gpu`, `multimodal_backend=cpu`,
  `multimodal_vision_backend=cpu`, `speculative_decoding=true`,
  `engine_ready=true`, `p1_runtime_ready=true`
- endpoint: `assessment_mode=gemma4-multimodal-v1`,
  `runner.mode=litert-multimodal-temporal`, `frames_analyzed=1`,
  `alert.level=green`

This endpoint result is the full JalRekha Node P1 proof. If the endpoint returns
`runner.mode=multimodal-unavailable-fallback`, do not count the visual flow as
P1 even if `/api/settings/runtime` reports `p1_runtime_ready=true`.

## First boot

From the repo root:

```bash
chmod +x scripts/run_node_pi8_multimodal_demo.sh
./scripts/run_node_pi8_multimodal_demo.sh
```

For the production profile:

```bash
chmod +x scripts/run_node_pi16_multimodal_prod.sh
./scripts/run_node_pi16_multimodal_prod.sh
```

## Probe without a camera

```bash
python3 scripts/pi_node.py \
  --api-base http://127.0.0.1:8000/api \
  --site-id puente-arroyo-01 \
  --synthetic
```

## Probe a real camera

```bash
python3 scripts/node_guard.py
```

Useful env:

```bash
export JALREKHA_CAMERA_SOURCE=/dev/video0
export JALREKHA_GUARD_INTERVAL_SECONDS=300
export JALREKHA_GUARD_CLIP_SECONDS=12
export JALREKHA_GUARD_FPS=2
```

The guard records a short MJPEG AVI with ffmpeg and posts it to
`POST /api/node/analyze`.

## What to check

- `node.provider=litert` means the node is configured for LiteRT-LM.
- `node.engine_ready=true` means the LiteRT runtime and model file are ready.
- `node.multimodal_backend=cpu` and
  `node.multimodal_vision_backend=cpu` are the Pi-safe image profile.
- `node.speculative_decoding=true` means the LiteRT engine is created with
  speculative decoding enabled.
- `node.p1_runtime_ready=true` means the configured JalRekha Node runtime is
  LiteRT-LM and the engine/model are ready. It is not proof that an analysis has
  completed.
- `node.counts_for_p1=true` is kept as a compatibility alias for
  `p1_runtime_ready`; prefer the clearer field in new docs and checks.
- `runner.mode=litert-multimodal-temporal` means Gemma 4 read the image(s) through LiteRT-LM.
- `runner.mode=multimodal-unavailable-fallback` means the CPU multimodal profile
  did not return valid JSON for the endpoint run and should be treated as a
  failed visual P1 proof.
- `fallback_used=true` means frames were prepared, but Gemma was down, timed out,
  or returned invalid JSON.
- Evidence images and JSON manifests are stored under `JALREKHA_UPLOAD_DIR`.
