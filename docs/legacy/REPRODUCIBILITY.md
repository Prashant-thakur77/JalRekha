# Reproducibility

Exact versions, commands, hardware, and expected outputs to verify the prototype is real.

## Versions

- Python: 3.10+ (3.11 tested)
- Node: 20 LTS (frontend Vite + TS)
- Android: SDK 34, Kotlin 1.9, Compose BOM 2024.06
- Ollama: 0.3.x (Gemma 4 multimodal support)
- System: `ffmpeg` available on PATH (frame extraction for `fetch_demo_assets.py`)
- Models (three-tier Gemma 4 setup, see [GEMMA_USAGE.md](GEMMA_USAGE.md)):
  - JalRekha Node Pi node: `google/gemma-4-E4B-it` (LiteRT, int4) — fits 16GB Pi / workstation profile
  - JalRekha Volunteer Android: `google/gemma-4-E2B-it` (LiteRT, int4) — `.litertlm` artifact in app `filesDir`
  - Central server: `gemma4:26b` via Ollama (q4_K_M, vision + tools capable) — used by docker-compose
- OS tested: Ubuntu 22.04, Windows 11 (WSL2), Raspberry Pi OS Bookworm 64-bit

## Hardware tested

| Profile | Hardware | Script |
|---|---|---|
| Pi 8GB demo | Raspberry Pi 5 8GB + Pi Camera Module 3 | `scripts/run_node_pi8_multimodal_demo.sh` |
| Pi 16GB prod | Raspberry Pi 5 16GB + USB cam / RTSP | `scripts/run_node_pi16_multimodal_prod.sh` |
| Workstation | x86_64, 16GB+ RAM, optional GPU | `scripts/demo.py` |
| Android | Pixel 7 / mid-range (>=6GB RAM) | `android/` Gradle build |

Full Pi setup: [`docs/raspberry-pi-node.md`](raspberry-pi-node.md).

## Reproducible commands

### Backend + Ollama (Docker)

```bash
cp .env.example .env
docker compose --profile llm up -d
# Pull the central-tier model used by docker-compose (vision + tools capable).
# E2B is text-only and rejects /api/chat tools; do not use it for the docker stack.
docker exec jalrekha-ollama ollama pull gemma4:26b
curl -s http://localhost:8000/health
# expected: {"status":"ok", ...}
```

For a lighter text-only local run (no docker, no multimodal), `ollama pull gemma4:e2b`
plus `JALREKHA_LLM_MODEL=gemma4:e2b` is enough. See `docker-compose.yml` header for
the exact constraints per slug.

### End-to-end demo

```bash
python scripts/fetch_demo_assets.py
python scripts/demo.py
# expected: prints FusedAlert with non-null reasoning_summary,
# writes audit pack under outputs/<run-id>/
```

### Connectivity-loss narrative (<90s)

```bash
python scripts/demo_connectivity.py
# expected: wifi-off -> local alert -> siren -> wifi-on -> queue drain
```

### Rioplatense eval

```bash
python scripts/eval_rioplatense.py
# expected: accuracy vs rule-based baseline on 82-example corpus,
# few-shot Gemma beats baseline; see docs/legacy/rioplatense_eval.md
```

### LiteRT-LM benchmark (Pi 8GB)

```bash
python scripts/fetch_litert_model.py     # downloads gemma-4-E2B-it.litertlm to backend/data/models/
python scripts/litert_smoke.py
python scripts/litert_benchmark.py
# expected: jsonl output matching docs/legacy/benchmarks/litert-e2b-pi5-8gb-*.jsonl
```

### Android on-device

```bash
cd android
./gradlew :app:assembleDebug
# Install .apk on a device with >=6GB RAM. The on-device LLM expects
# `gemma-4-E2B-it.litertlm` (the same artifact downloaded by
# scripts/fetch_litert_model.py) under the app's internal files dir.
# See android/README.md for the exact placement (adb push path) and verification.
# BenchActivity prints decode tokens/s and first-token latency.
```

### Backend tests

```bash
cd backend
uv sync
uv run pytest -q
# expected: green; see backend/tests/test_node_assessment.py,
# test_rioplatense.py, test_reasoning.py for the Gemma paths
```

## Expected outputs

- `outputs/<run-id>/audit/` contains curated frames, JSON `NodeAssessment`, fused alert, reasoning trace.
- `docs/legacy/benchmarks/litert-e2b-pi5-8gb-*.jsonl` are the recorded Pi 5 benchmark runs (image, text, reasoning, fresh-runtime variants).

## How to verify it is not mock

1. Stop Ollama: `docker stop jalrekha-ollama`. Re-run `python scripts/demo.py` - it must fail at the Gemma call, not silently produce an alert. Restart and confirm output returns.
2. Inspect `outputs/<run-id>/audit/raw_gemma_response.json` - contains the actual model JSON, not a hardcoded blob.
3. Android: airplane mode + run a report; parsing still works (on-device), proves no backend fallback. See `docs/android_gemma.md`.

## Known limits

- E4B reasoning on Pi 8GB CPU times out (see `litert-e4b-pi5-8gb-reasoning-timeout300.log`); use E2B for the 8GB demo.
- Open-Meteo enrichment requires internet at backend node (volunteer/edge can be offline).
