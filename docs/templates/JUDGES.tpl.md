# Judges' guide: every track, with proof

Numbers generated {{generated_at}} by `scripts/make_headline.py` from the result files; `make check-numbers` fails if this
page and the JSON disagree. Every row points to something you can open, run or query yourself.

**Live app:** https://gaq7chhmb2.execute-api.us-east-1.amazonaws.com · **Code:** this repository · **Report:** [docs/REPORT.pdf](REPORT.pdf) · **Film:** https://youtu.be/eVobF8Eg-b4

## Five minutes, end to end

1. Open the live app. **Live** → *Watch a replay*: a camera night at Chatara (Nepal) runs through OpenCV 5 and the agent on AWS Graviton4.
2. **Vision Lab**: one recorded cycle rebuilt stage by stage, with real images: quality gate, ORB/ALIKED matches, the gauge strip, three estimator profiles in metres, fusion, per-stage timing and the OpenCV build on the host.
3. **Agent trace** → *Try to fool the guard*: type a lying or injected model reply; the agent keeps the OpenCV reading and asks a person.
4. **Approvals**: the replay's drafts in Hindi, Maithili and English wait for a PIN (the PIN is in the private testing field).
5. **AWS cloud**: the CloudWatch log of agent cycles streaming, Logs Insights queries, OpenCV stage metrics and the state of every service in the stack.

## Track: Overall (OpenCV 5 for substantive image analysis, plus a meaningful AWS component)

| Requirement | What we built | Proof |
|---|---|---|
| OpenCV 5 does the core work | A camera reads a river gauge in metres: quality gate (Laplacian, histograms), ORB + `estimateAffinePartial2D` (USAC) registration with ALIKED + LightGlue through the OpenCV 5 DNN engine, `warpAffine` gauge strip, Scharr / DIS optical flow / Lab colour estimators, `KalmanFilter`, YuNet face and plate blur, GrabCut flooded-road check | `backend/src/jalrekha/vision/`; live **Vision Lab** (`/vision`); OpenCV {{B_cv2}} reported by the host |
| It works on real data | {{real_full_mae_cm}} cm average error on {{real_n}} real USGS staff-gauge frames (the method we started from: {{real_b0_on_subset_cm}} cm on the frames it could read); {{synth_full_mae_cm}} cm on {{synth_frames}} held-out synthetic frames | `eval/results/stage_real_physical.json`, `eval/results/stage_synth_test.json`; `make eval` |
| On a real camera, the agent acts on it | {{rr_frames}} archived frames from a USGS camera during a flood: {{rr_used_mae_cm}} cm error on the readings the agent used | `eval/results/real_replay.json`; live replay "Real camera: Hancock" |
| Meaningful AWS | One CloudFormation stack ({{ops_stack_resources}} resources): EC2 Graviton4, API Gateway, CloudWatch Logs + metrics + alarms + dashboard, S3 evidence archive, Step Functions, SNS, Polly, Lambda, SSM, Budgets | `infra/nadisaathi.yaml`; `make deploy`; live **AWS cloud** page (`/cloud`) |
| It runs in production | {{ops_cycles}} agent cycles ({{ops_frames}} frames) logged to CloudWatch; OpenCV {{ops_total_p50_ms}} ms per cycle median on Graviton4; {{ops_s3_objects}} evidence objects in S3; health probe {{soak_uptime}} up over {{soak_hours}} h ({{soak_probes}} probes) | `eval/results/cloud_ops.json` (`scripts/cloud_ops_report.py`), `eval/results/soak.json` (`scripts/soak_report.py`) |
| Built and tested | {{tests_backend_passed}} backend tests and {{tests_frontend_passed}} frontend tests passing; every number in the docs checked against the result files | `make test`, `make check-numbers`, `eval/results/tests.json` |

## Track: Agentic Vision (vision results change the next plan, tool call, action or human-approval request)

| What the rule asks | How NadiSaathi does it | Proof |
|---|---|---|
| Vision output changes the plan | Nine decision branches, each triggered by an OpenCV number: a bad frame changes the burst size (D1), lost registration escalates to ALIKED+LightGlue (D2), estimator disagreement calls a second opinion (D3), a significant rise changes cadence and computes downstream arrival times (D4), a crossing drafts alerts (D5) | `backend/src/jalrekha/agent/policy.py`, `runner.py`; branches taken in production: {{ops_branch_list}} (`cloud_ops.json`) |
| Tool calls and actions | Measure, register, verify with a model, compute ETA, draft SMS / voice / CAP, local siren at danger level, route-board update, all through a guard | `docs/traces/*.jsonl`; live **Agent trace** |
| Human approval | Every public alert waits for a named operator's PIN; Step Functions re-notifies while it waits | live **Approvals**; `infra/nadisaathi.yaml` (ApprovalEscalation) |
| A model in the loop, kept honest | Claude gives a second opinion only when the estimators disagree: {{live_opinions}} live calls on a real camera, {{live_confirmed}} confirmed, {{live_held}} held for a person. The guard caught {{guard_caught}}/{{guard_bad}} lying or injected replies in {{guard_cases}} cases, and never let one cancel the siren | `docs/traces/LIVE.md`, `eval/results/guard_eval.json` |
| Better than simpler agents | {{ag_success}} replays correct, first alert a median {{ag_lead_median_min}} min before the warning crossing, {{ag_false_alert_runs}} false-alert runs (the same rule without the vision gates: {{pj_false_alert_runs}}; a threshold agent: {{rb_success}}) | `eval/results/agent_suite.json` |
| Other agents can use it | An MCP server with {{mcp_tools}} tools over the live API; none can approve or send an alert, and a test checks it | `backend/src/jalrekha/mcp_server.py`, `.mcp.json`, `make mcp` |

## Track: Best use of COOL (Cloud-Optimized OpenCV on AWS Graviton)

| What we measured | Result | Proof |
|---|---|---|
| The core OpenCV workload on Graviton4 vs x86 (same 4 vCPU, same frames) | {{B_type}}: {{B_fps}} frames/s, {{B_usd_1m}} per million frames; c7i.xlarge: {{C_fps}} frames/s, {{C_usd_1m}}; {{BC_cost_saving}} cheaper on Graviton; outputs {{BC_equal}} | `bench/cool_bench.py`, `bench/results/`, [docs/COOL.md](COOL.md) |
| Arm acceleration inside OpenCV on the host | `Custom HAL: {{B_custom_hal}}` | the Vision Lab's timing panel reads `cv2.getBuildInformation()` live |
| Capacity | one c8g.xlarge serves about {{cloud_cams_300s}} cameras at a 5-minute cadence (from production timings) | [docs/COOL.md](COOL.md) |
| COOL-ready | `USE_COOL_AMI=true make deploy` switches the stack to the COOL Graviton4 AMI with one flag | `infra/nadisaathi.yaml`, `scripts/deploy/deploy.sh` |

## Where everything is

| Path | What |
|---|---|
| `backend/src/jalrekha/vision/` | the OpenCV 5 pipeline |
| `backend/src/jalrekha/agent/` | the agent, policy, guard, messages, CloudWatch cycle events |
| `backend/src/jalrekha/api/routers/` | the API, including `vision_lab.py` and `cloud_ops.py` |
| `frontend/` | the app (React + Vite, English / Hindi / Nepali) |
| `infra/` | CloudFormation and the instance bootstrap |
| `eval/`, `bench/`, `eval/results/` | every evaluation and its JSON |
| `docs/` | report (and PDF), architecture, model cards, responsible use, traces, screenshots |
| `video/` | the demo film, built from code |
