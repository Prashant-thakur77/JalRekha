from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Measurement:
    observed_at: datetime
    water_level: float
    rain_mm: float = 0.0
    reports_count: int = 0


@dataclass(frozen=True)
class Forecast:
    horizon_minutes: int
    expected_level: float
    trend_per_hour: float
    acceleration_per_hour2: float
    risk: str
    status: str = "ok"
    confidence: float = 0.0
    critical_threshold: float = 0.8
    minutes_to_threshold: int | None = None
    projected_points: list[dict[str, float]] | None = None
    uncertainty_band: list[dict[str, float]] | None = None
    warning: str | None = None


def _risk_for(expected: float, trend: float, acceleration: float, rain: float, reports: int) -> str:
    if expected >= 0.8 or trend >= 0.25 or acceleration >= 0.16 or rain >= 30 or reports >= 3:
        return "high"
    if expected >= 0.55 or trend >= 0.12 or acceleration >= 0.08 or rain >= 15 or reports >= 1:
        return "moderate"
    return "low"


def _minutes_to_threshold(
    current_level: float,
    trend_per_hour: float,
    acceleration_per_hour2: float,
    threshold: float,
    horizon_minutes: int,
) -> int | None:
    for minute in range(1, horizon_minutes + 1):
        hours = minute / 60.0
        projected = current_level + trend_per_hour * hours + 0.5 * acceleration_per_hour2 * hours * hours
        if projected >= threshold:
            return minute
    return None


def _clamp_acceleration(value: float) -> float:
    return max(-0.35, min(0.35, value))


def _confidence(sample_count: int, span_hours: float, gaps_ok: bool) -> float:
    if sample_count < 2:
        return 0.0
    score = 0.35 + min(0.35, span_hours / 2.0 * 0.35) + min(0.2, (sample_count - 2) * 0.05)
    if not gaps_ok:
        score -= 0.25
    return round(max(0.1, min(0.9, score)), 2)


def forecast_short_term(
    measurements: list[Measurement],
    *,
    horizon_minutes: int = 60,
    critical_threshold: float = 0.8,
) -> Forecast:
    if not measurements:
        return Forecast(
            horizon_minutes=horizon_minutes,
            expected_level=0.0,
            trend_per_hour=0.0,
            acceleration_per_hour2=0.0,
            risk="unknown",
            status="insufficient_data",
            confidence=0.0,
            critical_threshold=critical_threshold,
            minutes_to_threshold=None,
            projected_points=[],
            uncertainty_band=[],
            warning="No measurements available for forecast.",
        )
    ordered = sorted(measurements, key=lambda item: item.observed_at)
    if len(ordered) == 1:
        only = ordered[0]
        return Forecast(
            horizon_minutes=horizon_minutes,
            expected_level=round(max(0.0, only.water_level), 4),
            trend_per_hour=0.0,
            acceleration_per_hour2=0.0,
            risk="unknown",
            status="insufficient_data",
            confidence=0.0,
            critical_threshold=critical_threshold,
            minutes_to_threshold=0 if only.water_level >= critical_threshold else None,
            projected_points=[{"minute": 0, "level": round(max(0.0, only.water_level), 4)}],
            uncertainty_band=[{"minute": 0, "low": round(max(0.0, only.water_level), 4), "high": round(max(0.0, only.water_level), 4)}],
            warning="At least two measurements are required for trend forecast.",
        )
    first, last = ordered[0], ordered[-1]
    hours = max((last.observed_at - first.observed_at).total_seconds() / 3600.0, 1 / 60)
    trend = (last.water_level - first.water_level) / hours
    acceleration = 0.0
    if len(ordered) >= 3:
        prev = ordered[-2]
        early_hours = max((prev.observed_at - first.observed_at).total_seconds() / 3600.0, 1 / 60)
        recent_hours = max((last.observed_at - prev.observed_at).total_seconds() / 3600.0, 1 / 60)
        early_velocity = (prev.water_level - first.water_level) / early_hours
        recent_velocity = (last.water_level - prev.water_level) / recent_hours
        acceleration = _clamp_acceleration((recent_velocity - early_velocity) / max((early_hours + recent_hours) / 2.0, 1 / 60))
    gaps_ok = all(
        (right.observed_at - left.observed_at).total_seconds() <= 45 * 60
        for left, right in zip(ordered, ordered[1:])
    )
    horizon_hours = horizon_minutes / 60.0
    expected = last.water_level + trend * horizon_hours + 0.5 * acceleration * horizon_hours * horizon_hours
    rain = sum(item.rain_mm for item in ordered[-6:])
    reports = sum(item.reports_count for item in ordered[-6:])
    projected_points = []
    uncertainty_band = []
    conf = _confidence(len(ordered), hours, gaps_ok)
    spread_base = 0.04 + (1.0 - conf) * 0.12
    for minute in range(0, horizon_minutes + 1, 15):
        hours_ahead = minute / 60.0
        projected = last.water_level + trend * hours_ahead + 0.5 * acceleration * hours_ahead * hours_ahead
        level = max(0.0, projected)
        spread = spread_base * (hours_ahead / max(horizon_hours, 1 / 60))
        projected_points.append({"minute": minute, "level": round(level, 4)})
        uncertainty_band.append({
            "minute": minute,
            "low": round(max(0.0, level - spread), 4),
            "high": round(level + spread, 4),
        })
    warning = None if gaps_ok else "Forecast degraded because measurement gaps exceed 45 minutes."
    return Forecast(
        horizon_minutes=horizon_minutes,
        expected_level=round(max(0.0, expected), 4),
        trend_per_hour=round(trend, 4),
        acceleration_per_hour2=round(acceleration, 4),
        risk=_risk_for(expected, trend, acceleration, rain, reports),
        status="ok" if gaps_ok else "degraded",
        confidence=conf,
        critical_threshold=critical_threshold,
        minutes_to_threshold=_minutes_to_threshold(
            last.water_level,
            trend,
            acceleration,
            critical_threshold,
            horizon_minutes,
        ),
        projected_points=projected_points,
        uncertainty_band=uncertainty_band,
        warning=warning,
    )
