"""Stage accuracy on REAL USGS HIVIS staff-gauge cameras with physical calibration.

Protocol (eval/real_sites.json -> physical_protocol): the printed numerals are
clicked once on one reference frame; stage = numeral x 0.3048 m. Nothing is
fitted to gauge readings, so every frame at the site is held out. Estimator
code and thresholds are frozen from the synthetic train split.

    cd backend && uv run python ../eval/run_real_physical.py

Writes eval/results/stage_real_physical.json.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "eval"))

from run_stage import _boot_ci, config_sha  # noqa: E402
from jalrekha.services.deterministic_firewall import analyze_frames  # noqa: E402
from jalrekha.vision.gauge import GaugeCalibration, GaugeMark  # noqa: E402
from jalrekha.vision.pipeline import MeasureOptions, measure  # noqa: E402

DATA = ROOT / "datasets" / "usgs_hivis_stage"
SITES = ROOT / "eval" / "real_sites.json"
OUT = ROOT / "eval" / "results" / "stage_real_physical.json"
FT = 0.3048
RANGE_TOL = 0.05
CLAMP_TOL = 0.10

METHODS = {
    "full": dict(estimators=("E1_edge", "E2_temporal", "E3_colour")),
    "full_no_registration": dict(estimators=("E1_edge", "E2_temporal", "E3_colour"), use_registration=False),
    "E1_only": dict(estimators=("E1_edge",)),
    "E3_only": dict(estimators=("E3_colour",)),
    "B1_naive_max_edge": dict(estimators=("B1_naive",)),
}


def project_y(cal: GaugeCalibration, x: float, y: float) -> float:
    a, _ = cal.strip_endpoints()
    row = float(np.dot(np.array([x, y]) - a, cal.axis_unit))
    return cal.strip_row_to_stage(row)


def b0_stage(img: np.ndarray, cal: GaugeCalibration, cache_dir: Path) -> float | None:
    """Base-repo PIL heuristic: its waterline row, mapped through the same physical calibration."""
    h, w = img.shape[:2]
    s = 512 / max(h, w)
    small = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    p = cache_dir / "b0.png"
    cv2.imwrite(str(p), small)
    res = analyze_frames([str(p)], 1.0)
    y = res.frames[0].waterline_y if res.frames else None
    if y is None or y <= 0:
        return None
    gx = (cal.top[0] + cal.bottom[0]) / 2
    return project_y(cal, gx, y / s)


def score(preds: list[tuple[float, float | None]], lo: float, hi: float) -> dict:
    inr = [(t, v) for t, v in preds if lo - RANGE_TOL <= t <= hi + RANGE_TOL]
    out = [(t, v) for t, v in preds if not (lo - RANGE_TOL <= t <= hi + RANGE_TOL)]
    errs = np.array([v - t for t, v in inr if v is not None])
    e = np.abs(errs)
    res = {"in_range_frames": len(inr), "coverage": round(len(errs) / max(len(inr), 1), 4)}
    if len(e):
        res.update({
            "mae_cm": round(float(e.mean()) * 100, 2), "mae_ci95_cm": _boot_ci(e, 2000, 7),
            "median_abs_cm": round(float(np.median(e)) * 100, 2), "p90_abs_cm": round(float(np.percentile(e, 90)) * 100, 2),
            "bias_cm": round(float(errs.mean()) * 100, 2), "within_5cm": round(float((e <= 0.05).mean()), 4),
            "within_10cm": round(float((e <= 0.10).mean()), 4), "within_15cm": round(float((e <= 0.15).mean()), 4),
        })
    ok_out = 0
    for t, v in out:
        edge = lo if t < lo else hi
        ok_out += int(v is not None and abs(v - edge) <= CLAMP_TOL)
    res["out_of_range_frames"] = len(out)
    res["out_of_range_clamped_ok"] = ok_out
    return res


def main() -> int:
    cfg = json.loads(SITES.read_text())
    labels = list(csv.DictReader((DATA / "labels.csv").open()))
    t0 = time.time()
    tmp = ROOT / "eval" / "results" / ".tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    sites_out, pooled = {}, {m: [] for m in [*METHODS, "B0_base_repo_firewall"]}
    for sid, sc in cfg["sites"].items():
        if "numeral_marks_ft" not in sc:
            sites_out[sid] = {"in_scope": False, "reason": sc.get("physical_scope_note") or sc.get("scene")}
            continue
        rows = sorted([r for r in labels if r["site_id"] == sid], key=lambda r: r["timestamp_utc"])
        ref_row = next(r for r in rows if sc["numeral_reference"] in r["image_path"])
        ref = cv2.imread(str(DATA / ref_row["image_path"]))
        half = sc.get("numeral_half_width_px", sc.get("strip_half_width_px", 10))
        cal = GaugeCalibration(marks=[GaugeMark(x, y, n * FT) for x, y, n in sc["numeral_marks_ft"]],
                               strip_half_width_px=half, reference_size=(ref.shape[1], ref.shape[0]))
        lo, hi = cal.stage_range
        per_method: dict[str, list] = {m: [] for m in pooled}
        frames_detail = []
        for r in rows:
            img = cv2.imread(str(DATA / r["image_path"]))
            truth = float(r["stage_m"])
            row = {"t": r["timestamp_utc"], "truth_m": truth}
            for m, kw in METHODS.items():
                meas = measure([img], cal, ref, MeasureOptions(redact=False, draw_overlay=False, surface_motion=False, **kw))
                v = meas.reading.stage_m
                per_method[m].append((truth, v))
                row[m] = None if v is None else round(v, 4)
                if m == "full":
                    row["registration"] = meas.registration.method
                    row["quality_ok"] = meas.quality.ok
            v0 = b0_stage(img, cal, tmp)
            per_method["B0_base_repo_firewall"].append((truth, v0))
            row["B0_base_repo_firewall"] = None if v0 is None else round(v0, 4)
            frames_detail.append(row)
        site_res = {m: score(p, lo, hi) for m, p in per_method.items()}
        for m in pooled:
            pooled[m] += [(t, v) for t, v in per_method[m] if lo - RANGE_TOL <= t <= hi + RANGE_TOL]
        # Failure cases: the five worst in-range frames of the full method.
        worst = sorted([d for d in frames_detail if d["full"] is not None and lo - RANGE_TOL <= d["truth_m"] <= hi + RANGE_TOL],
                       key=lambda d: -abs(d["full"] - d["truth_m"]))[:5]
        sites_out[sid] = {"in_scope": True, "scene": sc["scene"], "frames": len(rows), "gauge_span_m": [round(lo, 3), round(hi, 3)],
                          "calibration": {"marks": sc["numeral_marks_ft"], "reference": sc["numeral_reference"], "fitted_parameters": 0},
                          "methods": site_res, "worst_frames_full": worst, "frames": frames_detail}
        print(sid, {m: (v.get("mae_cm"), v.get("within_10cm")) for m, v in site_res.items()}, flush=True)
    pooled_res = {}
    for m, p in pooled.items():
        errs = np.array([v - t for t, v in p if v is not None])
        e = np.abs(errs)
        pooled_res[m] = {"n": int(len(p)), "coverage": round(len(e) / max(len(p), 1), 4)}
        if len(e):
            pooled_res[m].update({"mae_cm": round(float(e.mean()) * 100, 2), "mae_ci95_cm": _boot_ci(e, 2000, 7),
                                  "median_abs_cm": round(float(np.median(e)) * 100, 2),
                                  "within_10cm": round(float((e <= 0.10).mean()), 4), "bias_cm": round(float(errs.mean()) * 100, 2)})
    result = {
        "meta": {"label": "REAL USGS HIVIS staff-gauge camera frames; physical numeral calibration, 0 fitted parameters, every frame held out",
                 "dataset": "datasets/usgs_hivis_stage (US public domain)", "protocol": cfg["physical_protocol"],
                 "config_sha256": config_sha(), "sites_config_sha256": hashlib.sha256(SITES.read_bytes()).hexdigest(),
                 "opencv_version": cv2.__version__, "generated_by": "eval/run_real_physical.py", "wall_s": round(time.time() - t0, 1),
                 "note": "Single hourly snapshots: the temporal estimator E2 needs a burst and abstains here."},
        "pooled_in_range": pooled_res,
        "sites": sites_out,
    }
    OUT.write_text(json.dumps(result, indent=1))
    print(json.dumps(pooled_res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
