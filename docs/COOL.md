# OpenCV 5 on AWS Graviton: benchmark and COOL status

Numbers generated 2026-10-26 09:56 UTC from `bench/results/*.json`.

The core workload is the JalRekha measurement on a 5-frame camera burst: quality gate, ORB registration, burst alignment, gauge strip, three waterline estimators (Scharr edges, DIS optical flow, Lab colour step), fusion, DIS surface motion, YuNet face/plate redaction and the overlay. It is what every agent cycle runs (`backend/src/jalrekha/vision/pipeline.py`).

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
| B | c8g.xlarge Graviton4 (`ami-09a93d801db0bafae`, Neoverse-V2) | opencv-python-headless 5.0.0 wheel, KleidiCV in build info: yes | measured |
| C | c7i.xlarge x86 (`ami-0d6dd9e8265d48906`, Intel(R) Xeon(R) Platinum 8488C) | opencv-python-headless 5.0.0 wheel, KleidiCV: no | measured |

## Results (B vs C, same 4 vCPUs, same frames)

| | B Graviton4 | C x86 | B vs C |
|---|---|---|---|
| ms per burst, all threads (mean of 5, sd) | 87.0 (0.19) | 92.5 (0.40) | 1.06× faster |
| ms per burst, 1 thread / 4 threads | 169.8 / 83.4 | 126.7 / 86.5 | |
| frames/s, 4 worker processes | 99.4 | 93.3 | 1.07× |
| cameras per instance at a 10 s cadence | 198 | 186 | |
| on-demand price per hour (AWS Price List API) | $0.1595 | $0.1785 | |
| cost per 1M frames | $0.446 | $0.531 | 16% cheaper |
| ALIKED+LightGlue registration, ms | 1,223 | 1,799 | 1.47× |
| DIS optical flow 960×540, ms | 16.4 | 25.0 | 1.53× |
| YuNet face + plate redaction, ms | 34.1 | 32.5 | |
| ORB registration, ms | 22.4 | 20.0 | |
| output hash (stage readings, 1 mm) | `c8eabe95ed5a` | `c8eabe95ed5a` | identical |

Per-stage p50 on Graviton4: registration 22.2 ms, redaction 33.9 ms, E2 temporal 7.8 ms, surface motion 10.8 ms, warp 9.6 ms, quality gate 0.7 ms. Registration and redaction are about two thirds of the time; both are candidates for running on every Nth burst when the camera is steady.

## What this means for the deployment

One c8g.xlarge costs $116 a month on demand. Two capacity figures, both estimates. Upper bound from this benchmark (measurement only, one process per vCPU): about 198 cameras at a 10-second cadence (the default fast cadence for real camera sites) or 5,967 at a 5-minute cadence. Conservative, from the OpenCV pipeline time measured on the deployed host (163 ms per cycle, CloudWatch `StageMs`, which includes the occasional ALIKED+LightGlue call but not database writes, voice or drafting; the agent suite's full-cycle median is 266 ms on a laptop): about 246 cameras at 10 s or 7,380 at 5 minutes, roughly $0.47 or $0.02 of compute per camera per month. Both figures assume one vision worker per vCPU; the current deployment runs a single API worker process, so its real capacity is lower until vision runs in a worker pool (storage, transfer and SMS not included). The expensive OpenCV 5 pieces (ALIKED+LightGlue, DIS flow) gain the most on Graviton4, and the agent only calls ALIKED+LightGlue when ORB fails.

## COOL (config A)

The COOL Graviton4 AMI is in the template (`USE_COOL_AMI=true make deploy`) and in the benchmark (`scripts/bench/cloud_bench.sh A`, which uses the AMI's own OpenCV build through system site-packages and never installs the pip wheel). Launching it needs the account owner to accept the Marketplace terms (7-day free trial). Until that run exists this document makes no COOL performance claim. When it runs, `bench/results/A-cool-c8g.xlarge.json` appears and `make check-numbers` regenerates this page with the A column, the AMI id and the build information as proof.
