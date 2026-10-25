"""Lead time gained by watching an UPSTREAM gauge, on real USGS river-gauge pairs.

Claim measured: an agent that runs the alert rule on an upstream gauge and
drafts the downstream alert when the upstream rise is detected warns the
downstream community earlier than the same rule run only at the downstream
site. Data are U.S. rivers (USGS NWIS gauge height), not Nepal/India.

Usage (from repo root; the data come from eval/fetch_hydro_pairs.py):
    cd backend && uv run python ../eval/run_leadtime.py --freeze   # TRAIN only -> eval/config.leadtime.frozen.json
    cd backend && uv run python ../eval/run_leadtime.py            # TEST (+TRAIN reference) -> eval/results/leadtime.json, eval/LEADTIME.md
    cd backend && uv run python ../eval/run_leadtime.py --md-only  # regenerate LEADTIME.md from the JSON

The alert rule is the agent's own (jalrekha.agent.runner D5 branch): the
Kalman filter jalrekha.vision.temporal.filter_series over the last
policy.HISTORY_HOURS of readings, then
    (filtered stage >= warning and not falling, or >= danger) or
    (rate >= policy.R_FAST_M_PER_H and projected crossing of warning <= policy.CROSS_HORIZON_H).
The filter is run causally: at each 15-min step only readings in [t - 6 h, t].
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import sys
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from jalrekha.agent import policy  # noqa: E402
from jalrekha.vision.temporal import filter_series  # noqa: E402

DATA = ROOT / "datasets" / "usgs_hydro_pairs"
CONFIG = ROOT / "eval" / "config.leadtime.frozen.json"
OUT = ROOT / "eval" / "results" / "leadtime.json"
OUT_V2 = ROOT / "eval" / "results" / "leadtime_v2.json"
MD = ROOT / "eval" / "LEADTIME.md"
POLICY_FILE = ROOT / "backend" / "src" / "jalrekha" / "agent" / "policy.py"
TEMPORAL_FILE = ROOT / "backend" / "src" / "jalrekha" / "vision" / "temporal.py"
STEP_MIN = 15
STEPS_PER_H = 60 // STEP_MIN
GRID_START = datetime(2021, 1, 1, tzinfo=timezone.utc)
GRID_END = datetime(2026, 10, 2, tzinfo=timezone.utc)  # exclusive (TEST ends 2026-10-01 inclusive)
TRAIN = ("2021-01-01", "2023-12-31")
TEST = ("2024-01-01", "2026-10-01")
FT_TO_M = 0.3048

# Settings fixed before any TEST run (copied into the frozen config by --freeze).
DEFAULTS = {
    "sigma_gauge_m": 0.03,
    "camera_noise_sigma_m": 0.05,
    "camera_noise_seed": 2026,
    "history_h": policy.HISTORY_HOURS,
    "event": {"dedup_h": 24, "persist_readings": 2,
              "definition": "downstream raw stage crosses warning from below, stays >= warning for 2 readings, and was below warning for the previous 24 h"},
    "window": {"travel_time_multiplier": 3.0, "max_h": 48.0, "min_h": 1.0, "downstream_search_after_h": 6.0,
               "definition": "upstream alert onset counts for a downstream event if it falls in [t_cross - W, t_cross], W = clip(3 x TRAIN median travel time, 1 h, 48 h), and after the downstream last fell below warning"},
    "false_alert": {"episode_merge_h": 6.0, "downstream_horizon_h": 6.0,
                    "definition": "an upstream alert episode is false if the downstream raw stage does not reach its warning level within W after the episode onset; a downstream-only episode is false if it does not reach warning within 6 h"},
    "travel_time": {"xcorr_max_lag_h": 60, "seg_before_h": 72, "seg_after_h": 24, "peak_search_h": 48,
                    "method": "per TRAIN downstream P95 event: lag maximising the cross-correlation of the positive hourly rises (1-h trailing mean) of upstream vs downstream; median over events"},
    "percentiles": {"warning": 95, "danger": 99},
    "nws_datum_tolerance_ft": 0.2,
    "primary_rule": "nws_action if >= 6 pairs have a usable NWS action stage at both gauges and those pairs have >= 30 TRAIN downstream events at action stage in total; else p95",
    "bootstrap": {"n": 2000, "seed": 7},
}


# --------------------------------------------------------------------------- data
def grid_len() -> int:
    return int((GRID_END - GRID_START).total_seconds() // 60 // STEP_MIN)


def day_index(d: str, end: bool = False) -> int:
    t = datetime.fromisoformat(d).replace(tzinfo=timezone.utc)
    if end:
        t += timedelta(days=1)
    return int((t - GRID_START).total_seconds() // 60 // STEP_MIN)


def load_site(site: str, data: Path = DATA) -> np.ndarray:
    """Stage (m) on the fixed 15-min grid, NaN where missing."""
    z = np.full(grid_len(), np.nan)
    with gzip.open(data / "sites" / f"{site}.csv.gz", "rt") as f:
        for row in csv.DictReader(f):
            t = datetime.strptime(row["timestamp_utc"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
            i = int((t - GRID_START).total_seconds() // 60 // STEP_MIN)
            if 0 <= i < len(z):
                z[i] = float(row["stage_m"])
    return z


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- the agent's rule
def kalman_track(z: np.ndarray, sigma: float, idx=None, t0: datetime = GRID_START,
                 history_h: float = policy.HISTORY_HOURS, return_sigma: bool = False):
    """Causal sliding-window Kalman: at each step i, filter_series over readings in [t_i - history_h, t_i].

    Returns (stage, rate_m_per_h, n_rejected) and, with return_sigma, also rate_sigma_m_per_h;
    NaN where not computed (no reading at i, fewer than 2 readings in the window, or i not in idx).
    """
    n = len(z)
    w = int(round(history_h * STEPS_PER_H))
    stage = np.full(n, np.nan)
    rate = np.full(n, np.nan)
    rej = np.zeros(n, np.int16)
    rsig = np.full(n, np.nan)
    fin = np.isfinite(z)
    ts = [t0 + timedelta(minutes=STEP_MIN * k) for k in range(n)]
    for i in (range(n) if idx is None else idx):
        if not fin[i]:
            continue
        lo = max(0, i - w)
        rd = [(ts[k], float(z[k]), sigma) for k in range(lo, i + 1) if fin[k]]
        if len(rd) < 2:  # the runner needs >= 2 readings too
            continue
        f = filter_series(rd)
        stage[i], rate[i], rej[i], rsig[i] = f.stage_m, f.rate_m_per_h, f.n_rejected, f.rate_sigma_m_per_h
    return (stage, rate, rej, rsig) if return_sigma else (stage, rate, rej)


def rule(stage: np.ndarray, rate: np.ndarray, warn: float, danger: float,
         z: float = 0.0, rate_sigma: np.ndarray | None = None) -> np.ndarray:
    """jalrekha.agent.runner D5: draft alerts if warning reached (and not falling, unless danger) or projected.

    v1 (z = 0): the projected branch needs rate >= R_FAST. v2 (z > 0): the rise must be
    significant, rate - z * rate_sigma >= R_FAST. The warning-reached branch is unchanged.
    """
    ok = np.isfinite(stage) & np.isfinite(rate)
    s = np.where(ok, stage, -np.inf)
    r = np.where(ok, rate, 0.0)
    level_warn = s >= warn
    level_danger = s >= danger
    falling = r < 0
    with np.errstate(divide="ignore", invalid="ignore"):
        t_cross = np.where((r > 0) & (s < warn), (warn - s) / np.where(r > 0, r, 1.0), np.inf)
    if z == 0:
        fast = r >= policy.R_FAST_M_PER_H
    else:
        if rate_sigma is None:
            raise ValueError("z > 0 needs rate_sigma")
        rs = np.where(np.isfinite(rate_sigma), rate_sigma, np.inf)
        fast = (r - z * rs) >= policy.R_FAST_M_PER_H
    projected = (t_cross <= policy.CROSS_HORIZON_H) & fast
    return ok & ((level_warn & ~(falling & ~level_danger)) | projected)


def _trailing_mean(z: np.ndarray, k: int) -> np.ndarray:
    v = np.where(np.isfinite(z), z, 0.0)
    c = np.where(np.isfinite(z), 1.0, 0.0)
    cv, cc = np.cumsum(np.r_[0.0, v]), np.cumsum(np.r_[0.0, c])
    i = np.arange(len(z))
    lo = np.maximum(0, i - k + 1)
    num, den = cv[i + 1] - cv[lo], cc[i + 1] - cc[lo]
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


# --------------------------------------------------------------------------- events, episodes, travel time
def find_events(z: np.ndarray, warn: float, dedup_h: float = 24, persist: int = 2) -> list[int]:
    """Indices where raw stage crosses warn from below, persists, and was below warn for the previous dedup_h."""
    fin = np.isfinite(z)
    above = fin & (z >= warn)
    d = int(dedup_h * STEPS_PER_H)
    out = []
    last_above = -10**9
    prev_val = np.nan
    for i in np.flatnonzero(fin):
        if above[i]:
            if prev_val < warn and i - last_above > d:
                nxt = np.flatnonzero(fin[i:i + 4 * persist])[:persist]
                if len(nxt) == persist and np.all(z[i + nxt] >= warn):
                    out.append(int(i))
            last_above = i
        prev_val = z[i]
    return out


def episodes(alert: np.ndarray, merge_h: float) -> list[int]:
    """Onsets of alert episodes; alerts separated by <= merge_h belong to one episode."""
    on = np.flatnonzero(alert)
    if len(on) == 0:
        return []
    gap = int(merge_h * STEPS_PER_H)
    starts = [int(on[0])]
    for a, b in zip(on[:-1], on[1:]):
        if b - a > gap:
            starts.append(int(b))
    return starts


def _rises(z: np.ndarray) -> np.ndarray:
    zs = _trailing_mean(z, STEPS_PER_H)
    r = np.zeros(len(z))
    r[STEPS_PER_H:] = zs[STEPS_PER_H:] - zs[:-STEPS_PER_H]
    return np.clip(np.nan_to_num(r, nan=0.0), 0, None)


def travel_times(zu: np.ndarray, zd: np.ndarray, events: list[int], tt: dict) -> dict:
    """Per-event cross-correlation lag of the rises and peak-to-peak lag (hours)."""
    ru, rd = _rises(zu), _rises(zd)
    a, b = int(tt["seg_before_h"] * STEPS_PER_H), int(tt["seg_after_h"] * STEPS_PER_H)
    L = int(tt["xcorr_max_lag_h"] * STEPS_PER_H)
    P = int(tt["peak_search_h"] * STEPS_PER_H)
    xl, pl = [], []
    n = len(zd)
    for i in events:
        lo, hi = i - a, i + b
        if lo - L < 0 or hi > n:
            continue
        seg_d = rd[lo:hi]
        if seg_d.sum() <= 0:
            continue
        cc = np.array([float(np.dot(ru[lo - k:hi - k], seg_d)) for k in range(L + 1)])
        if cc.max() > 0:
            xl.append(int(np.argmax(cc)) / STEPS_PER_H)
        wd = zd[i:min(n, i + P)]
        if np.isfinite(wd).any():
            dp = i + int(np.nanargmax(wd))
            wu = zu[max(0, dp - L):dp + 1]
            if np.isfinite(wu).any():
                pl.append((dp - (max(0, dp - L) + int(np.nanargmax(wu)))) / STEPS_PER_H)
    return {
        "n_events": len(events), "n_xcorr": len(xl), "n_peak": len(pl),
        "xcorr_lag_median_h": round(float(np.median(xl)), 2) if xl else None,
        "xcorr_lag_iqr_h": [round(float(np.percentile(xl, 25)), 2), round(float(np.percentile(xl, 75)), 2)] if xl else None,
        "peak_to_peak_median_h": round(float(np.median(pl)), 2) if pl else None,
        "peak_to_peak_iqr_h": [round(float(np.percentile(pl, 25)), 2), round(float(np.percentile(pl, 75)), 2)] if pl else None,
    }


def window_h(tt_h: float | None, w: dict) -> float:
    if tt_h is None:
        return w["min_h"]
    return float(min(w["max_h"], max(w["min_h"], w["travel_time_multiplier"] * tt_h)))


# --------------------------------------------------------------------------- evaluation
def evaluate(zu: np.ndarray, zd: np.ndarray, alert_u: np.ndarray, alert_d: np.ndarray,
             warn_u: float, warn_d: float, W_h: float, span: tuple[int, int], cfg: dict) -> dict:
    """Events and false alerts in [span[0], span[1]) for one pair, one condition."""
    a0, a1 = span
    ev = [i for i in find_events(zd, warn_d, cfg["event"]["dedup_h"], cfg["event"]["persist_readings"]) if a0 <= i < a1]
    W = int(round(W_h * STEPS_PER_H))
    after = int(cfg["window"]["downstream_search_after_h"] * STEPS_PER_H)
    cap48 = int(cfg["window"]["max_h"] * STEPS_PER_H)
    merge = cfg["false_alert"]["episode_merge_h"]
    up_on = np.array(episodes(alert_u, merge), int)
    dn_on = np.array(episodes(alert_d, merge), int)
    fin_d = np.isfinite(zd)
    above_d = fin_d & (zd >= warn_d)
    above_idx = np.flatnonzero(above_d)
    rows = []
    for i in ev:
        k = np.searchsorted(above_idx, i)
        last_above = int(above_idx[k - 1]) if k > 0 else -10**9
        lo_d = max(i - cap48, last_above + 1)
        dwin = np.flatnonzero(alert_d[lo_d:i + after + 1])
        t_down = lo_d + int(dwin[0]) if len(dwin) else None
        lo_u = max(i - W, last_above + 1)
        uw = up_on[(up_on >= lo_u) & (up_on <= i)]
        t_up = int(uw[0]) if len(uw) else None
        t_down_c = t_down if t_down is not None else i + after
        t_comb = min(t_down_c, t_up) if t_up is not None else t_down_c
        seg = zu[max(0, lo_u):i + 1]
        seg_f = seg[np.isfinite(seg)]
        u_rise = float(seg_f.max() - seg_f[0]) if len(seg_f) else None
        u_peak = float(seg_f.max()) if len(seg_f) else None
        if t_up is None:
            prior = up_on[up_on < lo_u]
            expired = bool(len(prior) and np.any(alert_u[lo_u:i + 1]))
            if expired:
                reason = "upstream alert started before the window (expired)"
            elif u_peak is not None and u_peak >= warn_u:
                reason = "upstream silent: reached its warning level but the rule did not fire in the window"
            elif u_rise is not None and u_rise >= 0.3:
                reason = "upstream silent: rose >= 0.3 m but stayed below its own warning level"
            else:
                reason = "upstream silent: rose < 0.3 m (rise from local/tributary inflow)"
        elif t_up >= t_down_c:
            reason = "upstream fired, but not before the downstream rule"
        else:
            reason = None
        rows.append({
            "i": i, "t_cross": iso(i),
            "t_alert_down": iso(t_down) if t_down is not None else None,
            "t_alert_up": iso(t_up) if t_up is not None else None,
            "down_missed_within_6h": t_down is None,
            "lead_down_min": (i - t_down_c) * STEP_MIN,
            "lead_comb_min": (i - t_comb) * STEP_MIN,
            "lead_up_min": None if t_up is None else (i - t_up) * STEP_MIN,
            "gain_min": (t_down_c - t_comb) * STEP_MIN,
            "up_rise_in_window_m": None if u_rise is None else round(u_rise, 3),
            "up_peak_minus_warn_m": None if u_peak is None else round(u_peak - warn_u, 3),
            "no_gain_reason": reason,
        })
    # False alerts
    days = (a1 - a0) / (24 * STEPS_PER_H)
    hz_d = int(cfg["false_alert"]["downstream_horizon_h"] * STEPS_PER_H)
    cum = np.r_[0, np.cumsum(above_d)]

    def reaches(j: int, h: int) -> bool:
        return cum[min(len(zd), j + h + 1)] - cum[j] > 0

    fa_up, n_up = [], 0
    for j in up_on[(up_on >= a0) & (up_on < a1)]:
        n_up += 1
        if not reaches(int(j), W):
            seg = zd[j:j + W + 1]
            useg = zu[j:j + W + 1]
            fa_up.append({"t_onset": iso(int(j)),
                          "down_max_minus_warn_m": round(float(np.nanmax(seg) - warn_d), 3) if np.isfinite(seg).any() else None,
                          "up_max_minus_warn_m": round(float(np.nanmax(useg) - warn_u), 3) if np.isfinite(useg).any() else None})
    n_dn = int(((dn_on >= a0) & (dn_on < a1)).sum())
    fa_dn = sum(1 for j in dn_on[(dn_on >= a0) & (dn_on < a1)] if not reaches(int(j), hz_d))
    return {"events": rows, "days": days, "up_episodes": n_up, "up_false": fa_up,
            "down_episodes": n_dn, "down_false": fa_dn}


def iso(i: int | None) -> str | None:
    return None if i is None else (GRID_START + timedelta(minutes=STEP_MIN * int(i))).strftime("%Y-%m-%dT%H:%MZ")


def boot_ci(x: np.ndarray, stat, n: int, seed: int) -> list[float] | None:
    if len(x) < 2:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), (n, len(x)))
    v = stat(x[idx], axis=1)
    return [round(float(np.percentile(v, 2.5)), 1), round(float(np.percentile(v, 97.5)), 1)]


def summarise(ev_rows: list[dict], fa_up: int, fa_dn: int, n_up: int, n_dn: int, days: float, boot: dict) -> dict:
    n = len(ev_rows)
    out: dict = {"n_events": n, "days": round(days, 1), "upstream_alert_episodes": n_up,
                 "false_alerts_upstream": fa_up, "false_alerts_downstream_only": fa_dn, "downstream_only_alert_episodes": n_dn,
                 "false_alerts_upstream_per_30d": round(fa_up / days * 30, 3) if days else None,
                 "false_alerts_downstream_only_per_30d": round(fa_dn / days * 30, 3) if days else None,
                 "false_alerts_combined_per_30d": round((fa_up + fa_dn) / days * 30, 3) if days else None,
                 "upstream_precision": round(1 - fa_up / n_up, 4) if n_up else None}
    if n == 0:
        return out
    g = np.array([r["gain_min"] for r in ev_rows], float)
    ld = np.array([r["lead_down_min"] for r in ev_rows], float)
    lc = np.array([r["lead_comb_min"] for r in ev_rows], float)
    out.update({
        "gain_median_min": round(float(np.median(g)), 1),
        "gain_median_ci95_min": boot_ci(g, np.median, boot["n"], boot["seed"]),
        "gain_mean_min": round(float(g.mean()), 1),
        "gain_mean_ci95_min": boot_ci(g, np.mean, boot["n"], boot["seed"]),
        "frac_events_with_gain": round(float((g > 0).mean()), 4),
        "lead_before_crossing_downstream_only_median_min": round(float(np.median(ld)), 1),
        "lead_before_crossing_downstream_only_mean_min": round(float(ld.mean()), 1),
        "lead_before_crossing_combined_median_min": round(float(np.median(lc)), 1),
        "lead_before_crossing_combined_mean_min": round(float(lc.mean()), 1),
        "detection_rate_downstream_only": round(float((ld > 0).mean()), 4),
        "detection_rate_combined": round(float((lc > 0).mean()), 4),
        "detection_rate_upstream_alone": round(float(np.mean([(r["lead_up_min"] or 0) > 0 for r in ev_rows])), 4),
        "downstream_only_missed_within_6h": int(sum(r["down_missed_within_6h"] for r in ev_rows)),
    })
    return out


# --------------------------------------------------------------------------- workers
def _series_task(args: tuple) -> dict:
    """Causal Kalman at every reading of one site series under one condition."""
    site, cond, cfg = args
    import cv2
    cv2.setNumThreads(1)
    z = load_site(site)
    if cond == "camera_noise":
        seed = cfg["camera_noise_seed"] + zlib.crc32(site.encode())
        rng = np.random.default_rng(seed)
        z = z + rng.normal(0.0, cfg["camera_noise_sigma_m"], len(z))
        sigma = cfg["camera_noise_sigma_m"]
    else:
        sigma = cfg["sigma_gauge_m"]
    t0 = time.time()
    stage, rate, rej, rsig = kalman_track(z, sigma, history_h=cfg["history_h"], return_sigma=True)
    ok = np.isfinite(rate)
    return {"site": site, "cond": cond, "stage": stage, "rate": rate, "rej": rej, "rate_sigma": rsig,
            "n_filtered": int(ok.sum()), "kalman_wall_s": round(time.time() - t0, 1),
            "rate_abs_p99_m_per_h": round(float(np.percentile(np.abs(rate[ok]), 99)), 3) if ok.any() else None,
            "frac_steps_rate_ge_r_fast": round(float((rate[ok] >= policy.R_FAST_M_PER_H).mean()), 5) if ok.any() else None,
            "frac_readings_rejected_by_gate": round(float(rej[ok].sum() / max(1, ok.sum() * 25)), 6),
            "z_noisy": z if cond == "camera_noise" else None}


# --------------------------------------------------------------------------- freeze (TRAIN only)
def freeze(force: bool) -> int:
    if CONFIG.exists() and not force:
        print(f"{CONFIG} exists; refusing to overwrite (use --force only if no TEST run has been made)")
        return 1
    meta = json.loads((DATA / "pairs.json").read_text())
    pairs = [p for p in meta["pairs"] if p["usable"]]
    tr = (day_index(TRAIN[0]), day_index(TRAIN[1], end=True))
    cfg = json.loads(json.dumps(DEFAULTS))
    sites = sorted({p[k] for p in pairs for k in ("up", "down")})
    thr: dict = {}
    zs: dict = {}
    for s in sites:
        z = load_site(s)
        zs[s] = z
        ztr = z[tr[0]:tr[1]]  # TRAIN rows only
        ztr = ztr[np.isfinite(ztr)]
        nws = (meta["sites"][s].get("nws") or {})
        st = nws.get("stages_ft") or {}
        dd = nws.get("datum_diff_ft")
        datum_ok = dd is not None and abs(dd) <= cfg["nws_datum_tolerance_ft"]
        thr[s] = {
            "p95_m": round(float(np.percentile(ztr, cfg["percentiles"]["warning"])), 4),
            "p99_m": round(float(np.percentile(ztr, cfg["percentiles"]["danger"])), 4),
            "nws_action_m": round(st["action"] * FT_TO_M, 4) if "action" in st and datum_ok else None,
            "nws_minor_m": round(st["minor"] * FT_TO_M, 4) if "minor" in st and datum_ok else None,
            "nws_lid": nws.get("lid"), "nws_datum_diff_ft": dd, "nws_datum_ok": datum_ok,
            "train_max_m": round(float(ztr.max()), 4),
        }
    tts: dict = {}
    n_action_pairs, n_action_events = 0, 0
    for p in pairs:
        zu, zd = np.copy(zs[p["up"]]), np.copy(zs[p["down"]])
        zu[tr[1]:] = np.nan  # TRAIN only
        zd[tr[1]:] = np.nan
        ev = find_events(zd, thr[p["down"]]["p95_m"], cfg["event"]["dedup_h"], cfg["event"]["persist_readings"])
        t = travel_times(zu, zd, ev, cfg["travel_time"])
        t["window_h"] = window_h(t["xcorr_lag_median_h"], cfg["window"])
        t["train_events_p95"] = len(ev)
        if thr[p["up"]]["nws_action_m"] and thr[p["down"]]["nws_action_m"]:
            n_action_pairs += 1
            ea = find_events(zd, thr[p["down"]]["nws_action_m"], cfg["event"]["dedup_h"], cfg["event"]["persist_readings"])
            t["train_events_nws_action"] = len(ea)
            n_action_events += len(ea)
        else:
            t["train_events_nws_action"] = None
        tts[p["id"]] = t
        print(p["id"], t)
    primary = "nws_action" if (n_action_pairs >= 6 and n_action_events >= 30) else "p95"
    cfg.update({
        "schema": "nadisaathi-leadtime-config-v1",
        "frozen_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "note": "Written by run_leadtime.py --freeze from TRAIN rows only, before any TEST metric was computed. (First freeze 2026-10-25 had a key collision that overwrote the travel-time settings with the per-pair results and crashed the first run before any TEST metric was produced; this re-freeze fixes the key and drops the step prescreen in favour of filtering every reading. TRAIN-derived values are unchanged.) Thresholds, travel times and windows below are fixed; the alert rule constants come from backend/src/jalrekha/agent/policy.py (hash below).",
        "splits": {"train": list(TRAIN), "test": list(TEST)},
        "data": {"pairs_json_sha256": sha256(DATA / "pairs.json"), "fetched_at_utc": meta["fetched_at_utc"]},
        "policy": {"R_FAST_M_PER_H": policy.R_FAST_M_PER_H, "CROSS_HORIZON_H": policy.CROSS_HORIZON_H,
                   "HISTORY_HOURS": policy.HISTORY_HOURS, "policy_py_sha256": sha256(POLICY_FILE),
                   "temporal_py_sha256": sha256(TEMPORAL_FILE)},
        "pairs": [{"id": p["id"], "river": p["river"], "up": p["up"], "down": p["down"], "up_name": p["up_name"],
                   "down_name": p["down_name"], "straight_line_km": p["straight_line_km"]} for p in pairs],
        "dropped_pairs": [p["id"] for p in meta["pairs"] if not p["usable"]],
        "thresholds": thr,
        "travel_time_train": tts,
        "primary_threshold": primary,
        "primary_threshold_evidence": {"pairs_with_nws_action": n_action_pairs, "train_events_nws_action": n_action_events},
    })
    CONFIG.write_text(json.dumps(cfg, indent=1))
    print(f"primary threshold: {primary} ({n_action_pairs} pairs with NWS action stage, {n_action_events} TRAIN events)")
    print(f"wrote {CONFIG} sha256={sha256(CONFIG)}")
    return 0


# --------------------------------------------------------------------------- main run
def threshold_sets(cfg: dict) -> dict:
    """condition -> {site: (warning, danger)} ; nws_action only for pairs with usable stages at both gauges."""
    th = cfg["thresholds"]
    out = {"p95": {s: (v["p95_m"], v["p99_m"]) for s, v in th.items()}}
    nws = {}
    for p in cfg["pairs"]:
        u, d = th[p["up"]], th[p["down"]]
        if u["nws_action_m"] and d["nws_action_m"]:
            for s, v in ((p["up"], u), (p["down"], d)):
                nws[s] = (v["nws_action_m"], v["nws_minor_m"] or v["p99_m"])
    out["nws_action"] = nws
    return out


def run(workers: int) -> int:
    if not CONFIG.exists():
        print(f"{CONFIG} missing: run with --freeze first (TRAIN only)")
        return 1
    t_start = time.time()
    cfg = json.loads(CONFIG.read_text())
    cfg_sha = sha256(CONFIG)
    for k, f in (("policy_py_sha256", POLICY_FILE), ("temporal_py_sha256", TEMPORAL_FILE)):
        if cfg["policy"][k] != sha256(f):
            print(f"WARNING: {f.name} changed since the config was frozen")
    data_ok = cfg["data"]["pairs_json_sha256"] == sha256(DATA / "pairs.json")
    ths = threshold_sets(cfg)
    pairs = cfg["pairs"]
    sites = sorted({p[k] for p in pairs for k in ("up", "down")})
    tasks = [(s, "gauge", cfg) for s in sites] + [(s, "camera_noise", cfg) for s in sorted({p["up"] for p in pairs})]
    series: dict = {}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_series_task, tasks):
            series[(r["site"], r["cond"])] = r
            print(f"  kalman {r['site']} {r['cond']}: {r['n_filtered']} steps in {r['kalman_wall_s']} s,"
                  f" |rate| p99 {r['rate_abs_p99_m_per_h']} m/h, rate>=R_FAST at {r['frac_steps_rate_ge_r_fast']} of steps", flush=True)
    raw = {s: load_site(s) for s in sites}
    spans = {"test": (day_index(TEST[0]), day_index(TEST[1], end=True)),
             "train": (day_index(TRAIN[0]), day_index(TRAIN[1], end=True))}
    results: dict = {}
    failure_cases: list = []
    per_pair: dict = {p["id"]: {"river": p["river"], "up": f"{p['up']} {p['up_name']}", "down": f"{p['down']} {p['down_name']}",
                                "straight_line_km": p["straight_line_km"], "travel_time_train": cfg["travel_time_train"][p["id"]],
                                "window_h": cfg["travel_time_train"][p["id"]]["window_h"], "conditions": {}} for p in pairs}
    for p in pairs:
        tt = cfg["travel_time_train"][p["id"]]
        km, pp = p["straight_line_km"], tt["peak_to_peak_median_h"]
        per_pair[p["id"]]["implied_celerity_km_per_h_straight_line"] = round(km / pp, 2) if km and pp else None
    pooled: dict = {}
    reasons: dict = {}
    for thr_name, th in ths.items():
        for cond in ("gauge", "camera_noise"):
            key = f"{thr_name}/{cond}"
            for split, span in spans.items():
                acc = {"ev": [], "fa_up": 0, "fa_dn": 0, "n_up": 0, "n_dn": 0, "days": 0.0, "pairs": 0}
                for p in pairs:
                    if p["up"] not in th or p["down"] not in th:
                        continue
                    (wu, du), (wd, dd) = th[p["up"]], th[p["down"]]
                    su = series[(p["up"], cond)]
                    sd = series[(p["down"], "gauge")]
                    au = rule(su["stage"], su["rate"], wu, du)
                    ad = rule(sd["stage"], sd["rate"], wd, dd)
                    zu = su["z_noisy"] if cond == "camera_noise" else raw[p["up"]]
                    W = cfg["travel_time_train"][p["id"]]["window_h"]
                    r = evaluate(zu, raw[p["down"]], au, ad, wu, wd, W, span, cfg)
                    sm = summarise(r["events"], len(r["up_false"]), r["down_false"], r["up_episodes"], r["down_episodes"], r["days"], cfg["bootstrap"])
                    sm["warning_m"] = {"up": wu, "down": wd}
                    entry = per_pair[p["id"]]["conditions"].setdefault(key, {})
                    entry[split] = sm
                    if split == "test":
                        for e in r["events"]:
                            if e["gain_min"] == 0:
                                rc = reasons.setdefault(key, {})
                                rc[e["no_gain_reason"]] = rc.get(e["no_gain_reason"], 0) + 1
                        entry["test_events"] = [{k: v for k, v in e.items() if k != "i"} for e in r["events"]]
                        if thr_name == cfg["primary_threshold"]:
                            for e in r["events"]:
                                if e["gain_min"] == 0:
                                    failure_cases.append({"kind": "no_gain", "condition": key, "pair": p["id"],
                                                          **{k: v for k, v in e.items() if k != "i"}})
                            for fa in r["up_false"]:
                                failure_cases.append({"kind": "false_alert_upstream", "condition": key, "pair": p["id"], **fa})
                    acc["ev"] += r["events"]
                    acc["fa_up"] += len(r["up_false"])
                    acc["fa_dn"] += r["down_false"]
                    acc["n_up"] += r["up_episodes"]
                    acc["n_dn"] += r["down_episodes"]
                    acc["days"] += r["days"]
                    acc["pairs"] += 1
                if acc["pairs"] == 0:
                    continue
                sm = summarise(acc["ev"], acc["fa_up"], acc["fa_dn"], acc["n_up"], acc["n_dn"], acc["days"], cfg["bootstrap"])
                sm["n_pairs"] = acc["pairs"]
                sm["note_false_alert_rate"] = "per 30 days per pair (summed false alerts / summed pair-days x 30)"
                pooled.setdefault(key, {})[split] = sm
    kalman_diag = {f"{s}/{c}": {k: v[k] for k in ("n_filtered", "rate_abs_p99_m_per_h", "frac_steps_rate_ge_r_fast", "frac_readings_rejected_by_gate")}
                   for (s, c), v in series.items()}
    out = {
        "meta": {
            "label": "REAL USGS gauge pairs, held-out 2024–2026 events",
            "claim": "lead time gained at the downstream site by running the agent's alert rule on the upstream gauge as well",
            "data_source": "USGS NWIS instantaneous gauge height (00065), U.S. public domain, credit U.S. Geological Survey; NWS action stages from NOAA NWPS where the datum check passed. U.S. rivers, not Nepal/India.",
            "dataset": "datasets/usgs_hydro_pairs", "data_fetched_at_utc": cfg["data"]["fetched_at_utc"],
            "data_matches_frozen_config": data_ok,
            "sites": {s: cfg["thresholds"][s] for s in sites},
            "periods": {"train": list(TRAIN), "test": list(TEST)},
            "config": "eval/config.leadtime.frozen.json", "config_sha256": cfg_sha, "config_frozen_at": cfg["frozen_at"],
            "primary_threshold": cfg["primary_threshold"],
            "primary_condition": f"{cfg['primary_threshold']}/gauge",
            "rule": {"R_FAST_M_PER_H": policy.R_FAST_M_PER_H, "CROSS_HORIZON_H": policy.CROSS_HORIZON_H,
                     "HISTORY_HOURS": policy.HISTORY_HOURS, "kalman": "jalrekha.vision.temporal.filter_series (cv2.KalmanFilter), causal 6 h window, 15-min steps",
                     "sigma_gauge_m": cfg["sigma_gauge_m"], "camera_noise_sigma_m": cfg["camera_noise_sigma_m"]},
            "definitions": {"event": cfg["event"]["definition"], "window": cfg["window"]["definition"],
                            "false_alert": cfg["false_alert"]["definition"],
                            "gain": "t_alert(downstream-only) - t_alert(combined), combined = min(upstream-driven, downstream-only); if the downstream-only rule has not fired by t_cross + 6 h its time is capped there",
                            "detection": "alert strictly before the crossing (lead > 0)",
                            "camera_noise": "Gaussian noise (sigma 5 cm) added to the upstream readings, filter told sigma = 5 cm; downstream stays a gauge",
                            "travel_time": cfg["travel_time"]["method"]},
            "generated_by": "eval/run_leadtime.py",
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "wall_s": round(time.time() - t_start, 1),
        },
        "pooled": pooled,
        "per_pair": per_pair,
        "failure_summary": {"no_gain_reasons_test": reasons},
        "failure_cases": failure_cases,
        "kalman_diagnostics": kalman_diag,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, default=float))
    write_md(out)
    print(json.dumps(pooled.get(out["meta"]["primary_condition"], {}).get("test", {}), indent=1))
    print(f"wrote {OUT} and {MD} in {time.time() - t_start:.0f} s")
    return 0


# --------------------------------------------------------------------------- markdown (numbers come from the JSON)
def _f(v, nd=0):
    if v is None:
        return "–"
    if isinstance(v, list):
        return f"[{_f(v[0], nd)}, {_f(v[1], nd)}]" if v else "–"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _pct(v):
    return "–" if v is None else f"{100 * v:.0f}%"


def write_md(res: dict) -> None:
    m = res["meta"]
    prim = m["primary_condition"]
    pt = res["pooled"].get(prim, {}).get("test", {})
    L = [
        "# Lead time gained by watching the upstream gauge",
        "",
        f"_Generated by `{m['generated_by']}` from `eval/results/leadtime.json` ({m['generated_at']}). "
        f"Do not edit numbers by hand. Label: **{m['label']}**._",
        "",
        "## What is measured",
        "",
        "The agent's alert rule (Kalman-filtered stage from `jalrekha.vision.temporal.filter_series`, warning reached or "
        f"rise ≥ {m['rule']['R_FAST_M_PER_H']} m/h projected to cross warning within {m['rule']['CROSS_HORIZON_H']} h) is run "
        "causally on 15-min gauge readings. **Baseline (downstream-only):** the rule on the downstream gauge. "
        "**Ours (combined):** the downstream rule plus the same rule on the upstream gauge against the upstream's own "
        "warning level; an upstream alert counts for a downstream event when it starts within W before the downstream "
        "crossing (W = 3 × TRAIN median travel time, at most 48 h). Gain = baseline alert time − combined alert time.",
        "",
        f"- Data: {m['data_source']}",
        f"- TRAIN {m['periods']['train'][0]} – {m['periods']['train'][1]} (thresholds, travel times); "
        f"TEST {m['periods']['test'][0]} – {m['periods']['test'][1]} (held out).",
        f"- Warning level: **{m['primary_threshold']}** (primary). Config `{m['config']}` frozen {m['config_frozen_at']}, "
        f"sha256 `{m['config_sha256'][:16]}…`.",
        f"- Event: {m['definitions']['event']}.",
        f"- False alert: {m['definitions']['false_alert']}.",
        "",
        f"## Headline (TEST, {prim})",
        "",
        f"- Downstream events: **{pt.get('n_events')}** over {pt.get('n_pairs')} pairs.",
        f"- Lead time gained: median **{_f(pt.get('gain_median_min'))} min** (95% CI {_f(pt.get('gain_median_ci95_min'))}), "
        f"mean {_f(pt.get('gain_mean_min'))} min (95% CI {_f(pt.get('gain_mean_ci95_min'))}); "
        f"{_pct(pt.get('frac_events_with_gain'))} of events gained any time.",
        f"- Lead before the crossing, median: downstream-only {_f(pt.get('lead_before_crossing_downstream_only_median_min'))} min, "
        f"combined {_f(pt.get('lead_before_crossing_combined_median_min'))} min.",
        f"- Detection (alert before the crossing): downstream-only {_pct(pt.get('detection_rate_downstream_only'))}, "
        f"combined {_pct(pt.get('detection_rate_combined'))}.",
        f"- False alerts per 30 days per pair: upstream-driven {_f(pt.get('false_alerts_upstream_per_30d'), 2)}, "
        f"downstream-only {_f(pt.get('false_alerts_downstream_only_per_30d'), 2)} "
        f"({pt.get('false_alerts_upstream')} of {pt.get('upstream_alert_episodes')} upstream alert episodes were not followed by a downstream crossing).",
        "",
        "## Reading the result",
        "",
    ]
    for key, d in res["pooled"].items():
        s = d.get("test")
        if key == prim or not s:
            continue
        L.append(f"- {key}: {s['n_events']} events, median gain {_f(s.get('gain_median_min'))} min "
                 f"(95% CI {_f(s.get('gain_median_ci95_min'))}), {_pct(s.get('frac_events_with_gain'))} of events gained, "
                 f"detection {_pct(s.get('detection_rate_downstream_only'))} → {_pct(s.get('detection_rate_combined'))}, "
                 f"upstream false alerts {_f(s.get('false_alerts_upstream_per_30d'), 2)} per 30 days per pair.")
    L += [
        "- The gain depends on whether the upstream warning level is reached when the downstream one is. Official action "
        "stages are set per town and are not consistent along a river, so in many events the upstream gauge rose but stayed "
        "below its own action stage (see the failure reasons). With percentile levels the two gauges are on the same "
        "statistical footing (compare the p95 lines above).",
        "- Camera-like noise (σ = 5 cm) makes the Kalman rate noisy enough to trigger the projected-crossing branch often; "
        "that is where its false alerts come from. Its larger 'gains' are not an improvement: with alerts firing at random, "
        "some land inside the window by chance and are credited. Read the camera-noise rows as a false-alert warning, "
        "not as a lead-time result.",
        "",
        "## All conditions (pooled)",
        "",
        "| condition | split | events | gain median min [95% CI] | gain mean min | lead down-only / combined (median min) | detection down-only / combined | false alerts /30 d up / down-only |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for key, d in res["pooled"].items():
        for split in ("test", "train"):
            s = d.get(split)
            if not s:
                continue
            L.append(f"| {key} | {split} | {s['n_events']} | {_f(s.get('gain_median_min'))} {_f(s.get('gain_median_ci95_min'))} | "
                     f"{_f(s.get('gain_mean_min'))} | {_f(s.get('lead_before_crossing_downstream_only_median_min'))} / "
                     f"{_f(s.get('lead_before_crossing_combined_median_min'))} | {_pct(s.get('detection_rate_downstream_only'))} / "
                     f"{_pct(s.get('detection_rate_combined'))} | {_f(s.get('false_alerts_upstream_per_30d'), 2)} / "
                     f"{_f(s.get('false_alerts_downstream_only_per_30d'), 2)} |")
    L += ["", "TRAIN rows are development numbers (the thresholds and travel times were set on TRAIN); TEST rows are the result.",
          "`camera_noise` adds σ = 5 cm Gaussian noise to the upstream readings to mimic a camera instead of a gauge.", "",
          f"## Per pair (TEST, {prim})", "",
          "| pair | up → down | straight km | travel time TRAIN xcorr / peak (h) | W (h) | events | gain median min [95% CI] | detection down-only / combined | false alerts /30 d |",
          "|---|---|---|---|---|---|---|---|---|"]
    for pid, p in res["per_pair"].items():
        s = p["conditions"].get(prim, {}).get("test")
        tt = p["travel_time_train"]
        if s is None:
            L.append(f"| {pid} | {p['up']} → {p['down']} | {_f(p['straight_line_km'])} | {_f(tt['xcorr_lag_median_h'], 1)} / {_f(tt['peak_to_peak_median_h'], 1)} | {_f(p['window_h'], 1)} | not in this condition | | | |")
            continue
        L.append(f"| {pid} | {p['up']} → {p['down']} | {_f(p['straight_line_km'])} | {_f(tt['xcorr_lag_median_h'], 1)} / "
                 f"{_f(tt['peak_to_peak_median_h'], 1)} | {_f(p['window_h'], 1)} | {s['n_events']} | {_f(s.get('gain_median_min'))} "
                 f"{_f(s.get('gain_median_ci95_min'))} | {_pct(s.get('detection_rate_downstream_only'))} / {_pct(s.get('detection_rate_combined'))} | "
                 f"{_f(s.get('false_alerts_upstream_per_30d'), 2)} |")
    L += ["", "Implied flood-wave celerity from the TRAIN peak-to-peak lag and the straight-line distance "
          "(river distance is longer, so true celerity is higher): " +
          ", ".join(f"{pid} {_f(p.get('implied_celerity_km_per_h_straight_line'), 1)} km/h" for pid, p in res["per_pair"].items()) + ".",
          "", f"## Failure cases (TEST, {prim})", ""]
    fs = res["failure_summary"]["no_gain_reasons_test"].get(prim, {})
    ng = [f for f in res["failure_cases"] if f["kind"] == "no_gain" and f["condition"] == prim]
    fa = [f for f in res["failure_cases"] if f["kind"] == "false_alert_upstream" and f["condition"] == prim]
    L.append(f"Events with **no gain**: {len(ng)} of {pt.get('n_events')}. Reasons:")
    L.append("")
    for k, v in sorted(fs.items(), key=lambda kv: -kv[1]):
        L.append(f"- {v} × {k}")
    for key, rc in res["failure_summary"]["no_gain_reasons_test"].items():
        if key != prim:
            L.append(f"- (for comparison, {key}: " + "; ".join(f"{v} × {k}" for k, v in sorted(rc.items(), key=lambda kv: -kv[1])) + ")")
    L += ["", "| pair | downstream crossing (UTC) | reason | upstream rise in window (m) | upstream peak − warning (m) | down-only lead (min) |",
          "|---|---|---|---|---|---|"]
    for f in ng:
        L.append(f"| {f['pair']} | {f['t_cross']} | {f['no_gain_reason']} | {_f(f['up_rise_in_window_m'], 2)} | "
                 f"{_f(f['up_peak_minus_warn_m'], 2)} | {f['lead_down_min']} |")
    L += ["", f"Upstream **false alerts**: {len(fa)} (upstream rule fired, downstream never reached its warning level within W).", "",
          "| pair | upstream alert onset (UTC) | upstream max − warning (m) | downstream max − warning (m) |", "|---|---|---|---|"]
    for f in fa:
        L.append(f"| {f['pair']} | {f['t_onset']} | {_f(f['up_max_minus_warn_m'], 2)} | {_f(f['down_max_minus_warn_m'], 2)} |")
    kd = res["kalman_diagnostics"]
    g_r = [v["frac_steps_rate_ge_r_fast"] for k, v in kd.items() if k.endswith("/gauge")]
    c_r = [v["frac_steps_rate_ge_r_fast"] for k, v in kd.items() if k.endswith("/camera_noise")]
    L += ["", "## Notes and limits", "",
          "- U.S. rivers with dense gauge networks; Nepal/India travel times, flashiness and data gaps differ. This shows the mechanism, not field performance there.",
          "- `nws_action` uses the official NWS action stage of each gauge (NOAA NWPS; datum checked against the live USGS reading). "
          "`p95` uses the 95th percentile of TRAIN stage: a statistical level, so its events are high-water rises, mostly not damaging floods.",
          "- The downstream-only time is the first rule firing in the run-up window (generous to the baseline); the upstream time is the onset of an upstream alert episode inside W (strict for ours).",
          f"- The Kalman filter runs at every reading (no skipping). Share of steps with filtered rate ≥ {m['rule']['R_FAST_M_PER_H']} m/h: "
          f"gauge readings median {_f(float(np.median(g_r)) * 100 if g_r else None, 2)}%, with 5 cm camera noise median {_f(float(np.median(c_r)) * 100 if c_r else None, 2)}% "
          "(the filter's process noise lets the rate follow fast changes, so noisy readings also produce noisy rates).",
          f"- Runtime {m['wall_s']} s. Reproduce: `cd backend && uv run python ../eval/fetch_hydro_pairs.py && uv run python ../eval/run_leadtime.py`.",
          ""]
    text = "\n".join(L)
    if OUT_V2.exists():  # keep the appended v2 section when v1's markdown is regenerated
        text += v2_md_section(json.loads(OUT_V2.read_text()), res)
    MD.write_text(text)


V2_MARK = "<!-- v2 section: generated by eval/run_leadtime_v2.py -->"


def v2_md_section(r2: dict, r1: dict) -> str:
    """Markdown for the v2 rule (significant-rise test), v1 and v2 side by side; numbers from the JSONs."""
    m = r2["meta"]
    L = ["", V2_MARK, "",
         "## v2 rule: the rise must be statistically significant",
         "",
         f"_Generated by `{m['generated_by']}` from `eval/results/leadtime_v2.json` ({m['generated_at']}). Label: **{m['label']}**._",
         "",
         f"v2 changes one thing: the projected-crossing branch counts a rise only if `rate − z × rate_sigma ≥ {m['rule']['R_FAST_M_PER_H']} m/h`, "
         "with `rate_sigma` the Kalman filter's own rate uncertainty. The warning-reached branch is unchanged. z = 0 is v1 "
         f"(check: z = 0 reproduces the v1 TEST numbers: **{m['z0_reproduces_v1']}**).",
         "",
         f"**z = {m['z']}**, chosen on TRAIN only: {m['z_selection']['rule']} "
         f"Config `{m['config']}` sha256 `{m['config_sha256'][:16]}…`.",
         "",
         "| z | TRAIN p95/camera_noise upstream false alerts /30 d | TRAIN p95/gauge detection (combined) | meets both |",
         "|---|---|---|---|"]
    for row in m["z_selection"]["table"]:
        L.append(f"| {row['z']} | {_f(row['camera_noise_false_alerts_per_30d'], 2)} | {_pct(row['gauge_detection_combined'])} | {'yes' if row['meets'] else 'no'} |")
    L += ["",
          f"**Caution:** {m['test_reuse_note']}",
          "",
          "### v1 vs v2 on TEST (pooled)",
          "",
          "| condition | rule | events | gain median min [95% CI] | gain mean min [95% CI] | detection down-only / combined | upstream false alerts /30 d |",
          "|---|---|---|---|---|---|---|"]
    for key in r2["pooled"]:
        for tag, rr in (("v1", r1), (f"v2 (z={m['z']})", r2)):
            s = rr["pooled"].get(key, {}).get("test")
            if not s:
                continue
            L.append(f"| {key} | {tag} | {s['n_events']} | {_f(s.get('gain_median_min'))} {_f(s.get('gain_median_ci95_min'))} | "
                     f"{_f(s.get('gain_mean_min'))} {_f(s.get('gain_mean_ci95_min'))} | {_pct(s.get('detection_rate_downstream_only'))} / "
                     f"{_pct(s.get('detection_rate_combined'))} | {_f(s.get('false_alerts_upstream_per_30d'), 2)} |")
    g1, g2 = r1["pooled"].get("p95/gauge", {}).get("test", {}), r2["pooled"].get("p95/gauge", {}).get("test", {})
    L += ["", "z applies to every gauge, the downstream one included. On real gauge readings it removes most early "
          f"projected-crossing alerts at the downstream site (p95/gauge downstream-only detection {_pct(g1.get('detection_rate_downstream_only'))} "
          f"in v1, {_pct(g2.get('detection_rate_downstream_only'))} in v2). The combined system keeps its detection mainly through the "
          "upstream gauge's warning-reached branch.",
          "", f"v2 runtime {m['wall_s']} s.", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--freeze", action="store_true", help="compute TRAIN-only thresholds/travel times and write the frozen config")
    ap.add_argument("--force", action="store_true", help="with --freeze: overwrite an existing config")
    ap.add_argument("--md-only", action="store_true", help="regenerate eval/LEADTIME.md from eval/results/leadtime.json")
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 2))
    a = ap.parse_args()
    if a.freeze:
        return freeze(a.force)
    if a.md_only:
        write_md(json.loads(OUT.read_text()))
        print(f"wrote {MD}")
        return 0
    return run(a.workers)


if __name__ == "__main__":
    raise SystemExit(main())
