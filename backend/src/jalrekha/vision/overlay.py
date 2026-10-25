"""Debug overlay for the UI, traces and the video."""

from __future__ import annotations

import cv2
import numpy as np

from jalrekha.vision.gauge import GaugeCalibration

COLOURS = {
    "E1_edge": (255, 160, 0),
    "E2_temporal": (255, 255, 0),
    "E3_colour": (200, 0, 255),
    "fused": (0, 255, 0),
    "warning": (0, 200, 255),
    "danger": (0, 0, 255),
}


def _label(img, text: str, org: tuple[int, int], colour, fs: float, right_align: bool = False) -> None:
    """Text on a dark box so it stays legible on water, sky and gauge stripes."""
    th = max(1, int(round(fs * 2)))
    (tw, tht), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, fs, th)
    x, y = org
    if right_align:
        x -= tw
    x = int(np.clip(x, 2, img.shape[1] - tw - 4))
    y = int(np.clip(y, tht + 4, img.shape[0] - base - 2))
    cv2.rectangle(img, (x - 3, y - tht - 3), (x + tw + 3, y + base + 2), (20, 20, 20), -1)
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, fs, colour, th, cv2.LINE_AA)


def _tick(img, calib: GaugeCalibration, stage: float, colour, label: str, length: int = 28, thickness: int = 2,
          fs: float = 0.5, left: bool = False):
    x, y = calib.stage_to_frame_point(stage)
    u = calib.axis_unit
    n = np.array([-u[1], u[0]])
    if n[0] < 0:
        n = -n  # n points to the right of the gauge
    p0 = (int(x - n[0] * length), int(y - n[1] * length))
    p1 = (int(x + n[0] * length), int(y + n[1] * length))
    cv2.line(img, p0, p1, colour, thickness, cv2.LINE_AA)
    if label:
        if left:
            _label(img, label, (p0[0] - 6, p0[1] + 5), colour, fs, right_align=True)
        else:
            _label(img, label, (p1[0] + 6, p1[1] + 5), colour, fs)


def draw_debug(
    frame: np.ndarray,
    calib: GaugeCalibration,
    per_estimator_m: dict[str, float | None],
    fused_m: float | None,
    sigma_m: float | None,
    quality_reasons: list[str],
    method: str,
) -> np.ndarray:
    img = frame.copy()
    h, w_img = img.shape[:2]
    fs = max(0.4, min(1.0, w_img / 960 * 0.55))
    m = calib.strip_transform()
    w = calib.strip_half_width_px * 2
    corners = np.array([[0, 0, 1], [w, 0, 1], [w, calib.strip_length_px(), 1], [0, calib.strip_length_px(), 1]]).T
    poly = (m @ corners).T.astype(np.int32)
    cv2.polylines(img, [poly], True, (255, 255, 255), 1, cv2.LINE_AA)
    for mark in calib.marks:
        cv2.circle(img, (int(mark.x), int(mark.y)), 3, (255, 255, 255), -1, cv2.LINE_AA)
    # Level lines on the left of the gauge, the reading on the right.
    if calib.warning_m is not None:
        _tick(img, calib, calib.warning_m, COLOURS["warning"], f"warning {calib.warning_m:.1f} m", 22, 2, fs, left=True)
    if calib.danger_m is not None:
        _tick(img, calib, calib.danger_m, COLOURS["danger"], f"danger {calib.danger_m:.1f} m", 22, 2, fs, left=True)
    for name, stage in per_estimator_m.items():
        if stage is not None:
            _tick(img, calib, stage, COLOURS.get(name, (180, 180, 180)), "", 14, 2)
    if fused_m is not None:
        label = f"{fused_m:.2f} m" + (f" +/- {sigma_m * 100:.0f} cm" if sigma_m else "")
        _tick(img, calib, fused_m, COLOURS["fused"], label, 36, 3, fs * 1.15)
    bar = int(28 * fs / 0.55)
    banner = f"OpenCV {cv2.__version__} | registration: {method}" + (" | QUALITY: " + ", ".join(quality_reasons) if quality_reasons else " | quality ok")
    cv2.rectangle(img, (0, 0), (w_img, bar), (0, 0, 0), -1)
    cv2.putText(img, banner, (8, int(bar * 0.68)), cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 0, 255) if quality_reasons else (255, 255, 255),
                max(1, int(round(fs * 2))), cv2.LINE_AA)
    # Legend: estimator colours and values, bottom-left.
    y = h - 10
    for name in ("E3_colour", "E2_temporal", "E1_edge"):
        v = per_estimator_m.get(name)
        _label(img, f"{name}: {'-' if v is None else f'{v:.2f} m'}", (8, y), COLOURS[name], fs * 0.85)
        y -= int(24 * fs / 0.55)
    return img
