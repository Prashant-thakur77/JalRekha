"""Stage-accuracy evaluation on the synthetic held-out scenes.

Usage (from repo root):
    uv run --project backend python eval/run_stage.py [--split test|train] [--quick]

Writes eval/results/stage_synth_<split>.json and eval/results/sweep_synth.json.
Every number in the README's accuracy tables is generated from these files by
scripts/sync_numbers.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from jalrekha.services.deterministic_firewall import analyze_frames  # noqa: E402
from jalrekha.vision import synth  # noqa: E402
from jalrekha.vision.gauge import GaugeCalibration  # noqa: E402
from jalrekha.vision.pipeline import MeasureOptions, measure  # noqa: E402

CONFIG_PATH = ROOT / "eval" / "config.frozen.json"
RESULTS = ROOT / "eval" / "results"

METHOD_OPTS = {
    "B1_naive_max_edge": dict(estimators=("B1_naive",)),
    "E1_only": dict(estimators=("E1_edge",)),
    "E2_only": dict(estimators=("E2_temporal",)),
    "E3_only": dict(estimators=("E3_colour",)),
    "full_no_registration": dict(use_registration=False),
    "full": dict(),
}


def config_sha() -> str:
    return hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest()


def _frame_y_to_stage(cal: GaugeCalibration, y: float) -> float:
    a, _ = cal.strip_endpoints()
    u = cal.axis_unit
    t = (y - a[1]) / u[1] if abs(u[1]) > 1e-6 else 0.0
    return cal.strip_row_to_stage(t)


def run_b0(frame: np.ndarray, cal: GaugeCalibration, y_offset: int = 0) -> tuple[float | None, float]:
    """Base-repo PIL firewall exactly as the node used it: frame downsized to
    512 px max side, whole-frame strongest-edge row. Given OUR gauge calibration
    to convert its row to metres, which is generous to the baseline."""
    t0 = time.perf_counter()
    h, w = frame.shape[:2]
    s = 512 / max(h, w)
    small = cv2.resize(frame, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        cv2.imwrite(tmp.name, small)
        res = analyze_frames([tmp.name], 0.5)
    os.unlink(tmp.name)
    ms = (time.perf_counter() - t0) * 1000
    y = res.frames[0].waterline_y if res.frames else -1
    if y is None or y <= 0:
        return None, ms
    return _frame_y_to_stage(cal, y / s + y_offset), ms


def run_b0r(frame: np.ndarray, cal: GaugeCalibration) -> tuple[float | None, float]:
    """B0r: the base-repo algorithm with its border artefact repaired.

    PIL FIND_EDGES leaves a full-strength edge on the outermost pixel rows, so
    the unmodified firewall (``_row_edge_density`` + argmax) picks row 0 on
    almost every frame. B0r runs the identical computation (same 512 px
    downscale, same FIND_EDGES, same 0.02 density floor) but ignores the 3
    outermost rows. Reported alongside B0 so we beat a fair version too."""
    from PIL import Image, ImageFilter

    t0 = time.perf_counter()
    h, w = frame.shape[:2]
    s = 512 / max(h, w)
    small = cv2.resize(frame, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    gray = Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
    edges = np.asarray(gray.filter(ImageFilter.FIND_EDGES), dtype=np.float64)
    density = edges.sum(axis=1) / (edges.shape[1] * 255.0)
    density[:3] = 0.0
    density[-3:] = 0.0
    ms = (time.perf_counter() - t0) * 1000
    if density.max() <= 0.02:
        return None, ms
    return _frame_y_to_stage(cal, float(np.argmax(density)) / s), ms


def eval_case(args: tuple) -> list[dict]:
    seed, cond_name, cond, frac, cfg = args
    cv2.setNumThreads(1)
    site = synth.make_site(seed)
    cal = site.calibration()
    ref = synth.reference_frame(site)
    truth = site.gauge_len_m * frac
    frames = synth.render_burst(
        site,
        truth,
        n=cfg["burst_frames"],
        dt=cfg["burst_dt_s"],
        deg=synth.Degradation(**cond),
        rng=np.random.default_rng(seed * 7919 + int(frac * 1000) + hash(cond_name) % 997),
    )
    rows = []
    stage, ms = run_b0(frames[-1], cal)
    rows.append(_row(seed, cond_name, frac, truth, "B0_base_repo_firewall", stage, ms, None, None))
    stage, ms = run_b0r(frames[-1], cal)
    rows.append(_row(seed, cond_name, frac, truth, "B0r_base_repo_border_fixed", stage, ms, None, None))
    for method, kw in METHOD_OPTS.items():
        opts = MeasureOptions(redact=False, draw_overlay=False, surface_motion=False, burst_dt_s=cfg["burst_dt_s"], **kw)
        m = measure(frames, cal, ref, opts)
        rows.append(
            _row(
                seed, cond_name, frac, truth, method, m.reading.stage_m, m.timings_ms["total"], m.usable,
                {"q": m.quality.reasons, "reg": m.registration.method, "agree": m.reading.agree, "sigma": m.reading.sigma_m},
            )
        )
    return rows


def _row(seed, cond, frac, truth, method, stage, ms, usable, extra) -> dict:
    return {
        "seed": seed,
        "condition": cond,
        "frac": frac,
        "truth_m": round(truth, 4),
        "method": method,
        "stage_m": None if stage is None else round(float(stage), 4),
        "err_m": None if stage is None else round(float(stage) - truth, 4),
        "ms": round(ms, 2),
        "usable": usable,
        "extra": extra,
    }


def _boot_ci(errs: np.ndarray, n: int, seed: int) -> list[float]:
    if len(errs) < 2:
        return [float("nan"), float("nan")]
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(errs), (n, len(errs)))
    means = np.abs(errs[idx]).mean(axis=1)
    return [round(float(np.percentile(means, 2.5)) * 100, 2), round(float(np.percentile(means, 97.5)) * 100, 2)]


def summarise(rows: list[dict], cfg: dict) -> dict:
    out: dict = {}
    methods = sorted({r["method"] for r in rows})
    conds = sorted({r["condition"] for r in rows})
    for m in methods:
        mr = [r for r in rows if r["method"] == m]
        out[m] = {"overall": _stats(mr, cfg), "by_condition": {c: _stats([r for r in mr if r["condition"] == c], cfg) for c in conds}}
        usable = [r for r in mr if r["usable"]]
        if usable and mr[0]["usable"] is not None:
            out[m]["usable_only"] = _stats(usable, cfg)
            out[m]["usable_rate"] = round(len(usable) / len(mr), 4)
    return out


def _stats(rows: list[dict], cfg: dict) -> dict:
    errs = np.array([r["err_m"] for r in rows if r["err_m"] is not None], dtype=float)
    n = len(rows)
    if len(errs) == 0:
        return {"n": n, "coverage": 0.0}
    return {
        "n": n,
        "coverage": round(len(errs) / n, 4),
        "mae_cm": round(float(np.abs(errs).mean()) * 100, 2),
        "mae_ci95_cm": _boot_ci(errs, cfg["bootstrap"]["n"], cfg["bootstrap"]["seed"]),
        "median_abs_cm": round(float(np.median(np.abs(errs))) * 100, 2),
        "p90_abs_cm": round(float(np.percentile(np.abs(errs), 90)) * 100, 2),
        "bias_cm": round(float(errs.mean()) * 100, 2),
        "within_5cm": round(float((np.abs(errs) <= 0.05).mean()), 4),
        "within_10cm": round(float((np.abs(errs) <= 0.10).mean()), 4),
        "ms_p50": round(float(np.median([r["ms"] for r in rows])), 2),
    }


def sweep_case(args: tuple) -> list[dict]:
    seed, kind, level, value, frac, cfg = args
    cv2.setNumThreads(1)
    site = synth.make_site(seed)
    cal = site.calibration()
    ref = synth.reference_frame(site)
    truth = site.gauge_len_m * frac
    deg = synth.Degradation(**{kind: value})
    frames = synth.render_burst(site, truth, n=cfg["burst_frames"], dt=cfg["burst_dt_s"], deg=deg,
                                rng=np.random.default_rng(seed * 31 + int(level * 100) + int(frac * 10)))
    rows = []
    stage, ms = run_b0(frames[-1], cal)
    rows.append({"seed": seed, "kind": kind, "level": level, "method": "B0_base_repo_firewall",
                 "err_m": None if stage is None else stage - truth, "usable": None, "reg": None})
    stage, _ = run_b0r(frames[-1], cal)
    rows.append({"seed": seed, "kind": kind, "level": level, "method": "B0r_base_repo_border_fixed",
                 "err_m": None if stage is None else stage - truth, "usable": None, "reg": None})
    for method, kw in (("full", {}), ("full_orb_only", {"allow_heavy_registration": False})):
        m = measure(frames, cal, ref, MeasureOptions(redact=False, draw_overlay=False, surface_motion=False, **kw))
        rows.append({"seed": seed, "kind": kind, "level": level, "method": method,
                     "err_m": None if m.reading.stage_m is None else m.reading.stage_m - truth,
                     "usable": m.usable, "reg": m.registration.method, "reg_ok": m.registration.ok,
                     "flagged": not m.quality.ok})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test", choices=["test", "train"])
    ap.add_argument("--quick", action="store_true", help="3 seeds, for CI")
    ap.add_argument("--no-sweep", action="store_true")
    ap.add_argument("--workers", type=int, default=min(6, max(1, (os.cpu_count() or 2) - 2)))  # ONNX models ~1 GB per worker
    a = ap.parse_args()
    cfg_all = json.loads(CONFIG_PATH.read_text())
    cfg = {**cfg_all["synthetic"], "bootstrap": cfg_all["bootstrap"]}
    seeds = cfg[f"{a.split}_seeds"][: 3 if a.quick else None]
    jobs = [(s, cn, c, f, cfg) for s in seeds for cn, c in cfg["conditions"].items() for f in cfg["stage_fracs"]]
    t0 = time.time()
    rows: list[dict] = []
    with ProcessPoolExecutor(a.workers) as ex:
        for part in ex.map(eval_case, jobs, chunksize=4):
            rows.extend(part)
    RESULTS.mkdir(parents=True, exist_ok=True)
    meta = {
        "dataset": cfg["label"],
        "split": a.split,
        "seeds": seeds,
        "config_sha256": config_sha(),
        "opencv_version": cv2.__version__,
        "generated_by": "eval/run_stage.py",
        "wall_s": round(time.time() - t0, 1),
        "quick": a.quick,
    }
    out = {"meta": meta, "summary": summarise(rows, cfg), "rows": rows}
    suffix = "_quick" if a.quick else ""
    path = RESULTS / f"stage_synth_{a.split}{suffix}.json"
    path.write_text(json.dumps(out, indent=1))
    print(f"wrote {path} ({len(rows)} rows, {meta['wall_s']} s)")
    for m, s in out["summary"].items():
        o = s["overall"]
        print(f"  {m:24s} MAE {o.get('mae_cm')} cm  CI {o.get('mae_ci95_cm')}  cov {o.get('coverage')}  usable_MAE {s.get('usable_only', {}).get('mae_cm')}")

    if a.split == "test" and not a.no_sweep and not a.quick:
        sw = cfg["sweep"]
        sjobs = [
            (s, k, lv, lv * sw["max"][k], f, cfg)
            for s in sw["seeds"] for k in sw["types"] for lv in sw["levels"] for f in sw["stage_fracs"]
        ]
        srows: list[dict] = []
        with ProcessPoolExecutor(a.workers) as ex:
            for part in ex.map(sweep_case, sjobs, chunksize=4):
                srows.extend(part)
        curves: dict = {}
        for k in sw["types"]:
            for m in ("B0_base_repo_firewall", "B0r_base_repo_border_fixed", "full", "full_orb_only"):
                pts = []
                for lv in sw["levels"]:
                    rr = [r for r in srows if r["kind"] == k and r["level"] == lv and r["method"] == m]
                    errs = np.array([r["err_m"] for r in rr if r["err_m"] is not None], float)
                    pt = {"level": lv, "value": lv * sw["max"][k], "n": len(rr),
                          "mae_cm": round(float(np.abs(errs).mean()) * 100, 2) if len(errs) else None}
                    if not m.startswith("B0"):
                        pt["usable_rate"] = round(sum(1 for r in rr if r["usable"]) / max(1, len(rr)), 3)
                        pt["flagged_rate"] = round(sum(1 for r in rr if r["flagged"]) / max(1, len(rr)), 3)
                        pt["reg_ok_rate"] = round(sum(1 for r in rr if r["reg_ok"]) / max(1, len(rr)), 3)
                        pt["reg_heavy_rate"] = round(sum(1 for r in rr if r["reg"] == "aliked_lightglue") / max(1, len(rr)), 3)
                        ue = np.array([r["err_m"] for r in rr if r["usable"] and r["err_m"] is not None], float)
                        pt["usable_mae_cm"] = round(float(np.abs(ue).mean()) * 100, 2) if len(ue) else None
                    pts.append(pt)
                curves.setdefault(k, {})[m] = pts
        spath = RESULTS / "sweep_synth.json"
        spath.write_text(json.dumps({"meta": {**meta, "kind": "robustness_sweep"}, "curves": curves}, indent=1))
        print(f"wrote {spath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
