# Live traces from the AWS deployment (REAL CAMERA REPLAY)

Run `run_088eeb6d61` on the deployed stack: 88 archived USGS HIVIS frames from the Hancock staff-gauge camera, measured by the OpenCV pipeline on Graviton4, with the agent calling Claude for a second opinion whenever its estimators could not confirm each other. Warning and danger marks on this gauge are illustrative. Exported by `scripts/export_live_traces.py` from the public API; every cycle is also an event in CloudWatch Logs and an evidence file in S3.

| Cycle | Camera | Truth | Second opinion | Model | Latency | Cost | Result |
|---|---|---|---|---|---|---|---|
| 1 | 2.95 m | 2.835 m | 2.8 m | claude:claude-opus-5-5 | 6.1 s | $0.0106 | held for a person |
| 2 | 2.95 m | 2.835 m | 3.0 m | claude:claude-opus-5-5 | 4.9 s | $0.0087 | confirmed |
| 12 | 2.94 m | 2.822 m | abstained | claude:claude-opus-5-5 | 3.2 s | $0.0072 | held for a person |
| 13 | 2.94 m | 2.822 m | 3.04 m | claude:claude-opus-5-5 | 3.6 s | $0.0075 | confirmed |
| 23 | 2.94 m | 2.835 m | 3.0 m | claude:claude-opus-5-5 | 3.2 s | $0.0072 | confirmed |
| 24 | 2.94 m | 2.832 m | 3.03 m | claude:claude-opus-5-5 | 1.7 s | $0.0038 | confirmed |
| 34 | 5.25 m | 5.313 m | 5.43 m | claude:claude-opus-5-5 | 1.6 s | $0.0038 | held for a person |
| 35 | 4.98 m | 5.215 m | 5.3 m | claude:claude-opus-5-5 | 6.0 s | $0.0117 | held for a person |
| 36 | 5.23 m | 5.16 m | 5.34 m | claude:claude-opus-5-5 | 4.1 s | $0.0087 | confirmed |
| 37 | 5.55 m | 5.224 m | 5.38 m | claude:claude-opus-5-5 | 4.2 s | $0.0087 | held for a person |
| 38 | 5.55 m | 5.367 m | 5.52 m | claude:claude-opus-5-5 | 4.5 s | $0.0083 | confirmed |
| 39 | 4.84 m | 5.511 m | 5.67 m | claude:claude-opus-5-5 | 5.2 s | $0.0108 | held for a person |
| 40 | 5.54 m | 5.489 m | 5.53 m | claude:claude-opus-5-5 | 3.2 s | $0.0064 | confirmed |
| 41 | 5.27 m | 5.374 m | 5.3 m | claude:claude-opus-5-5 | 4.7 s | $0.0103 | confirmed |
| 42 | 5.02 m | 5.16 m | 5.13 m | claude:claude-opus-5-5 | 5.0 s | $0.0090 | confirmed |
| 43 | 4.94 m | 4.932 m | 4.82 m | claude:claude-opus-5-5 | 3.9 s | $0.0073 | confirmed |
| 45 | 3.83 m | 3.856 m | 3.9 m | claude:claude-opus-5-5 | 4.3 s | $0.0081 | confirmed |
| 52 | 6.20 m | 3.691 m | 3.9 m | claude:claude-opus-5-5 | 1.4 s | $0.0038 | held for a person |
| 53 | 3.73 m | 3.673 m | 3.83 m | claude:claude-opus-5-5 | 4.2 s | $0.0083 | confirmed |
| 54 | 3.70 m | 3.651 m | 3.78 m | claude:claude-opus-5-5 | 3.9 s | $0.0085 | confirmed |
| 57 | 3.46 m | 3.441 m | 3.44 m | claude:claude-opus-5-5 | 4.4 s | $0.0087 | confirmed |
| 67 | 3.27 m | 3.264 m | 3.23 m | claude:claude-opus-5-5 | 3.7 s | $0.0074 | confirmed |
| 68 | 3.23 m | 3.261 m | 3.11 m | claude:claude-opus-5-5 | 4.1 s | $0.0083 | confirmed |
| 78 | 3.18 m | 3.167 m | 3.17 m | claude:claude-opus-5-5 | 3.8 s | $0.0077 | confirmed |
| 79 | 3.18 m | 3.164 m | 3.08 m | claude:claude-opus-5-5 | 4.0 s | $0.0083 | confirmed |

25 second opinions in 88 cycles.
