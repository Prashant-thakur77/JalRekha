# JalRekha — Demo Reproduction Guide

This package replays the hardware pipeline so a judge can verify the demo
without owning the Raspberry Pi camera node.

## Option A — Replay demo without hardware (recommended)

1. Open the hardware replay notebook (`notebooks/jalrekha_live_hardware_replay_demo.ipynb`), hosted on any Jupyter service:
   `notebooks/jalrekha_live_hardware_replay_demo.ipynb`

2. Click **Run all**.

3. The notebook loads from this package:
   - `inputs/video/river_nominal.mp4` and frames
   - `inputs/video/river_warning.mp4`
   - `inputs/video/river_critical.mp4` and frames
   - `inputs/audio/report_bridge_water.wav` plus its transcript
   - `inputs/reports/report_bridge_water.txt`
   - `config/thresholds.json`, `config/model_config.json`,
     `config/prompt_templates.md`

4. Expected progression:

   ```
   NOMINAL  ->  WARNING  ->  URGENT / CRITICAL
   ```

5. Compare the notebook outputs against `eval/expected_outputs.json`. They
   must match `outputs/logs/*.jsonl` and `outputs/alerts/*.json` in this
   package.

## Option B — Real Raspberry Pi deployment

Hardware:

- Raspberry Pi 4 (8 GB) or Pi 5
- Pi Camera module v2/v3 or USB camera
- Local Gemma 4 runtimes per tier:
  - JalRekha Node: LiteRT serving `google/gemma-4-E4B-it` (int4)
  - JalRekha Volunteer app:     LiteRT serving `google/gemma-4-E2B-it` (int4)
  - Central node:  Ollama serving `google/gemma-4-26B-A4B-it` (q4_K_M)
- Optional: Android device with `app/volunteer-demo.apk` installed

Commands:

```bash
git clone https://github.com/<your-github-user>/JalRekha.git
cd JalRekha
bash scripts/setup.sh
bash scripts/run_node_pi8_multimodal_demo.sh

# Replay one of the captured cases through the live node:
python scripts/demo.py --case demo-artifacts/jalrekha-demo-artifacts/inputs/video/river_critical.mp4
```

Expected stdout:

```
final_state=CRITICAL
evidence_count=4
cloud_required=false
```

## What "live demo" proves

- Local node detects water-level change against thresholds in
  `config/thresholds.json` (deterministic firewall, no LLM).
- JalRekha Volunteer citizen report is transcribed and passed to `gemma-4-E2B-it` on the
  handset with the prompt in `config/prompt_templates.md`.
- JalRekha Node classifies camera frames with `gemma-4-E4B-it` (LiteRT, int4).
- Central node fuses node telemetry + citizen evidence with
  `gemma-4-26B-A4B-it` (Ollama, q4_K_M), returns structured JSON
  (severity, evidence, recommended_action, uncertainty).
- Final alert is written to `outputs/alerts/` and surfaced on the dashboard
  (`outputs/screenshots/dashboard_urgent.png`) and the JalRekha Volunteer app
  (`outputs/screenshots/mobile_queue.png`).
- No cloud dependency. Offline queue path captured in
  `outputs/logs/volunteer_report_run.jsonl`.
