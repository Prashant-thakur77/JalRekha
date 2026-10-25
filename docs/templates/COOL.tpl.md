# OpenCV 5 on AWS Graviton: benchmark and COOL status

Numbers generated {{generated_at}} from `bench/results/*.json`.

The core workload is the JalRekha measurement on a 5-frame camera burst: quality gate, ORB registration, burst alignment, gauge strip, three waterline estimators (Sobel edges, DIS optical flow, Lab colour step), fusion, DIS surface motion, YuNet face/plate redaction and the overlay. It is what every agent cycle runs (`backend/src/jalrekha/vision/pipeline.py`).

## Method

`bench/cool_bench.py` renders the same 144 bursts on every host (12 held-out gauge scenes × 4 conditions × 3 stages, 960×540), runs the full pipeline 5 times, and records:

- p50/p95 per stage
- thread scaling (`cv2.setNumThreads`, one fresh process per setting)
- throughput with one single-threaded worker process per vCPU
- micro-benchmarks of ALIKED+LightGlue, DIS flow, YuNet and GrabCut
- an output hash of every stage reading rounded to 1 mm
- proof of the build: `cv2.getBuildInformation()` KleidiCV lines and the EC2 instance id, type and AMI id from IMDSv2

`scripts/bench/cloud_bench.sh A|B|C` launches a temporary instance, runs it from user-data, uploads the JSON to S3 and terminates the instance.

| Config | Instance | OpenCV | Status |
|---|---|---|---|
| A | c8g.xlarge Graviton4 | COOL AMI `ami-01db31139bc5615d8` (OpenCV 5 + KleidiCV) | needs the AWS Marketplace subscription (not yet accepted on this account) |
| B | c8g.xlarge Graviton4 (`{{B_ami}}`, {{B_cpu}}) | opencv-python-headless {{B_cv2}} wheel, KleidiCV in build info: {{B_kleidi}} | measured |
| C | c7i.xlarge x86 (`{{C_ami}}`, {{C_cpu}}) | opencv-python-headless {{C_cv2}} wheel, KleidiCV: {{C_kleidi}} | measured |

## Results (B vs C, same 4 vCPUs, same frames)

| | B Graviton4 | C x86 | B vs C |
|---|---|---|---|
| ms per burst, all threads (mean of 5, sd) | {{B_ms}} ({{B_ms_sd}}) | {{C_ms}} ({{C_ms_sd}}) | {{BC_speedup}} faster |
| ms per burst, 1 thread / 4 threads | {{B_t1}} / {{B_t4}} | {{C_t1}} / {{C_t4}} | |
| frames/s, 4 worker processes | {{B_fps}} | {{C_fps}} | {{BC_tp_ratio}} |
| cameras per instance at a 10 s cadence | {{B_cams}} | {{C_cams}} | |
| on-demand price per hour (AWS Price List API) | {{B_usd_h}} | {{C_usd_h}} | |
| cost per 1M frames | {{B_usd_1m}} | {{C_usd_1m}} | {{BC_cost_saving}} cheaper |
| ALIKED+LightGlue registration, ms | {{B_aliked_ms}} | {{C_aliked_ms}} | {{BC_aliked_speedup}} |
| DIS optical flow 960×540, ms | {{B_dis_ms}} | {{C_dis_ms}} | {{BC_dis_speedup}} |
| YuNet face + plate redaction, ms | {{B_yunet_ms}} | {{C_yunet_ms}} | |
| ORB registration, ms | {{B_orb_ms}} | {{C_orb_ms}} | |
| output hash (stage readings, 1 mm) | `{{B_hash}}` | `{{C_hash}}` | {{BC_equal}} |

Per-stage p50 on Graviton4: registration {{B_st_register}} ms, redaction {{B_st_redact}} ms, E2 temporal {{B_st_E2_temporal}} ms, surface motion {{B_st_surface_motion}} ms, warp {{B_st_warp}} ms, quality gate {{B_st_quality}} ms. Registration and redaction are about two thirds of the time; both are candidates for running on every Nth burst when the camera is steady.

## What this means for the deployment

One c8g.xlarge costs {{B_usd_month}} a month on demand. Two capacity figures, both estimates. Upper bound from this benchmark (measurement only, one process per vCPU): about {{B_cams_10s}} cameras at a 10-second cadence (the default fast cadence for real camera sites) or {{B_cams_300s}} at a 5-minute cadence. Conservative, from the OpenCV pipeline time measured on the deployed host ({{cloud_cycle_ms}} ms per cycle, CloudWatch `StageMs`, which includes the occasional ALIKED+LightGlue call but not database writes, voice or drafting; the agent suite's full-cycle median is {{ag_ms_cycle}} ms on a laptop): about {{cloud_cams_10s}} cameras at 10 s or {{cloud_cams_300s}} at 5 minutes, roughly {{cloud_usd_cam_month_10s}} or {{cloud_usd_cam_month_300s}} of compute per camera per month. Both figures assume one vision worker per vCPU; the current deployment runs a single API worker process, so its real capacity is lower until vision runs in a worker pool (storage, transfer and SMS not included). The expensive OpenCV 5 pieces (ALIKED+LightGlue, DIS flow) gain the most on Graviton4, and the agent only calls ALIKED+LightGlue when ORB fails.

## COOL (config A)

The COOL Graviton4 AMI is in the template (`USE_COOL_AMI=true make deploy`) and in the benchmark (`scripts/bench/cloud_bench.sh A`, which uses the AMI's own OpenCV build through system site-packages and never installs the pip wheel). Launching it needs the account owner to accept the Marketplace terms (7-day free trial). Until that run exists this document makes no COOL performance claim. When it runs, `bench/results/A-cool-c8g.xlarge.json` appears and `make check-numbers` regenerates this page with the A column, the AMI id and the build information as proof.
