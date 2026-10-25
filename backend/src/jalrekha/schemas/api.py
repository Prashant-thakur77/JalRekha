from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ConnectivityStatus(BaseModel):
    is_online: bool


class CalibrationPayload(BaseModel):
    roi_polygon: list[list[int]] | None = None
    critical_line: list[list[int]] | None = None
    reference_line: list[list[int]] | None = None
    notes: str | None = None


class RuntimeStatus(BaseModel):
    is_online: bool
    llm: dict[str, Any]
    node: dict[str, Any]
    hydromet: dict[str, Any]


class RecomputeRequest(BaseModel):
    site_id: str | None = None
    use_historical_context: bool = False


class HistoricalContextUpsert(BaseModel):
    source: str
    title: str
    summary: str
    threshold_level: float | None = Field(default=None, ge=0.0, le=1.5)
    jurisdiction: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    source_uri: str | None = None


class SiteExperimentalSettingsPayload(BaseModel):
    historical_context_enabled: bool | None = None
    forecast_enabled: bool | None = None
    forecast_horizon_minutes: int | None = Field(default=None, ge=15, le=180)
    forecast_critical_threshold: float | None = Field(default=None, ge=0.1, le=1.5)


class ExternalSnapshotResponse(BaseModel):
    site_id: str
    signal_score: float
    summary: str
    precipitation_mm: float = Field(default=0.0)
    precipitation_probability: float = Field(default=0.0)
    river_discharge: float | None = None
    river_discharge_max: float | None = None
    river_discharge_trend: float | None = None
