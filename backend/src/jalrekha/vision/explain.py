"""Vision Lab: what the OpenCV pipeline did for one cycle, stage by stage.

:func:`explain` runs the normal :func:`~jalrekha.vision.pipeline.measure` with
its opt-in ``capture`` dict, so every number here comes from the same run
that produced the reading. It then turns the intermediates into small JPEG
data URLs (always from redacted frames) and per-row arrays for the UI:

1. quality gate: each metric against its threshold, plus a |Laplacian| heat map
2. registration: inlier matches (cv2.drawMatches) and a reference/aligned checkerboard
3. gauge strip: the warpAffine strip of the last frame and the burst median
4. estimator profiles: the per-row signal each estimator fitted, rows in metres
5. fusion: per-estimator metres, the weighted median, sigma and agreement
6. timing: per-stage milliseconds and the host's OpenCV build
7. privacy: faces and plates blurred by YuNet

The normal measurement path does not import this module.
"""

from __future__ import annotations

import base64
import dataclasses
import functools
import os
import platform

import cv2
import numpy as np

from jalrekha.vision import privacy, quality, register
from jalrekha.vision.fuse import DISAGREE_M, MIN_CONF, PRIOR, STILL_WATER_E1_FACTOR
from jalrekha.vision.gauge import GaugeCalibration
from jalrekha.vision.pipeline import ALL_ESTIMATORS, MeasureOptions, _strip_mask, measure

SCHEMA = "jalrekha-vision-lab-v1"
MAX_IMAGE_BYTES = 250_000
STAGE_ORDER = (
    "register", "warp", "quality", "median", "E1_edge", "E2_temporal", "E3_colour",
    "fuse", "surface_motion", "redact", "overlay",
)
LIME_BGR = (61, 255, 198)  # #C6FF3D
GRAPHITE_BGR = (17, 18, 18)  # #121211
MATCHES_DRAWN = 60
STRIP_DISPLAY_SCALE = 4

ESTIMATOR_OPS = {
    "E1_edge": "cv2.Scharr(gray, CV_32F, 0, 1) -> mean |d/dy| per row -> cv2.GaussianBlur -> log1p",
    "E2_temporal": "cv2.DISOpticalFlow (FAST) between burst strips + per-pixel temporal std -> log1p -> cv2.GaussianBlur",
    "E3_colour": "cv2.cvtColor(BGR2Lab) -> mean L*a*b* per row -> cv2.GaussianBlur",
}
QUALITY_METRICS = (
    # key, threshold, rule ("min" = value must be at least the threshold), OpenCV call
    ("blur_var", quality.BLUR_MIN_VAR, "min", "cv2.Laplacian(strip, CV_64F).var()"),
    ("mean_luma", quality.NIGHT_MAX_MEAN, "min", "mean grey level of the frame"),
    ("clipped_frac", quality.CLIP_MAX_FRAC, "max", "cv2.calcHist: share of pixels at 0-5 or 250-255"),
    ("glare_frac", quality.GLARE_MAX_FRAC, "max", "share of strip pixels at 250 or above"),
    ("strip_contrast", quality.CONTRAST_MIN_STD, "min", "cv2.meanStdDev(strip)"),
)


# ------------------------------------------------------------------ images
def jpeg_data_url(img: np.ndarray, max_side: int = 960, quality_: int = 82) -> str:
    """JPEG data URL no larger than MAX_IMAGE_BYTES (lower quality, then smaller size)."""
    h, w = img.shape[:2]
    s = max_side / max(h, w)
    if s < 1.0:
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    while True:
        for q in (quality_, 72, 62, 50):
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
            if ok and buf.nbytes <= MAX_IMAGE_BYTES:
                return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
        img = cv2.resize(img, None, fx=0.75, fy=0.75, interpolation=cv2.INTER_AREA)


@functools.lru_cache(maxsize=1)
def _lime_lut() -> np.ndarray:
    """256-entry colour map from graphite to lime, for cv2.applyColorMap."""
    t = np.linspace(0.0, 1.0, 256) ** 0.75
    lo, hi = np.array(GRAPHITE_BGR, float), np.array(LIME_BGR, float)
    return (lo + (hi - lo) * t[:, None]).astype(np.uint8).reshape(256, 1, 3)


def _strip_polygon(calib: GaugeCalibration) -> np.ndarray:
    m = calib.strip_transform()
    w = calib.strip_half_width_px * 2
    length = calib.strip_length_px()
    corners = np.array([[0, 0, 1], [w, 0, 1], [w, length, 1], [0, length, 1]]).T
    return (m @ corners).T.astype(np.int32)


def laplacian_heatmap(frame_bgr: np.ndarray, calib: GaugeCalibration) -> np.ndarray:
    """|Laplacian| of the frame through a graphite-to-lime colour map, gauge strip outlined."""
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY) if frame_bgr.ndim == 3 else frame_bgr
    lap = cv2.convertScaleAbs(cv2.Laplacian(gray, cv2.CV_16S, ksize=3))
    top = max(float(np.percentile(lap, 99.5)), 1.0)
    u8 = cv2.convertScaleAbs(lap, alpha=255.0 / top)
    heat = cv2.applyColorMap(u8, _lime_lut())
    cv2.polylines(heat, [_strip_polygon(calib)], True, (243, 242, 238), 2, cv2.LINE_AA)
    return heat


def checkerboard(a: np.ndarray, b: np.ndarray, block: int = 64) -> np.ndarray:
    """Alternate blocks of two same-size images; misalignment shows as broken edges."""
    if b.shape[:2] != a.shape[:2]:
        b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
    yy, xx = np.indices(a.shape[:2])
    pick = ((yy // block + xx // block) % 2).astype(bool)
    return np.where(pick[..., None], a, b)


def match_image(cur_bgr: np.ndarray, ref_bgr: np.ndarray, ms: register.MatchSet, mask: np.ndarray,
                limit: int = MATCHES_DRAWN) -> tuple[np.ndarray, int]:
    """All keypoints (grey) and up to ``limit`` RANSAC inliers (lime), at the matcher's working scale."""
    c = cv2.resize(cur_bgr, (ms.gray_cur.shape[1], ms.gray_cur.shape[0]), interpolation=cv2.INTER_AREA)
    r = cv2.resize(ref_bgr, (ms.gray_ref.shape[1], ms.gray_ref.shape[0]), interpolation=cv2.INTER_AREA)
    grey = (150, 150, 150)
    c = cv2.drawKeypoints(c, ms.kp_cur, None, color=grey)
    r = cv2.drawKeypoints(r, ms.kp_ref, None, color=grey)
    inl = [m for m, keep in zip(ms.matches, mask) if keep]
    if len(inl) > limit:
        # Evenly spaced over the best-scoring half so the lines cover the frame.
        inl = sorted(inl, key=lambda m: m.distance)
        inl = [inl[int(i)] for i in np.linspace(0, len(inl) - 1, limit)]
    img = cv2.drawMatches(c, ms.kp_cur, r, ms.kp_ref, inl, None, matchColor=LIME_BGR,
                          flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS)
    return img, len(inl)


def _blur_boxes_copy(img: np.ndarray, boxes: list[list[int]]) -> np.ndarray:
    if not boxes:
        return img
    out = img.copy()
    privacy._blur_boxes(out, [b[:4] for b in boxes])
    return out


# ------------------------------------------------------------------ numbers
def _r(v, nd: int = 4):
    return None if v is None else round(float(v), nd)


def _arr(a: np.ndarray | None, nd: int = 4) -> list[float] | None:
    return None if a is None else [round(float(x), nd) for x in np.asarray(a, float).ravel()]


def display_signal(name: str, features: np.ndarray, row: float | None) -> np.ndarray:
    """One curve per estimator for the chart.

    E1 fits a single feature, shown as is. E2 fits two (temporal std, flow):
    shown as their mean after standardising. E3 fits three (L*, a*, b*):
    shown projected onto the direction between the mean colour above and
    below the chosen row, which is the step the fit found.
    """
    f = np.asarray(features, np.float64)
    if f.ndim == 1 or f.shape[1] == 1:
        return f.ravel()
    z = (f - f.mean(axis=0)) / (f.std(axis=0) + 1e-9)
    if name == "E2_temporal":
        return z.mean(axis=1)
    n = len(z)
    if row is None or not 4 <= int(row) <= n - 4:
        return z[:, 0]
    k = int(row)
    d = z[:k].mean(axis=0) - z[k:].mean(axis=0)
    norm = float(np.linalg.norm(d))
    return z[:, 0] if norm < 1e-9 else z @ (d / norm)


def agreeing(per: dict[str, float | None], fused: float | None, tol: float = DISAGREE_M) -> list[str]:
    """Estimators in at least one pair within ``tol`` of each other whose midpoint is within ``tol`` of the fused value."""
    names = [k for k, v in per.items() if v is not None]
    members: set[str] = set()
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            va, vb = per[a], per[b]
            if abs(va - vb) <= tol and (fused is None or abs((va + vb) / 2 - fused) <= tol):
                members |= {a, b}
    return [n for n in names if n in members]


@functools.lru_cache(maxsize=1)
def host_info() -> dict:
    """Machine, OpenCV version and the CPU / HAL lines of cv2.getBuildInformation()."""
    info = cv2.getBuildInformation()
    lines = info.splitlines()
    cpu: list[str] = []
    in_cpu = False
    for ln in lines:
        if ln.strip().startswith("CPU/HW features"):
            in_cpu = True
            continue
        if in_cpu:
            if not ln.strip():
                break
            cpu.append(" ".join(ln.split()))
    pick = lambda key: next((" ".join(ln.split()) for ln in lines if key in ln), None)  # noqa: E731
    return {
        "machine": platform.machine(),
        "system": platform.system(),
        "python": platform.python_version(),
        "opencv": cv2.__version__,
        "cpu_count": os.cpu_count(),
        "cpu_features": cpu[:3],
        "hal": [" ".join(ln.split()) for ln in lines if "HAL" in ln][:3],
        "kleidicv": "kleidicv" in info.lower(),
        "ipp": pick("Intel IPP:"),
        "parallel": pick("Parallel framework"),
    }


# ------------------------------------------------------------------ explain
def explain(
    frames: list[np.ndarray],
    calib: GaugeCalibration,
    reference: np.ndarray | None = None,
    options: MeasureOptions | None = None,
) -> dict:
    """Run one measurement with capture on and describe every stage (see module docstring)."""
    # Every image below must come from a redacted frame.
    opts = dataclasses.replace(options or MeasureOptions(burst_dt_s=0.5), redact=True, draw_overlay=True)
    cap: dict = {}
    m = measure(frames, calib, reference, opts, capture=cap)
    aligned: list[np.ndarray] = cap["aligned"]
    shown = m.redacted_bgr if m.redacted_bgr is not None else aligned[-1]
    red = m.redaction
    boxes = red.boxes if red is not None else []

    # 1. Quality ---------------------------------------------------------------
    q = m.quality
    metrics = []
    for key, thr, rule, op in QUALITY_METRICS:
        v = float(getattr(q, key))
        ok = v >= thr if rule == "min" else v <= thr
        metrics.append({"key": key, "value": round(v, 4), "threshold": thr, "rule": rule, "pass": bool(ok), "op": op})
    quality_sec = {
        "ok": q.ok, "reasons": q.reasons, "night": q.night, "metrics": metrics,
        "heatmap_image": jpeg_data_url(laplacian_heatmap(shown, calib), 720),
    }

    # 2. Registration ------------------------------------------------------------
    reg = m.registration
    reg_sec: dict = {**reg.to_dict(), "matrix": [[round(float(x), 5) for x in row] for row in reg.matrix],
                     "reference": "calibration" if reference is not None else None,
                     "matches_image": None, "compare_image": None, "matcher": None,
                     "keypoints_current": 0, "keypoints_reference": 0, "matches": 0,
                     "inliers_shown": 0, "inliers_drawn": 0}
    ref_faces = ref_plates = None
    if reference is not None:
        cur_red, _ = privacy.redact(frames[-1], keep_mask=_strip_mask(calib, frames[-1].shape[:2]))
        ref_red, ref_report = privacy.redact(reference, keep_mask=_strip_mask(calib, reference.shape[:2]))
        ref_faces, ref_plates = ref_report.faces, ref_report.plates
        method = "aliked_lightglue" if reg.method == "aliked_lightglue" else "orb"
        ms, mask = register.inlier_matches(frames[-1], reference, method)
        if ms is not None:
            img, drawn = match_image(cur_red, ref_red, ms, mask)
            reg_sec.update(matcher=method, keypoints_current=len(ms.kp_cur), keypoints_reference=len(ms.kp_ref),
                           matches=len(ms.matches), inliers_shown=int(mask.sum()), inliers_drawn=drawn,
                           matches_image=jpeg_data_url(img, 1280, 78))
        reg_sec["compare_image"] = jpeg_data_url(checkerboard(ref_red, shown), 960)

    # 3. Gauge strip -------------------------------------------------------------
    if boxes:
        strips = [calib.extract_strip(_blur_boxes_copy(a, boxes)) for a in aligned]
        still = np.median(np.stack(strips), axis=0).astype(np.uint8) if len(strips) > 1 else strips[-1]
    else:
        strips, still = cap["strips"], cap["still"]
    rows = int(cap["strips"][-1].shape[0])
    widen = lambda s: cv2.resize(s, (s.shape[1] * STRIP_DISPLAY_SCALE, s.shape[0]), interpolation=cv2.INTER_NEAREST)  # noqa: E731
    strip_sec = {
        "rows": rows, "width_px": int(strips[-1].shape[1]), "display_scale_x": STRIP_DISPLAY_SCALE, "frames": len(strips),
        "transform": [[round(float(x), 5) for x in row] for row in calib.strip_transform()],
        "last_image": jpeg_data_url(widen(strips[-1]), 1200, 88),
        "median_image": jpeg_data_url(widen(still), 1200, 88),
    }

    # 4. Estimator profiles ------------------------------------------------------
    per = m.reading.per_estimator_m
    still_water = any(e.name == "E2_temporal" and e.detail.get("still_water") for e in m.estimates)
    profiles = cap["profiles"]
    est_list = []
    for e in m.estimates:
        feats = profiles.get(e.name)
        weight = None
        if e.row is not None and e.confidence >= MIN_CONF:
            weight = e.confidence * PRIOR.get(e.name, 0.5) * (STILL_WATER_E1_FACTOR if still_water and e.name == "E1_edge" else 1.0)
        channels = None
        if feats is not None and np.asarray(feats).ndim == 2:
            channels = [_arr(np.asarray(feats)[:, i]) for i in range(np.asarray(feats).shape[1])]
        est_list.append({
            "name": e.name, "row": _r(e.row, 2), "stage_m": _r(per.get(e.name)), "confidence": round(e.confidence, 3),
            "separation": round(e.separation, 3), "used": e.name in m.reading.used, "weight": _r(weight, 3),
            "detail": e.detail, "op": ESTIMATOR_OPS.get(e.name),
            "signal": None if feats is None else _arr(display_signal(e.name, feats, e.row)),
            "channels": channels,
        })
    order = {n: i for i, n in enumerate(ALL_ESTIMATORS)}
    est_list.sort(key=lambda d: order.get(d["name"], 99))
    profiles_sec = {
        "rows": rows,
        "axis_m": [round(calib.strip_row_to_stage(r), 4) for r in range(rows)],
        "marks": [{"row": round(calib.stage_to_strip_row(mk.stage_m), 2), "stage_m": mk.stage_m} for mk in calib.marks],
        "warning_m": calib.warning_m, "danger_m": calib.danger_m,
        "metres_per_px": round(calib.metres_per_px(), 6),
        "estimators": est_list,
    }

    # 5. Fusion ------------------------------------------------------------------
    rd = m.reading
    fused_row = None if rd.stage_m is None else round(calib.stage_to_strip_row(rd.stage_m), 2)
    fusion_sec = {
        "per_estimator_m": {k: _r(v) for k, v in per.items()},
        "fused_m": _r(rd.stage_m), "fused_row": fused_row, "sigma_m": _r(rd.sigma_m), "confidence": round(rd.confidence, 3),
        "spread_m": _r(rd.spread_m), "used": rd.used, "agree_all_used": rd.agree,
        "agreeing": agreeing(per, rd.stage_m), "tolerance_m": DISAGREE_M,
        "rule": "weighted median of estimators with confidence >= 0.15; weight = confidence x reliability prior",
    }

    # 6. Timing ------------------------------------------------------------------
    t = m.timings_ms
    start = 0.0
    stages = []
    for name in STAGE_ORDER:
        if name in t:
            stages.append({"name": name, "ms": round(t[name], 3), "start_ms": round(start, 3)})
            start += t[name]
    timing_sec = {"stages": stages, "total_ms": round(t.get("total", start), 3), "host": host_info()}

    # 7. Privacy -----------------------------------------------------------------
    rdict = red.to_dict() if red is not None else {}
    privacy_sec = {
        "faces": red.faces if red is not None else None, "plates": red.plates if red is not None else None,
        "face_detector": rdict.get("face_detector"), "plate_detector": rdict.get("plate_detector"),
        "mode": rdict.get("mode"), "reference_faces": ref_faces, "reference_plates": ref_plates,
        "images_redacted": True,
    }

    return {
        "schema": SCHEMA,
        "opencv_version": cv2.__version__,
        "summary": {
            "stage_m": _r(rd.stage_m), "sigma_m": _r(rd.sigma_m), "usable": m.usable, "frames": m.frames,
            "notes": m.notes, "surface_motion": m.surface,
            "overlay_image": jpeg_data_url(m.overlay_bgr, 960) if m.overlay_bgr is not None else None,
        },
        "quality": quality_sec,
        "registration": reg_sec,
        "strip": strip_sec,
        "profiles": profiles_sec,
        "fusion": fusion_sec,
        "timing": timing_sec,
        "privacy": privacy_sec,
    }
