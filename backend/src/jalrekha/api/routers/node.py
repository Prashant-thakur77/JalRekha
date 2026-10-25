from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, desc, select

from jalrekha.api.deps import (
    node_engine,
    node_image_assessor,
    node_runtime,
    enqueue_entity,
)
from jalrekha.api.serializers import serialize_observation
from jalrekha.core.settings import get_settings
from jalrekha.db.database import get_session
from jalrekha.models.domain import NodeAssessmentArtifact, ActuationRecord, FusedAlert, Incident, NodeObservation, Site
from jalrekha.services.node_assessment import NodeAssessment, NodeAssessmentEngine, cv_level
from jalrekha.services.vision_runner import stage_series_rate
from jalrekha.vision.gauge import GaugeCalibration
from jalrekha.services.calibration import get_latest_site_calibration
from jalrekha.services.decision_engine import recompute_site_alert
from jalrekha.services.storage import persist_upload, public_asset_url_for_path, resolve_local_asset_path


router = APIRouter(tags=["node"])


def _should_run_multimodal_verifier(
    session: Session,
    site_id: str,
    assessment: NodeAssessment,
) -> tuple[bool, str]:
    settings = get_settings()
    if not settings.node_multimodal_verifier_enabled:
        return False, "disabled"
    if not assessment.evidence_pack.evidence_frame_path:
        return False, "no evidence frame"

    triggers: list[str] = []
    if assessment.crossed_critical_line_hint:
        triggers.append("critical line crossed")
    if assessment.verdict.assessment_score >= settings.node_multimodal_score_threshold:
        triggers.append(f"score>={settings.node_multimodal_score_threshold:.2f}")
    if assessment.confidence <= settings.node_multimodal_confidence_threshold:
        triggers.append(f"confidence<={settings.node_multimodal_confidence_threshold:.2f}")

    last_verified = session.exec(
        select(NodeObservation)
        .where(NodeObservation.site_id == site_id)
        .where(NodeObservation.image_assessment_model.is_not(None))
        .order_by(desc(NodeObservation.ended_at))
    ).first()
    if last_verified is None:
        interval_due = True
        seconds_since = None
    else:
        seconds_since = max(0.0, (datetime.utcnow() - last_verified.ended_at).total_seconds())
        interval_due = seconds_since >= settings.node_multimodal_min_interval_seconds

    if assessment.crossed_critical_line_hint:
        return True, "triggered: " + ", ".join(triggers)
    if interval_due:
        if triggers:
            return True, "scheduled with trigger: " + ", ".join(triggers)
        if seconds_since is None:
            return True, "scheduled: first multimodal verification"
        return True, f"scheduled: {seconds_since:.0f}s since last verification"
    if triggers:
        return False, f"interval hold after trigger ({', '.join(triggers)}): {seconds_since:.0f}s since last verification"
    return False, f"interval hold: {seconds_since:.0f}s since last verification"


def apply_vision_to_observation(session: Session, observation: NodeObservation, assessment: NodeAssessment) -> None:
    """Copy the OpenCV gauge measurement onto the observation and add the Kalman rise rate.

    When the reading is usable, the deterministic metric level (stage vs the
    site's warning/danger levels and rise rate) sets severity; the model's own
    level is kept in critical_evidence as ``model_level`` for audit.
    """
    vision = assessment.evidence_pack.vision
    if vision is None:
        return
    m = vision.measurement
    observation.cv_measurement_json = json.dumps(m, ensure_ascii=True)
    observation.cv_usable = vision.usable
    observation.cv_method = (m.get("registration") or {}).get("method")
    observation.cv_quality = json.dumps((m.get("quality") or {}).get("reasons", []))
    observation.overlay_path = vision.overlay_path
    if vision.redacted_path:
        observation.evidence_frame_path = vision.redacted_path
    if not vision.usable or vision.stage_m is None:
        return
    observation.stage_m = vision.stage_m
    observation.stage_sigma_m = vision.sigma_m
    since = observation.ended_at - timedelta(hours=3)
    history = session.exec(
        select(NodeObservation)
        .where(NodeObservation.site_id == observation.site_id)
        .where(NodeObservation.stage_m.is_not(None))
        .where(NodeObservation.ended_at >= since)
    ).all()
    series = [(h.ended_at, h.stage_m, h.stage_sigma_m or 0.03) for h in history]
    series.append((observation.ended_at, vision.stage_m, vision.sigma_m or 0.03))
    filtered = stage_series_rate(series)
    if filtered is not None and filtered["n_used"] >= 2:
        observation.rate_m_per_h = filtered["rate_m_per_h"]
    calibration = get_latest_site_calibration(session, observation.site_id)
    gauge = GaugeCalibration.from_json(getattr(calibration, "gauge_json", None))
    level, score = cv_level(
        vision.stage_m,
        gauge.warning_m if gauge else None,
        gauge.danger_m if gauge else None,
        observation.rate_m_per_h,
    )
    evidence = json.loads(observation.critical_evidence or "{}")
    evidence["model_level"] = observation.assessment_level
    evidence["model_score"] = observation.assessment_score
    evidence["cv_level"] = level
    observation.critical_evidence = json.dumps(evidence, ensure_ascii=True)
    observation.assessment_level = level
    observation.severity_score = score
    observation.assessment_score = score
    observation.crossed_critical_line = bool(gauge and gauge.danger_m is not None and vision.stage_m >= gauge.danger_m)
    observation.analysis_mode = "opencv5-gauge-v1"


def create_node_observation(
    session: Session,
    site_id: str,
    source_type: str,
    video_path: str,
    assessment: NodeAssessment,
) -> tuple[NodeObservation, FusedAlert]:
    settings = get_settings()
    artifact_payload = {
        "manifest_path": assessment.evidence_pack.artifact_pack.manifest_path,
        "selected_frame_paths": assessment.evidence_pack.artifact_pack.selected_frame_paths,
        "evidence_frame_path": assessment.evidence_pack.artifact_pack.evidence_frame_path,
        "retention_days": settings.node_artifact_retention_days,
        "max_curated_frames": settings.node_max_curated_frames,
        "multimodal_primary": {
            "enabled": settings.node_multimodal_enabled,
            "base_url": settings.node_multimodal_base_url,
            "model": settings.node_multimodal_model,
            "max_frames": settings.node_multimodal_max_frames,
            "frame_sample_seconds": settings.node_multimodal_frame_sample_seconds,
            "image_max_side": settings.node_multimodal_image_max_side,
            "num_ctx": settings.node_multimodal_num_ctx,
        },
    }
    artifact = NodeAssessmentArtifact(
        site_id=site_id,
        source_type=source_type,
        video_path=video_path,
        assessment_mode="gemma4-multimodal-v1",
        frames_analyzed=assessment.evidence_pack.frames_analyzed,
        temporal_summary=assessment.verdict.temporal_summary,
        reasoning_summary=assessment.verdict.reasoning_summary,
        reasoning_steps=json.dumps(assessment.verdict.reasoning_steps, ensure_ascii=True),
        critical_evidence=json.dumps(assessment.verdict.critical_evidence, ensure_ascii=True),
        runner_name=assessment.verdict.runner_name,
        runner_mode=assessment.verdict.runner_mode,
        fallback_used=assessment.verdict.fallback_used,
        bundle_json=NodeAssessmentEngine.bundle_json(assessment.evidence_pack),
        verdict_json=json.dumps(assessment.verdict.__dict__, ensure_ascii=True),
        artifact_refs=json.dumps(artifact_payload, ensure_ascii=True),
    )
    session.add(artifact)
    session.flush()
    enqueue_entity(session, "node_assessment_artifact", artifact)

    run_multimodal, multimodal_reason = _should_run_multimodal_verifier(session, site_id, assessment)
    assessment.decision_trace.append(f"multimodal verifier {multimodal_reason}")

    image_summary = None
    if run_multimodal:
        frame_path = (
            resolve_local_asset_path(assessment.evidence_pack.evidence_frame_path)
            or Path(assessment.evidence_pack.evidence_frame_path)
        )
        try:
            image_summary = node_image_assessor.assess(frame_path)
        except Exception:
            image_summary = None
        if image_summary is None:
            assessment.decision_trace.append("multimodal verifier unavailable or invalid, kept primary multimodal verdict")
        else:
            assessment.decision_trace.append(
                f"multimodal verifier {image_summary.model_name} returned confidence={image_summary.confidence:.2f}"
            )

    observation = NodeObservation(
        site_id=site_id,
        source_type=source_type,
        video_path=video_path,
        started_at=assessment.evidence_pack.started_at,
        ended_at=assessment.evidence_pack.ended_at,
        frames_analyzed=assessment.evidence_pack.frames_analyzed,
        waterline_ratio=assessment.waterline_ratio_hint,
        rise_velocity=assessment.rise_velocity_hint,
        crossed_critical_line=assessment.crossed_critical_line_hint,
        confidence=assessment.confidence,
        decision_trace=json.dumps(assessment.decision_trace, ensure_ascii=True),
        severity_score=assessment.verdict.assessment_score,
        assessment_score=assessment.verdict.assessment_score,
        assessment_level=assessment.verdict.assessment_level,
        evidence_frame_path=assessment.evidence_pack.evidence_frame_path,
        analysis_mode="ffmpeg-frame-sampler-v1",
        assessment_mode="gemma4-multimodal-v1",
        temporal_summary=assessment.verdict.temporal_summary,
        reasoning_summary=assessment.verdict.reasoning_summary,
        reasoning_steps=json.dumps(assessment.verdict.reasoning_steps, ensure_ascii=True),
        critical_evidence=json.dumps(assessment.verdict.critical_evidence, ensure_ascii=True),
        runner_name=assessment.verdict.runner_name,
        runner_mode=assessment.verdict.runner_mode,
        fallback_used=assessment.verdict.fallback_used,
        artifact_refs=json.dumps(artifact_payload, ensure_ascii=True),
        assessment_artifact_id=artifact.id,
    )

    apply_vision_to_observation(session, observation, assessment)

    if image_summary is not None:
        observation.image_description = image_summary.description_es
        observation.image_assessment_model = image_summary.model_name
        observation.image_assessment_confidence = image_summary.confidence
        observation.image_water_visible = image_summary.water_visible
        observation.image_infrastructure_at_risk = image_summary.infrastructure_at_risk

    session.add(observation)
    session.flush()
    enqueue_entity(session, "node_observation", observation)

    alert = recompute_site_alert(session, site_id, node_runtime)
    session.flush()
    enqueue_entity(session, "fused_alert", alert)
    if alert.incident_id is not None:
        incident = session.get(Incident, alert.incident_id)
        if incident is not None:
            enqueue_entity(session, "incident", incident)
    for record in session.exec(select(ActuationRecord).where(ActuationRecord.alert_id == alert.id)).all():
        enqueue_entity(session, "actuation_record", record)
    session.commit()
    session.refresh(observation)
    session.refresh(alert)
    return observation, alert


@router.post("/node/analyze")
async def analyze_node(
    site_id: str = Form(...),
    video: UploadFile | None = File(None),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    if video is None:
        raise HTTPException(status_code=400, detail="video is required for real node analysis")

    video_path = persist_upload(video, "video")
    calibration = get_latest_site_calibration(session, site_id)
    try:
        result = node_engine.assess_video(site, video_path or "", calibration, source_type="video")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Node analysis failed: {exc}") from exc

    observation, alert = create_node_observation(
        session=session,
        site_id=site_id,
        source_type="video",
        video_path=video_path or "",
        assessment=result,
    )

    if alert.local_alarm_triggered:
        print(f"!!! LOCAL ALARM TRIGGERED FOR SITE {site_id} VIA NODE ANALYSIS !!!")

    return {"observation": serialize_observation(observation), "alert": alert}


@router.post("/node/explain-frame")
async def explain_frame(frame: UploadFile = File(...)) -> dict[str, Any]:
    path = persist_upload(frame, "frame")
    if not path:
        raise HTTPException(status_code=400, detail="frame upload failed")
    assessment = node_image_assessor.assess(path)
    if assessment is None:
        raise HTTPException(status_code=503, detail="Image assessment unavailable (LLM down or invalid output)")
    return {
        "description_es": assessment.description_es,
        "water_visible": assessment.water_visible,
        "infrastructure_at_risk": assessment.infrastructure_at_risk,
        "confidence": assessment.confidence,
        "model_name": assessment.model_name,
        "frame_url": public_asset_url_for_path(path),
    }


@router.post("/sites/{site_id}/sample-node-analysis")
async def analyze_site_sample(site_id: str, session: Session = Depends(get_session)) -> dict[str, object]:
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    if not site.sample_video_path:
        raise HTTPException(status_code=404, detail="Site does not have a bundled sample clip")

    sample_path = resolve_local_asset_path(site.sample_video_path)
    if sample_path is None or not sample_path.exists():
        raise HTTPException(status_code=404, detail="Bundled sample clip is missing from disk")

    calibration = get_latest_site_calibration(session, site_id)
    try:
        result = node_engine.assess_video(site, str(sample_path), calibration, source_type="sample_video")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Sample node analysis failed: {exc}") from exc

    observation, alert = create_node_observation(
        session=session,
        site_id=site_id,
        source_type="sample_video",
        video_path=str(sample_path),
        assessment=result,
    )

    return {
        "observation": serialize_observation(observation),
        "alert": alert,
        "sample_video_url": public_asset_url_for_path(site.sample_video_path),
        "sample_video_source_url": site.sample_video_source_url,
    }
