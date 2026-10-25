"""Lead-time evaluation, v2 rule: the projected-crossing branch needs a statistically significant rise.

v1 (eval/run_leadtime.py) fires the projected branch when the Kalman rate >= R_FAST. With camera-like
noise that rate is noisy and the branch fires often. v2 requires rate - z * rate_sigma >= R_FAST,
rate_sigma being the filter's own rate uncertainty (FilteredStage.rate_sigma_m_per_h). Everything
else (data, thresholds, travel times, windows, events) is v1's frozen config.

z is chosen on TRAIN only (see Z_RULE) and frozen in eval/config.leadtime.v2.frozen.json.
TEST was already seen in v1, so the v2 TEST numbers are a second look at the same test set.

Usage (from repo root):
    cd backend && uv run python ../eval/run_leadtime_v2.py --freeze   # TRAIN only -> eval/config.leadtime.v2.frozen.json
    cd backend && uv run python ../eval/run_leadtime_v2.py            # -> eval/results/leadtime_v2.json + section in eval/LEADTIME.md

Kalman outputs are cached (float64, exact) under ~/.cache/nadisaathi/leadtime_kalman/ so the second
command does not refilter; the cache key covers the data, temporal.py and the noise settings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_leadtime as lt  # noqa: E402

CONFIG_V2 = lt.ROOT / "eval" / "config.leadtime.v2.frozen.json"
Z_GRID = [0.0, 0.5, 1.0, 1.5, 2.0, 3.0]
FA_TARGET = 1.0  # camera-noise upstream false alerts per 30 days per pair (p95, TRAIN)
DET_TOL = 0.05  # TRAIN p95/gauge combined detection may drop at most 5 points vs z = 0
Z_RULE = (f"smallest z in {Z_GRID} with TRAIN p95/camera_noise upstream false alerts <= {FA_TARGET} per 30 days per pair "
          f"and TRAIN p95/gauge combined detection >= detection at z = 0 minus {DET_TOL:.2f}; if none meets both, the "
          "largest z that keeps the detection condition (the false-alert target is then reported as not met).")
CONDS = ["p95/gauge", "p95/camera_noise", "nws_action/gauge", "nws_action/camera_noise"]


# --------------------------------------------------------------------------- Kalman series (cached)
def cache_dir(cfg: dict) -> Path:
    key = json.dumps({"data": lt.sha256(lt.DATA / "pairs.json"), "temporal": lt.sha256(lt.TEMPORAL_FILE),
                      "sg": cfg["sigma_gauge_m"], "sc": cfg["camera_noise_sigma_m"], "seed": cfg["camera_noise_seed"],
                      "h": cfg["history_h"], "grid": [lt.GRID_START.isoformat(), lt.GRID_END.isoformat()]}, sort_keys=True)
    base = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "nadisaathi" / "leadtime_kalman"
    return base / hashlib.sha256(key.encode()).hexdigest()[:16]


def noisy(site: str, cfg: dict) -> np.ndarray:
    z = lt.load_site(site)
    rng = np.random.default_rng(cfg["camera_noise_seed"] + zlib.crc32(site.encode()))
    return z + rng.normal(0.0, cfg["camera_noise_sigma_m"], len(z))


def load_series(cfg: dict, workers: int) -> tuple[dict, bool]:
    pairs = cfg["pairs"]
    sites = sorted({p[k] for p in pairs for k in ("up", "down")})
    tasks = [(s, "gauge", cfg) for s in sites] + [(s, "camera_noise", cfg) for s in sorted({p["up"] for p in pairs})]
    cd = cache_dir(cfg)
    series, todo = {}, []
    for t in tasks:
        f = cd / f"{t[0]}_{t[1]}.npz"
        if f.exists():
            d = np.load(f)
            series[(t[0], t[1])] = {"stage": d["stage"], "rate": d["rate"], "rate_sigma": d["rate_sigma"]}
        else:
            todo.append(t)
    if todo:
        cd.mkdir(parents=True, exist_ok=True)
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for r in ex.map(lt._series_task, todo):
                np.savez(cd / f"{r['site']}_{r['cond']}.npz", stage=r["stage"], rate=r["rate"], rate_sigma=r["rate_sigma"])
                series[(r["site"], r["cond"])] = {k: r[k] for k in ("stage", "rate", "rate_sigma")}
                print(f"  kalman {r['site']} {r['cond']}: {r['kalman_wall_s']} s", flush=True)
    for (s, c), v in series.items():
        v["z"] = noisy(s, cfg) if c == "camera_noise" else lt.load_site(s)
    return series, not todo


# --------------------------------------------------------------------------- evaluation for one condition
def eval_condition(cfg: dict, series: dict, key: str, split: str, z: float) -> dict:
    thr_name, cond = key.split("/")
    th = lt.threshold_sets(cfg)[thr_name]
    span = {"test": (lt.day_index(lt.TEST[0]), lt.day_index(lt.TEST[1], end=True)),
            "train": (lt.day_index(lt.TRAIN[0]), lt.day_index(lt.TRAIN[1], end=True))}[split]
    acc = {"ev": [], "fa_up": 0, "fa_dn": 0, "n_up": 0, "n_dn": 0, "days": 0.0, "pairs": 0}
    per_pair, fails = {}, []
    for p in cfg["pairs"]:
        if p["up"] not in th or p["down"] not in th:
            continue
        (wu, du), (wd, dd) = th[p["up"]], th[p["down"]]
        su, sd = series[(p["up"], cond)], series[(p["down"], "gauge")]
        au = lt.rule(su["stage"], su["rate"], wu, du, z=z, rate_sigma=su["rate_sigma"])
        ad = lt.rule(sd["stage"], sd["rate"], wd, dd, z=z, rate_sigma=sd["rate_sigma"])
        r = lt.evaluate(su["z"], sd["z"], au, ad, wu, wd, cfg["travel_time_train"][p["id"]]["window_h"], span, cfg)
        sm = lt.summarise(r["events"], len(r["up_false"]), r["down_false"], r["up_episodes"], r["down_episodes"], r["days"], cfg["bootstrap"])
        per_pair[p["id"]] = sm
        for e in r["events"]:
            if e["gain_min"] == 0:
                fails.append({"kind": "no_gain", "pair": p["id"], **{k: v for k, v in e.items() if k != "i"}})
        fails += [{"kind": "false_alert_upstream", "pair": p["id"], **fa} for fa in r["up_false"]]
        acc["ev"] += r["events"]
        acc["fa_up"] += len(r["up_false"])
        acc["fa_dn"] += r["down_false"]
        acc["n_up"] += r["up_episodes"]
        acc["n_dn"] += r["down_episodes"]
        acc["days"] += r["days"]
        acc["pairs"] += 1
    pooled = lt.summarise(acc["ev"], acc["fa_up"], acc["fa_dn"], acc["n_up"], acc["n_dn"], acc["days"], cfg["bootstrap"])
    pooled["n_pairs"] = acc["pairs"]
    pooled["note_false_alert_rate"] = "per 30 days per pair (summed false alerts / summed pair-days x 30)"
    return {"pooled": pooled, "per_pair": per_pair, "failure_cases": fails}


# --------------------------------------------------------------------------- freeze (TRAIN only)
def freeze(force: bool, workers: int) -> int:
    if CONFIG_V2.exists() and not force:
        print(f"{CONFIG_V2} exists; refusing to overwrite")
        return 1
    t0 = time.time()
    cfg = json.loads(lt.CONFIG.read_text())
    series, _ = load_series(cfg, workers)
    table = []
    det0 = None
    for z in Z_GRID:
        fa = eval_condition(cfg, series, "p95/camera_noise", "train", z)["pooled"]["false_alerts_upstream_per_30d"]
        det = eval_condition(cfg, series, "p95/gauge", "train", z)["pooled"]["detection_rate_combined"]
        det0 = det if z == 0 else det0
        table.append({"z": z, "camera_noise_false_alerts_per_30d": fa, "gauge_detection_combined": det})
    for row in table:
        row["detection_ok"] = row["gauge_detection_combined"] >= det0 - DET_TOL - 1e-12
        row["meets"] = row["detection_ok"] and row["camera_noise_false_alerts_per_30d"] <= FA_TARGET
        print(row)
    ok = [r for r in table if r["meets"]]
    if ok:
        chosen, target_met = ok[0]["z"], True
    else:
        chosen, target_met = max(r["z"] for r in table if r["detection_ok"]), False
    doc = {
        "schema": "nadisaathi-leadtime-config-v2",
        "frozen_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "note": "v2 rule: projected branch needs rate - z * rate_sigma >= R_FAST. z chosen on TRAIN only. Everything else is the v1 frozen config (hash below). TEST was already seen in v1.",
        "v1_config": "eval/config.leadtime.frozen.json", "v1_config_sha256": lt.sha256(lt.CONFIG),
        "z_grid": Z_GRID, "z_rule": Z_RULE, "z": chosen, "false_alert_target_met": target_met,
        "selection_table_train": table,
        "policy_py_sha256": lt.sha256(lt.POLICY_FILE), "temporal_py_sha256": lt.sha256(lt.TEMPORAL_FILE),
    }
    CONFIG_V2.write_text(json.dumps(doc, indent=1))
    print(f"chosen z = {chosen} (target met: {target_met}); wrote {CONFIG_V2} in {time.time() - t0:.0f} s")
    return 0


# --------------------------------------------------------------------------- TEST run
def run(workers: int) -> int:
    if not CONFIG_V2.exists():
        print(f"{CONFIG_V2} missing: run with --freeze first (TRAIN only)")
        return 1
    t0 = time.time()
    c2 = json.loads(CONFIG_V2.read_text())
    cfg = json.loads(lt.CONFIG.read_text())
    if c2["v1_config_sha256"] != lt.sha256(lt.CONFIG):
        print("WARNING: v1 config changed since v2 was frozen")
    series, cached = load_series(cfg, workers)
    z = c2["z"]
    r1 = json.loads(lt.OUT.read_text())
    # z = 0 must reproduce v1 exactly (same series, same code path as v1's rule).
    z0 = {k: eval_condition(cfg, series, k, "test", 0.0)["pooled"] for k in CONDS}
    z0_same = all(json.loads(json.dumps(z0[k], default=float)) == r1["pooled"][k]["test"] for k in CONDS)
    pooled, per_pair, fails = {}, {}, []
    for k in CONDS:
        for split in ("test", "train"):
            r = eval_condition(cfg, series, k, split, z)
            pooled.setdefault(k, {})[split] = r["pooled"]
            if split == "test":
                for pid, sm in r["per_pair"].items():
                    per_pair.setdefault(pid, {})[k] = sm
                fails += [{"condition": k, **f} for f in r["failure_cases"]]
    out = {
        "meta": {
            "label": "REAL USGS gauge pairs, 2024–2026 events; TEST already seen in v1 (second look, optimistic)",
            "test_reuse_note": "TEST was already seen in v1, so v2 is a second look at the same test set and its numbers are optimistic. z itself was chosen on TRAIN only.",
            "rule": {"R_FAST_M_PER_H": lt.policy.R_FAST_M_PER_H, "CROSS_HORIZON_H": lt.policy.CROSS_HORIZON_H,
                     "v2_change": "projected branch requires rate - z * rate_sigma >= R_FAST (rate_sigma = filter_series(...).rate_sigma_m_per_h); warning-reached branch unchanged"},
            "z": z, "z_selection": {"rule": c2["z_rule"], "table": c2["selection_table_train"], "target_met": c2["false_alert_target_met"]},
            "z0_reproduces_v1": z0_same,
            "config": "eval/config.leadtime.v2.frozen.json", "config_sha256": lt.sha256(CONFIG_V2),
            "v1_config_sha256": lt.sha256(lt.CONFIG), "v1_results": "eval/results/leadtime.json",
            "data_source": r1["meta"]["data_source"], "periods": r1["meta"]["periods"],
            "kalman_from_cache": cached,
            "generated_by": "eval/run_leadtime_v2.py",
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "wall_s": round(time.time() - t0, 1),
        },
        "pooled": pooled,
        "per_pair_test": per_pair,
        "failure_cases_test": fails,
    }
    lt.OUT_V2.write_text(json.dumps(out, indent=1, default=float))
    md = lt.MD.read_text()
    if lt.V2_MARK in md:
        md = md[:md.index(lt.V2_MARK)].rstrip("\n") + "\n"
    lt.MD.write_text(md + lt.v2_md_section(out, r1))
    print(f"z = {z}; z=0 reproduces v1: {z0_same}")
    for k in CONDS:
        a, b = r1["pooled"][k]["test"], pooled[k]["test"]
        print(f"{k}: v1 gain med {a.get('gain_median_min')} mean {a.get('gain_mean_min')} det {a.get('detection_rate_combined')} fa {a['false_alerts_upstream_per_30d']}"
              f" | v2 gain med {b.get('gain_median_min')} {b.get('gain_median_ci95_min')} mean {b.get('gain_mean_min')} det {b.get('detection_rate_combined')} fa {b['false_alerts_upstream_per_30d']}")
    print(f"wrote {lt.OUT_V2} and appended the v2 section to {lt.MD} in {time.time() - t0:.0f} s")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--md-only", action="store_true", help="rewrite the v2 section of eval/LEADTIME.md from the JSONs")
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 2))
    a = ap.parse_args()
    if a.md_only:
        lt.write_md(json.loads(lt.OUT.read_text()))  # v1 markdown + v2 section from the two JSONs
        print(f"wrote {lt.MD}")
        return 0
    return freeze(a.force, a.workers) if a.freeze else run(a.workers)


if __name__ == "__main__":
    raise SystemExit(main())
