# NadiSaathi (नदी साथी, "river friend")

> A camera on the Koshi at Chatara, Nepal, reads the river in metres with OpenCV 5 on AWS Graviton; when the water starts to climb, an agent looks more often, checks itself, works out when the wave reaches Birpur in Bihar, and drafts Hindi, Maithili and Nepali alerts that a named person approves with a PIN.

Live demo: **https://gaq7chhmb2.execute-api.us-east-1.amazonaws.com** (opens on **Live**; press *Run replay*, then open **Approvals**). The operator PIN for approvals is in the Devpost testing instructions.

![The agent on a real USGS camera during the July 2026 Hancock flood: OpenCV reads 5.25 m off the staff gauge (gauge: 5.31 m) and the agent sounds the danger siren](docs/screenshots/real_camera_d6.png)

| Live replay: OpenCV reads 6.02 m rising 1.2 m/h, the agent checks every 300 s and four alerts wait for a person | Trace: the vision model claims 3.1 m and tells the agent to cancel alerts; the guard keeps OpenCV's 6.40 m and the siren fires | Approvals on a phone: Hindi, Maithili and English drafts with SMS segment counts and voice |
|---|---|---|
| ![Live page](docs/screenshots/live_rising.png) | ![D7 trace](docs/screenshots/trace_d7.png) | ![Approvals](docs/screenshots/approvals_phone.png) |
| **Try to fool the guard**: type any model reply; the agent keeps OpenCV's 6.55 m and the siren | **Story in Hindi** (also Nepali), every figure with its source | **River graph**: arrival bands from Chatara across the border |
| ![Red-team panel](docs/screenshots/redteam.png) | ![Story in Hindi](docs/screenshots/story_hindi.png) | ![Rivers ETA](docs/screenshots/rivers_eta.png) |

NadiSaathi is a flood early-warning and relief tool for the rivers that rise in Nepal and flood the plains of Bihar and Uttar Pradesh. Its measurement engine, JalRekha (जलरेखा, "waterline"), turns an ordinary camera pointed at a staff gauge into a calibrated river gauge. The agent around it uses each reading to decide what to do next, and the river graph turns an upstream rise into a downstream arrival window, across the border.

Numbers generated {{generated_at}} by `scripts/make_headline.py` from `eval/results/*.json` and `bench/results/*.json`. `make check-numbers` fails if this file and the JSON disagree.

## Results

| What | NadiSaathi | Baseline | Data |
|---|---|---|---|
| Stage error on real USGS staff-gauge cameras, physical calibration (gauge numerals clicked once, nothing fitted to gauge data) | **{{real_full_mae_cm}} cm MAE** (95% CI {{real_full_ci}}), median {{real_full_median_cm}} cm | original PIL edge heuristic: answers only {{real_b0_coverage}} of frames; on those same {{real_b0_subset_n}} frames it is {{real_b0_on_subset_cm}} cm vs {{real_full_on_b0_subset_cm}} cm for ours; naive max-edge {{real_b1_mae_cm}} cm | REAL, {{real_n}} in-range frames, 2 sites |
| A vision-language model as the gauge reader ({{vlm_model}} on the same real frames) | OpenCV: {{cv_on_vlm_answered_cm}} cm on the frames the model answered, in ~0.09 s per burst on Graviton for $0.446 per million frames | {{vlm_model}}: {{vlm_on_answered_cm}} cm, answered {{vlm_coverage}} of frames, ~{{vlm_latency_s}} s and {{vlm_cost_1k}} per 1,000 frames | REAL, {{vlm_frames}} frames, the model given the gauge span and units |
| The agent on a real camera (USGS Hancock, July 2026 flood, {{rr_frames}} archived frames) | used {{rr_used}} readings at **{{rr_used_mae_cm}} cm MAE** (median {{rr_used_median_cm}} cm), held {{rr_held_pct}} for review; siren on the first frame above the danger mark: {{rr_siren_first}}; {{rr_quiet_alerts}} alert drafts on the quiet days; all-clear proposed: {{rr_all_clear}}. No warning lead on this camera: the rise happened overnight, when it records nothing | – | REAL, illustrative warning/danger marks (14 ft / 17 ft) |
| Stage error, synthetic scenes, 9 conditions (rain, fog, night, shake, blur, glare, JPEG, still water) | **{{synth_full_mae_cm}} cm MAE** (CI {{synth_full_ci}}), {{synth_full_within5}} within 5 cm | original heuristic, border-fixed {{synth_b0r_mae_cm}} cm; as shipped it answers {{synth_b0_coverage}} of frames | SYNTHETIC, {{synth_frames}} frames, 30 scene seeds never used for tuning |
| Lead time gained downstream by watching the upstream gauge | Official NWS action stages (pre-registered primary): median **{{lt_nws_gain_median_min}} min**, mean {{lt_nws_gain_mean_h}} h, detection before the crossing {{lt_nws_det_down}} → {{lt_nws_det_comb}}. Percentile warning levels: median **{{lt_p95_gain_median_h}} h** (CI {{lt_p95_gain_ci}} min), detection {{lt_p95_det_down}} → {{lt_p95_det_comb}} | same rule on the downstream gauge only | REAL USGS gauge pairs, {{lt_pairs}} pairs, held-out 2024–2026 events |
| Agent scenario suite | first alert a median **{{ag_lead_median_min}} min before** the true warning crossing; {{ag_success}} runs correct, {{ag_false_alert_runs}} false-alert runs | same projection rule without the vision gates: {{pj_lead_median_min}} min, {{pj_success}} correct, {{pj_false_alert_runs}} false-alert runs; threshold agent: {{rb_lead_median_min}} min, {{rb_success}} | SYNTHETIC, {{ag_flood_runs}} flood + {{ag_quiet_runs}} no-flood runs incl. camera knocks near the warning level |
| Guard against a lying or hijacked vision model | **{{guard_caught}}/{{guard_bad}} bad replies caught** (contradictions, prompt injections in English/Hindi/Nepali, malformed), {{guard_confirm_ok}} honest confirmations accepted, danger siren never cancelled | – | SYNTHETIC danger-level burst, {{guard_cases}} scripted replies through the full agent cycle |
| Volunteer photo triage on real Indian and Nepali flood photos (Claude, after face/plate blur) | flagged **{{pt_road_hit}}/{{pt_road_pos}}** flooded roads and underpasses; also flagged {{pt_others_flagged}} of the other {{pt_others}} photos (a washed-out bridge, a boat rescue); ~{{pt_latency_s}} s and {{pt_cost_photo}} per photo | – | REAL, {{pt_photos}} licensed Wikimedia Commons photos, labels from the photo subject; small n, a sanity check |
| CV pipeline on Graviton4 vs x86 (same 4 vCPU, same frames, identical outputs) | c8g.xlarge **{{B_fps}} frames/s, {{B_usd_1m}} per 1M frames** | c7i.xlarge {{C_fps}} frames/s, {{C_usd_1m}} per 1M frames ({{BC_cost_saving}} cheaper on Graviton) | benchmark workload, `bench/cool_bench.py` |
| Deployed endpoint | {{soak_uptime}} of {{soak_probes}} health probes OK over {{soak_hours}} h, p50 {{soak_p50_ms}} ms / p95 {{soak_p95_ms}} ms | – | REAL, CloudWatch (keep-warm probe every 5 min) |

What these numbers do not show, and the failures we found:

- With official NWS action stages, most downstream floods gained no lead time (median {{lt_nws_gain_median_min}} min). Action stages are set town by town; in many events the upstream gauge rose but never reached its own action stage. The cross-border logic is only as good as the warning levels it is given.
- Camera-like noise (σ = 5 cm) on the upstream readings raised upstream false alerts to {{lt_p95cam_fa_up}} per 30 days per pair. A rise-significance rule (rate − {{lt2_z}}·σ ≥ 0.30 m/h, chosen on the training years) brings that to {{lt2_p95cam_fa_up}}; the test years had already been seen, so that second number is optimistic. The agent now uses this rule; with it, detection before the crossing is {{lt2_nws_det_down}} → {{lt2_nws_det_comb}} (action stages) and {{lt2_p95_det_down}} → {{lt2_p95_det_comb}} (percentiles), and the median gains are unchanged ({{lt2_nws_gain_median_min}} min, {{lt2_p95_gain_median_h}} h). The table above shows the pre-registered v1 rule.
- On real hourly snapshots the fused reading equals the colour estimator E3 alone ({{real_e3_mae_cm}} cm): the temporal estimator needs a burst and abstains, and the edge estimator is down-weighted. Fusion helps on bursts (synthetic: E3 alone {{synth_e3_mae_cm}} cm, fused {{synth_full_mae_cm}} cm), not yet on real snapshots.
- On the real Moravia camera, which was reframed after a flood, image registration made accuracy worse ({{real_moravia_within10}} within 10 cm with it, {{real_moravia_noreg_within10}} without).
- Our first real-camera protocol fitted a camera-to-stage line on each site's first frames and failed ({{real_fitted_protocol_mae_cm}} cm, no better than a constant). We then switched to physical calibration on the same frames, and excluded a third site (Avon) after inspection because its staff plates use another datum and stay dry for most of the event. Nothing is fitted to gauge readings, but the protocol choice was made after seeing the first failure.
- In the agent suite most of the lead time comes from the Kalman projection, which the "projection without gates" baseline shares. The vision gates show their value on the hard no-flood runs: when a knocked camera's misregistered frame reads high, the system without gates drafts alerts on a steady river ({{pj_false_alert_runs}} false-alert runs) while the agent's registration check marks the site degraded instead ({{split_variant}}, T+{{split_t}} min: "{{split_agent_summary}}"). Both of those runs come from scenes never used for development. The first run of the hard variants also found an agent failure (glare biasing readings, then a recovery jump read as a rise), fixed with a post-gap confirmation rule; the suite also caught a scenario-cache bug and drafts rewritten after the peak. All fixed and covered by tests.
- The adversarial replies in the guard evaluation are scripted test inputs. The live second opinion is Claude ({{vlm_model}}); as a gauge reader on its own it is slower, costlier and, on these frames, less accurate than the OpenCV pipeline, which is why the agent calls it only when its own estimators disagree.
- Glare on the gauge is the worst synthetic condition ({{synth_full_glare_mae_cm}} cm MAE), and it is a blind spot for the agent: in {{glare_wrong}} of {{glare_bursts}} strong-glare bursts ({{glare_wrong_pct}}) the quality gate passed and two estimators agreed on a reading {{glare_err_range}} too low. Because the estimators agree, the agent does not ask for a second opinion, so the guard would keep the wrong value and an alert could come late. A glare-specific detector, or always confirming readings taken under glare, is the next fix.

## What happens in one cycle

```
camera burst ─► quality gate ─► registration ─► gauge strip ─► 3 waterline estimators ─► fusion ─► Kalman
 (5 frames)    blur/night/     ORB, rescue     warpAffine     E1 edge energy (Scharr)     robust    level +
               glare/fog       with ALIKED+    along the      E2 temporal texture (DIS)  median,   rise rate
                               LightGlue       gauge axis     E3 colour step (Lab)       sigma     (m/h)
                                                                                                    │
     ┌──────────────────────────────── the reading picks the branch ◄─────────────────────────────┘
     ▼
  D1 bad frame ─► no alert from it, longer burst, ask a volunteer for a photo after two in a row
  D2 camera moved ─► ALIKED+LightGlue, keyframe chain; if lost, site degraded + recalibration request
  D3 estimators disagree ─► only now pay for a VLM second opinion (Claude), else hold the reading
  D4 fast rise ─► capture every 5 min instead of 10, compute downstream ETA bands on the river graph
  D5 warning reached or projected ─► draft local + cross-border alerts (SMS, voice, CAP) for approval
  D6 danger level, estimators agree ─► local siren (the only public action it takes alone)
  D7 VLM contradicts a confident measurement, is malformed or carries instructions ─► keep OpenCV value, ask a human
  D8 relief photo shows a flooded road ─► route-board update drafted for approval
  D9 falling after the peak ─► cadence back down, all-clear proposed for approval
```

Every step lands in a trace (tool, inputs, outputs, decision before → after, latency, estimated cost, model, guard verdict). Open any trace from the Live page. On the Agent trace page, "Try to fool the guard" lets you type your own vision-model reply (a false reading, an instruction, any language); the real agent runs one danger-level cycle at a sandbox camera and shows whether it kept the OpenCV measurement.

## Nepal and India, concretely

- Region profiles `backend/src/jalrekha/regions/data/np.json` and `in.json`: languages, authority roles (ward focal person and municipal EOC in Nepal; DDMA control room, SDMA, panchayat volunteer, NGO team in India), alert channels and CAP settings.
- River graphs for the Koshi, Gandak, Karnali and Bagmati (`regions/data/rivers/`). Indian gauge nodes carry CWC warning and danger levels from the CWC flood-forecasting SOP (April 2025). Distances are sourced where a source exists (Chatara–Kosi barrage 43 km; Birpur–Basua 64.25 km); every travel time that is a distance/celerity estimate says so in the API and the UI.
- Alerts in Nepali, Hindi, Maithili, Bhojpuri and English, each at most two SMS segments (UCS-2, 70/67 characters). Voice: Amazon Polly Kajal for Hindi and English; Polly has no Nepali, Maithili or Bhojpuri voice, so Nepali uses an offline espeak-ng voice and Maithili/Bhojpuri use a labelled fallback. Maithili and Bhojpuri texts are marked for native review.
- Every fact used in the story and the profiles is in `docs/FACTS.md` with its source and a verified / secondary / unverified status.

## Architecture on AWS

![Architecture: camera, OpenCV 5 pipeline and agent on EC2 Graviton4, managed AWS services](docs/diagrams/architecture_blocks.png)

Agent workflow: `docs/diagrams/agent_workflow.png` (source: `docs/ARCHITECTURE.md`).

```
 phone / browser ─► API Gateway HTTPS ─► (VPC link) ─► EC2 c8g.xlarge Graviton4, Ubuntu 24.04 arm64
                                                       FastAPI + PWA, OpenCV 5 worker, agent loop
                                                       │      │        │         │          │
                                         S3 (evidence per  Claude    Polly     SNS        CloudWatch: JSON event
                                         cycle, CAP files, API (VLM  (Hindi/   (operator   per cycle, OpenCV stage
                                         deploy bundles)   2nd op.)  English)  + SMS)      metrics, Insights, alarms
 EventBridge (5 min) ─► Lambda keep-warm ─► /api/health ─► alarm ─► SNS
 Step Functions: a drafted public alert starts a timer (wait 15 min ─► Lambda checks the approval ─► still pending? re-notify, up to 3×)
 SSM Parameter Store (operator PIN), least-privilege instance role, AWS Budgets
 CloudFormation: infra/nadisaathi.yaml   `make deploy` (about 60 s per update)   `make destroy`
```

Capacity, as an estimate: from the OpenCV pipeline time measured on the cloud host ({{cloud_cycle_ms}} ms per cycle, CloudWatch), one c8g.xlarge with one vision worker per vCPU would serve about {{cloud_cams_300s}} cameras at a 5-minute cadence, about {{cloud_usd_cam_month_300s}} of compute per camera per month (the benchmark upper bound is {{B_cams_300s}}; the current deployment runs a single worker process). Details in `docs/COOL.md`. The core workload runs on Graviton4 with the stock OpenCV 5 wheel. COOL (Cloud-Optimized OpenCV, AWS Marketplace) is wired as `USE_COOL_AMI=true make deploy` but has not run yet: it needs the account owner to accept the Marketplace terms; the benchmark for COOL vs the stock wheel vs x86 is in `docs/COOL.md`. The second opinion, report structuring, photo descriptions and situation summaries run on Claude ({{vlm_model}}) through the Anthropic API with server-side refusal fallbacks; Amazon Bedrock is wired as an alternative (its account quota is zero today). Without either, every second opinion takes the labelled rule fallback.

### What the deployment records

Every agent cycle writes one JSON event to CloudWatch Logs (the river level, error bar, alignment method and inliers, each estimator's reading, the time of every OpenCV stage, the second opinion's model, latency and cost) and archives that event with its blurred overlay in S3 for 90 days. The OpenCV stage times also become CloudWatch metrics, with an alarm if the pipeline slows past 1 s. Over the last {{ops_days}} days the live stack logged {{ops_cycles}} cycles ({{ops_frames}} frames, {{ops_sites}} camera sites): OpenCV took {{ops_total_p50_ms}} ms per cycle at the median and {{ops_total_p95_ms}} ms at the 95th percentile on the Graviton4 host; ORB aligned {{ops_orb_cycles}} cycles ({{ops_orb_inliers}} inliers on average), ALIKED+LightGlue rescued {{ops_aliked_cycles}}, and {{ops_reg_failed}} cycles failed to align and were held (the camera-knock scenario); Claude gave {{ops_claude_calls}} live second opinions at {{ops_claude_p50_s}} s median for {{ops_claude_usd}} in total. Numbers from `scripts/cloud_ops_report.py` (CloudWatch Logs Insights), REAL deployment, replays of synthetic and archived camera frames.

Two pages in the app show this: **Vision Lab** (`/vision`) rebuilds any recorded cycle and shows each OpenCV stage with its real images and numbers (quality metrics and Laplacian map, ORB or ALIKED matches, the rectified gauge strip, the three estimator profiles in metres, fusion and Kalman, per-stage timing and the OpenCV build on the host); **AWS cloud** (`/cloud`) streams the CloudWatch log, runs fixed Logs Insights queries, charts the stage metrics and shows the state of each service in the stack.

## Run it

```bash
make setup          # backend (uv) + frontend (npm ci)
make test           # backend pytest + frontend vitest + lint
make eval           # all evaluations -> eval/results/*.json, then the docs are regenerated
make check-numbers  # README / report / Devpost / video script match the JSON
make dev            # API on :8000, PWA on :5173
make deploy         # AWS (see docs/DEPLOY.md); make destroy removes everything
```

Scenario replays run without any hardware: `POST /api/scenarios/koshi-night-rise/run`. API reference: `docs/API_AGENT.md`.

## Responsible use

NadiSaathi is decision support. It does not replace DHM, CWC, IMD or NDMA warnings, and every public message needs a named person's approval. Faces and number plates are blurred with YuNet before any frame is stored; relief requests keep no names or phone numbers. When a frame is too poor to read, the system says "unknown", never "safe". Details: `docs/RESPONSIBLE_USE.md` (consent, signage text in three languages, retention, failure behaviour), `docs/REPORT.md` (sections 8 and 9) and `docs/MODEL_CARDS.md`.

## Repository

```
backend/src/jalrekha/vision/    OpenCV 5 measurement: quality, register, gauge, waterline, fuse, temporal, flow, privacy, relief
backend/src/jalrekha/agent/     agent loop, policy, approvals, scenarios, relief, cloud adapters, guardrails
backend/src/jalrekha/regions/   Nepal / India / Argentina profiles and river graphs
frontend/src/pages/             Live, Traces, Approvals, Rivers, Relief, Story + the original dashboard pages
eval/  bench/  infra/  docs/    evaluations, benchmark, CloudFormation, report and facts
android/                        volunteer app (unchanged)
```

## Data and model notices

USGS HIVIS imagery and NWIS gauge data are U.S. public domain (credit: U.S. Geological Survey). Weather data by Open-Meteo.com (CC BY 4.0). OpenCV is Apache-2.0. YuNet face and plate detectors (opencv_zoo), ALIKED (BSD-3-Clause) and LightGlue (Apache-2.0) ONNX weights are downloaded at runtime with SHA-1 checks and are not redistributed here. Gemma model weights, used by the edge components, are under the Gemma Terms of Use and are fetched at runtime.

The flood photos from India and Nepal in the app and in `datasets/india_flood_photos/` are from Wikimedia Commons under public domain, CC0, CC BY and CC BY-SA licences; each photo's author, licence and source are listed in `docs/PHOTO_CREDITS.md`, on the app's Credits page and next to the photo. The web copies are resized and re-encoded; CC BY-SA photos stay under CC BY-SA.
