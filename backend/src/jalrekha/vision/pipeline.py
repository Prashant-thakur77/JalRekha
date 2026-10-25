"""End-to-end measurement: frames + gauge calibration -> stage in metres.

    quality gate -> registration (ORB, escalate to ALIKED+LightGlue)
    -> gauge strip (warpAffine along the gauge axis)
    -> E1 edge energy, E2 temporal texture (DIS flow), E3 colour step
    -> robust fusion -> surface motion -> redaction -> overlay

Every stage is timed so the COOL benchmark can report per-stage cost.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from jalrekha.vision import flow, overlay, privacy, quality, register, waterline
from jalrekha.vision.fuse import StageReading, fuse_estimates
from jalrekha.vision.gauge import GaugeCalibration

SCHEMA = "jalrekha-measurement-v1"
ALL_ESTIMATORS = ("E1_edge", "E2_temporal", "E3_colour")


@dataclass
class MeasureOptions:
    estimators: tuple[str, ...] = ALL_ESTIMATORS
    use_registration: bool = True
    allow_heavy_registration: bool = True
    force_heavy_registration: bool = False
    redact: bool = True
    draw_overlay: bool = True
    surface_motion: bool = True
    burst_dt_s: float = 0.5


@dataclass
class Measurement:
    reading: StageReading
    quality: quality.QualityReport
    registration: register.Registration
    estimates: list[waterline.Estimate]
    surface: dict
    redaction: privacy.RedactionReport | None
    timings_ms: dict[str, float]
    frames: int
    overlay_bgr: np.ndarray | None = None
    redacted_bgr: np.ndarray | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.reading.stage_m is not None and self.quality.ok and self.registration.ok

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA,
            "opencv_version": cv2.__version__,
            "usable": self.usable,
            "reading": self.reading.to_dict(),
            "quality": self.quality.to_dict(),
            "registration": self.registration.to_dict(),
            "estimates": [e.to_dict() for e in self.estimates],
            "surface_motion": self.surface,
            "redaction": self.redaction.to_dict() if self.redaction else None,
            "timings_ms": {k: round(v, 3) for k, v in self.timings_ms.items()},
            "frames": self.frames,
            "notes": self.notes,
        }


class _Timer:
    def __init__(self) -> None:
        self.ms: dict[str, float] = {}

    def __call__(self, name: str):
        timer = self

        class _Ctx:
            def __enter__(self_inner):
                self_inner.t = time.perf_counter()

            def __exit__(self_inner, *exc):
                timer.ms[name] = timer.ms.get(name, 0.0) + (time.perf_counter() - self_inner.t) * 1000

        return _Ctx()


def _strip_mask(calib: GaugeCalibration, shape: tuple[int, int]) -> np.ndarray:
    m = calib.strip_transform()
    w = calib.strip_half_width_px * 2
    length = calib.strip_length_px()
    pad = calib.strip_half_width_px
    corners = np.array([[-pad, 0, 1], [w + pad, 0, 1], [w + pad, length, 1], [-pad, length, 1]]).T
    mask = np.zeros(shape, np.uint8)
    cv2.fillPoly(mask, [(m @ corners).T.astype(np.int32)], 255)
    return mask


def measure(
    frames: list[np.ndarray],
    calib: GaugeCalibration,
    reference: np.ndarray | None = None,
    options: MeasureOptions | None = None,
    capture: dict | None = None,
) -> Measurement:
    """Measure the stage from a burst.

    ``capture`` is opt-in (vision/explain.py): when a dict is passed, the
    aligned frames, gauge strips, burst median and each estimator's per-row
    profile are stored in it. Outputs are identical either way.
    """
    if not frames:
        raise ValueError("measure() needs at least one frame")
    opts = options or MeasureOptions()
    tm = _Timer()
    t_all = time.perf_counter()
    notes: list[str] = []
    current = frames[-1]

    with tm("register"):
        if opts.use_registration and reference is not None:
            probe = np.float32([calib.top, calib.bottom])
            reg = register.register(
                current,
                reference,
                probe_points=probe,
                allow_heavy=opts.allow_heavy_registration,
                force_heavy=opts.force_heavy_registration,
            )
        else:
            reg = register.register(current, None)
    ref_shape = reference.shape[:2] if reference is not None else current.shape[:2]
    with tm("warp"):
        h_ref, w_ref = ref_shape
        offsets = register.burst_offsets(frames) if opts.use_registration and len(frames) > 1 else [(0.0, 0.0)] * len(frames)
        aligned = []
        for f, (dx, dy) in zip(frames, offsets):
            if reg.method in {"identity", "failed"} and dx == 0.0 and dy == 0.0:
                aligned.append(f)
                continue
            m = register.compose_with_offset(reg, dx, dy)
            aligned.append(cv2.warpAffine(f, m, (w_ref, h_ref), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE))
        strips = [calib.extract_strip(f) for f in aligned]
    with tm("quality"):
        q = quality.assess_quality(aligned[-1], strips[-1])
    if not reg.ok:
        notes.append("registration_failed: calibration may not hold; reading flagged unusable")

    # A per-pixel temporal median over the burst removes most wave and rain
    # texture before the single-image estimators run.
    with tm("median"):
        still = np.median(np.stack(strips), axis=0).astype(np.uint8) if len(strips) > 1 else strips[-1]

    estimates: list[waterline.Estimate] = []
    profiles: dict[str, np.ndarray | None] = {}
    if "E1_edge" in opts.estimators:
        with tm("E1_edge"):
            est, profiles["E1_edge"] = waterline.edge_energy_profile(still)
            estimates.append(est)
    if "E2_temporal" in opts.estimators:
        with tm("E2_temporal"):
            est, profiles["E2_temporal"] = waterline.temporal_texture_profile(strips)
            estimates.append(est)
    if "E3_colour" in opts.estimators:
        with tm("E3_colour"):
            est, profiles["E3_colour"] = waterline.colour_step_profile(still)
            estimates.append(est)
    if "B1_naive" in opts.estimators:
        with tm("B1_naive"):
            estimates.append(waterline.naive_max_edge(strips[-1]))

    with tm("fuse"):
        reading = fuse_estimates(estimates, calib, 1.0)

    surface: dict = {"available": False}
    if opts.surface_motion and len(aligned) >= 2 and reading.stage_m is not None:
        with tm("surface_motion"):
            _, wy = calib.stage_to_frame_point(reading.stage_m)
            surface = flow.surface_motion(aligned[-3:], calib, wy, opts.burst_dt_s)

    redaction = None
    redacted = None
    if opts.redact:
        with tm("redact"):
            redacted, redaction = privacy.redact(aligned[-1], keep_mask=_strip_mask(calib, aligned[-1].shape[:2]))
    ov = None
    if opts.draw_overlay:
        with tm("overlay"):
            base = redacted if redacted is not None else aligned[-1]
            ov = overlay.draw_debug(
                base, calib, reading.per_estimator_m, reading.stage_m, reading.sigma_m, q.reasons, reg.method
            )
    tm.ms["total"] = (time.perf_counter() - t_all) * 1000
    if capture is not None:
        capture.update(aligned=aligned, strips=strips, still=still, profiles=profiles)
    return Measurement(
        reading=reading,
        quality=q,
        registration=reg,
        estimates=estimates,
        surface=surface,
        redaction=redaction,
        timings_ms=tm.ms,
        frames=len(frames),
        overlay_bgr=ov,
        redacted_bgr=redacted,
        notes=notes,
    )
