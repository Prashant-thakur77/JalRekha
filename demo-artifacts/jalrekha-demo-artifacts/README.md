# JalRekha — Demo Artifacts

Reproducible demo package for JalRekha.

The production deployment runs on a Raspberry Pi 4/5 camera node plus the JalRekha Volunteer
Android app. This package lets a judge verify the full alerting pipeline
**without** owning the physical hardware: captured node inputs, citizen audio
reports, telemetry logs, model and runtime configuration, expected outputs, and
demo builds for the dashboard and mobile app.

## Contents

```
jalrekha-demo-artifacts/
  README.md                  - this file
  DEMO.md                    - step-by-step reproduction guide
  manifest.json              - machine-readable index of every artifact

  inputs/                    - what the Raspberry Pi node / JalRekha Volunteer app captured
    video/                   - water-level evidence (nominal / warning / critical)
    audio/                   - resident voice reports
    reports/                 - .txt transcripts (skip STT if needed)

  outputs/                   - what the system produced from those inputs
    logs/                    - JSONL telemetry from each node run
    alerts/                  - final alert payloads
    screenshots/             - dashboard + mobile UI evidence

  app/                       - installable demo builds (optional)
    volunteer-demo.apk           - Android JalRekha Volunteer build (demo mode)
    jalrekha-dashboard-demo.zip - static dashboard build

  config/                    - everything needed to prove the run is real
    model_config.json        - Gemma 4 three-tier model setup (E4B node / E2B mobile / 26B-A4B central)
    thresholds.json          - water-level / severity thresholds
    runtime_config.yaml      - node + backend runtime config
    lite_rt_config.json      - on-device LiteRT config
    prompt_templates.md      - exact prompts used by JalRekha Volunteer / JalRekha Node

  eval/                      - reproducibility evidence
    expected_outputs.json    - canonical outputs per case
    replay_results.json      - what this package's replay produced
```

## How to verify the demo

See `DEMO.md`. Two paths:

- **Option A — replay without hardware**: run the hardware replay notebook linked from
  the submission. It loads the files in `inputs/` and produces the artifacts
  shown in `outputs/`.
- **Option B — real Raspberry Pi deployment**: clone the repo, follow the
  hardware deployment section.

## Notes

- Gemma 4 weights are **not** bundled. The system runs three Gemma 4 variants,
  one per tier (see `config/model_config.json`):
  - `google/gemma-4-E4B-it` on the JalRekha Node Raspberry Pi camera node (LiteRT, int4)
  - `google/gemma-4-E2B-it` on the JalRekha Volunteer Android app (LiteRT, int4)
  - `google/gemma-4-26B-A4B-it` on the central server (Ollama, q4_K_M)
  The package ships configuration and prompts only.
- All inputs are real captures from the JalRekha Node and JalRekha Volunteer app, not
  synthetic. Filenames map 1:1 to entries in `manifest.json`.
