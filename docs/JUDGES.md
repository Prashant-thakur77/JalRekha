# Judges' guide: every track, with proof

Numbers generated 2026-10-26 15:40 UTC by `scripts/make_headline.py` from the result files; `make check-numbers` fails if this
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
| OpenCV 5 does the core work | A camera reads a river gauge in metres: quality gate (Laplacian, histograms), ORB + `estimateAffinePartial2D` (USAC) registration with ALIKED + LightGlue through the OpenCV 5 DNN engine, `warpAffine` gauge strip, Scharr / DIS optical flow / Lab colour estimators, `KalmanFilter`, YuNet face and plate blur, GrabCut flooded-road check | `backend/src/jalrekha/vision/`; live **Vision Lab** (`/vision`); OpenCV 5.0.0 reported by the host |
| It works on real data | 10.6 cm average error on 115 real USGS staff-gauge frames (the method we started from: 99.2 cm on the frames it could read); 8.0 cm on 2,160 held-out synthetic frames | `eval/results/stage_real_physical.json`, `eval/results/stage_synth_test.json`; `make eval` |
| On a real camera, the agent acts on it | 88 archived frames from a USGS camera during a flood: 6.5 cm error on the readings the agent used | `eval/results/real_replay.json`; live replay "Real camera: Hancock" |
| Meaningful AWS | One CloudFormation stack (36 resources): EC2 Graviton4, API Gateway, CloudWatch Logs + metrics + alarms + dashboard, S3 evidence archive, Step Functions, SNS, Polly, Lambda, SSM, Budgets | `infra/nadisaathi.yaml`; `make deploy`; live **AWS cloud** page (`/cloud`) |
| It runs in production | 285 agent cycles (1,093 frames) logged to CloudWatch; OpenCV 93 ms per cycle median on Graviton4; 575 evidence objects in S3; health probe 100.0% up over 23.0 h (275 probes) | `eval/results/cloud_ops.json` (`scripts/cloud_ops_report.py`), `eval/results/soak.json` (`scripts/soak_report.py`) |
| Built and tested | 164 backend tests and 57 frontend tests passing; every number in the docs checked against the result files | `make test`, `make check-numbers`, `eval/results/tests.json` |

## Track: Agentic Vision (vision results change the next plan, tool call, action or human-approval request)

| What the rule asks | How NadiSaathi does it | Proof |
|---|---|---|
| Vision output changes the plan | Nine decision branches, each triggered by an OpenCV number: a bad frame changes the burst size (D1), lost registration escalates to ALIKED+LightGlue (D2), estimator disagreement calls a second opinion (D3), a significant rise changes cadence and computes downstream arrival times (D4), a crossing drafts alerts (D5) | `backend/src/jalrekha/agent/policy.py`, `runner.py`; branches taken in production: D1 ×9, D2 ×15, D3 ×26, D4 ×4, D5 ×4, D7 ×4, D9 ×1 (`cloud_ops.json`) |
| Tool calls and actions | Measure, register, verify with a model, compute ETA, draft SMS / voice / CAP, local siren at danger level, route-board update, all through a guard | `docs/traces/*.jsonl`; live **Agent trace** |
| Human approval | Every public alert waits for a named operator's PIN; Step Functions re-notifies while it waits | live **Approvals**; `infra/nadisaathi.yaml` (ApprovalEscalation) |
| A model in the loop, kept honest | Claude gives a second opinion only when the estimators disagree: 25 live calls on a real camera, 18 confirmed, 7 held for a person. The guard caught 32/32 lying or injected replies in 40 cases, and never let one cancel the siren | `docs/traces/LIVE.md`, `eval/results/guard_eval.json` |
| Better than simpler agents | 36/36 replays correct, first alert a median 62 min before the warning crossing, 0 false-alert runs (the same rule without the vision gates: 2; a threshold agent: 35/36) | `eval/results/agent_suite.json` |
| Other agents can use it | An MCP server with 10 tools over the live API; none can approve or send an alert, and a test checks it | `backend/src/jalrekha/mcp_server.py`, `.mcp.json`, `make mcp` |

## Track: Best use of COOL (Cloud-Optimized OpenCV on AWS Graviton)

| What we measured | Result | Proof |
|---|---|---|
| The core OpenCV workload on Graviton4 vs x86 (same 4 vCPU, same frames) | c8g.xlarge: 99.4 frames/s, $0.446 per million frames; c7i.xlarge: 93.3 frames/s, $0.531; 16% cheaper on Graviton; outputs identical | `bench/cool_bench.py`, `bench/results/`, [docs/COOL.md](COOL.md) |
| Arm acceleration inside OpenCV on the host | `Custom HAL: YES (carotene (ver 0.0.1) KleidiCV (ver 26.03))` | the Vision Lab's timing panel reads `cv2.getBuildInformation()` live |
| Capacity | one c8g.xlarge serves about 7,380 cameras at a 5-minute cadence (from production timings) | [docs/COOL.md](COOL.md) |
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
