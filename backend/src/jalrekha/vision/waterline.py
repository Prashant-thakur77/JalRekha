"""Waterline estimators on the gauge strip.

All three estimators build a per-row feature profile along the gauge axis
(row 0 = top of the strip) and fit a two-segment step model to it: the
gauge face above the waterline looks different from the water below. They
differ only in *which* evidence they use, so they fail in different ways:

- E1 edge energy: printed gauge marks give strong horizontal edges; water
  (even rippled) gives weaker, less regular ones.
- E2 temporal texture: across a short burst, water rows change (DIS optical
  flow + temporal std) while the gauge rows stay still.
- E3 colour: gauge paint versus water colour in Lab space.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Estimate:
    name: str
    row: float | None  # strip row of the waterline (None = no estimate)
    confidence: float  # 0..1
    separation: float  # Fisher-like separation of the two segments
    detail: dict

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "row": None if self.row is None else round(self.row, 2),
            "confidence": round(self.confidence, 3),
            "separation": round(self.separation, 3),
            "detail": self.detail,
        }


def _smooth(profile: np.ndarray, k: int) -> np.ndarray:
    k = max(1, int(k) | 1)
    if profile.ndim == 1:
        profile = profile[:, None]
    return cv2.GaussianBlur(profile.astype(np.float32), (1, k), 0)


def step_fit(features: np.ndarray, *, min_seg: int = 4, expect_upper_higher: int | None = None) -> tuple[int | None, float]:
    """Best single change point of a (rows, k) feature profile.

    Minimises the within-segment sum of squares (a 1-D two-class Otsu over
    rows). Returns (row, separation) where separation is the between-segment
    distance divided by the pooled within-segment std. If
    ``expect_upper_higher`` is +1/-1, only splits where the first feature's
    upper-segment mean is higher/lower are accepted.
    """
    x = np.asarray(features, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    n = x.shape[0]
    if n < 2 * min_seg:
        return None, 0.0
    c1 = np.cumsum(x, axis=0)
    c2 = np.cumsum(x * x, axis=0)
    r = np.arange(min_seg, n - min_seg + 1)
    n_a = r[:, None].astype(np.float64)
    n_b = (n - r)[:, None].astype(np.float64)
    s1a, s2a = c1[r - 1], c2[r - 1]
    s1b, s2b = c1[-1] - s1a, c2[-1] - s2a
    var_a = s2a - s1a * s1a / n_a
    var_b = s2b - s1b * s1b / n_b
    cost = np.sum(var_a + var_b, axis=1)
    mean_a, mean_b = s1a / n_a, s1b / n_b
    if expect_upper_higher is not None:
        bad = mean_a[:, 0] <= mean_b[:, 0] if expect_upper_higher > 0 else mean_a[:, 0] >= mean_b[:, 0]
        cost = np.where(bad, np.inf, cost)
    i = int(np.argmin(cost))
    if not np.isfinite(cost[i]):
        return None, 0.0
    pooled = np.sqrt(np.maximum((var_a[i] + var_b[i]) / max(n - 2, 1), 1e-12))
    sep = float(np.linalg.norm((mean_a[i] - mean_b[i]) / pooled) / np.sqrt(x.shape[1]))
    return int(r[i]), sep


def _confidence(separation: float, scale: float) -> float:
    return float(1.0 - np.exp(-max(separation, 0.0) / scale))


SATURATED = 245


def _saturated_rows(gray: np.ndarray, frac: float = 0.4) -> np.ndarray:
    return (gray >= SATURATED).mean(axis=1) > frac


def _repair_rows(profile: np.ndarray, bad: np.ndarray) -> np.ndarray:
    """Replace feature rows hit by specular glare with linear interpolation."""
    if not bad.any() or bad.all():
        return profile
    out = profile.astype(np.float64).copy()
    idx = np.arange(len(bad))
    good = ~bad
    cols = out if out.ndim == 2 else out[:, None]
    for c in range(cols.shape[1]):
        cols[bad, c] = np.interp(idx[bad], idx[good], cols[good, c])
    return cols if out.ndim == 2 else cols[:, 0]


def edge_energy(strip_bgr: np.ndarray) -> Estimate:
    return edge_energy_profile(strip_bgr)[0]


def edge_energy_profile(strip_bgr: np.ndarray) -> tuple[Estimate, np.ndarray]:
    """E1 plus the per-row feature it fitted: smoothed log Scharr energy, shape (rows,)."""
    gray = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2GRAY) if strip_bgr.ndim == 3 else strip_bgr
    bad = _saturated_rows(gray)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    gy = cv2.Scharr(gray, cv2.CV_32F, 0, 1)
    row_energy = _repair_rows(np.abs(gy).mean(axis=1), bad)
    win = max(5, gray.shape[0] // 40)
    prof = _smooth(row_energy, win * 2 + 1).ravel()
    prof = np.log1p(prof)
    row, sep = step_fit(prof, expect_upper_higher=+1)
    est = Estimate("E1_edge", None if row is None else float(row), _confidence(sep, 1.5), sep, {"window": win, "glare_rows": int(bad.sum())})
    return est, prof


def colour_step(strip_bgr: np.ndarray) -> Estimate:
    return colour_step_profile(strip_bgr)[0]


def colour_step_profile(strip_bgr: np.ndarray) -> tuple[Estimate, np.ndarray]:
    """E3 plus the per-row feature it fitted: smoothed mean L*, a*, b*, shape (rows, 3)."""
    lab = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2Lab).astype(np.float32)
    gray = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2GRAY)
    bad = _saturated_rows(gray)
    rows = _repair_rows(lab.mean(axis=1), bad)  # (rows, 3)
    win = max(3, strip_bgr.shape[0] // 60)
    rows = _smooth(rows, win * 2 + 1).reshape(-1, 3)
    # Gauge paint is brighter than water in every scene we target: require
    # higher L above the split, which removes splits inside the water body.
    row, sep = step_fit(rows, expect_upper_higher=+1)
    est = Estimate("E3_colour", None if row is None else float(row), _confidence(sep, 2.0), sep, {"window": win, "glare_rows": int(bad.sum())})
    return est, rows


_DIS_LOCAL = threading.local()


def _dis():
    """One DIS optical-flow object per thread: it keeps internal buffers between calls."""
    dis = getattr(_DIS_LOCAL, "dis", None)
    if dis is None:
        dis = _DIS_LOCAL.dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_FAST)
    return dis


def temporal_texture(strips_bgr: list[np.ndarray]) -> Estimate:
    return temporal_texture_profile(strips_bgr)[0]


def temporal_texture_profile(strips_bgr: list[np.ndarray]) -> tuple[Estimate, np.ndarray | None]:
    """E2 plus the per-row feature it fitted: smoothed log temporal std and log DIS flow
    magnitude, shape (rows, 2). The profile is None when the burst is too short."""
    if len(strips_bgr) < 3:
        return Estimate("E2_temporal", None, 0.0, 0.0, {"reason": "needs_burst_of_3"}), None
    grays = [cv2.cvtColor(s, cv2.COLOR_BGR2GRAY) if s.ndim == 3 else s for s in strips_bgr]
    stack = np.stack([g.astype(np.float32) for g in grays], axis=0)
    tstd = stack.std(axis=0).mean(axis=1)
    flows = []
    for a, b in zip(grays[:-1], grays[1:]):
        f = _dis().calc(a, b, None)
        flows.append(np.linalg.norm(f, axis=2).mean(axis=1))
    flow = np.mean(flows, axis=0)
    win = max(5, grays[0].shape[0] // 40)
    feats = np.stack([np.log1p(tstd), np.log1p(flow * 4.0)], axis=1)
    feats = _smooth(feats, win * 2 + 1).reshape(-1, 2)
    row, sep = step_fit(feats, expect_upper_higher=-1)
    still = float(np.median(tstd)) < 0.6 and float(np.median(flow)) < 0.05
    conf = 0.0 if still else _confidence(sep, 1.5)
    est = Estimate(
        "E2_temporal",
        None if (row is None or still) else float(row),
        conf,
        sep,
        {"frames": len(strips_bgr), "still_water": still},
    )
    return est, feats


def naive_max_edge(strip_bgr: np.ndarray) -> Estimate:
    """Baseline B1: the single strongest horizontal edge row in the strip."""
    gray = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2GRAY) if strip_bgr.ndim == 3 else strip_bgr
    gy = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)).mean(axis=1)
    row = int(np.argmax(gy))
    return Estimate("B1_naive_max_edge", float(row), 0.5, 0.0, {})
