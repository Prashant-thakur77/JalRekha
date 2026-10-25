"""Staff-gauge calibration: pixel position along the gauge axis -> stage in metres.

An operator clicks two or more marks on the gauge in the reference frame and
types the stage value printed at each mark. The gauge axis runs from the
highest mark (top of the gauge) to the lowest. Stage between marks is
piecewise linear, which also absorbs mild perspective foreshortening.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import cv2
import numpy as np

Point = tuple[float, float]


@dataclass
class GaugeMark:
    x: float
    y: float
    stage_m: float


@dataclass
class GaugeCalibration:
    marks: list[GaugeMark]
    strip_half_width_px: float = 12.0
    # Strip extends this far beyond the outermost marks (as a fraction of the
    # mark span) so a waterline just below the lowest mark is still found.
    margin_frac: float = 0.08
    reference_size: tuple[int, int] | None = None  # (width, height) of the reference frame
    warning_m: float | None = None
    danger_m: float | None = None
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.marks) < 2:
            raise ValueError("gauge calibration needs at least two marks")
        self.marks = sorted(self.marks, key=lambda m: -m.stage_m)  # top (highest stage) first
        if abs(self.marks[0].stage_m - self.marks[-1].stage_m) < 1e-6:
            raise ValueError("gauge marks must have different stage values")

    # ---- axis geometry -------------------------------------------------
    @property
    def top(self) -> np.ndarray:
        return np.array([self.marks[0].x, self.marks[0].y], dtype=np.float64)

    @property
    def bottom(self) -> np.ndarray:
        return np.array([self.marks[-1].x, self.marks[-1].y], dtype=np.float64)

    @property
    def axis_unit(self) -> np.ndarray:
        d = self.bottom - self.top
        return d / max(np.linalg.norm(d), 1e-9)

    @property
    def span_px(self) -> float:
        return float(np.linalg.norm(self.bottom - self.top))

    def strip_endpoints(self) -> tuple[np.ndarray, np.ndarray]:
        margin = self.span_px * self.margin_frac
        return self.top - self.axis_unit * margin, self.bottom + self.axis_unit * margin

    def strip_length_px(self) -> int:
        a, b = self.strip_endpoints()
        return int(round(np.linalg.norm(b - a)))

    def strip_transform(self, scale: float = 1.0) -> np.ndarray:
        """Affine 2x3 mapping strip coords (u across, v along axis) -> frame coords."""
        a, _ = self.strip_endpoints()
        along = self.axis_unit
        across = np.array([-along[1], along[0]])
        w = self.strip_half_width_px
        origin = a - across * w
        return np.array(
            [
                [across[0] / scale, along[0] / scale, origin[0]],
                [across[1] / scale, along[1] / scale, origin[1]],
            ],
            dtype=np.float64,
        )

    def extract_strip(self, frame: np.ndarray, scale: float = 1.0) -> np.ndarray:
        """Resample the gauge strip so rows run top->bottom along the axis."""
        width = max(4, int(round(2 * self.strip_half_width_px * scale)))
        height = max(8, int(round(self.strip_length_px() * scale)))
        m = self.strip_transform(scale)
        return cv2.warpAffine(
            frame,
            m,
            (width, height),
            flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
            borderMode=cv2.BORDER_REPLICATE,
        )

    # ---- pixel <-> stage ------------------------------------------------
    def _mark_positions(self) -> np.ndarray:
        a, _ = self.strip_endpoints()
        return np.array(
            [float(np.dot(np.array([m.x, m.y]) - a, self.axis_unit)) for m in self.marks]
        )

    def strip_row_to_stage(self, row: float, scale: float = 1.0) -> float:
        pos = row / scale
        xs = self._mark_positions()
        ys = np.array([m.stage_m for m in self.marks])
        # np.interp needs increasing xs; positions grow downwards, stage falls.
        if pos <= xs[0] or pos >= xs[-1]:
            # linear extrapolation from the nearest segment
            i0, i1 = (0, 1) if pos <= xs[0] else (-2, -1)
            slope = (ys[i1] - ys[i0]) / (xs[i1] - xs[i0])
            return float(ys[i0] + slope * (pos - xs[i0]))
        return float(np.interp(pos, xs, ys))

    def stage_to_strip_row(self, stage_m: float, scale: float = 1.0) -> float:
        xs = self._mark_positions()
        ys = np.array([m.stage_m for m in self.marks])
        order = np.argsort(ys)
        return float(np.interp(stage_m, ys[order], xs[order])) * scale

    def stage_to_frame_point(self, stage_m: float) -> Point:
        a, _ = self.strip_endpoints()
        p = a + self.axis_unit * self.stage_to_strip_row(stage_m)
        return float(p[0]), float(p[1])

    def metres_per_px(self) -> float:
        return abs(self.marks[0].stage_m - self.marks[-1].stage_m) / max(self.span_px, 1e-9)

    @property
    def stage_range(self) -> tuple[float, float]:
        return self.marks[-1].stage_m, self.marks[0].stage_m

    # ---- serialisation --------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "marks": [{"x": m.x, "y": m.y, "stage_m": m.stage_m} for m in self.marks],
            "strip_half_width_px": self.strip_half_width_px,
            "margin_frac": self.margin_frac,
            "reference_size": list(self.reference_size) if self.reference_size else None,
            "warning_m": self.warning_m,
            "danger_m": self.danger_m,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "GaugeCalibration":
        ref = payload.get("reference_size")
        return cls(
            marks=[GaugeMark(float(m["x"]), float(m["y"]), float(m["stage_m"])) for m in payload["marks"]],
            strip_half_width_px=float(payload.get("strip_half_width_px", 12.0)),
            margin_frac=float(payload.get("margin_frac", 0.08)),
            reference_size=(int(ref[0]), int(ref[1])) if ref else None,
            warning_m=payload.get("warning_m"),
            danger_m=payload.get("danger_m"),
        )

    @classmethod
    def from_json(cls, raw: str | None) -> "GaugeCalibration | None":
        if not raw:
            return None
        try:
            return cls.from_dict(json.loads(raw))
        except (ValueError, KeyError, TypeError):
            return None
