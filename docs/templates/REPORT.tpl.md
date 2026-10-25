# NadiSaathi technical report

OpenCV AI Competition 2026 entry. Numbers generated {{generated_at}} from `eval/results/*.json` and `bench/results/*.json` by `scripts/make_headline.py`; `make check-numbers` verifies this file against them. Every number below says which data it comes from: REAL (USGS cameras or gauges), SYNTHETIC (procedural scenes with exact truth) or SCENARIO (a replay built from synthetic frames).

One sentence: a camera on the Koshi at Chatara, Nepal, reads the river in metres with OpenCV 5 on AWS Graviton; when the water starts to climb, an agent looks more often, checks itself, works out when the wave reaches Birpur in Bihar, and drafts Hindi, Maithili and Nepali alerts that a named person approves with a PIN.

## 1. Problem and users

The Koshi, Gandaki/Narayani, Karnali and Bagmati rise in Nepal's hills and flood the plains of Bihar and Uttar Pradesh hours later. On 18 August 2008 the eastern Kosi embankment breached near Kusaha in Nepal and flooded Sunsari and Saptari in Nepal and six districts of Bihar (WRD Bihar). On 29 September 2024 the Kosi at the Birpur barrage peaked at 661,295 cusecs, the highest since 1968 (Government of Bihar). Bihar's flood-affected area is about 17.2% of India's flood-prone area (Government of Bihar). Bihar's own Kosi forecast bulletins in October 2026 note that observed rainfall and water-level data from Nepal were unavailable to them (WRD Bihar). After the August 2026 Bhotekoshi–Trishuli flood, critics said official SMS warnings were generic and lacked exact locations (Mongabay India, secondary). Sources and status for each fact: `docs/FACTS.md`.

Official gauges exist, but between them, on tributaries and at bridges, nobody measures, and the data that do exist do not always cross the border in time. A camera on a staff gauge costs little and can be one more gauge. If it sees the rise upstream, the downstream side gets hours.

| Side | User | What NadiSaathi gives them |
|---|---|---|
| Nepal | Ward disaster focal person (rural municipality, Saptari or Sunsari) | the measured level and rise rate in Nepali, a drafted ward SMS and voice clip, one-tap approval |
| Nepal | Community gauge reader | the camera reads the same gauge every few minutes; asks them for a photo only when it cannot see |
| India | DDMA control-room operator (Supaul, Saharsa, Khagaria) | an upstream-derived arrival window for named places, a drafted CAP alert and Hindi/Maithili SMS + voice, an approval inbox |
| India | Panchayat volunteer, NGO relief team | relief requests de-duplicated and ranked; road photos checked for depth; shelter list |
| Both | Riverside families | a short, plain message in their language, also as audio; a local siren if the cloud is down |

The personas in the demo (Sita, Rakesh) are illustrative composites, not real people. No partnership with any agency exists; DHM, CWC, IMD, NDMA, state authorities and community early-warning programmes are the people to approach next.

## 2. Architecture

```
 edge / camera ──► POST /api/agent/cycle (burst) ─┐        scenario replays (procedural frames) ─┐
 volunteer PWA / Android ──► /api/reports, /relief │                                             │
                                                   ▼                                             ▼
                     ┌──────────────────────── EC2 c8g.xlarge (Graviton4), FastAPI ───────────────────────┐
                     │ JalRekha OpenCV 5 pipeline ─► agent loop (policy D1–D9) ─► guard ─► act / approval │
                     │ region profiles + river graphs     traces (SQLite, S3)     original fusion engine  │
                     └──┬───────────┬────────────┬───────────┬────────────┬───────────────────────────────┘
                        S3     Claude API      Polly        SNS        CloudWatch (logs, metrics, alarms)
 API Gateway HTTPS (VPC link) in front; EventBridge + Lambda keep-warm; SSM Parameter Store; AWS Budgets
```

Diagrams: `docs/ARCHITECTURE.md` (system and agent workflow, Mermaid). The original stack (FastAPI routes for sites, node analysis, volunteer reports, fused alerts, incidents, sync, CAP; the PWA; the Android app; the Raspberry Pi scripts) is kept and still tested; section 10 lists what existed before and what was built for this competition.

## 3. OpenCV 5 work

The measurement engine is `backend/src/jalrekha/vision/`, pure OpenCV 5 + NumPy. It runs in the API process on the cloud and out of process on a Raspberry Pi (LiteRT and NumPy in one process corrupted the Vulkan runtime there).

| Stage | File | OpenCV used | Output |
|---|---|---|---|
| Quality gate | `quality.py` | Laplacian variance, `calcHist` clipping, mean luma, glare fraction, `meanStdDev` contrast on the gauge strip | ok / reasons; a failed frame cannot change an alert |
| Registration | `register.py` | ORB + `estimateAffinePartial2D` (USAC); escalation to **ALIKED + LightGlue** ONNX models through the OpenCV 5 DNN engine; burst alignment | 2×3 transform, inliers, residual; keyframe chaining when high water hides the reference features |
| Gauge geometry | `gauge.py` | `warpAffine` strip along the gauge axis | piecewise-linear pixel→metre from clicked numerals |
| Estimator E1 | `waterline.py` | Scharr edge energy profile + step fit | waterline row, confidence |
| Estimator E2 | `waterline.py` | **DIS optical flow** temporal texture over the burst | water moves, the gauge does not |
| Estimator E3 | `waterline.py` | Lab colour step fit on the burst median | waterline row |
| Fusion | `fuse.py` | weighted median, spread → sigma | stage m ± sigma, agreement |
| Temporal | `temporal.py` | `cv2.KalmanFilter` (level, rate), irregular time steps, Mahalanobis gate | level, rise rate m/h |
| Surface motion | `flow.py` | DIS flow in the water band | surface speed proxy (not discharge) |
| Privacy | `privacy.py` | **YuNet** face and licence-plate detectors (`FaceDetectorYN`, DNN), Gaussian blur | redacted frame, counts |
| Relief photo | `relief.py` | GrabCut seeded by texture, morphology, connected components | water mask, depth at a reference object ± error |
| Overlay | `overlay.py` | drawing for the UI and traces | annotated JPEG |

**Vision Lab** (`/vision` in the app, `GET /api/vision/lab/{trace_id}`, `vision/explain.py`) shows what OpenCV did for one real agent cycle, stage by stage. It rebuilds the cycle's input frames (scenario frames are regenerated from their seed and cycle time; the Hancock replay reads the archived USGS frame), runs the same `measure()` with an opt-in capture of its intermediates, and returns: each quality metric against its threshold with a |Laplacian| heat map; the ORB (or ALIKED+LightGlue) RANSAC inliers drawn with `cv2.drawMatches` and a checkerboard of the reference against the warped frame; the `warpAffine` gauge strip and its burst median; the per-row signal each estimator fitted, on a gauge axis in metres, with its chosen waterline; the weighted-median fusion, the two-of-three consensus and the agent's Kalman value; and per-stage milliseconds with the host's `cv2.getBuildInformation()` CPU and HAL lines. Every image comes from the YuNet-redacted frame. The page also compares the rebuilt reading with the one stored in the trace; across a full Chatara scenario replay and the full Hancock replay they matched on every cycle checked.

The base method of the original repository (a PIL edge-row heuristic, `services/deterministic_firewall.py`) is kept unchanged as fallback and as baseline B0. It used to report `opencv_used=True` while using PIL; the label is truthful now.

## 4. AWS deployment

One CloudFormation stack, `infra/nadisaathi.yaml`, deploys in about 5 minutes and updates in about 60 s (`make deploy`):

- EC2 c8g.xlarge Graviton4 (Ubuntu 24.04 arm64, stock OpenCV 5 wheel; `USE_COOL_AMI=true` is wired for the COOL AMI but has not been run, because the Marketplace terms are not yet accepted on this account), IMDSv2, no SSH (SSM only), port 8000 reachable only through the API Gateway VPC link.
- API Gateway HTTP API as the public HTTPS front door. CloudFront is in the template; the account must be verified by AWS before it can create CloudFront resources.
- S3: the evidence archive (each agent cycle's JSON event and its face/plate-blurred overlay, `cycles/<site>/<date>/<trace>`, kept 90 days by a lifecycle rule; {{ops_s3_objects}} objects after the replays below), CAP files and deploy bundles. The bucket name contains the account id, so the app serves evidence through its own API instead of presigned links.
- CloudWatch: one JSON event per agent cycle in the stack log group (stage, error, alignment method and inliers, each estimator, every OpenCV stage time, second-opinion model, latency and cost), per-stage OpenCV metrics (`StageMs` by `Stage`), `AgentCycles`, `ApprovalsPending`, `Escalations`, fixed Logs Insights queries, a dashboard, and alarms for instance health, the public health probe and an OpenCV pipeline slower than 1 s ({{ops_alarms}} alarms).
- SNS (operator topic; SMS to verified test numbers only), Polly (Hindi/English voice), SSM Parameter Store (operator PINs, camera key, model key), AWS Budgets, an EventBridge-scheduled keep-warm Lambda with a health alarm, and a Step Functions state machine that re-notifies operators every 15 minutes (up to three times) while a drafted public alert is still waiting for a decision. {{ops_stack_resources}} resources in one stack.
- Production numbers, read back from CloudWatch (`scripts/cloud_ops_report.py`): {{ops_cycles}} cycles and {{ops_frames}} frames over {{ops_days}} days on {{ops_sites}} camera sites; OpenCV {{ops_total_p50_ms}} ms per cycle at the median and {{ops_total_p95_ms}} ms at p95 on Graviton4 (registration {{ops_register_ms}} ms, face/plate blur {{ops_redact_ms}} ms, DIS-flow estimator {{ops_e2_ms}} ms on average); ORB aligned {{ops_orb_cycles}} cycles, ALIKED+LightGlue rescued {{ops_aliked_cycles}}, {{ops_reg_failed}} could not be aligned and were held; {{ops_claude_calls}} live Claude second opinions at {{ops_claude_p50_s}} s median, {{ops_claude_usd}} in total. Health probe: {{soak_probes}} probes over {{soak_hours}} h, {{soak_uptime}} up.
- The app's Cloud page (`/cloud`) shows the same data live: the log tail, the Insights queries with their query text, the stage metrics and the state of each service. An MCP server (`make mcp`) exposes the agent's read-only tools and replays to other agents; no tool can approve or send an alert.
- Least-privilege instance role: S3 on the stack bucket, metrics only in the `NadiSaathi` namespace, SNS on the stack topic, logs on the stack log group, and read-only views (metrics, the instance, the stack, escalation runs, the budget) for the Cloud page.
- Cost: c8g.xlarge on-demand is {{B_usd_h}}/h (AWS Price List API); the judging window is an estimate of about $58 for the whole stack (`docs/DEPLOY.md`).

Language and vision model: Claude ({{vlm_model}}) through the Anthropic API, with server-side refusal fallbacks, structured JSON outputs and a key held in SSM Parameter Store. It writes the second opinion on a gauge reading (D3/D7), structures volunteer reports and relief requests in five languages, describes volunteer photos after face/plate blur, and drafts situation summaries that the numbers-from-tools guard checks. Amazon Bedrock is wired as an alternative provider, but this account's Bedrock quota is zero, so it is not used. Every model call has a deterministic fallback.

On {{pt_photos}} licensed flood photos from India and Nepal (`eval/run_photo_triage.py`, faces and plates blurred first), Claude marked {{pt_road_hit}} of {{pt_road_pos}} flooded roads and underpasses as flooded and {{pt_others_flagged}} of the other {{pt_others}} photos as well (a washed-out mountain bridge and an NDRF boat rescue in floodwater), at ~{{pt_latency_s}} s and {{pt_cost_photo}} per photo. The labels come from each photo's subject and n is small, so this is a sanity check on real Indian scenes, not an accuracy figure. The photo description never sets a road's status: D8 needs the GrabCut depth check and an operator's approval.

## 5. The agent

The agent (`backend/src/jalrekha/agent/runner.py`) runs one cycle per camera burst: perceive → assess → plan → guard → act or ask → trace. The OpenCV numbers choose the branch:

| Branch | Trigger (OpenCV output) | Next action changes to |
|---|---|---|
| D1 | quality gate fails | no alert from this frame; burst 5 → 9 frames; photo request after two bad frames |
| D2 | ORB registration fails | ALIKED+LightGlue or keyframe chain; if still lost or the gauge leaves the view, site degraded + recalibration request |
| D3 | fewer than 2 of 3 estimators within 10 cm, or sigma > 8 cm | VLM second opinion (Claude); if unavailable, hold the reading; after 3 held readings in a row, ask a person |
| D4 | significant Kalman rise: rate − 1.5·σ_rate ≥ 0.30 m/h | capture cadence 600 → 300 s (scenario sites); downstream ETA bands |
| D5 | stage ≥ warning, or projected to cross within 1.5 h (right after bad frames: only after 3 significant-rise cycles in a row) | local and cross-border drafts (SMS, voice, CAP) for the right authority role |
| D6 | stage ≥ danger, quality OK, at least 2 of 3 estimators within 10 cm (sigma from the agreeing pair ≤ 8 cm; the trace records both this and the fused sigma) | local siren through the guard (schema, severity ≤ evidence, region bounds, 6/h rate limit) |
| D7 | VLM contradicts a confident reading, is malformed, or carries extra text / instructions | keep the OpenCV value, request human review; a VLM that abstains cannot veto a confident reading |
| D8 | relief photo depth ≥ 0.30 m at a reference object | route-board "blocked" update drafted for approval |
| D9 | falling for 3 cycles after a peak | cadence back down; all-clear proposed for approval |

Autonomy policy (`agent/policy.py`, also `GET /api/agent/policy`): the agent alone changes what the camera does, calls the VLM, computes ETAs, drafts messages and sounds the local siren at danger level. Public SMS, voice, CAP, cross-border notices, all-clears, road status and relief dispatch need an operator PIN and a named approver; edits to a draft are kept next to the original text.

Guardrails: strict JSON parsing of VLM replies (only three keys are read; extra prose is reported and ignored), an injection detector, a numbers-must-come-from-tools check for model-written text (`agent/guardrails.py`), the original action guard now wired in with region bounds, fail-safe defaults (a missing reading is "unknown", never "safe"), camera keys on the frame-upload route (a spoofed camera cannot drive the siren), a PIN lockout after five wrong attempts in ten minutes, and API Gateway throttling. A shared operator PIN is a pilot simplification; per-operator credentials are the next step.

The scenario `koshi-night-rise` exercises D1, D2, D4, D5, D6, D7 and D9 (including the all-clear proposal) in one replay; its D7 step uses a scripted adversarial reply, labelled in the trace; `karnali-quiet-storm` checks that bad weather alone raises nothing; `bagmati-camera-moved` checks D2 failure handling. Traces are exported in `docs/traces/`.

## 6. Evaluation

Protocols are frozen before test runs (`eval/config.frozen.json`, `eval/config.leadtime.frozen.json`; their hashes are stored in each result file). Test sets are held out by scene seed, by site or by date.

### 6.1 Stage accuracy on real cameras (REAL)

USGS HIVIS cameras at two staff-gauge sites (Hancock, NY on the East Branch Delaware; Moravia, NY on Owasco Inlet), paired with NWIS gauge height within one minute. Calibration is physical: the printed numerals were clicked once on one reference frame, stage = numeral × 0.3048 m, with no fitted parameters, so every frame is a test frame. Single hourly snapshots, so E2 (which needs a burst) abstains.

| Method | MAE cm (pooled, {{real_n}} in-range frames) |
|---|---|
| Full pipeline | **{{real_full_mae_cm}}** (95% CI {{real_full_ci}}), median {{real_full_median_cm}}, {{real_full_within10}} within 10 cm |
| Full, no registration | {{real_noreg_mae_cm}} ({{real_noreg_within10}} within 10 cm) |
| E1 edge only | {{real_e1_mae_cm}} |
| Naive max-edge (B1) | {{real_b1_mae_cm}} |
| E3 colour only | {{real_e3_mae_cm}} ({{real_e3_within10}} within 10 cm), identical to the full pipeline: on single snapshots E2 abstains and E1 is down-weighted |
| Original PIL heuristic (B0) | {{real_b0_mae_cm}} on the {{real_b0_coverage}} of frames it answers; on those same {{real_b0_subset_n}} frames the full pipeline is {{real_full_on_b0_subset_cm}} |

Per site: Hancock {{real_hancock_mae_cm}} cm MAE, median {{real_hancock_median_cm}} cm, {{real_hancock_within10}} within 10 cm ({{real_hancock_frames}} frames); Moravia {{real_moravia_mae_cm}} cm ({{real_moravia_frames}} frames). Frames with the water below the gauge foot or the gauge submerged are scored separately: {{real_hancock_out_ok}} of {{real_hancock_out}} (Hancock) and {{real_moravia_out_ok}} of {{real_moravia_out}} (Moravia) were reported at the gauge end within 10 cm. {{vlm_sentence}} A third staff-gauge site (Avon, NY) is out of scope: its plates use another datum and stay above the water for nearly the whole event. Caveat on the protocol: our first protocol (fit a line on each site's first frames) failed on these same frames ({{real_fitted_protocol_mae_cm}} cm, no better than a constant at {{real_fitted_protocol_const_cm}} cm); we switched to physical calibration and excluded Avon after seeing that. Nothing in the reported pipeline is fitted to gauge readings, but the choice of protocol was made after the first look. Registration hurt at Moravia ({{real_moravia_within10}} within 10 cm with it, {{real_moravia_noreg_within10}} without); we report it rather than tune it on the test frames.

### 6.1b The agent on a real camera (REAL)

`eval/run_real_replay.py` feeds the {{rr_frames}} archived daytime frames of the Hancock camera (July 2026 flood) to the agent in time order, with the physical calibration and illustrative warning/danger marks on the staff gauge (14 ft and 17 ft; not official flood categories). The camera stores one frame per hour, so the temporal estimator cannot run; for such snapshot cameras the agent takes three consecutive frames within 10 cm as the second vote. Results: {{rr_used}} readings used at {{rr_used_mae_cm}} cm MAE (median {{rr_used_median_cm}} cm); {{rr_held_pct}} held (the first frame after each overnight gap, and the turbulent peak), which sent a review request to a person; the danger siren sounded on the first frame above the danger mark ({{rr_siren_first}}); {{rr_quiet_alerts}} alert drafts on the quiet days; the all-clear was proposed on the recession ({{rr_all_clear}}). The steep rise happened overnight, when this camera records nothing, so the first warning came at the first morning frame: a real limitation of daytime-only cameras, and the reason the agent asks a deployed camera for more frequent bursts during a rise. The snapshot vote was added after the first run of this replay showed the agent holding almost every reading.

### 6.2 Stage accuracy on held-out synthetic scenes (SYNTHETIC)

{{synth_frames}} frames, 30 held-out scene seeds, 9 conditions. Full pipeline {{synth_full_mae_cm}} cm MAE (CI {{synth_full_ci}}), median {{synth_full_median_cm}} cm, {{synth_full_within5}} within 5 cm. Single estimators: E1 {{synth_e1_mae_cm}}, E2 {{synth_e2_mae_cm}}, E3 {{synth_e3_mae_cm}} cm; without registration {{synth_noreg_mae_cm}} cm. Original heuristic: answers {{synth_b0_coverage}} of frames as shipped; with its border bug fixed, {{synth_b0r_mae_cm}} cm. Robustness curves for six degradation types are in `eval/results/sweep_synth.json`.

### 6.3 Lead time gained across a river (REAL)

{{lt_pairs}} upstream→downstream USGS gauge pairs (Delaware, Susquehanna, Potomac, Juniata, Wabash), 15-minute gauge height, TRAIN 2021–2023, TEST 2024–Oct 2026. The agent's own alert rule (Kalman rate, projected crossing) runs causally on the downstream gauge alone (baseline) and on both gauges (ours). These are U.S. rivers because Nepal and India gauge series are not public; the measurement is of the mechanism, not of the Koshi.

| Warning levels | Events | Median gain | Mean gain | Detection before crossing | Upstream false alerts / 30 days / pair |
|---|---|---|---|---|---|
| NWS action stage (pre-registered primary) | {{lt_nws_events}} | {{lt_nws_gain_median_min}} min | {{lt_nws_gain_mean_h}} h | {{lt_nws_det_down}} → {{lt_nws_det_comb}} | {{lt_nws_fa_up}} |
| 95th percentile of TRAIN stage | {{lt_p95_events}} | {{lt_p95_gain_median_h}} h (CI {{lt_p95_gain_ci}} min) | {{lt_p95_gain_mean_h}} h | {{lt_p95_det_down}} → {{lt_p95_det_comb}} | {{lt_p95_fa_up}} |
| 95th percentile, camera noise σ = 5 cm | {{lt_p95cam_events}} | {{lt_p95cam_gain_median_h}} h | {{lt_p95cam_gain_mean_h}} h | {{lt_p95cam_det_down}} → {{lt_p95cam_det_comb}} | {{lt_p95cam_fa_up}} |

The window W within which an upstream alert counts is three times the TRAIN travel time, capped at 48 h, so long gains are possible by construction and the false-alert rate is the check on them. The primary result is a null median: with official action stages the upstream gauge often rose without reaching its own action stage, because those stages are set town by town. With levels on the same statistical footing the median gain is {{lt_p95_gain_median_h}} h. Camera noise makes the rise rate jumpy and multiplies false alerts; the camera-noise "gains" partly come from chance alerts landing in the window and are not claimed.

Version 2 of the rule counts a rise only when it is significant (rate − z·σ_rate ≥ 0.30 m/h). z = {{lt2_z}} was chosen on TRAIN only and frozen (`eval/config.leadtime.v2.frozen.json`); TEST had already been seen in v1, so these are optimistic second-look numbers. Camera-noise upstream false alerts fall from {{lt_p95cam_fa_up}} to {{lt2_p95cam_fa_up}} per 30 days per pair; the median gain with percentile levels stays {{lt2_p95_gain_median_h}} h; with action stages it stays {{lt2_nws_gain_median_min}} min. The cost: early projected-crossing alerts at the downstream gauge become rarer (downstream-only detection {{lt_p95_det_down}} → {{lt2_p95_det_down}}). The agent uses v2. Details and failure cases: `eval/LEADTIME.md`.

### 6.4 Agent scenario suite (SYNTHETIC)

{{ag_runs}} runs on held-out gauge scenes: {{ag_flood_runs}} floods with rain, glare and camera knocks during the rise, and {{ag_quiet_runs}} no-flood runs: bad weather on a steady river, the river held 30 cm below the warning level while glare, a knock, rain/fog and dusk hit the camera, and the camera mount knocked hard while the river sits 50 cm below the warning level. Two baselines use the same OpenCV reading: a threshold agent (no Kalman, fixed 10-minute cadence) and the agent's own projection rule with no quality gate, no consensus check and no second opinion.

| | Agent | Projection rule, no gates | Threshold only |
|---|---|---|---|
| Correct runs | {{ag_success}} | {{pj_success}} | {{rb_success}} |
| First alert vs true warning crossing (median) | {{ag_lead_median_min}} min before | {{pj_lead_median_min}} min | {{rb_lead_median_min}} min |
| False alerts / false sirens / missed sirens | {{ag_false_alert_runs}} / {{ag_false_sirens}} / {{ag_missed_sirens}} | {{pj_false_alert_runs}} / {{pj_false_sirens}} / {{pj_missed_sirens}} | {{rb_false_alert_runs}} / {{rb_false_sirens}} / {{rb_missed_sirens}} |

On the {{agu_runs}} runs from gauge scenes added after the last agent change (never used for development): agent {{agu_success}} correct, {{agu_false_alert_runs}} false-alert runs, median lead {{agu_lead_median_min}} min; projection without gates {{pju_success}}, {{pju_false_alert_runs}}, {{pju_lead_median_min}} min; threshold {{rbu_success}}, {{rbu_false_alert_runs}}, {{rbu_lead_median_min}} min.

Reading it honestly: the lead time comes from the Kalman projection, which the "no gates" baseline shares. Where the gates matter is false alarms when the camera fails near the warning line. In the camera-knock runs a misregistered frame reads high; the system without gates drafts alerts ({{pj_false_alert_runs}} runs, both on unseen scenes) and the agent does not. The suite records where the plans split: in {{split_variant}} at T+{{split_t}} min the no-gates system alerts while the agent's trace shows branch {{split_branches}}: "{{split_agent_summary}}" (`eval/results/agent_suite.json`, `plan_splits`). The first run of the hard variants found a failure in the agent that the baselines did not have: glare that passed the quality gate biased two readings 40 cm low, and when the glare ended the jump back looked like a 1.2 m/h rise, so the agent drafted alerts (for approval) on a steady river. The fix is a post-gap rule: right after bad frames, a projected crossing needs three significant-rise cycles in a row. The numbers above are after the fix; on the original seeds they are optimistic, which is why the unseen seeds are reported separately. Where the gates matter is false alarms on bad frames near the warning line. The suite found two real bugs during development (scenario reference frames cached per site instead of per scene, which made the agent miss two floods; drafts rewritten with a falling rate after the peak); both are fixed and covered by tests, and the hard near-warning variants were added after a fresh-eyes review.

### 6.5 Guard against the vision model (SYNTHETIC)

{{guard_cases}} scripted VLM replies, each run through a full agent cycle on a danger-level burst (truth above danger, three estimators agreeing): honest confirmations, clean contradictions, prompt injections paraphrased in English, Hindi and Nepali, and malformed output. {{guard_caught}} of {{guard_bad}} bad replies were caught (measurement kept, siren not cancelled) and {{guard_confirm_ok}} honest confirmations were accepted (`eval/results/guard_eval.json`). Building this set exposed one flaw, now fixed: a VLM that answered "cannot see" made the agent hold a confident danger reading and skip the siren. The guard has a blind spot that the evaluation also measures: in {{glare_wrong}} of {{glare_bursts}} strong-glare bursts ({{glare_wrong_pct}}) OpenCV was confidently wrong, reading {{glare_err_range}} too low with two estimators agreeing, so no second opinion is requested and the low value would stand. These are scripted inputs, not a live model; the injection detector is a pattern list, but the guard does not rely on it: only three JSON keys are ever read, and any contradiction of a confident measurement goes to a person.

### 6.6 Performance and cost (benchmark workload)

`bench/cool_bench.py`, same frames and config on every host; full table in `docs/COOL.md`. Graviton4 c8g.xlarge with the stock OpenCV 5.0 wheel: {{B_ms}} ms per 5-frame burst (sd {{B_ms_sd}} over 5 repeats), {{B_fps}} frames/s with one process per vCPU, {{B_cams}} cameras at a 10 s cadence, {{B_usd_1m}} per million frames. x86 c7i.xlarge: {{C_ms}} ms, {{C_fps}} frames/s, {{C_usd_1m}}. Outputs are {{BC_equal}} to the millimetre across the two architectures. ALIKED+LightGlue is {{BC_aliked_speedup}} and DIS flow {{BC_dis_speedup}} faster on Graviton. The aarch64 opencv-python 5.0 wheel already reports KleidiCV in its build information.

## 7. Reliability

- Tests: backend pytest (agent scenarios, approvals and PIN, guardrails, relief, photo check, lead-time code, and all the original tests), frontend vitest, ESLint, all in `make test`.
- Nothing lost: `make smoke` calls every original API route and the new ones against the deployed stack (34 of 34 as expected on the last run, including the original sample-video analysis and the PIN-protected writes).
- Repeatability: benchmark repeats have a standard deviation of {{B_ms_sd}} ms on c8g; scenario replays are deterministic (seeded).
- The deployed endpoint has a keep-warm Lambda every 5 minutes, an EC2 status-check auto-recover alarm, and a health alarm to SNS. Observed so far: {{soak_uptime}} of {{soak_probes}} probes OK over {{soak_hours}} h, health latency p50 {{soak_p50_ms}} ms / p95 {{soak_p95_ms}} ms, {{soak_cycles}} agent cycles run on the cloud host (`scripts/soak_report.py` reads CloudWatch; the number grows through judging).

## 8. Limitations

- Two real camera sites, both in the United States, both with staff gauges. No Nepal or India camera footage was available; the Koshi, Gandak, Karnali and Bagmati runs are scenario replays and are labelled so.
- Physical calibration assumes the staff gauge shares the official gauge datum (true at both evaluated sites; Avon shows it is not always true).
- Hourly snapshots only on the real cameras; the burst estimator E2 and the cadence logic are evaluated on synthetic scenes.
- Travel times are distance/celerity estimates except one reported value (Devghat–Valmikinagar about six hours, a secondary source).
- Lead-time gains depend on consistent warning levels along the river (6.3).
- No Polly voice for Nepali, Maithili or Bhojpuri; Maithili and Bhojpuri texts need native review.
- SMS to India needs TRAI DLT registration; Nepal bulk SMS goes through telecom operators. The pilot sends only to verified test numbers.
- The language and vision model is a hosted API (Claude); the edge box falls back to rules (or an on-device Gemma model) when it is offline.
- Face and plate redaction recall has not been measured on our own data; we rely on the detectors' published behaviour, and stored frames, approvals and traces are readable through the public demo API (they contain synthetic scenes and no personal data). A real deployment should restrict read access to operators.

## 9. Responsible use

Faces and number plates are blurred before storage; the agent never tracks people. Relief requests keep text, a coarse location (3 decimal places) and parsed fields, no names or phone numbers. Every public message is approved by a named person with a PIN, and the CAP file carries a note that it is a pilot and complements official warnings. Unknown is never reported as safe. Model cards: `docs/MODEL_CARDS.md`.

## 10. What existed before and what was built for this competition

The repository builds on an earlier open-source flood-alert stack. The table separates what existed before from what was built for this competition.

| Area | Before | Built for this competition |
|---|---|---|
| Vision | PIL edge-row heuristic; a language model reading frames | OpenCV 5 metric pipeline (quality, ORB/ALIKED+LightGlue registration, three estimators, Kalman, DIS flow, YuNet redaction, relief photo check) |
| Region | one country, Spanish | Nepal and India profiles, four basin graphs with CWC levels, five languages, voice |
| Agent | language model chooses actuators; guard not wired | perception-driven policy D1–D9, approvals, wired guard, guardrails, traces, scenario replays |
| Cloud | none | CloudFormation on Graviton, API Gateway, S3, Polly, SNS, Claude API (Bedrock wired as alternative), CloudWatch, Budgets, keep-warm |
| Evaluation | parsing accuracy on authored sentences; Pi latency | real-camera stage accuracy, synthetic robustness, real lead time, agent suite, Graviton/x86 benchmark |
| UI | dashboard, report, queue, calibration, settings | Live replay, traces, approvals, rivers, relief, story; EN/HI/NE; accessibility fixes |
| Kept | all original API routes, fusion engine, incidents, sync, CAP, Android app, Pi scripts | still tested |
