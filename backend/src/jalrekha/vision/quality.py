"""Cheap deterministic quality gate, run before any estimator or model call."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

# Thresholds are on 8-bit grey levels at the analysis scale. They were set on
# the synthetic *train* seeds and frozen in eval/config.frozen.json.
BLUR_MIN_VAR = 25.0
NIGHT_MAX_MEAN = 45.0
CLIP_MAX_FRAC = 0.35
GLARE_MAX_FRAC = 0.25
CONTRAST_MIN_STD = 9.0


@dataclass
class QualityReport:
    ok: bool
    blur_var: float
    mean_luma: float
    clipped_frac: float
    glare_frac: float
    strip_contrast: float
    night: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, float):
                d[k] = round(v, 3)
        return d


def assess_quality(frame_bgr: np.ndarray, strip_bgr: np.ndarray | None = None) -> QualityReport:
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY) if frame_bgr.ndim == 3 else frame_bgr
    target = gray
    if strip_bgr is not None and strip_bgr.size:
        target = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2GRAY) if strip_bgr.ndim == 3 else strip_bgr

    blur_var = float(cv2.Laplacian(target, cv2.CV_64F).var())
    mean_luma = float(gray.mean())
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).ravel()
    total = max(float(hist.sum()), 1.0)
    clipped = float(hist[:6].sum() + hist[250:].sum()) / total
    glare = float((target >= 250).mean())
    _, std = cv2.meanStdDev(target)
    contrast = float(std.ravel()[0])

    reasons: list[str] = []
    night = mean_luma < NIGHT_MAX_MEAN
    if night:
        reasons.append("night_or_underexposed")
    if blur_var < BLUR_MIN_VAR:
        reasons.append("blurred")
    if clipped > CLIP_MAX_FRAC:
        reasons.append("exposure_clipped")
    if glare > GLARE_MAX_FRAC:
        reasons.append("glare_on_gauge")
    if contrast < CONTRAST_MIN_STD:
        reasons.append("low_contrast_fog_or_occlusion")

    return QualityReport(
        ok=not reasons,
        blur_var=blur_var,
        mean_luma=mean_luma,
        clipped_frac=clipped,
        glare_frac=glare,
        strip_contrast=contrast,
        night=night,
        reasons=reasons,
    )
