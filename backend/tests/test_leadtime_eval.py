"""Lead-time evaluation core on a synthetic upstream/downstream pair with a known lag (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval"))

import run_leadtime as lt  # noqa: E402

LAG_H = 6
N = 5 * 24 * lt.STEPS_PER_H  # 5 days of 15-min readings


def hydrograph(peak_h: float, base: float = 1.0, amp: float = 2.0) -> np.ndarray:
    """Smooth flood wave: logistic rise (~8 h) to base+amp, slow recession."""
    t = np.arange(N) / lt.STEPS_PER_H
    rise = 1.0 / (1.0 + np.exp(-(t - (peak_h - 4.0)) / 1.2))
    fall = np.exp(-np.clip(t - peak_h, 0, None) / 20.0)
    return base + amp * rise * fall


def pair():
    up = hydrograph(48.0)
    down = hydrograph(48.0 + LAG_H)
    return up, down


def run_pair(up, down, warn=2.0, window_h=3 * LAG_H):
    cfg = lt.DEFAULTS
    out = []
    for z in (up, down):
        s, r, _ = lt.kalman_track(z, 0.03)
        out.append(lt.rule(s, r, warn, np.inf))
    return lt.evaluate(up, down, out[0], out[1], warn, warn, window_h, (0, N), cfg), out


def test_gain_matches_known_lag():
    up, down = pair()
    res, _ = run_pair(up, down)
    assert len(res["events"]) == 1
    e = res["events"][0]
    # Same wave, same rule, same warning level -> the upstream alert leads by the lag.
    assert abs(e["gain_min"] - LAG_H * 60) <= 30, e
    assert e["lead_comb_min"] > e["lead_down_min"]
    assert e["no_gain_reason"] is None
    assert res["up_false"] == []


def test_travel_time_recovers_lag():
    up, down = pair()
    ev = lt.find_events(down, 2.0)
    tt = dict(lt.DEFAULTS["travel_time"], seg_before_h=30, xcorr_max_lag_h=12)
    t = lt.travel_times(up, down, ev, tt)
    assert abs(t["xcorr_lag_median_h"] - LAG_H) <= 0.5
    assert abs(t["peak_to_peak_median_h"] - LAG_H) <= 0.5
    assert lt.window_h(t["xcorr_lag_median_h"], lt.DEFAULTS["window"]) == 3 * t["xcorr_lag_median_h"]


def test_upstream_bump_without_downstream_crossing_is_a_false_alert():
    up = hydrograph(48.0)
    down = np.full(N, 1.0)  # downstream never rises (e.g. the wave attenuates)
    res, _ = run_pair(up, down)
    assert res["events"] == []
    assert len(res["up_false"]) == 1


def test_local_rain_downstream_gives_no_gain():
    up = np.full(N, 1.0)  # upstream flat: rise came from a downstream tributary
    down = hydrograph(54.0)
    res, _ = run_pair(up, down)
    assert len(res["events"]) == 1
    e = res["events"][0]
    assert e["gain_min"] == 0
    assert "silent" in e["no_gain_reason"]


def test_v2_rule_with_z0_equals_v1():
    up, down = pair()
    rng = np.random.default_rng(0)
    noisy = up + rng.normal(0, 0.05, N)  # camera-like readings exercise the projected branch
    for z_in, sig in ((up, 0.03), (down, 0.03), (noisy, 0.05)):
        s1, r1, j1 = lt.kalman_track(z_in, sig)
        s2, r2, j2, rs = lt.kalman_track(z_in, sig, return_sigma=True)
        assert np.array_equal(s1, s2, equal_nan=True) and np.array_equal(r1, r2, equal_nan=True)
        assert np.isfinite(rs[np.isfinite(r2)]).all()
        for warn in (1.5, 2.0, 2.5):
            v1 = lt.rule(s1, r1, warn, np.inf)
            assert np.array_equal(v1, lt.rule(s2, r2, warn, np.inf, z=0.0, rate_sigma=rs))
            # A significance margin can only remove projected alerts, never add any.
            v2 = lt.rule(s2, r2, warn, np.inf, z=2.0, rate_sigma=rs)
            assert not np.any(v2 & ~v1)


def test_v2_keeps_the_gain_on_a_clean_wave():
    up, down = pair()
    cfg = lt.DEFAULTS
    al = []
    for z_in in (up, down):
        s, r, _, rs = lt.kalman_track(z_in, 0.03, return_sigma=True)
        al.append(lt.rule(s, r, 2.0, np.inf, z=1.0, rate_sigma=rs))
    res = lt.evaluate(up, down, al[0], al[1], 2.0, 2.0, 3 * LAG_H, (0, N), cfg)
    assert len(res["events"]) == 1 and abs(res["events"][0]["gain_min"] - LAG_H * 60) <= 30
