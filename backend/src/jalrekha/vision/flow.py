"""Surface-motion proxy from DIS optical flow in the water region.

This is *not* discharge. It is the median image-plane speed of the water
surface below the waterline, scaled to m/s with the gauge's metres-per-pixel
(valid only near the gauge plane). The agent uses it as a secondary cue:
a fast, turbulent surface with a stable stage is reported, not alerted on.
"""

from __future__ import annotations

import cv2
import numpy as np

from jalrekha.vision.gauge import GaugeCalibration


def surface_motion(
    frames_ref: list[np.ndarray],
    calib: GaugeCalibration,
    waterline_y: float | None,
    dt_s: float,
) -> dict:
    if len(frames_ref) < 2 or waterline_y is None or dt_s <= 0:
        return {"available": False}
    h, w = frames_ref[0].shape[:2]
    top = int(np.clip(waterline_y + 6, 0, h - 2))
    if h - top < 12:
        return {"available": False, "reason": "no water region below waterline"}
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_FAST)
    speeds, dirs = [], []
    for a, b in zip(frames_ref[:-1], frames_ref[1:]):
        ga = cv2.cvtColor(a[top:], cv2.COLOR_BGR2GRAY)
        gb = cv2.cvtColor(b[top:], cv2.COLOR_BGR2GRAY)
        f = dis.calc(ga, gb, None)
        mag, ang = cv2.cartToPolar(f[..., 0], f[..., 1], angleInDegrees=True)
        speeds.append(float(np.median(mag)))
        dirs.append(float(np.median(ang)))
    px_per_s = float(np.median(speeds)) / dt_s
    return {
        "available": True,
        "speed_px_s": round(px_per_s, 3),
        "speed_mps_proxy": round(px_per_s * calib.metres_per_px(), 3),
        "direction_deg": round(float(np.median(dirs)), 1),
        "label": "surface-motion proxy (not discharge)",
    }
