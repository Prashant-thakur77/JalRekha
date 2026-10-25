# LiteRT-LM Benchmark Card

Quantitative card for the LiteRT Prize path. The current target is the real
Raspberry Pi 5 8GB JalRekha Node running Gemma 4 E2B through LiteRT-LM, with
text/reasoning on GPU and multimodal image mode on CPU/CPU to avoid the Pi 8GB
buffer overflow seen with GPU multimodal.

## Run on the Pi

From the repo checkout on the Raspberry Pi. The measured run below used the
LiteRT worktree at `~/JalRekha-litert` and the backend virtual
environment at `backend/.venv/bin/python`.

```bash
cd ~/JalRekha-litert
export JALREKHA_NODE_PROVIDER=litert
export JALREKHA_NODE_MODEL_PATH=backend/data/models/gemma-4-E2B-it.litertlm
export JALREKHA_NODE_BACKEND=gpu
export JALREKHA_NODE_MULTIMODAL_BACKEND=cpu
export JALREKHA_NODE_MULTIMODAL_VISION_BACKEND=cpu
export JALREKHA_NODE_ENABLE_SPECULATIVE_DECODING=true
export PYTHONPATH=backend/src

backend/.venv/bin/python scripts/litert_smoke.py --reasoning

backend/.venv/bin/python scripts/litert_benchmark.py \
  --mode text \
  --repeats 2 \
  --output docs/legacy/benchmarks/litert-e2b-pi5-8gb-text.jsonl

backend/.venv/bin/python scripts/litert_benchmark.py \
  --mode reasoning \
  --repeats 2 \
  --output docs/legacy/benchmarks/litert-e2b-pi5-8gb-reasoning.jsonl

# Use this for comparable repeated text/reasoning measurements on the current
# Pi 5 GPU runtime, because shared text-engine warm calls are unstable.
backend/.venv/bin/python scripts/litert_benchmark.py \
  --mode text \
  --repeats 2 \
  --fresh-runtime-per-run \
  --output docs/legacy/benchmarks/litert-e2b-pi5-8gb-text-fresh-runtime.jsonl

backend/.venv/bin/python scripts/litert_benchmark.py \
  --mode reasoning \
  --repeats 2 \
  --fresh-runtime-per-run \
  --output docs/legacy/benchmarks/litert-e2b-pi5-8gb-reasoning-fresh-runtime.jsonl
```

If a frame asset is present, add multimodal:

```bash
PYTHONPATH=backend/src backend/.venv/bin/python scripts/litert_benchmark.py \
  --mode image \
  --image fixtures/frames/silverado_015s.jpg \
  --repeats 2 \
  --output docs/legacy/benchmarks/litert-e2b-pi5-8gb-image.jsonl
```

To test another model, pass `--model-path /path/to/model.litertlm` or set
`JALREKHA_NODE_MODEL_PATH`. The E2B/E4B comparison for the Pi 5 8GB operating
profile is documented in [`e2b-e4b-ablation.md`](./e2b-e4b-ablation.md).

## Metrics

Real metrics recorded by `scripts/litert_benchmark.py`:

- model name and model path
- mode: `text`, `reasoning`, or `image`
- backend, multimodal backend, and multimodal vision backend
- speculative decoding setting
- cold/warm label per mode
- wall-clock elapsed seconds around the runtime call
- process RSS peak MB from `resource.getrusage(RUSAGE_SELF).ru_maxrss`
- pass/fail and error detail

Metrics intentionally not estimated:

- `output_token_count`: unavailable because the current
  `LiteRTNodeRuntime`/`litert_lm` response path exposes final text/JSON only,
  not tokenizer counts or usage metadata.
- `decode_tok_s`: unavailable because reliable output token count is
  unavailable.
- `ttft_seconds`: unavailable because the current API path exposes no streaming
  callback or first-token event.

RSS note: warm-run RSS is the same process high-water mark, so it is useful as a
memory ceiling for the benchmark process, not as an isolated per-run allocation
delta.

Observed stability note: in the measured Pi run, text and reasoning cold runs
returned LiteRT output, but the second call through the same GPU text engine
failed after about 20 seconds with
`RuntimeError: litert_lm_conversation_send_message failed`. Disabling
speculative decoding did not fix shared-engine reuse. Running each repeat with
`--fresh-runtime-per-run` made repeated text and reasoning calls pass in the
same Python process, so comparable repeated text/reasoning numbers should use
that option until the LiteRT-LM GPU text-engine reuse issue is resolved. The
image/multimodal CPU/CPU mode succeeded on both cold and warm runs.

Production mitigation: `LiteRTNodeRuntime` now resets the affected cached engine
and retries once when this GPU text-engine reuse error appears. The retry keeps
the backend from falling straight to deterministic reasoning, but it can make
the second call slower and raise process RSS because the engine is recreated.

## Initial E2B Table

Measured on Raspberry Pi 5 8GB from:

- `docs/legacy/benchmarks/litert-e2b-pi5-8gb-text.jsonl`
- `docs/legacy/benchmarks/litert-e2b-pi5-8gb-reasoning.jsonl`
- `docs/legacy/benchmarks/litert-e2b-pi5-8gb-image.jsonl`

| Model | Mode | Backend | MM backend | Vision backend | Spec decode | Run | Elapsed s | RSS peak MB | Output tokens | Decode tok/s | TTFT s | Result |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| gemma-4-E2B-it.litertlm | text | gpu | cpu | cpu | true | cold | 93.913 | 3067.0 | n/a | n/a | n/a | pass |
| gemma-4-E2B-it.litertlm | text | gpu | cpu | cpu | true | warm | 20.024 | 3067.0 | n/a | n/a | n/a | fail: runtime returned no text |
| gemma-4-E2B-it.litertlm | reasoning | gpu | cpu | cpu | true | cold | 252.926 | 3137.2 | n/a | n/a | n/a | pass |
| gemma-4-E2B-it.litertlm | reasoning | gpu | cpu | cpu | true | warm | 20.025 | 3137.2 | n/a | n/a | n/a | fail: fallback after no usable text |
| gemma-4-E2B-it.litertlm | image | gpu | cpu | cpu | true | cold | 28.316 | 2592.3 | n/a | n/a | n/a | pass |
| gemma-4-E2B-it.litertlm | image | gpu | cpu | cpu | true | warm | 23.714 | 2604.3 | n/a | n/a | n/a | pass |

For the E2B vs E4B ablation used to decide the Pi 5 8GB operating profile, see
[`docs/legacy/e2b-e4b-ablation.md`](./e2b-e4b-ablation.md).
