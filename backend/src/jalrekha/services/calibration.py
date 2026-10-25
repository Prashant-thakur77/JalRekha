from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable

from sqlmodel import Session, select

from jalrekha.models.domain import SiteCalibration

Point = tuple[int, int]
Line = tuple[Point, Point]


@dataclass
class CalibrationConfig:
    roi_polygon: list[Point]
    critical_line: Line
    reference_line: Line



def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))



def _decode_points(raw: str | None) -> list[Point]:
    if not raw:
        return []
    parsed = json.loads(raw)
    points: list[Point] = []
    for item in parsed:
        if not isinstance(item, Iterable):
            continue
        x, y = item
        points.append((int(x), int(y)))
    return points



def get_latest_site_calibration(session: Session, site_id: str) -> SiteCalibration | None:
    statement = (
        select(SiteCalibration)
        .where(SiteCalibration.site_id == site_id)
        .order_by(SiteCalibration.created_at.desc())
    )
    return session.exec(statement).first()



def build_calibration_config(
    calibration: SiteCalibration | None,
    width: int,
    height: int,
) -> CalibrationConfig:
    full_roi = [(0, 0), (width - 1, 0), (width - 1, height - 1), (0, height - 1)]
    default_critical_y = int(height * 0.45)
    default_reference_y = int(height * 0.65)

    if calibration is None:
        return CalibrationConfig(
            roi_polygon=full_roi,
            critical_line=((0, default_critical_y), (width - 1, default_critical_y)),
            reference_line=((0, default_reference_y), (width - 1, default_reference_y)),
        )

    roi = _decode_points(calibration.roi_polygon) or full_roi
    critical_points = _decode_points(calibration.critical_line)
    reference_points = _decode_points(calibration.reference_line)

    if len(critical_points) < 2:
        critical_points = [(0, default_critical_y), (width - 1, default_critical_y)]
    if len(reference_points) < 2:
        reference_points = [(0, default_reference_y), (width - 1, default_reference_y)]

    clamped_roi = [(_clamp(x, 0, width - 1), _clamp(y, 0, height - 1)) for x, y in roi]
    critical_line = (
        (_clamp(critical_points[0][0], 0, width - 1), _clamp(critical_points[0][1], 0, height - 1)),
        (_clamp(critical_points[1][0], 0, width - 1), _clamp(critical_points[1][1], 0, height - 1)),
    )
    reference_line = (
        (_clamp(reference_points[0][0], 0, width - 1), _clamp(reference_points[0][1], 0, height - 1)),
        (_clamp(reference_points[1][0], 0, width - 1), _clamp(reference_points[1][1], 0, height - 1)),
    )

    return CalibrationConfig(
        roi_polygon=clamped_roi,
        critical_line=critical_line,
        reference_line=reference_line,
    )
