"""Fuse estimator outputs into one stage reading with an uncertainty."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from jalrekha.vision.gauge import GaugeCalibration
from jalrekha.vision.waterline import Estimate

# Estimators that disagree by more than this are flagged; the agent treats a
# flagged reading as "needs verification" (decision branch D3).
DISAGREE_M = 0.10
MIN_CONF = 0.15
# Reliability priors per estimator, from the synthetic TRAIN seeds only
# (eval/results/stage_synth_train_quick.json: clean MAE E3 1.8 cm, E2 5.0 cm,
# E1 9.7 cm). Multiplied with each estimator's own confidence.
PRIOR = {"E1_edge": 0.35, "E2_temporal": 0.7, "E3_colour": 1.0, "B1_naive_max_edge": 1.0}
# Still water mirrors the gauge, so edge energy continues below the waterline.
STILL_WATER_E1_FACTOR = 0.3


@dataclass
class StageReading:
    stage_m: float | None
    sigma_m: float | None
    confidence: float
    agree: bool
    spread_m: float | None
    used: list[str]
    per_estimator_m: dict[str, float | None]

    def to_dict(self) -> dict:
        r = lambda v: None if v is None else round(float(v), 4)  # noqa: E731
        return {
            "stage_m": r(self.stage_m),
            "sigma_m": r(self.sigma_m),
            "confidence": round(self.confidence, 3),
            "agree": self.agree,
            "spread_m": r(self.spread_m),
            "used": self.used,
            "per_estimator_m": {k: r(v) for k, v in self.per_estimator_m.items()},
        }


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cdf = np.cumsum(w) / w.sum()
    return float(v[np.searchsorted(cdf, 0.5)])


def fuse_estimates(estimates: list[Estimate], calib: GaugeCalibration, scale: float) -> StageReading:
    per: dict[str, float | None] = {}
    vals, wts, names = [], [], []
    still = any(e.name == "E2_temporal" and e.detail.get("still_water") for e in estimates)
    for e in estimates:
        if e.row is None:
            per[e.name] = None
            continue
        stage = calib.strip_row_to_stage(e.row, scale)
        per[e.name] = stage
        if e.confidence >= MIN_CONF:
            w = e.confidence * PRIOR.get(e.name, 0.5)
            if still and e.name == "E1_edge":
                w *= STILL_WATER_E1_FACTOR
            vals.append(stage)
            wts.append(w)
            names.append(e.name)
    if not vals:
        return StageReading(None, None, 0.0, False, None, [], per)
    v, w = np.array(vals), np.array(wts)
    stage = _weighted_median(v, w)
    spread = float(v.max() - v.min()) if len(v) > 1 else None
    # One-pixel quantisation floor plus estimator spread.
    px = calib.metres_per_px() / max(scale, 1e-9)
    sigma = float(np.sqrt(px**2 + (np.sqrt(np.average((v - stage) ** 2, weights=w)) if len(v) > 1 else 0.02) ** 2))
    agree = spread is None or spread <= DISAGREE_M
    raw_conf = [e.confidence for e in estimates if e.name in names]
    conf = float(np.clip(np.mean(raw_conf) * (1.0 if agree else 0.5) * min(1.0, 0.6 + 0.2 * len(v)), 0.0, 1.0))
    return StageReading(stage, sigma, conf, agree, spread, names, per)
