"""Baseline B2: a vision-language model reads the staff gauge on every real frame.

Same frames and truth as eval/run_real_physical.py (USGS HIVIS, Hancock and
Moravia, in-range frames). The model gets the frame and the gauge range and
must answer with the JSON schema the agent uses. Reports MAE, coverage,
latency and estimated cost per frame next to the OpenCV pipeline.

    cd backend && NADISAATHI_AWS_ENABLED=1 uv run python ../eval/run_vlm_baseline.py [--limit 40]

If Bedrock is not available on the account, the script writes the result
file with status "unavailable" and the error, and claims nothing.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
os.environ.setdefault("NADISAATHI_AWS_ENABLED", "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from jalrekha.agent import cloud  # noqa: E402

DATA = ROOT / "datasets" / "usgs_hivis_stage"
FT = 0.3048
OUT = ROOT / "eval" / "results" / "vlm_baseline.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="max frames per site (0 = all in-range frames)")
    ap.add_argument("--model", default=os.environ.get("NADISAATHI_BEDROCK_MODEL", "us.amazon.nova-lite-v1:0"))
    a = ap.parse_args()
    phys = json.loads((ROOT / "eval" / "results" / "stage_real_physical.json").read_text())
    vlm = cloud.BedrockVLM(a.model)
    labels = {r["timestamp_utc"]: r for r in csv.DictReader((DATA / "labels.csv").open())}
    rows, errors = [], []
    t0 = time.perf_counter()
    for sid, site in phys["sites"].items():
        if not site.get("in_scope"):
            continue
        lo, hi = site["gauge_span_m"]
        frames = [f for f in site["frames"] if lo - 0.05 <= f["truth_m"] <= hi + 0.05]
        if a.limit:
            frames = frames[:: max(1, len(frames) // a.limit)][: a.limit]
        for f in frames:
            lab = labels.get(f["t"])
            if lab is None:
                continue
            img = cv2.imread(str(DATA / lab["image_path"]))
            ok, jpeg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
            try:
                ans = vlm.ask_gauge(jpeg.tobytes(), lo, hi)
            except cloud.VLMUnavailable as exc:
                errors.append(str(exc))
                if len(errors) >= 3 and not rows:
                    break
                continue
            parsed = cloud.parse_gauge_answer(ans.raw_text)
            rows.append({"site": sid, "t": f["t"], "truth_m": f["truth_m"], "vlm_m": parsed.get("stage_m"), "cv_m": f.get("full"),
                         "parsed_ok": parsed["ok"], "latency_ms": round(ans.latency_ms, 1), "cost_usd_est": ans.cost_usd_est})
        if len(errors) >= 3 and not rows:
            break
    res: dict = {"meta": {"label": "REAL USGS HIVIS frames (same in-range frames as stage_real_physical.json)", "model": vlm.name,
                          "generated_by": "eval/run_vlm_baseline.py", "generated_at": datetime.now(timezone.utc).isoformat(),
                          "wall_s": round(time.perf_counter() - t0, 1)}}
    if not rows:
        res.update(status="unavailable", error=errors[0] if errors else "no frames", frames=0)
    else:
        e_v = np.array([abs(r["vlm_m"] - r["truth_m"]) for r in rows if r["vlm_m"] is not None])
        e_c = np.array([abs(r["cv_m"] - r["truth_m"]) for r in rows if r["cv_m"] is not None])
        res.update(status="ok", frames=len(rows),
                   vlm={"coverage": round(len(e_v) / len(rows), 4), "mae_cm": round(float(e_v.mean()) * 100, 2) if len(e_v) else None,
                        "median_abs_cm": round(float(np.median(e_v)) * 100, 2) if len(e_v) else None,
                        "latency_ms_p50": round(float(np.median([r["latency_ms"] for r in rows])), 1),
                        "cost_usd_per_1k_frames_est": round(1000 * float(np.mean([r["cost_usd_est"] for r in rows])), 4)},
                   opencv_same_frames={"mae_cm": round(float(e_c.mean()) * 100, 2) if len(e_c) else None},
                   rows=rows, errors=errors[:5])
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
