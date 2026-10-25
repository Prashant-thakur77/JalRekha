# LiteRT E2B vs E4B Ablation

Raspberry Pi 5 8GB, LiteRT-LM, `backend/.venv/bin/python`, model files under
`backend/data/models/`. Text and reasoning runs use `--fresh-runtime-per-run`
because the current GPU text engine is unstable on second reuse inside one
process. Image runs use the Pi-safe multimodal CPU/CPU profile.

## Commands

```bash
cd ~/JalRekha-litert
export PYTHONPATH=backend/src
export JALREKHA_NODE_PROVIDER=litert
export JALREKHA_NODE_BACKEND=gpu
export JALREKHA_NODE_MULTIMODAL_BACKEND=cpu
export JALREKHA_NODE_MULTIMODAL_VISION_BACKEND=cpu
export JALREKHA_NODE_ENABLE_SPECULATIVE_DECODING=true

JALREKHA_NODE_MODEL_PATH=backend/data/models/gemma-4-E2B-it.litertlm \
  backend/.venv/bin/python scripts/litert_benchmark.py --mode text \
  --repeats 2 --fresh-runtime-per-run \
  --output docs/legacy/benchmarks/litert-e2b-pi5-8gb-text-fresh-runtime.jsonl

JALREKHA_NODE_MODEL_PATH=backend/data/models/gemma-4-E2B-it.litertlm \
  backend/.venv/bin/python scripts/litert_benchmark.py --mode reasoning \
  --repeats 2 --fresh-runtime-per-run \
  --output docs/legacy/benchmarks/litert-e2b-pi5-8gb-reasoning-fresh-runtime.jsonl

JALREKHA_NODE_MODEL_PATH=backend/data/models/gemma-4-E2B-it.litertlm \
  backend/.venv/bin/python scripts/litert_benchmark.py --mode image \
  --image fixtures/frames/silverado_015s.jpg --repeats 2 \
  --output docs/legacy/benchmarks/litert-e2b-pi5-8gb-image-p14.jsonl

JALREKHA_NODE_MODEL_PATH=backend/data/models/gemma-4-E4B-it.litertlm \
  backend/.venv/bin/python scripts/litert_benchmark.py --mode text \
  --repeats 2 --fresh-runtime-per-run \
  --output docs/legacy/benchmarks/litert-e4b-pi5-8gb-text.jsonl

JALREKHA_NODE_MODEL_PATH=backend/data/models/gemma-4-E4B-it.litertlm \
  backend/.venv/bin/python scripts/litert_benchmark.py --mode reasoning \
  --repeats 2 --fresh-runtime-per-run \
  --output docs/legacy/benchmarks/litert-e4b-pi5-8gb-reasoning.jsonl

JALREKHA_NODE_MODEL_PATH=backend/data/models/gemma-4-E4B-it.litertlm \
  backend/.venv/bin/python scripts/litert_benchmark.py --mode image \
  --image fixtures/frames/silverado_015s.jpg --repeats 2 \
  --output docs/legacy/benchmarks/litert-e4b-pi5-8gb-image.jsonl
```

E4B GPU text/reasoning did not complete a normal benchmark run before external
timeouts. The harness was killed before emitting a normal run record; a failure
record was added using the same schema, with native log paths in
`error_detail`. CPU fallback was tested with:

```bash
JALREKHA_NODE_MODEL_PATH=backend/data/models/gemma-4-E4B-it.litertlm \
JALREKHA_NODE_BACKEND=cpu \
  backend/.venv/bin/python scripts/litert_benchmark.py --mode text \
  --repeats 2 --fresh-runtime-per-run \
  --output docs/legacy/benchmarks/litert-e4b-pi5-8gb-text-cpu.jsonl

JALREKHA_NODE_MODEL_PATH=backend/data/models/gemma-4-E4B-it.litertlm \
JALREKHA_NODE_BACKEND=cpu \
  backend/.venv/bin/python scripts/litert_benchmark.py --mode reasoning \
  --repeats 2 --fresh-runtime-per-run \
  --output docs/legacy/benchmarks/litert-e4b-pi5-8gb-reasoning-cpu.jsonl
```

## Results

| Model | Mode | Backend used by run | Runtime reuse | Result | Elapsed s | RSS peak MB | Notes |
| --- | --- | --- | --- | --- | ---: | ---: | --- |
| E2B | text | GPU | fresh per run | pass/pass | 100.595 / 97.177 | 3050.8 / 3582.2 | Stable with fresh runtime. |
| E2B | reasoning | GPU | fresh per run | pass/pass | 255.575 / 263.033 | 3124.8 / 3548.3 | Stable with fresh runtime. |
| E2B | image | multimodal CPU, vision CPU | shared | pass/pass | 26.351 / 22.489 | 2590.7 / 2603.2 | Pi-safe multimodal path. |
| E4B | text | GPU | fresh per run | fail | 900 timeout | n/a | WebGPU buffer validation error; failure record added after timeout. |
| E4B | reasoning | GPU | fresh per run | fail | 300 timeout | n/a | WebGPU Invalid BindGroup/CommandBuffer; failure record added after timeout. |
| E4B | image | multimodal CPU, vision CPU | shared | pass/pass | 60.863 / 36.616 | 4507.4 / 4517.4 | Works, but uses much more memory than E2B. |
| E4B | text | CPU | fresh per run | pass/pass | 7.540 / 9.862 | 2848.8 / 2919.8 | Fallback check; not the documented GPU profile. |
| E4B | reasoning | CPU | fresh per run | pass/pass | 18.807 / 11.412 | 2922.0 / 2995.1 | Fallback check; not the documented GPU profile. |

## Finding

E2B remains the recommended Raspberry Pi 5 8GB operating profile for the
demo: text/reasoning works on GPU when each repeat uses a fresh
runtime, and the multimodal CPU/CPU path works cold and warm.

E4B is not recommended as the Pi 5 8GB GPU text/reasoning profile. The GPU path
did not produce a final text/reasoning response before the external timeout, so
the normal harness record was not emitted; a failure record was added using the
same JSONL schema. The text log
`docs/legacy/benchmarks/litert-e4b-pi5-8gb-text-timeout900.log` shows a WebGPU
validation failure:
`Binding size (167772160) ... is larger than the maximum storage buffer binding
size (134217728)`. The reasoning log
`docs/legacy/benchmarks/litert-e4b-pi5-8gb-reasoning-timeout300.log` shows
`Invalid BindGroup` / `Invalid CommandBuffer` before `RunDecodeAsync`.

E4B multimodal CPU/CPU works on the Pi 5 8GB, but with roughly 4.5 GB process
RSS peak for this small image smoke. That leaves less safety margin for the
full backend, artifact handling, API server, and OS. E4B text/reasoning CPU also
passes on the small benchmark prompts, but it is a fallback measurement rather
than the intended LiteRT Prize GPU profile.

Recommendation: keep E2B as the Pi 5 8GB operational profile. Treat E4B as a
candidate for Raspberry Pi 16GB / workstation validation, or as a CPU fallback
for very narrow prompts only after more end-to-end testing.

Runtime follow-up status: the GPU text-engine reuse issue is mitigated in
`LiteRTNodeRuntime` by discarding the affected cached engine and retrying once
after `RuntimeError: litert_lm_conversation_send_message failed`. Pi validation
confirmed repeated text/reasoning calls no longer fall straight to fallback, but
the reset path has higher latency and process RSS because it reloads the engine.
