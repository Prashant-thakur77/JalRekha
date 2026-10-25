from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from jalrekha.api.deps import node_runtime, enqueue_entity
from jalrekha.db.database import get_session
from jalrekha.models.domain import ActuationRecord, FusedAlert, HydrometSnapshot, Incident, NodeObservation, ParsedObservation, Site, SyncQueueItem, VolunteerReport
from jalrekha.schemas.api import RecomputeRequest
from jalrekha.services.decision_engine import recompute_site_alert
from jalrekha.services.historical_context import render_historical_context, retrieve_historical_context


router = APIRouter(tags=["alerts"])


def _parsed_json(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value) if value else fallback
    except json.JSONDecodeError:
        return fallback


def _trace_rules(trace: Any) -> list[Any]:
    if isinstance(trace, list):
        return trace
    if isinstance(trace, dict):
        rules = trace.get("rules_fired")
        if isinstance(rules, list):
            return rules
    return []


def _enqueue_decision_side_effects(session: Session, alert: FusedAlert) -> None:
    if alert.incident_id is not None:
        incident = session.get(Incident, alert.incident_id)
        if incident is not None:
            enqueue_entity(session, "incident", incident)
    for record in session.exec(select(ActuationRecord).where(ActuationRecord.alert_id == alert.id)).all():
        enqueue_entity(session, "actuation_record", record)


def _alert_payload(alert: FusedAlert, *, include_historical_context: bool = False) -> dict[str, Any]:
    payload = alert.model_dump(mode="json")
    if not include_historical_context:
        return payload
    trace = _parsed_json(alert.decision_trace, {})
    if not isinstance(trace, dict):
        trace = {"legacy_trace": trace}
    current_level = None
    evidence = trace.get("evidence")
    if isinstance(evidence, list):
        for event in evidence:
            if isinstance(event, dict) and event.get("source") == "node":
                event_payload = event.get("payload")
                if isinstance(event_payload, dict):
                    current_level = event_payload.get("waterline_ratio")
                    break
    hits = retrieve_historical_context(alert.site_id, current_level=float(current_level or 0.0))
    trace["historical_context"] = {
        "enabled": True,
        "mode": "edge-rag-sqlite",
        "hits": [hit.__dict__ for hit in hits],
    }
    context = render_historical_context(hits)
    if context:
        payload["reasoning_summary"] = f"{payload.get('reasoning_summary') or alert.summary} Historical context: {context[:180]}"
    payload["decision_trace"] = json.dumps(trace, ensure_ascii=True)
    return payload


@router.get("/alerts")
async def get_alerts(
    historical_context: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    alerts = session.exec(select(FusedAlert).order_by(FusedAlert.created_at.desc())).all()
    return [_alert_payload(alert, include_historical_context=historical_context) for alert in alerts]


@router.get("/alerts/{alert_id}")
async def get_alert(alert_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    alert = session.get(FusedAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    payload = alert.model_dump(mode="json")
    payload["reasoning_chain_parsed"] = _parsed_json(alert.reasoning_chain, [])
    structured_trace = _parsed_json(alert.decision_trace, {})
    payload["decision_trace_parsed"] = _trace_rules(structured_trace)
    payload["decision_trace_structured"] = structured_trace
    payload["incident"] = session.get(Incident, alert.incident_id) if alert.incident_id else None
    payload["actuations"] = session.exec(select(ActuationRecord).where(ActuationRecord.alert_id == alert.id)).all()
    return payload


@router.post("/alerts/{alert_id}/export-sinagir")
async def export_alert_sinagir(alert_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    alert = session.get(FusedAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    site = session.get(Site, alert.site_id)
    trace = _parsed_json(alert.decision_trace, {})
    chain = _parsed_json(alert.reasoning_chain, [])
    incident = session.get(Incident, alert.incident_id) if alert.incident_id else None
    actuations = session.exec(select(ActuationRecord).where(ActuationRecord.alert_id == alert.id)).all()
    return {
        "schema": "sinagir-ready-v1",
        "disclaimer": "Schema export only. Not submitted to SINAGIR production endpoints.",
        "event": {
            "external_id": f"node-alert-{alert.id}",
            "observed_at": alert.created_at.isoformat() if alert.created_at else None,
            "site": {
                "id": alert.site_id,
                "name": site.name if site else alert.site_id,
                "region": site.region if site else None,
                "lat": site.lat if site else None,
                "lng": site.lng if site else None,
            },
            "hazard_type": "inundacion",
            "severity": {
                "level": alert.level,
                "score": alert.score,
            },
            "trigger_source": alert.trigger_source,
            "summary": alert.summary,
            "explanation": _trace_rules(trace),
            "decision_trace": trace,
            "reasoning": {
                "summary": alert.reasoning_summary,
                "chain": chain,
                "model": alert.reasoning_model,
            },
            "local_actuation": {
                "siren_triggered": alert.local_alarm_triggered,
                "records": [record.model_dump(mode="json") for record in actuations],
            },
            "incident": {
                "id": incident.id,
                "state": incident.lifecycle_state,
                "current_level": incident.current_level,
                "opened_at": incident.opened_at.isoformat() if incident.opened_at else None,
                "closed_at": incident.closed_at.isoformat() if incident.closed_at else None,
            } if incident else None,
            "origin_system": "JalRekha (edge)",
        },
    }


@router.get("/sites/{site_id}/operator-summary")
async def get_site_operator_summary(site_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")

    latest_alert = session.exec(
        select(FusedAlert).where(FusedAlert.site_id == site_id).order_by(FusedAlert.created_at.desc())
    ).first()
    active_incident = session.exec(
        select(Incident)
        .where(Incident.site_id == site_id)
        .where(Incident.closed_at.is_(None))
        .order_by(Incident.updated_at.desc())
    ).first()
    latest_node = session.exec(
        select(NodeObservation).where(NodeObservation.site_id == site_id).order_by(NodeObservation.ended_at.desc())
    ).first()
    latest_report = session.exec(
        select(VolunteerReport).where(VolunteerReport.site_id == site_id).order_by(VolunteerReport.created_at.desc())
    ).first()
    latest_parsed = None
    if latest_report and latest_report.id is not None:
        latest_parsed = session.exec(
            select(ParsedObservation)
            .where(ParsedObservation.volunteer_report_id == latest_report.id)
            .order_by(ParsedObservation.id.desc())
        ).first()
    latest_hydromet = session.exec(
        select(HydrometSnapshot).where(HydrometSnapshot.site_id == site_id).order_by(HydrometSnapshot.created_at.desc())
    ).first()
    latest_actuation = session.exec(
        select(ActuationRecord).where(ActuationRecord.site_id == site_id).order_by(ActuationRecord.created_at.desc())
    ).first()
    sync_items = session.exec(select(SyncQueueItem)).all()
    sync_counts = {"pending": 0, "synced": 0, "failed": 0}
    for item in sync_items:
        sync_counts[item.status] = sync_counts.get(item.status, 0) + 1

    return {
        "site": site,
        "current_level": latest_alert.level if latest_alert else "green",
        "current_score": latest_alert.score if latest_alert else 0.0,
        "active_incident": active_incident,
        "latest_alert": latest_alert,
        "latest_evidence": {
            "node": latest_node,
            "volunteer_report": latest_report,
            "parsed_observation": latest_parsed,
            "hydromet": latest_hydromet,
        },
        "sync": sync_counts,
        "latest_actuation": latest_actuation,
    }


@router.get("/incidents/{incident_id}/timeline")
async def get_incident_timeline(incident_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    alerts = session.exec(
        select(FusedAlert).where(FusedAlert.incident_id == incident_id).order_by(FusedAlert.created_at)
    ).all()
    actuations = session.exec(
        select(ActuationRecord).where(ActuationRecord.incident_id == incident_id).order_by(ActuationRecord.created_at)
    ).all()
    return {
        "incident": incident,
        "alerts": [
            {
                **alert.model_dump(mode="json"),
                "decision_trace_parsed": _parsed_json(alert.decision_trace, {}),
            }
            for alert in alerts
        ],
        "actuations": actuations,
    }


@router.post("/incidents/{incident_id}/ack")
async def acknowledge_incident(
    incident_id: int,
    operator: str = Query(default="operator"),
    session: Session = Depends(get_session),
) -> Incident:
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    incident.acknowledged_at = datetime.utcnow()
    incident.acknowledged_by = operator
    incident.updated_at = incident.acknowledged_at
    session.add(incident)
    session.flush()
    enqueue_entity(session, "incident", incident)
    session.commit()
    session.refresh(incident)
    return incident


@router.post("/incidents/{incident_id}/close")
async def close_incident(
    incident_id: int,
    reason: str = Query(default="manual_operator_close"),
    session: Session = Depends(get_session),
) -> Incident:
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    now = datetime.utcnow()
    incident.lifecycle_state = "closed"
    incident.current_level = "green"
    incident.closed_at = now
    incident.updated_at = now
    incident.close_reason = reason
    session.add(incident)
    session.flush()
    enqueue_entity(session, "incident", incident)
    session.commit()
    session.refresh(incident)
    return incident


@router.post("/alerts/recompute")
async def recompute_alerts(
    payload: RecomputeRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    site_ids = [payload.site_id] if payload.site_id else [site.id for site in session.exec(select(Site)).all()]
    results: list[dict[str, object]] = []
    for site_id in site_ids:
        alert = recompute_site_alert(
            session,
            site_id,
            node_runtime,
            use_historical_context=payload.use_historical_context,
        )
        session.flush()
        enqueue_entity(session, "fused_alert", alert)
        _enqueue_decision_side_effects(session, alert)
        results.append({"site_id": site_id, "score": alert.score, "level": alert.level})
    session.commit()
    return {"recomputed": len(results), "items": results}

