from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

import httpx

from jalrekha.core.settings import get_settings
from jalrekha.models.domain import HydrometSnapshot, Site


@dataclass
class ExternalDataStatus:
    enabled: bool
    reachable: bool
    detail: str


class ExternalDataService:
    WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
    FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"

    def __init__(self) -> None:
        self.settings = get_settings()

    def health(self) -> ExternalDataStatus:
        if not self.settings.hydromet_enabled:
            return ExternalDataStatus(False, False, "disabled by env")
        try:
            with httpx.Client(timeout=min(self.settings.hydromet_timeout_seconds, 5.0)) as client:
                response = client.get(
                    self.WEATHER_URL,
                    params={
                        "latitude": 0,
                        "longitude": 0,
                        "current": "precipitation",
                        "forecast_hours": 1,
                    },
                )
                response.raise_for_status()
            return ExternalDataStatus(True, True, "ok")
        except Exception as exc:  # pragma: no cover - network errors vary by environment
            return ExternalDataStatus(True, False, str(exc))

    def fetch_snapshot(self, site: Site) -> HydrometSnapshot:
        if not self.settings.hydromet_enabled:
            raise RuntimeError("Hydromet integration is disabled")

        with httpx.Client(timeout=self.settings.hydromet_timeout_seconds) as client:
            weather_response = client.get(
                self.WEATHER_URL,
                params={
                    "latitude": site.lat,
                    "longitude": site.lng,
                    "current": "precipitation,rain,showers,weather_code",
                    "hourly": "precipitation,precipitation_probability",
                    "forecast_hours": 12,
                },
            )
            weather_response.raise_for_status()
            flood_response = client.get(
                self.FLOOD_URL,
                params={
                    "latitude": site.lat,
                    "longitude": site.lng,
                    "daily": "river_discharge,river_discharge_mean,river_discharge_max",
                    "past_days": 2,
                    "forecast_days": 7,
                },
            )
            flood_response.raise_for_status()

        weather_payload = weather_response.json()
        flood_payload = flood_response.json()

        current = weather_payload.get("current", {})
        hourly = weather_payload.get("hourly", {})
        flood_daily = flood_payload.get("daily", {})

        hourly_precip = [float(value) for value in hourly.get("precipitation", [])[:12] if value is not None]
        hourly_prob = [float(value) for value in hourly.get("precipitation_probability", [])[:12] if value is not None]
        river_discharge_series = [float(value) for value in flood_daily.get("river_discharge", []) if value is not None]
        river_discharge_max_series = [float(value) for value in flood_daily.get("river_discharge_max", []) if value is not None]

        precipitation_mm = float(current.get("precipitation") or 0.0)
        rain_mm = float(current.get("rain") or 0.0) + float(current.get("showers") or 0.0)
        precipitation_probability = max(hourly_prob) if hourly_prob else 0.0
        river_discharge = river_discharge_series[0] if river_discharge_series else None
        river_discharge_max = max(river_discharge_max_series) if river_discharge_max_series else None
        river_discharge_trend = None
        if len(river_discharge_series) >= 2:
            river_discharge_trend = river_discharge_series[1] - river_discharge_series[0]

        signal_score = 0.0
        signal_score += min(sum(hourly_precip) / 50.0, 0.35)
        signal_score += min(precipitation_probability / 100.0, 0.25)
        if river_discharge is not None and river_discharge_max:
            signal_score += min(river_discharge / max(river_discharge_max, 1.0), 0.25)
        if river_discharge_trend is not None and river_discharge_trend > 0:
            signal_score += min(river_discharge_trend / 20.0, 0.15)
        signal_score = max(0.0, min(1.0, signal_score))

        summary_parts = [
            f"rain now {precipitation_mm:.1f} mm",
            f"12h precip prob {precipitation_probability:.0f}%",
        ]
        if river_discharge is not None:
            summary_parts.append(f"river discharge {river_discharge:.1f} m3/s")
        if river_discharge_trend is not None:
            trend_word = "rising" if river_discharge_trend > 0 else "falling"
            summary_parts.append(f"river trend {trend_word} {abs(river_discharge_trend):.1f} m3/s/day")

        raw_payload = {
            "weather": weather_payload,
            "flood": flood_payload,
            "fetched_at": datetime.utcnow().isoformat(),
        }

        return HydrometSnapshot(
            site_id=site.id,
            provider="open-meteo",
            weather_code=current.get("weather_code"),
            precipitation_mm=precipitation_mm,
            rain_mm=rain_mm,
            precipitation_probability=precipitation_probability,
            river_discharge=river_discharge,
            river_discharge_max=river_discharge_max,
            river_discharge_trend=river_discharge_trend,
            signal_score=signal_score,
            summary=", ".join(summary_parts),
            raw_payload=json.dumps(raw_payload, ensure_ascii=True),
        )
