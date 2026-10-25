"""Stage accuracy on REAL held-out frames: USGS HIVIS staff-gauge cameras.

Usage (from repo root):
    uv run --project backend python eval/run_real.py

Protocol in eval/real_sites.json. Writes eval/results/stage_real.json.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
from collections import defaultdict
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
OUT = ROOT / "eval" / "results" / "stage_real.json"
FT = 0.3048

METHODS = {
    "full": dict(),
    "E1_only": dict(estimators=("E1_edge",)),
    "E3_only": dict(estimators=("E3_colour",)),
    "full_no_registration": dict(use_registration=False),
    "B1_naive_max_edge": dict(estimators=("B1_naive",)),
}


def unit_calib(strip, half_w, size) -> GaugeCalibration:
    """Provisional calibration: strip top = 1.0, bottom = 0.0 (unitless position)."""
    return GaugeCalibration(
        marks=[GaugeMark(strip[0][0], strip[0][1], 1.0), GaugeMark(strip[1][0], strip[1][1], 0.0)],
        strip_half_width_px=half_w,
        margin_frac=0.0,
        reference_size=size,
    )


def frame_y_to_unit(cal: GaugeCalibration, y: float) -> float:
    a, _ = cal.strip_endpoints()
    u = cal.axis_unit
    return cal.strip_row_to_stage((y - a[1]) / u[1])


def b0_unit(img, cal, repaired: bool) -> float | None:
    from PIL import Image, ImageFilter
    import tempfile, os

    h, w = img.shape[:2]
    s = 512 / max(h, w)
    small = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    if not repaired:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            cv2.imwrite(tmp.name, small)
            res = analyze_frames([tmp.name], 1.0)
        os.unlink(tmp.name)
        y = res.frames[0].waterline_y
        return None if y is None or y <= 0 else frame_y_to_unit(cal, y / s)
    edges = np.asarray(Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)).filter(ImageFilter.FIND_EDGES), float)
    d = edges.sum(axis=1) / (edges.shape[1] * 255.0)
    d[:3] = 0
    d[-3:] = 0
    return None if d.max() <= 0.02 else frame_y_to_unit(cal, float(np.argmax(d)) / s)


def theil_sen(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    if len(x) < 2:
        return float(np.median(y)) if len(y) else 0.0, 0.0
    i, j = np.triu_indices(len(x), 1)
    dx = x[j] - x[i]
    ok = np.abs(dx) > 1e-6
    b = float(np.median((y[j] - y[i])[ok] / dx[ok])) if ok.any() else 0.0
    a = float(np.median(y - b * x))
    return a, b


def stats(errs: list[float], n_total: int) -> dict:
    e = np.array(errs, float)
    if len(e) == 0:
        return {"n": n_total, "coverage": 0.0}
    return {
        "n": n_total,
        "coverage": round(len(e) / n_total, 4),
        "mae_cm": round(float(np.abs(e).mean()) * 100, 2),
        "mae_ci95_cm": _boot_ci(e, 2000, 7),
        "median_abs_cm": round(float(np.median(np.abs(e))) * 100, 2),
        "p90_abs_cm": round(float(np.percentile(np.abs(e), 90)) * 100, 2),
        "within_15cm": round(float((np.abs(e) <= 0.15).mean()), 4),
        "bias_cm": round(float(e.mean()) * 100, 2),
    }


def main() -> int:
    cfg = json.loads(SITES.read_text())
    rows = list(csv.DictReader((DATA / "labels.csv").open()))
    by = defaultdict(list)
    for r in rows:
        by[r["site_id"]].append(r)
    t0 = time.time()
    results: dict = {}
    per_frame: list[dict] = []
    for site_id, scfg in cfg["sites"].items():
        rr = sorted(by.get(site_id, []), key=lambda r: r["timestamp_utc"])
        if not scfg.get("in_scope"):
            results[site_id] = {"in_scope": False, "scene": scfg["scene"], "n_frames": len(rr)}
            continue
        imgs = [cv2.imread(str(DATA / r["image_path"])) for r in rr]
        h, w = imgs[0].shape[:2]
        cal = unit_calib(scfg["strip"], scfg["strip_half_width_px"], (w, h))
        ref = imgs[0]
        n_cal = max(3, int(round(len(rr) * cfg["calib_frac"])))
        truth = np.array([float(r["stage_m"]) for r in rr])
        outputs: dict[str, list] = {m: [] for m in [*METHODS, "B0_base_repo_firewall", "B0r_base_repo_border_fixed"]}
        usable: list[bool] = []
        meta: list[dict] = []
        for img in imgs:
            for m, kw in METHODS.items():
                res = measure([img], cal, ref, MeasureOptions(redact=False, draw_overlay=False, surface_motion=False, **kw))
                outputs[m].append(res.reading.stage_m)
                if m == "full":
                    usable.append(res.usable)
                    meta.append({"reg": res.registration.method, "q": res.quality.reasons, "agree": res.reading.agree})
            outputs["B0_base_repo_firewall"].append(b0_unit(img, cal, False))
            outputs["B0r_base_repo_border_fixed"].append(b0_unit(img, cal, True))
        site_res: dict = {
            "in_scope": True,
            "scene": scfg["scene"],
            "n_frames": len(rr),
            "n_calibration": n_cal,
            "n_test": len(rr) - n_cal,
            "stage_range_m": [round(float(truth.min()), 3), round(float(truth.max()), 3)],
            "test_stage_range_m": [round(float(truth[n_cal:].min()), 3), round(float(truth[n_cal:].max()), 3)],
            "methods": {},
        }
        for m, vals in outputs.items():
            x = np.array([np.nan if v is None else v for v in vals], float)
            cal_ok = ~np.isnan(x[:n_cal])
            a, b = theil_sen(x[:n_cal][cal_ok], truth[:n_cal][cal_ok])
            pred = a + b * x
            errs = [float(pred[i] - truth[i]) for i in range(n_cal, len(rr)) if not np.isnan(x[i])]
            entry = {"fit": {"a": round(a, 4), "b": round(b, 4)}, "test": stats(errs, len(rr) - n_cal)}
            if m == "full":
                ue = [float(pred[i] - truth[i]) for i in range(n_cal, len(rr)) if not np.isnan(x[i]) and usable[i]]
                entry["test_usable_only"] = stats(ue, len(rr) - n_cal)
                entry["usable_rate_test"] = round(sum(usable[n_cal:]) / max(1, len(rr) - n_cal), 4)
                for i in range(len(rr)):
                    per_frame.append({
                        "site": site_id, "t": rr[i]["timestamp_utc"], "split": "cal" if i < n_cal else "test",
                        "truth_m": round(float(truth[i]), 4),
                        "pred_m": None if np.isnan(x[i]) else round(float(pred[i]), 4),
                        "usable": usable[i], **meta[i],
                    })
            site_res["methods"][m] = entry
        # Constant baseline: the median calibration-period stage (no vision at all).
        c = float(np.median(truth[:n_cal]))
        site_res["methods"]["B_const_calibration_median"] = {"test": stats([c - t for t in truth[n_cal:]], len(rr) - n_cal)}
        if "numeral_marks_ft" in scfg:
            marks = [GaugeMark(x, y, n * FT) for x, y, n in scfg["numeral_marks_ft"]]
            gcal = GaugeCalibration(marks=marks, strip_half_width_px=scfg["strip_half_width_px"], margin_frac=0.08, reference_size=(w, h))
            raw = []
            for img in imgs:
                res = measure([img], gcal, ref, MeasureOptions(redact=False, draw_overlay=False, surface_motion=False))
                raw.append(np.nan if res.reading.stage_m is None else res.reading.stage_m)
            raw = np.array(raw, float)
            ok = ~np.isnan(raw[:n_cal])
            offset = float(np.median(truth[:n_cal][ok] - raw[:n_cal][ok])) if ok.any() else 0.0
            errs = [float(raw[i] + offset - truth[i]) for i in range(n_cal, len(rr)) if not np.isnan(raw[i])]
            site_res["methods"]["full_numeral_calibration"] = {
                "fit": {"datum_offset_m": round(offset, 4)},
                "note": scfg["numeral_note"],
                "test": stats(errs, len(rr) - n_cal),
            }
        results[site_id] = site_res
        print(site_id, {m: v["test"].get("mae_cm") for m, v in site_res["methods"].items()})
    pooled: dict = {}
    for m in [*METHODS, "B0_base_repo_firewall", "B0r_base_repo_border_fixed", "B_const_calibration_median"]:
        errs = []
        for row in per_frame if m == "full" else []:
            pass
        site_maes = [r["methods"][m]["test"].get("mae_cm") for r in results.values() if r.get("in_scope")]
        pooled[m] = {"mean_site_mae_cm": round(float(np.mean([v for v in site_maes if v is not None])), 2) if any(v is not None for v in site_maes) else None,
                     "sites_with_readings": sum(v is not None for v in site_maes)}
    OUT.write_text(json.dumps({
        "meta": {
            "dataset": cfg["dataset"],
            "protocol": cfg["protocol"],
            "label": "REAL held-out frames (later 75% of each site's time series)",
            "config_sha256": config_sha(),
            "sites_config_sha256": hashlib.sha256(SITES.read_bytes()).hexdigest(),
            "opencv_version": cv2.__version__,
            "generated_by": "eval/run_real.py",
            "wall_s": round(time.time() - t0, 1),
        },
        "pooled": pooled,
        "sites": results,
        "frames": per_frame,
    }, indent=1))
    print("pooled", pooled)
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
