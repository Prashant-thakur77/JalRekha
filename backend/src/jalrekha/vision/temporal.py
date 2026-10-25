"""Temporal filtering of stage readings with cv2.KalmanFilter.

State = [stage_m, rate_m_per_s]. Time steps are irregular (cadence changes
when the agent speeds up capture), so the transition matrix is rebuilt per
step. Readings whose innovation exceeds a Mahalanobis gate are rejected as
outliers (a splash, a person standing in front of the gauge).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import cv2
import numpy as np

GATE_SIGMA = 4.0
# Process noise: how fast the true rise rate can change (m/s^2). 1.5e-7 m/s^2
# lets the rise rate change by about 2 m/h within an hour (flashy hill rivers).
ACCEL_STD = 1.5e-7


@dataclass
class FilteredStage:
    stage_m: float
    rate_m_per_h: float
    stage_sigma_m: float
    rate_sigma_m_per_h: float
    n_used: int
    n_rejected: int

    def to_dict(self) -> dict:
        return {
            "stage_m": round(self.stage_m, 4),
            "rate_m_per_h": round(self.rate_m_per_h, 4),
            "stage_sigma_m": round(self.stage_sigma_m, 4),
            "rate_sigma_m_per_h": round(self.rate_sigma_m_per_h, 4),
            "n_used": self.n_used,
            "n_rejected": self.n_rejected,
        }


def filter_series(readings: list[tuple[datetime, float, float]]) -> FilteredStage | None:
    """readings: (time, stage_m, sigma_m), any order. Returns the latest state."""
    pts = sorted((r for r in readings if r[1] is not None), key=lambda r: r[0])
    if not pts:
        return None
    kf = cv2.KalmanFilter(2, 1, 0, cv2.CV_64F)
    kf.measurementMatrix = np.array([[1.0, 0.0]])
    kf.statePost = np.array([[pts[0][1]], [0.0]])
    kf.errorCovPost = np.diag([max(pts[0][2], 0.01) ** 2, (0.5 / 3600) ** 2])
    used, rejected = 1, 0
    prev_t = pts[0][0]
    for t, z, s in pts[1:]:
        dt = max((t - prev_t).total_seconds(), 1.0)
        prev_t = t
        kf.transitionMatrix = np.array([[1.0, dt], [0.0, 1.0]])
        q = ACCEL_STD**2
        kf.processNoiseCov = q * np.array([[dt**4 / 4, dt**3 / 2], [dt**3 / 2, dt**2]])
        kf.measurementNoiseCov = np.array([[max(s, 0.005) ** 2]])
        pred = kf.predict()
        innov = z - float(pred[0, 0])
        s_tot = float(kf.errorCovPre[0, 0] + kf.measurementNoiseCov[0, 0])
        if abs(innov) / np.sqrt(s_tot) > GATE_SIGMA and used >= 3:
            rejected += 1
            kf.statePost = kf.statePre.copy()
            kf.errorCovPost = kf.errorCovPre.copy()
            continue
        kf.correct(np.array([[z]]))
        used += 1
    st, cov = kf.statePost, kf.errorCovPost
    return FilteredStage(
        stage_m=float(st[0, 0]),
        rate_m_per_h=float(st[1, 0]) * 3600,
        stage_sigma_m=float(np.sqrt(cov[0, 0])),
        rate_sigma_m_per_h=float(np.sqrt(cov[1, 1])) * 3600,
        n_used=used,
        n_rejected=rejected,
    )
