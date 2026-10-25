"""Demo-only router for Persona C escalada (verde -> amarillo -> rojo).

Gated by env `JALREKHA_ENABLE_DEMO_INJECT=1`. Never include in production builds.
Inserts a synthetic NodeObservation (camera signal) and re-runs the fusion engine
so the operator dashboard reflects the new alert in real time.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from jalrekha.api.deps import enqueue_entity, llm_client
from jalrekha.db.database import get_session
from jalrekha.models.domain import (
    ActuationRecord,
    Incident,
    NodeObservation,
    ParsedObservation,
    Site,
    VolunteerReport,
)
from jalrekha.services.decision_engine import recompute_site_alert


router = APIRouter(tags=["demo-inject"])


def demo_inject_enabled() -> bool:
    return os.environ.get("JALREKHA_ENABLE_DEMO_INJECT", "").lower() in {"1", "true", "yes"}


class NodeInjectRequest(BaseModel):
    site_id: str
    severity_score: float = Field(ge=0.0, le=1.0)
    waterline_ratio: float = Field(default=0.55, ge=0.0, le=1.0)
    rise_velocity: float = Field(default=0.04, ge=0.0)
    crossed_critical_line: bool = False
    confidence: float = Field(default=0.78, ge=0.0, le=1.0)
    temporal_summary: str = "Fixed camera: synthetic reading injected for demo."
    assessment_level: str | None = None


@router.post("/demo/inject-node-observation")
async def inject_node_observation(
    payload: NodeInjectRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    if not demo_inject_enabled():
        raise HTTPException(status_code=404, detail="Demo inject endpoint disabled")

    site = session.get(Site, payload.site_id)
    if site is None:
        raise HTTPException(status_code=404, detail=f"Site {payload.site_id} not found")

    now = datetime.utcnow()
    observation = NodeObservation(
        site_id=payload.site_id,
        source_type="demo_inject",
        video_path=None,
        started_at=now - timedelta(seconds=30),
        ended_at=now,
        frames_analyzed=12,
        waterline_ratio=payload.waterline_ratio,
        rise_velocity=payload.rise_velocity,
        crossed_critical_line=payload.crossed_critical_line,
        confidence=payload.confidence,
        decision_trace=json.dumps(
            ["demo_inject: synthetic node observation for Persona C escalation"],
            ensure_ascii=True,
        ),
        severity_score=payload.severity_score,
        assessment_score=payload.severity_score,
        assessment_level=payload.assessment_level,
        analysis_mode="demo-inject",
        assessment_mode="demo-inject",
        temporal_summary=payload.temporal_summary,
        runner_name="demo-inject",
        runner_mode="synthetic",
        fallback_used=False,
    )
    session.add(observation)
    session.flush()
    enqueue_entity(session, "node_observation", observation)

    alert = recompute_site_alert(session, payload.site_id, llm_client)
    session.flush()
    enqueue_entity(session, "fused_alert", alert)
    if alert.incident_id is not None:
        incident = session.get(Incident, alert.incident_id)
        if incident is not None:
            enqueue_entity(session, "incident", incident)
    for record in session.exec(
        select(ActuationRecord).where(ActuationRecord.alert_id == alert.id)
    ).all():
        enqueue_entity(session, "actuation_record", record)
    session.commit()
    session.refresh(observation)
    session.refresh(alert)

    return {
        "observation_id": observation.id,
        "alert": _serialize_alert(alert),
    }


def _serialize_alert(alert) -> dict[str, object]:
    return {
        "id": alert.id,
        "site_id": alert.site_id,
        "level": alert.level,
        "score": alert.score,
        "trigger_source": alert.trigger_source,
        "summary": alert.summary,
        "local_alarm_triggered": alert.local_alarm_triggered,
    }


class VolunteerInjectRequest(BaseModel):
    site_id: str
    reporter_name: str = "Vecino Demo"
    reporter_role: str = "ciudadano"
    transcript_text: str
    severity_score: float = Field(ge=0.0, le=1.0)
    water_level_category: str = "unknown"
    trend: str = "stable"
    road_status: str = "open"
    bridge_status: str = "unknown"
    homes_affected: bool = False
    urgency: str = "low"
    summary: str = ""


@router.post("/demo/inject-volunteer-report")
async def inject_volunteer_report(
    payload: VolunteerInjectRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    if not demo_inject_enabled():
        raise HTTPException(status_code=404, detail="Demo inject endpoint disabled")

    site = session.get(Site, payload.site_id)
    if site is None:
        raise HTTPException(status_code=404, detail=f"Site {payload.site_id} not found")

    report = VolunteerReport(
        site_id=payload.site_id,
        reporter_name=payload.reporter_name,
        reporter_role=payload.reporter_role,
        transcript_text=payload.transcript_text,
        offline_created=False,
    )
    session.add(report)
    session.flush()
    enqueue_entity(session, "volunteer_report", report)

    parsed = ParsedObservation(
        volunteer_report_id=report.id or 0,
        water_level_category=payload.water_level_category,
        trend=payload.trend,
        road_status=payload.road_status,
        bridge_status=payload.bridge_status,
        homes_affected=payload.homes_affected,
        urgency=payload.urgency,
        confidence=0.85,
        structured_json=json.dumps({"demo_inject": True}, ensure_ascii=True),
        decision_trace=json.dumps(["demo_inject: synthetic volunteer report"], ensure_ascii=True),
        parser_source="demo-inject",
        severity_score=payload.severity_score,
        summary=payload.summary or payload.transcript_text[:140],
    )
    session.add(parsed)
    session.flush()
    enqueue_entity(session, "parsed_observation", parsed)

    alert = recompute_site_alert(session, payload.site_id, llm_client)
    session.flush()
    enqueue_entity(session, "fused_alert", alert)
    if alert.incident_id is not None:
        incident = session.get(Incident, alert.incident_id)
        if incident is not None:
            enqueue_entity(session, "incident", incident)
    for record in session.exec(
        select(ActuationRecord).where(ActuationRecord.alert_id == alert.id)
    ).all():
        enqueue_entity(session, "actuation_record", record)
    session.commit()
    session.refresh(parsed)
    session.refresh(alert)

    return {
        "report_id": report.id,
        "parsed_id": parsed.id,
        "alert": _serialize_alert(alert),
    }
