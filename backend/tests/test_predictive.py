from __future__ import annotations

from datetime import datetime, timedelta

from jalrekha.services.predictive import Measurement, forecast_short_term


def test_short_term_forecast_uses_water_trend():
    now = datetime(2026, 5, 16, 12, 0, 0)
    forecast = forecast_short_term(
        [
            Measurement(now - timedelta(minutes=30), 0.4),
            Measurement(now, 0.6, rain_mm=10, reports_count=1),
        ],
        horizon_minutes=60,
    )
    assert forecast.expected_level > 0.9
    assert forecast.risk == "high"
    assert forecast.acceleration_per_hour2 == 0.0
    assert forecast.minutes_to_threshold is not None
    assert forecast.projected_points


def test_short_term_forecast_uses_acceleration():
    now = datetime(2026, 5, 16, 12, 0, 0)
    forecast = forecast_short_term(
        [
            Measurement(now - timedelta(minutes=30), 0.35),
            Measurement(now - timedelta(minutes=15), 0.40),
            Measurement(now, 0.55),
        ],
        horizon_minutes=60,
    )
    assert forecast.acceleration_per_hour2 > 0
    assert forecast.expected_level > 0.85
    assert forecast.status == "ok"
    assert forecast.confidence > 0
    assert forecast.uncertainty_band


def test_short_term_forecast_requires_two_samples():
    now = datetime(2026, 5, 16, 12, 0, 0)
    forecast = forecast_short_term([Measurement(now, 0.5)])
    assert forecast.status == "insufficient_data"
    assert forecast.warning
    assert forecast.minutes_to_threshold is None


def test_short_term_forecast_degrades_on_large_gaps():
    now = datetime(2026, 5, 16, 12, 0, 0)
    forecast = forecast_short_term(
        [
            Measurement(now - timedelta(hours=3), 0.2),
            Measurement(now, 0.4),
        ],
    )
    assert forecast.status == "degraded"
    assert forecast.warning
