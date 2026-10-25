from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select

from jalrekha.api.deps import (
    asr_client,
    enqueue_entity,
    get_decision_runtime,
    image_assessor,
    text_structurer,
)
from jalrekha.db.database import get_session, session_scope
from jalrekha.models.domain import ActuationRecord, Incident, ParsedObservation, Site, VolunteerReport
from jalrekha.services.decision_engine import recompute_site_alert
from jalrekha.services.report_structuring import structure_report, structured_result_to_json
from jalrekha.services.storage import persist_upload


_LOGGER = logging.getLogger(__name__)


router = APIRouter(tags=["volunteer"])


@router.post("/reports")
async def create_report(
    background_tasks: BackgroundTasks,
    site_id: str = Form(...),
    reporter_name: str = Form(...),
    reporter_role: str = Form(...),
    transcript_text: str = Form(""),
    offline_created: bool = Form(False),
    photo: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")

    photo_path = persist_upload(photo, "photo")
    audio_path = persist_upload(audio, "audio")

    effective_transcript = transcript_text
    if (not effective_transcript or not effective_transcript.strip()) and audio_path:
        transcribed = asr_client.transcribe(audio_path)
        if transcribed:
            effective_transcript = transcribed
            _LOGGER.info("ASR populated transcript for site %s: %d chars", site_id, len(transcribed))

    report = VolunteerReport(
        site_id=site_id,
        reporter_name=reporter_name,
        reporter_role=reporter_role,
        photo_path=photo_path,
        audio_path=audio_path,
        transcript_text=effective_transcript,
        offline_created=offline_created,
    )
    session.add(report)
    session.flush()
    enqueue_entity(session, "volunteer_report", report)

    structured = structure_report(effective_transcript, site, text_structurer)
    parsed = ParsedObservation(
        volunteer_report_id=report.id or 0,
        water_level_category=structured.water_level_category,
        trend=structured.trend,
        road_status=structured.road_status,
        bridge_status=structured.bridge_status,
        homes_affected=structured.homes_affected,
        urgency=structured.urgency,
        confidence=structured.confidence,
        structured_json=structured_result_to_json(structured),
        decision_trace=json.dumps(structured.decision_trace, ensure_ascii=True),
        parser_source=structured.parser_source,
        severity_score=structured.severity_score,
        summary=structured.summary,
    )
    session.add(parsed)
    session.flush()
    enqueue_entity(session, "parsed_observation", parsed)

    alert = recompute_site_alert(session, site_id, get_decision_runtime())
    session.flush()
    enqueue_entity(session, "fused_alert", alert)
    if alert.incident_id is not None:
        incident = session.get(Incident, alert.incident_id)
        if incident is not None:
            enqueue_entity(session, "incident", incident)
    for record in session.exec(select(ActuationRecord).where(ActuationRecord.alert_id == alert.id)).all():
        enqueue_entity(session, "actuation_record", record)
    session.commit()
    session.refresh(report)
    session.refresh(parsed)
    session.refresh(alert)

    if alert.local_alarm_triggered:
        _LOGGER.info(
            "local alarm triggered for site %s (alert id=%s level=%s)",
            site_id,
            alert.id,
            alert.level,
        )

    if photo_path and image_assessor.settings.volunteer_image_enabled:
        background_tasks.add_task(_enrich_with_image_assessment, parsed.id, photo_path)

    return {"report": report, "parsed": parsed, "alert": alert}


@router.get("/reports")
async def get_reports(session: Session = Depends(get_session)) -> list[VolunteerReport]:
    return session.exec(select(VolunteerReport).order_by(VolunteerReport.created_at.desc())).all()


def _enrich_with_image_assessment(parsed_id: int | None, photo_path: str) -> None:
    """Background task: run image_assessor on the volunteer photo and append the
    description to the ParsedObservation's decision_trace. Strictly descriptive
    — never modifies severity_score or alert level (the alert was already
    emitted; reopening it would be a separate ``recompute_site_alert`` call)."""
    if parsed_id is None:
        return
    try:
        result = image_assessor.assess(photo_path)
    except Exception as exc:  # pragma: no cover - defensive
        _LOGGER.warning("image_assessor failed: %s", exc)
        return
    if result is None:
        return
    try:
        with session_scope() as session:
            parsed = session.get(ParsedObservation, parsed_id)
            if parsed is None:
                return
            try:
                trace = json.loads(parsed.decision_trace or "[]")
                if not isinstance(trace, list):
                    trace = []
            except json.JSONDecodeError:
                trace = []
            trace.append(f"image_description: {result.description_es}")
            trace.append(
                f"image_flags: water_visible={result.water_visible} "
                f"infrastructure_at_risk={result.infrastructure_at_risk} "
                f"confidence={result.confidence:.2f}"
            )
            parsed.decision_trace = json.dumps(trace, ensure_ascii=True)
            session.add(parsed)
            session.commit()
            _LOGGER.info("image assessment persisted for parsed_observation %d", parsed_id)
    except Exception as exc:  # pragma: no cover - defensive
        _LOGGER.warning("image enrichment commit failed: %s", exc)
