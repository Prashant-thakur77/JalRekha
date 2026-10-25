# Gemma 4 Usage

Concrete map of where Gemma 4 runs in this repo, which runtime is used, and how to verify it.

## Models (three-tier setup)

| Tier | Variant | Where | Runtime | Notes |
|---|---|---|---|---|
| JalRekha Node Pi node | `google/gemma-4-E4B-it` | LiteRT artifact on Pi 16GB / workstation | LiteRT-LM | Multimodal temporal assessment |
| JalRekha Volunteer Android | `google/gemma-4-E2B-it` | `gemma-4-E2B-it.litertlm` in app `filesDir` | LiteRT-LM Android (`com.google.ai.edge.litertlm:litertlm-android`) | Text + audio transcript fusion |
| Central server | `gemma4:26b` (Ollama tag for 26B-A4B q4_K_M) | Backend docker / workstation | Ollama | Vision + tools, alert reasoning + actuator dispatch |
| (local light dev) | `gemma4:e2b` | Local Ollama, text-only experiments | Ollama | Text-only; rejects `/api/chat` tools |

Selection lives in [`backend/src/jalrekha/core/settings.py`](../backend/src/jalrekha/core/settings.py) (env vars `JALREKHA_LLM_MODEL`, `JALREKHA_MULTIMODAL_MODEL`, `JALREKHA_NODE_PROVIDER`).

The full hardware × tier matrix and quantization choices are in [`demo-artifacts/jalrekha-demo-artifacts/config/model_config.json`](../demo-artifacts/jalrekha-demo-artifacts/config/model_config.json).

## Where Gemma 4 is used

### 1. Edge node temporal assessment (JalRekha Node)
- Curates frames from fixed camera, builds temporal evidence pack, asks Gemma for `assessment_level / assessment_score / temporal_summary / reasoning_summary / reasoning_steps`.
- Files:
  - [`backend/src/jalrekha/services/node_assessment.py`](../backend/src/jalrekha/services/node_assessment.py)
  - [`backend/src/jalrekha/adapters/video_assessment.py`](../backend/src/jalrekha/adapters/video_assessment.py)
  - [`backend/src/jalrekha/adapters/image_assessment.py`](../backend/src/jalrekha/adapters/image_assessment.py)
  - [`backend/src/jalrekha/adapters/llm.py`](../backend/src/jalrekha/adapters/llm.py) (Ollama client + LiteRT stub)
  - [`scripts/pi_node.py`](../scripts/pi_node.py), [`scripts/node_guard.py`](../scripts/node_guard.py)

### 2. volunteer report understanding
- Structures free-form Rioplatense Spanish reports into typed observations.
- Files:
  - [`backend/src/jalrekha/adapters/text_structuring_gemma_fewshot.py`](../backend/src/jalrekha/adapters/text_structuring_gemma_fewshot.py)
  - [`backend/src/jalrekha/services/report_structuring.py`](../backend/src/jalrekha/services/report_structuring.py)
  - Android on-device path: [`android/app/src/main/java/com/jalrekha/android/data/GemmaOnDevice.kt`](../android/app/src/main/java/com/jalrekha/android/data/GemmaOnDevice.kt) (LiteRT-LM Android, no backend fallback).

### 3. Alert reasoning / audit trace
- Generates Spanish reasoning block for every non-green fused alert.
- Files:
  - [`backend/src/jalrekha/services/reasoning.py`](../backend/src/jalrekha/services/reasoning.py)
  - [`backend/src/jalrekha/services/node_analysis.py`](../backend/src/jalrekha/services/node_analysis.py)
  - [`backend/src/jalrekha/services/actuators.py`](../backend/src/jalrekha/services/actuators.py)

## Why this runtime

- **Ollama** for backend dev: simple model pull, multimodal in one process, matches Pi 16GB / workstation profile.
- **LiteRT-LM** target for the Pi 8GB demo profile: smaller footprint, on-device decode benchmarks live in [`docs/legacy/benchmarks/`](benchmarks/) (`litert-e2b-pi5-8gb-*.jsonl`). Runner stub: [`scripts/litert_benchmark.py`](../scripts/litert_benchmark.py), [`scripts/litert_smoke.py`](../scripts/litert_smoke.py).
- **LiteRT-LM Android** on Android: same `.litertlm` artifact as the backend, no silent network fallback (see [`android_gemma.md`](android_gemma.md)). MediaPipe `tasks-genai` was the original plan but Google has not published a Gemma 4 `.task` file.

## Prompt / schema

- JalRekha Node assessment schema: [`shared/`](../shared/) JSON schemas + `node_assessment.py` prompt builder.
- JalRekha Volunteer few-shot prompt: `text_structuring_gemma_fewshot.py` (12-shot Rioplatense corpus from [`datasets/`](../datasets/)).
- Reasoning prompt: `services/reasoning.py` emits structured `reasoning_steps[]` plus `temporal_summary`.

## Inputs / outputs

| Path | Input | Output |
|---|---|---|
| JalRekha Node | curated frames + metadata | `NodeAssessment` JSON (level, score, summaries, steps, audit artifacts) |
| JalRekha Volunteer text | free-form Spanish report | `LocalParsedObservation` (typed fields, confidence) |
| Reasoning | fused alert context | Spanish reasoning block + deterministic rule trace |

## Limitations (honest)

- Multimodal latency on Pi 8GB: see `e2b-e4b-ablation.md` and timeout logs. E4B reasoning is workstation/Pi 16GB territory.
- LiteRT-LM runner is currently a benchmark/stub path; production inference uses Ollama until LiteRT-LM ships a multimodal release we can pin.
- Few-shot Rioplatense corpus is 82 examples - small, but versioned and reproducible (`scripts/eval_rioplatense.py`).

## Verify it is not mock

```bash
# 1. Backend hitting real Ollama (central tier, vision + tools)
docker compose --profile llm up
docker exec jalrekha-ollama ollama pull gemma4:26b
curl -s http://localhost:11434/api/tags | grep gemma4

# 2. JalRekha Node assessment end-to-end (real frames)
python scripts/demo.py

# 3. Rioplatense eval (real model vs labeled corpus)
python scripts/eval_rioplatense.py

# 4. Pi node demo runner
bash scripts/run_node_pi8_multimodal_demo.sh
```

See [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md) for expected outputs.
