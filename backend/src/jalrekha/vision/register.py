"""Register a frame to the site's reference frame so the gauge calibration holds.

Fixed cameras still move: wind, mast sway, a bumped housing. Registration is
two-tier, mirroring the agent's cheap-then-expensive pattern:

1. ORB + brute-force Hamming + RANSAC similarity fit (~tens of ms).
2. If ORB fails (too few inliers, e.g. rain, night, heavy blur), ALIKED
   keypoints matched with LightGlue, both from the OpenCV 5 features module
   running on the new DNN graph engine (~1 s on CPU).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import numpy as np

from jalrekha.vision import models

MIN_INLIERS = 20
MAX_MEDIAN_RESIDUAL_PX = 2.5
WORK_SIDE = 640


@dataclass
class Registration:
    ok: bool
    method: str  # identity | orb | aliked_lightglue | failed
    matrix: np.ndarray  # 2x3, current -> reference (full resolution)
    inliers: int
    residual_px: float
    drift_px: float
    ms: float
    tried: list[str]

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "method": self.method,
            "inliers": self.inliers,
            "residual_px": round(self.residual_px, 3),
            "drift_px": round(self.drift_px, 2),
            "ms": round(self.ms, 2),
            "tried": self.tried,
        }


_ORB = None
_ALIKED = None
_LG = None


def _gray_small(img: np.ndarray) -> tuple[np.ndarray, float]:
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    s = WORK_SIDE / max(g.shape[:2])
    if s < 1.0:
        g = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    else:
        s = 1.0
    return g, s


def _fit(p_cur: np.ndarray, p_ref: np.ndarray, s_cur: float, s_ref: float) -> tuple[np.ndarray | None, int, float]:
    if len(p_cur) < 6:
        return None, 0, float("inf")
    m, inl = cv2.estimateAffinePartial2D(
        p_cur, p_ref, method=cv2.RANSAC, ransacReprojThreshold=2.0, maxIters=2000, confidence=0.995
    )
    if m is None or inl is None:
        return None, 0, float("inf")
    mask = inl.ravel().astype(bool)
    proj = (m[:, :2] @ p_cur[mask].T).T + m[:, 2]
    resid = float(np.median(np.linalg.norm(proj - p_ref[mask], axis=1))) if mask.any() else float("inf")
    # Lift from working scale to full resolution: x_ref = (A (s_cur x) + t) / s_ref
    full = m.copy()
    full[:, :2] = m[:, :2] * (s_cur / s_ref)
    full[:, 2] = m[:, 2] / s_ref
    return full, int(mask.sum()), resid


def _orb(cur: np.ndarray, ref: np.ndarray) -> tuple[np.ndarray | None, int, float]:
    global _ORB
    if _ORB is None:
        _ORB = cv2.ORB_create(nfeatures=1500, fastThreshold=12)
    gc, sc = _gray_small(cur)
    gr, sr = _gray_small(ref)
    kc, dc = _ORB.detectAndCompute(gc, None)
    kr, dr = _ORB.detectAndCompute(gr, None)
    if dc is None or dr is None or len(kc) < 8 or len(kr) < 8:
        return None, 0, float("inf")
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    pairs = matcher.knnMatch(dc, dr, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.8 * p[1].distance]
    p_cur = np.float32([kc[m.queryIdx].pt for m in good])
    p_ref = np.float32([kr[m.trainIdx].pt for m in good])
    return _fit(p_cur, p_ref, sc, sr)


def aliked_available() -> bool:
    return models.model_path("aliked") is not None and models.model_path("lightglue") is not None


def _aliked(cur: np.ndarray, ref: np.ndarray) -> tuple[np.ndarray | None, int, float]:
    global _ALIKED, _LG
    if not aliked_available():
        return None, 0, float("inf")
    if _ALIKED is None:
        _ALIKED = cv2.ALIKED_create(str(models.model_path("aliked")))
        _LG = cv2.LightGlueMatcher_create(str(models.model_path("lightglue")))
    gc, sc = _gray_small(cur)
    gr, sr = _gray_small(ref)
    bc = cv2.cvtColor(gc, cv2.COLOR_GRAY2BGR)
    br = cv2.cvtColor(gr, cv2.COLOR_GRAY2BGR)
    kc, dc = _ALIKED.detectAndCompute(bc, None)
    kr, dr = _ALIKED.detectAndCompute(br, None)
    if dc is None or dr is None or len(kc) < 8 or len(kr) < 8:
        return None, 0, float("inf")
    pc = np.float32([k.pt for k in kc])
    pr = np.float32([k.pt for k in kr])
    _LG.setPairInfo(pc, pr, (gc.shape[1], gc.shape[0]), (gr.shape[1], gr.shape[0]))
    matches = _LG.match(dc, dr)
    p_cur = np.float32([kc[m.queryIdx].pt for m in matches])
    p_ref = np.float32([kr[m.trainIdx].pt for m in matches])
    return _fit(p_cur, p_ref, sc, sr)


def _drift(m: np.ndarray, probe: np.ndarray) -> float:
    proj = (m[:, :2] @ probe.T).T + m[:, 2]
    return float(np.max(np.linalg.norm(proj - probe, axis=1)))


def register(
    cur: np.ndarray,
    ref: np.ndarray | None,
    *,
    probe_points: np.ndarray | None = None,
    allow_heavy: bool = True,
    force_heavy: bool = False,
) -> Registration:
    t0 = time.perf_counter()
    identity = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    if ref is None:
        return Registration(True, "identity", identity, 0, 0.0, 0.0, 0.0, [])
    h, w = ref.shape[:2]
    probe = probe_points if probe_points is not None else np.float32([[w * 0.5, h * 0.5]])
    tried: list[str] = []
    best = (None, 0, float("inf"))
    method = "failed"
    if not force_heavy:
        tried.append("orb")
        best = _orb(cur, ref)
        if best[0] is not None and best[1] >= MIN_INLIERS and best[2] <= MAX_MEDIAN_RESIDUAL_PX:
            method = "orb"
    if method == "failed" and allow_heavy and aliked_available():
        tried.append("aliked_lightglue")
        heavy = _aliked(cur, ref)
        if heavy[0] is not None and heavy[1] >= MIN_INLIERS and heavy[2] <= MAX_MEDIAN_RESIDUAL_PX:
            best, method = heavy, "aliked_lightglue"
    ms = (time.perf_counter() - t0) * 1000
    if method == "failed":
        m = best[0] if best[0] is not None else identity
        return Registration(False, "failed", identity, best[1], best[2], _drift(m, probe), ms, tried)
    m = best[0]
    return Registration(True, method, m, best[1], best[2], _drift(m, probe), ms, tried)


def warp_to_reference(cur: np.ndarray, reg: Registration, ref_shape: tuple[int, int]) -> np.ndarray:
    if reg.method in {"identity", "failed"}:
        return cur
    h, w = ref_shape
    return cv2.warpAffine(cur, reg.matrix, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def burst_offsets(frames: list[np.ndarray]) -> list[tuple[float, float]]:
    """Translation of each burst frame relative to the last one (phase correlation).

    Wind shake differs frame to frame inside a burst. ORB registers the last
    frame to the reference; phase correlation (sub-millisecond on a 320 px
    copy) then aligns the other burst frames to the last one.
    """
    if len(frames) < 2:
        return [(0.0, 0.0)] * len(frames)
    last, s = _gray_small(frames[-1])
    scale = 320 / max(last.shape[:2])
    small = lambda g: cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA).astype(np.float32)  # noqa: E731
    ref = small(last)
    win = cv2.createHanningWindow((ref.shape[1], ref.shape[0]), cv2.CV_32F)
    out = []
    for f in frames[:-1]:
        g, _ = _gray_small(f)
        (dx, dy), _resp = cv2.phaseCorrelate(small(g), ref, win)
        out.append((dx / (scale * s), dy / (scale * s)))
    out.append((0.0, 0.0))
    return out


def compose_with_offset(reg: Registration, dx: float, dy: float) -> np.ndarray:
    """Matrix taking a burst frame -> reference: first shift onto the last frame, then reg."""
    base = reg.matrix if reg.method not in {"identity", "failed"} else np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    m = base.copy()
    m[:, 2] = base[:, :2] @ np.array([dx, dy]) + base[:, 2]
    return m
