from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlmodel import Session, select

from jalrekha.models.domain import (
    ActuationRecord,
    FusedAlert,
    HydrometSnapshot,
    Incident,
    NodeObservation,
    ParsedObservation,
    VolunteerReport,
)
from jalrekha.services.actuators import ACTUATOR_REGISTRY, dispatch_actuators
from jalrekha.services.historical_context import render_historical_context, retrieve_historical_context
from jalrekha.services.predictive import Measurement, forecast_short_term
from jalrekha.services.reasoning import generate_alert_reasoning, serialize_chain


DEFAULT_EVIDENCE_WINDOW_MINUTES = 45
STALE_DECAY_FLOOR = 0.45


class DecisionRuntime(Protocol):
    def generate_text(self, system_prompt: str, user_prompt: str, max_tokens: int = 320) -> str | None: ...


LEVEL_MEANINGS = {
    "green": "No recent evidence of operational risk.",
    "yellow": "Emerging risk or moderate local evidence requiring monitoring.",
    "orange": "Corroborated high risk or one critical source requiring local preparation/action.",
    "red": "Severe risk or observed impact requiring immediate action.",
}


@dataclass(frozen=True)
class EvidenceEvent:
    source: str
    entity_id: int | None
    observed_at: datetime
    raw_score: float
    weighted_score: float
    weight: float
    summary: str
    rules: list[str]
    payload: dict[str, Any]


def level_from_score(score: float) -> str:
    if score >= 0.82:
        return "red"
    if score >= 0.62:
        return "orange"
    if score >= 0.4:
        return "yellow"
    return "green"


def normalize_score(score: float | None) -> float:
    if score is None:
        return 0.0
    return max(0.0, min(1.0, float(score)))


def temporal_weight(observed_at: datetime, now: datetime, window_minutes: int) -> float:
    age_seconds = max(0.0, (now - observed_at).total_seconds())
    window_seconds = max(60.0, window_minutes * 60.0)
    if age_seconds < 1.0:
        return 1.0
    if age_seconds > window_seconds:
        return 0.0
    return max(STALE_DECAY_FLOOR, 1.0 - (age_seconds / window_seconds) * (1.0 - STALE_DECAY_FLOOR))


def _node_rules(node: NodeObservation) -> list[str]:
    rules = [f"node_score={node.severity_score:.2f}"]
    if node.crossed_critical_line:
        rules.append("node_critical_line_crossed")
    if node.rise_velocity > 0.08:
        rules.append("node_fast_rise")
    if node.assessment_level:
        rules.append(f"node_level={node.assessment_level}")
    return rules


def _volunteer_rules(parsed: ParsedObservation) -> list[str]:
    rules = [f"volunteer_score={parsed.severity_score:.2f}"]
    if parsed.water_level_category in {"high", "critical", "above_critical"}:
        rules.append("volunteer_mark_exceeded")
    if parsed.trend in {"rising_fast", "rapid_rise", "subiendo_rapido"}:
        rules.append("volunteer_fast_rise")
    if parsed.homes_affected:
        rules.append("volunteer_homes_affected")
    if parsed.road_status in {"closed", "cut", "blocked", "cortada"}:
        rules.append("volunteer_road_cut")
    if parsed.bridge_status in {"compromised", "unsafe", "blocked", "cortado"}:
        rules.append("volunteer_bridge_compromised")
    if parsed.urgency in {"high", "critical", "urgent"}:
        rules.append(f"volunteer_urgency={parsed.urgency}")
    return rules


def _hydromet_rules(snapshot: HydrometSnapshot) -> list[str]:
    rules = [f"hydromet_score={snapshot.signal_score:.2f}"]
    if snapshot.precipitation_mm >= 20 or snapshot.rain_mm >= 20:
        rules.append("hydromet_heavy_rain")
    if snapshot.precipitation_probability >= 70:
        rules.append("hydromet_high_rain_probability")
    if snapshot.river_discharge_trend and snapshot.river_discharge_trend > 0:
        rules.append("hydromet_river_rising")
    return rules


def _volunteer_is_critical(parsed: ParsedObservation | None) -> bool:
    if parsed is None:
        return False
    return any(
        rule
        in {
            "volunteer_mark_exceeded",
            "volunteer_fast_rise",
            "volunteer_homes_affected",
            "volunteer_road_cut",
            "volunteer_bridge_compromised",
            "volunteer_urgency=critical",
        }
        for rule in _volunteer_rules(parsed)
    )


def _collect_evidence(
    session: Session,
    site_id: str,
    now: datetime,
    window_minutes: int,
) -> list[EvidenceEvent]:
    window_start = now - timedelta(minutes=window_minutes)
    events: list[EvidenceEvent] = []

    nodes = session.exec(
        select(NodeObservation)
        .where(NodeObservation.site_id == site_id)
        .where(NodeObservation.ended_at >= window_start)
        .order_by(NodeObservation.ended_at.desc())
    ).all()
    for node in nodes:
        raw = normalize_score(node.severity_score)
        weight = temporal_weight(node.ended_at, now, window_minutes)
        events.append(
            EvidenceEvent(
                source="node",
                entity_id=node.id,
                observed_at=node.ended_at,
                raw_score=raw,
                weighted_score=raw * weight,
                weight=weight,
                summary=node.temporal_summary
                or f"Node ratio {node.waterline_ratio:.2f} ({'crossed' if node.crossed_critical_line else 'below'} critical)",
                rules=_node_rules(node),
                payload={
                    "waterline_ratio": node.waterline_ratio,
                    "rise_velocity": node.rise_velocity,
                    "crossed_critical_line": node.crossed_critical_line,
                    "confidence": node.confidence,
                    "temporal_summary": node.temporal_summary,
                    "runner_name": node.runner_name,
                    "runner_mode": node.runner_mode,
                    "fallback_used": node.fallback_used,
                },
            )
        )

    reports = session.exec(
        select(VolunteerReport)
        .where(VolunteerReport.site_id == site_id)
        .where(VolunteerReport.created_at >= window_start)
        .order_by(VolunteerReport.created_at.desc())
    ).all()
    for report in reports:
        if report.id is None:
            continue
        parsed = session.exec(
            select(ParsedObservation)
            .where(ParsedObservation.volunteer_report_id == report.id)
            .order_by(ParsedObservation.id.desc())
        ).first()
        if parsed is None:
            continue
        raw = normalize_score(parsed.severity_score)
        if _volunteer_is_critical(parsed):
            raw = min(1.0, max(raw, 0.72))
        weight = temporal_weight(report.created_at, now, window_minutes)
        events.append(
            EvidenceEvent(
                source="volunteer",
                entity_id=parsed.id,
                observed_at=report.created_at,
                raw_score=raw,
                weighted_score=raw * weight,
                weight=weight,
                summary=parsed.summary,
                rules=_volunteer_rules(parsed),
                payload={
                    "report_id": report.id,
                    "water_level_category": parsed.water_level_category,
                    "trend": parsed.trend,
                    "road_status": parsed.road_status,
                    "bridge_status": parsed.bridge_status,
                    "homes_affected": parsed.homes_affected,
                    "urgency": parsed.urgency,
                    "summary": parsed.summary,
                },
            )
        )

    hydromet = session.exec(
        select(HydrometSnapshot)
        .where(HydrometSnapshot.site_id == site_id)
        .where(HydrometSnapshot.created_at >= window_start)
        .order_by(HydrometSnapshot.created_at.desc())
    ).all()
    for snapshot in hydromet:
        raw = normalize_score(snapshot.signal_score)
        weight = temporal_weight(snapshot.created_at, now, window_minutes)
        events.append(
            EvidenceEvent(
                source="hydromet",
                entity_id=snapshot.id,
                observed_at=snapshot.created_at,
                raw_score=raw,
                weighted_score=raw * weight,
                weight=weight,
                summary=snapshot.summary,
                rules=_hydromet_rules(snapshot),
                payload={
                    "precipitation_mm": snapshot.precipitation_mm,
                    "rain_mm": snapshot.rain_mm,
                    "precipitation_probability": snapshot.precipitation_probability,
                    "river_discharge": snapshot.river_discharge,
                    "river_discharge_trend": snapshot.river_discharge_trend,
                },
            )
        )

    return sorted(events, key=lambda event: event.observed_at, reverse=True)


def _score_events(events: list[EvidenceEvent]) -> tuple[float, str, list[str]]:
    if not events:
        return 0.0, "fused", ["no_recent_evidence"]

    strongest = max(events, key=lambda event: event.weighted_score)
    fused_score = strongest.weighted_score
    rules_fired = [rule for event in events for rule in event.rules]

    supporting_sources = {event.source for event in events if event.weighted_score >= 0.35}
    if len(supporting_sources) >= 2:
        bonus = min(0.18, 0.08 * (len(supporting_sources) - 1))
        fused_score = min(1.0, fused_score + bonus)
        rules_fired.append(f"corroboration_sources={','.join(sorted(supporting_sources))}")

    medium_signals = [event for event in events if 0.38 <= event.weighted_score < 0.62]
    if len({event.source for event in medium_signals}) >= 2:
        fused_score = max(fused_score, 0.62)
        rules_fired.append("two_medium_sources_escalate_to_orange")

    local_sources = {event.source: event.weighted_score for event in events}
    if local_sources.get("node", 0.0) < 0.25 and local_sources.get("volunteer", 0.0) >= 0.62:
        rules_fired.append("contradiction_node_low_volunteer_high")
    if local_sources.get("hydromet", 0.0) < 0.25 and max(local_sources.get("node", 0.0), local_sources.get("volunteer", 0.0)) >= 0.62:
        rules_fired.append("local_evidence_stronger_than_hydromet")

    critical_rules = {rule for rule in rules_fired if rule.startswith("volunteer_") or rule == "node_critical_line_crossed"}
    if "node_critical_line_crossed" in critical_rules:
        fused_score = max(fused_score, 0.82)
    if critical_rules.intersection(
        {
            "volunteer_mark_exceeded",
            "volunteer_homes_affected",
            "volunteer_road_cut",
            "volunteer_bridge_compromised",
        }
    ):
        fused_score = max(fused_score, 0.72)

    return min(1.0, fused_score), strongest.source, rules_fired


def _event_trace(events: list[EvidenceEvent], window_minutes: int, now: datetime, rules_fired: list[str]) -> dict[str, Any]:
    return {
        "schema": "decision-trace-v2",
        "generated_at": now.isoformat(),
        "window": {
            "minutes": window_minutes,
            "started_at": (now - timedelta(minutes=window_minutes)).isoformat(),
            "ended_at": now.isoformat(),
        },
        "severity_contract": LEVEL_MEANINGS,
        "rules_fired": rules_fired,
        "evidence": [
            {
                "source": event.source,
                "entity_id": event.entity_id,
                "observed_at": event.observed_at.isoformat(),
                "raw_score": round(event.raw_score, 4),
                "weight": round(event.weight, 4),
                "weighted_score": round(event.weighted_score, 4),
                "summary": event.summary,
                "rules": event.rules,
                "payload": event.payload,
            }
            for event in events
        ],
    }


def _get_active_incident(session: Session, site_id: str) -> Incident | None:
    return session.exec(
        select(Incident)
        .where(Incident.site_id == site_id)
        .where(Incident.closed_at.is_(None))
        .order_by(Incident.updated_at.desc())
    ).first()


def _upsert_incident(
    session: Session,
    site_id: str,
    level: str,
    summary: str,
    window_minutes: int,
    events: list[EvidenceEvent],
    now: datetime,
) -> Incident | None:
    active = _get_active_incident(session, site_id)
    has_critical_human = any(event.source == "volunteer" and any(rule.startswith("volunteer_") for rule in event.rules) for event in events)
    should_open = level in {"yellow", "orange", "red"} or has_critical_human

    if active is None and not should_open:
        return None

    if active is None:
        active = Incident(
            site_id=site_id,
            current_level=level,
            lifecycle_state="active" if level == "yellow" else "escalated",
            opened_at=now,
            updated_at=now,
            evidence_window_minutes=window_minutes,
            summary=summary,
        )
        session.add(active)
        session.flush()
        return active

    active.current_level = level
    active.updated_at = now
    active.evidence_window_minutes = window_minutes
    active.summary = summary
    if level in {"orange", "red"}:
        active.lifecycle_state = "escalated"
    elif level == "yellow":
        active.lifecycle_state = "active"
    elif events:
        active.lifecycle_state = "stabilizing"
    else:
        active.lifecycle_state = "closed"
        active.closed_at = now
        active.close_reason = "automatic_no_recent_risk_evidence"
    session.add(active)
    session.flush()
    return active


def _recommended_actuators(level: str) -> list[str]:
    if level == "red":
        return ["trigger_alarm", "send_radio_payload", "notify_app"]
    if level == "orange":
        return ["send_radio_payload", "notify_app"]
    return []


def _record_actuators(
    session: Session,
    alert: FusedAlert,
    incident: Incident | None,
    llm: DecisionRuntime | None,
) -> list[str]:
    if alert.level not in {"orange", "red"}:
        return []

    target_key = incident.id if incident and incident.id is not None else alert.id
    already_success = session.exec(
        select(ActuationRecord)
        .where(ActuationRecord.site_id == alert.site_id)
        .where(ActuationRecord.incident_id == target_key if incident else ActuationRecord.alert_id == target_key)
        .where(ActuationRecord.status == "success")
    ).all()
    completed = {record.actuator_type for record in already_success}

    requested = _recommended_actuators(alert.level)
    pending = [name for name in requested if name not in completed]
    if not pending:
        return []

    dispatched = (
        dispatch_actuators(alert, llm, allowed_tools=set(pending))
        if llm is not None
        else []
    )
    dispatched_pending = {name for name in dispatched if name in pending}
    fallback_pending = [name for name in pending if name not in dispatched_pending]

    records: list[str] = []
    for name in pending:
        payload = {
            "level": alert.level,
            "score": alert.score,
            "summary": alert.summary,
            "recommended": name in requested,
        }
        record = ActuationRecord(
            alert_id=alert.id,
            incident_id=incident.id if incident else None,
            site_id=alert.site_id,
            actuator_type=name,
            payload=json.dumps(payload, ensure_ascii=True),
            status="success",
            error=None,
        )
        if name in fallback_pending:
            actuator = ACTUATOR_REGISTRY.get(name)
            if actuator is not None:
                try:
                    actuator.fire(payload)
                except Exception as exc:  # pragma: no cover - defensive
                    record.status = "failed"
                    record.error = str(exc)
        session.add(record)
        records.append(f"{name}:{record.status}")
    return records


def recompute_site_alert(
    session: Session,
    site_id: str,
    llm: DecisionRuntime | None = None,
    *,
    window_minutes: int = DEFAULT_EVIDENCE_WINDOW_MINUTES,
    now: datetime | None = None,
    use_historical_context: bool = False,
) -> FusedAlert:
    now = now or datetime.utcnow()
    events = _collect_evidence(session, site_id, now, window_minutes)
    weighted_score, trigger_source, rules_fired = _score_events(events)
    level = level_from_score(weighted_score)
    local_alarm_triggered = level in {"orange", "red"}
    latest_by_source: dict[str, EvidenceEvent] = {}
    for event in events:
        latest_by_source.setdefault(event.source, event)

    summary_parts = [event.summary for event in latest_by_source.values() if event.summary]
    summary = " | ".join(summary_parts[:3]) or "No recent signals available"

    representative = {source: event.payload for source, event in latest_by_source.items()}
    latest_level = None
    if "node" in latest_by_source:
        latest_level = float(latest_by_source["node"].payload.get("waterline_ratio") or 0.0)

    historical_hits = (
        retrieve_historical_context(site_id, current_level=latest_level)
        if use_historical_context
        else []
    )
    historical_context = render_historical_context(historical_hits) if historical_hits else None
    reasoning = generate_alert_reasoning(
        level=level,
        fused_score=weighted_score,
        node_obs=representative.get("node"),
        volunteer_parsed=representative.get("volunteer"),
        hydromet=representative.get("hydromet"),
        rules_fired=rules_fired,
        llm=llm if level != "green" else None,
        historical_context=historical_context,
        historical_hits=historical_hits,
    )

    incident = _upsert_incident(session, site_id, level, summary, window_minutes, events, now)
    trace = _event_trace(events, window_minutes, now, rules_fired)
    node_measurements = [
        Measurement(
            observed_at=event.observed_at,
            water_level=float(event.payload.get("waterline_ratio") or 0.0),
        )
        for event in reversed(events)
        if event.source == "node"
    ]
    if node_measurements:
        trace["forecast"] = forecast_short_term(node_measurements, horizon_minutes=60).__dict__
    if historical_hits:
        trace["historical_context"] = {
            "enabled": True,
            "mode": "edge-rag-sqlite",
            "hits": [hit.__dict__ for hit in historical_hits],
        }
    if incident is not None:
        trace["incident"] = {
            "id": incident.id,
            "state": incident.lifecycle_state,
            "current_level": incident.current_level,
            "opened_at": incident.opened_at.isoformat() if incident.opened_at else None,
            "updated_at": incident.updated_at.isoformat() if incident.updated_at else None,
            "closed_at": incident.closed_at.isoformat() if incident.closed_at else None,
        }

    alert = FusedAlert(
        site_id=site_id,
        incident_id=incident.id if incident else None,
        level=level,
        score=round(weighted_score, 4),
        trigger_source=trigger_source,
        summary=summary,
        decision_trace=json.dumps(trace, ensure_ascii=True),
        local_alarm_triggered=local_alarm_triggered,
        reasoning_summary=reasoning.llm_summary,
        reasoning_chain=serialize_chain(reasoning.llm_chain_of_thought),
        reasoning_model=reasoning.model_name,
    )
    session.add(alert)
    session.flush()

    actuation_results = _record_actuators(session, alert, incident, llm)
    if actuation_results:
        trace["actuation"] = actuation_results
        alert.decision_trace = json.dumps(trace, ensure_ascii=True)
        session.add(alert)
    return alert
