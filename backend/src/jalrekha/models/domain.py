from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Site(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    region: str
    lat: float
    lng: float
    description: Optional[str] = None
    sample_video_path: Optional[str] = None
    sample_video_source_url: Optional[str] = None
    sample_frame_path: Optional[str] = None
    is_active: bool = True


class SiteCalibration(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: str = Field(index=True)
    roi_polygon: Optional[str] = None
    critical_line: Optional[str] = None
    reference_line: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # OpenCV staff-gauge calibration (jalrekha.vision.gauge.GaugeCalibration JSON)
    gauge_json: Optional[str] = None
    reference_frame_path: Optional[str] = None


class SiteExperimentalSettings(SQLModel, table=True):
    site_id: str = Field(primary_key=True)
    historical_context_enabled: bool = False
    forecast_enabled: bool = True
    forecast_horizon_minutes: int = 60
    forecast_critical_threshold: float = 0.8
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class NodeObservation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: str = Field(index=True)
    source_type: str
    video_path: Optional[str] = None
    started_at: datetime
    ended_at: datetime
    frames_analyzed: int
    waterline_ratio: float
    rise_velocity: float
    crossed_critical_line: bool
    confidence: float
    decision_trace: str
    severity_score: float
    assessment_score: float = 0.0
    assessment_level: Optional[str] = None
    evidence_frame_path: Optional[str] = None
    analysis_mode: str = "temporal-gradient"
    assessment_mode: str = "temporal-gemma-v1"
    sync_status: str = "pending"
    image_description: Optional[str] = None
    image_assessment_model: Optional[str] = None
    image_assessment_confidence: Optional[float] = None
    image_water_visible: Optional[bool] = None
    image_infrastructure_at_risk: Optional[bool] = None
    temporal_summary: Optional[str] = None
    reasoning_summary: Optional[str] = None
    reasoning_steps: Optional[str] = None
    critical_evidence: Optional[str] = None
    runner_name: Optional[str] = None
    runner_mode: Optional[str] = None
    fallback_used: bool = False
    artifact_refs: Optional[str] = None
    assessment_artifact_id: Optional[int] = Field(default=None, index=True)
    # OpenCV 5 metric measurement (null when the site has no gauge calibration)
    stage_m: Optional[float] = None
    stage_sigma_m: Optional[float] = None
    rate_m_per_h: Optional[float] = None
    cv_usable: Optional[bool] = None
    cv_method: Optional[str] = None
    cv_quality: Optional[str] = None
    overlay_path: Optional[str] = None
    cv_measurement_json: Optional[str] = None


class VolunteerReport(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    reporter_name: str
    reporter_role: str
    photo_path: Optional[str] = None
    audio_path: Optional[str] = None
    transcript_text: str
    offline_created: bool = False
    sync_status: str = "pending"


class ParsedObservation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    volunteer_report_id: int = Field(index=True)
    water_level_category: str
    trend: str
    road_status: str
    bridge_status: str
    homes_affected: bool
    urgency: str
    confidence: float
    structured_json: str
    decision_trace: str
    parser_source: str = "rules"
    severity_score: float = 0.0
    summary: str = ""


class HydrometSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    provider: str = "open-meteo"
    weather_code: Optional[int] = None
    precipitation_mm: float = 0.0
    rain_mm: float = 0.0
    precipitation_probability: float = 0.0
    river_discharge: Optional[float] = None
    river_discharge_max: Optional[float] = None
    river_discharge_trend: Optional[float] = None
    signal_score: float = 0.0
    summary: str = ""
    raw_payload: str = "{}"
    sync_status: str = "pending"


class FusedAlert(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: str = Field(index=True)
    incident_id: Optional[int] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    level: str
    score: float
    trigger_source: str
    summary: str
    decision_trace: str
    local_alarm_triggered: bool = False
    sync_status: str = "pending"
    reasoning_summary: Optional[str] = None
    reasoning_chain: Optional[str] = None
    reasoning_model: Optional[str] = None


class Incident(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: str = Field(index=True)
    current_level: str = "green"
    lifecycle_state: str = "monitoring"
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    close_reason: Optional[str] = None
    evidence_window_minutes: int = 45
    summary: str = ""
    sync_status: str = "pending"


class ActuationRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    alert_id: Optional[int] = Field(default=None, index=True)
    incident_id: Optional[int] = Field(default=None, index=True)
    site_id: str = Field(index=True)
    actuator_type: str = Field(index=True)
    payload: str = "{}"
    status: str = "pending"
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    sync_status: str = "pending"


class NodeAssessmentArtifact(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: str = Field(index=True)
    source_type: str
    video_path: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    assessment_mode: str = "temporal-gemma-v1"
    frames_analyzed: int = 0
    temporal_summary: str = ""
    reasoning_summary: Optional[str] = None
    reasoning_steps: str = "[]"
    critical_evidence: str = "{}"
    runner_name: Optional[str] = None
    runner_mode: Optional[str] = None
    fallback_used: bool = False
    bundle_json: str = "{}"
    verdict_json: str = "{}"
    artifact_refs: str = "{}"
    sync_status: str = "pending"


class SyncQueueItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    entity_type: str
    entity_id: int
    payload: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    status: str = "pending"
    attempts: int = 0
    last_error: Optional[str] = None
    synced_at: Optional[datetime] = None
