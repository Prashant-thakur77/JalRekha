"""Tables for the perception-driven agent: traces, per-site state, approvals, relief."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class AgentSiteState(SQLModel, table=True):
    site_id: str = Field(primary_key=True)
    mode: str = "normal"  # normal | watch | alert | degraded
    cadence_s: int = 60
    normal_cadence_s: int = 60
    fast_cadence_s: int = 10
    siren_active: bool = False
    burst_frames: int = 5
    last_stage_m: Optional[float] = None
    last_sigma_m: Optional[float] = None
    last_rate_m_per_h: Optional[float] = None
    last_quality: Optional[str] = None
    last_overlay_url: Optional[str] = None
    last_frame_url: Optional[str] = None
    last_measured_at: Optional[datetime] = None
    bad_quality_streak: int = 0
    held_streak: int = 0
    rise_streak: int = 0
    cycles_since_bad: int = 99
    heavy_last: bool = False
    falling_streak: int = 0
    peak_stage_m: Optional[float] = None
    cycle: int = 0
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StageReadingRow(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: str = Field(index=True)
    at: datetime = Field(index=True)
    stage_m: Optional[float] = None
    sigma_m: Optional[float] = None
    usable: bool = False
    filtered_stage_m: Optional[float] = None
    rate_m_per_h: Optional[float] = None
    source: str = "camera"  # camera | vlm | gauge | volunteer
    trace_id: Optional[str] = Field(default=None, index=True)


class AgentTrace(SQLModel, table=True):
    trace_id: str = Field(primary_key=True)
    site_id: str = Field(index=True)
    cycle: int = 0
    started_at: datetime = Field(index=True)
    branches: str = "[]"
    summary: str = ""
    measurement_json: str = "{}"
    steps_json: str = "[]"
    scenario_run_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ApprovalRequest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = Field(default="pending", index=True)  # pending | approved | rejected | superseded
    action: str = Field(index=True)
    site_id: Optional[str] = Field(default=None, index=True)
    region_id: str = "np"
    role: str = ""
    dedupe_key: str = Field(default="", index=True)
    title: str = ""
    rationale: str = ""
    level: str = "watch"
    payload_json: str = "{}"
    evidence_json: str = "[]"
    trace_id: Optional[str] = None
    scenario_run_id: Optional[str] = Field(default=None, index=True)
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    decision_note: Optional[str] = None
    dispatch_json: Optional[str] = None


class ReliefRequest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    text: str
    lang: str = "en"
    channel: str = "app"
    need: str = "other"
    people: Optional[int] = None
    urgency: str = "medium"
    priority: float = 0.0
    lat: Optional[float] = None
    lng: Optional[float] = None
    site_id: Optional[str] = None
    region_id: Optional[str] = None
    duplicate_of: Optional[int] = None
    status: str = "pending_approval"  # pending_approval | dispatched | rejected | duplicate
    parsed_by: str = "rules"
    team: Optional[str] = None
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None


class RouteStatus(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    region_id: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    status: str = "unknown"  # passable | blocked | unknown
    verified: bool = False
    source: str = "seed"
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Shelter(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    region_id: str
    admin_unit: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    capacity: int = 0
    occupancy: int = 0
    source: str = "illustrative seed"
