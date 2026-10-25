from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, select

from jalrekha.adapters.litert_node import LiteRTNodeRuntime
from jalrekha.api.deps import enqueue_entity
from jalrekha.api.routers.sync import flush_sync
from jalrekha.core import settings as settings_module
from jalrekha.db.database import central_engine, edge_engine, init_db
from jalrekha.models.domain import (
    ActuationRecord,
    FusedAlert,
    HydrometSnapshot,
    Incident,
    NodeObservation,
    ParsedObservation,
    Site,
    SyncQueueItem,
    VolunteerReport,
)
from jalrekha.services.actuators import RECORDED_CALLS, reset_recorded_calls
from jalrekha.services.decision_engine import level_from_score, recompute_site_alert, temporal_weight


init_db()


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JALREKHA_ACTUATORS_ENABLED", "true")
    settings_module.get_settings.cache_clear()
    for engine in (edge_engine, central_engine):
        with Session(engine) as session:
            for table in reversed(SQLModel.metadata.sorted_tables):
                session.exec(table.delete())
            session.commit()
    with Session(edge_engine) as session:
        session.add(Site(id="site-a", name="Puente A", region="Demo", lat=-32.95, lng=-60.64))
        session.commit()
    reset_recorded_calls()
    yield
    for engine in (edge_engine, central_engine):
        with Session(engine) as session:
            for table in reversed(SQLModel.metadata.sorted_tables):
                session.exec(table.delete())
            session.commit()
    with Session(edge_engine) as session:
        session.add(Site(id="test-site", name="Puente Test", region="Zona Demo", lat=-32.95, lng=-60.64))
        session.commit()
    reset_recorded_calls()
    settings_module.get_settings.cache_clear()


def _node(site_id: str, observed_at: datetime, score: float, crossed: bool = False) -> NodeObservation:
    return NodeObservation(
        site_id=site_id,
        source_type="test",
        started_at=observed_at - timedelta(minutes=2),
        ended_at=observed_at,
        frames_analyzed=4,
        waterline_ratio=0.8 if crossed else 0.4,
        rise_velocity=0.12 if crossed else 0.02,
        crossed_critical_line=crossed,
        confidence=0.8,
        decision_trace="[]",
        severity_score=score,
        assessment_score=score,
        assessment_level=level_from_score(score),
        temporal_summary="nivel observado por nodo fijo",
    )


def _report_pair(site_id: str, observed_at: datetime, score: float, text: str = "reporte medio") -> tuple[VolunteerReport, ParsedObservation]:
    report = VolunteerReport(
        site_id=site_id,
        created_at=observed_at,
        reporter_name="v",
        reporter_role="brigadista",
        transcript_text=text,
        offline_created=True,
    )
    parsed = ParsedObservation(
        volunteer_report_id=0,
        water_level_category="medium",
        trend="rising",
        road_status="open",
        bridge_status="stable",
        homes_affected=False,
        urgency="medium",
        confidence=0.8,
        structured_json="{}",
        decision_trace="[]",
        severity_score=score,
        summary=text,
    )
    return report, parsed


def test_level_from_score_thresholds():
    assert level_from_score(0.39) == "green"
    assert level_from_score(0.40) == "yellow"
    assert level_from_score(0.62) == "orange"
    assert level_from_score(0.82) == "red"


def test_temporal_weight_keeps_fresh_evidence_at_full_strength():
    now = datetime(2026, 5, 14, 12, 0, 0)
    observed_at = now - timedelta(milliseconds=250)

    assert temporal_weight(observed_at, now, 45) == 1.0


def test_temporal_fusion_escalates_two_medium_sources():
    now = datetime(2026, 5, 14, 12, 0, 0)
    with Session(edge_engine) as session:
        session.add(_node("site-a", now - timedelta(minutes=5), 0.5))
        report, parsed = _report_pair("site-a", now - timedelta(minutes=4), 0.5)
        session.add(report)
        session.flush()
        parsed.volunteer_report_id = report.id or 0
        session.add(parsed)
        alert = recompute_site_alert(session, "site-a", None, now=now)
        level = alert.level
        decision_trace = alert.decision_trace
        session.commit()

    trace = json.loads(decision_trace)
    assert level == "orange"
    assert "two_medium_sources_escalate_to_orange" in trace["rules_fired"]
    assert len(trace["evidence"]) == 2


def test_old_signal_does_not_keep_alert_high():
    now = datetime(2026, 5, 14, 12, 0, 0)
    with Session(edge_engine) as session:
        session.add(_node("site-a", now - timedelta(hours=2), 0.95, crossed=True))
        alert = recompute_site_alert(session, "site-a", None, now=now, window_minutes=45)
        level = alert.level
        decision_trace = alert.decision_trace
        session.commit()

    assert level == "green"
    assert json.loads(decision_trace)["evidence"] == []


def test_incident_reused_and_actuators_idempotent():
    now = datetime(2026, 5, 14, 12, 0, 0)
    with Session(edge_engine) as session:
        session.add(_node("site-a", now - timedelta(minutes=2), 0.9, crossed=True))
        first = recompute_site_alert(session, "site-a", None, now=now)
        first_incident = first.incident_id
        second = recompute_site_alert(session, "site-a", None, now=now + timedelta(minutes=1))
        first_level = first.level
        second_incident = second.incident_id
        records = session.exec(select(ActuationRecord)).all()
        record_statuses = [record.status for record in records]
        incidents = session.exec(select(Incident)).all()
        incident_count = len(incidents)
        session.commit()

    assert first_level == "red"
    assert second_incident == first_incident
    assert incident_count == 1
    assert len([status for status in record_statuses if status == "success"]) == 3
    assert [name for name, _payload in RECORDED_CALLS] == ["trigger_alarm", "send_radio_payload", "notify_app"]


def test_malformed_litert_actuator_selection_uses_deterministic_fallback():
    class MalformedLiteRTRuntime(LiteRTNodeRuntime):
        def __init__(self):
            self.json_calls = 0

        @property
        def model_name(self) -> str:
            return "fake-litert"

        def generate_text(self, *_args, **_kwargs):
            return "Resumen: alerta roja por nodo. Cadena: nodo -> regla -> actuar"

        def generate_json(self, *_args, **_kwargs):
            self.json_calls += 1
            return None

    now = datetime(2026, 5, 14, 12, 0, 0)
    runtime = MalformedLiteRTRuntime()
    with Session(edge_engine) as session:
        session.add(_node("site-a", now - timedelta(minutes=2), 0.9, crossed=True))
        alert = recompute_site_alert(session, "site-a", runtime, now=now)
        level = alert.level
        records = session.exec(select(ActuationRecord)).all()
        record_types = [record.actuator_type for record in records]
        record_statuses = {record.status for record in records}
        session.commit()

    assert level == "red"
    assert runtime.json_calls == 1
    assert record_types == [
        "trigger_alarm",
        "send_radio_payload",
        "notify_app",
    ]
    assert record_statuses == {"success"}
    assert [name for name, _payload in RECORDED_CALLS] == [
        "trigger_alarm",
        "send_radio_payload",
        "notify_app",
    ]


def test_partial_litert_actuator_selection_completes_recommended_fallback():
    class PartialLiteRTRuntime(LiteRTNodeRuntime):
        @property
        def model_name(self) -> str:
            return "fake-litert"

        def generate_text(self, *_args, **_kwargs):
            return "Resumen: alerta roja por nodo. Cadena: nodo -> regla -> actuar"

        def generate_json(self, *_args, **_kwargs):
            return {"tool_calls": [{"name": "notify_app", "arguments": {"text": "alerta roja"}}]}

    now = datetime(2026, 5, 14, 12, 0, 0)
    with Session(edge_engine) as session:
        session.add(_node("site-a", now - timedelta(minutes=2), 0.9, crossed=True))
        alert = recompute_site_alert(session, "site-a", PartialLiteRTRuntime(), now=now)
        level = alert.level
        records = session.exec(select(ActuationRecord)).all()
        record_types = [record.actuator_type for record in records]
        record_statuses = [record.status for record in records]
        session.commit()

    fired_names = [name for name, _payload in RECORDED_CALLS]
    assert level == "red"
    assert record_types == ["trigger_alarm", "send_radio_payload", "notify_app"]
    assert record_statuses == ["success", "success", "success"]
    assert set(fired_names) == {"trigger_alarm", "send_radio_payload", "notify_app"}
    assert fired_names.count("notify_app") == 1


def test_orange_litert_selection_is_constrained_to_recommended_pending_actuators():
    class OverreachingLiteRTRuntime(LiteRTNodeRuntime):
        @property
        def model_name(self) -> str:
            return "fake-litert"

        def generate_text(self, *_args, **_kwargs):
            return "Resumen: alerta naranja por dos fuentes. Cadena: corroborar -> preparar"

        def generate_json(self, *_args, **_kwargs):
            return {
                "tool_calls": [
                    {"name": "trigger_alarm", "arguments": {"reason": "modelo pidio sirena"}},
                    {"name": "notify_app", "arguments": {"text": "alerta naranja"}},
                ]
            }

    now = datetime(2026, 5, 14, 12, 0, 0)
    with Session(edge_engine) as session:
        session.add(_node("site-a", now - timedelta(minutes=2), 0.72, crossed=False))
        alert = recompute_site_alert(session, "site-a", OverreachingLiteRTRuntime(), now=now)
        level = alert.level
        records = session.exec(select(ActuationRecord)).all()
        record_types = [record.actuator_type for record in records]
        record_statuses = [record.status for record in records]
        session.commit()

    fired_names = [name for name, _payload in RECORDED_CALLS]
    assert level == "orange"
    assert record_types == ["send_radio_payload", "notify_app"]
    assert record_statuses == ["success", "success"]
    assert fired_names == ["notify_app", "send_radio_payload"]


@pytest.mark.anyio
async def test_central_integration_flow_and_idempotent_sync():
    now = datetime(2026, 5, 14, 12, 0, 0)
    with Session(edge_engine) as session:
        report, parsed = _report_pair(
            "site-a",
            now - timedelta(minutes=8),
            0.72,
            "agua supero la marca y hay viviendas afectadas",
        )
        parsed.water_level_category = "critical"
        parsed.homes_affected = True
        parsed.urgency = "critical"
        session.add(report)
        session.flush()
        parsed.volunteer_report_id = report.id or 0
        session.add(parsed)
        session.add(_node("site-a", now - timedelta(minutes=4), 0.88, crossed=True))
        session.add(
            HydrometSnapshot(
                site_id="site-a",
                created_at=now - timedelta(minutes=3),
                precipitation_mm=35.0,
                precipitation_probability=85.0,
                river_discharge=50.0,
                river_discharge_trend=2.0,
                signal_score=0.58,
                summary="lluvia intensa y rio en ascenso",
            )
        )
        session.flush()
        enqueue_entity(session, "volunteer_report", report)
        enqueue_entity(session, "parsed_observation", parsed)
        for node in session.exec(select(NodeObservation)).all():
            enqueue_entity(session, "node_observation", node)
        for snapshot in session.exec(select(HydrometSnapshot)).all():
            enqueue_entity(session, "hydromet_snapshot", snapshot)

        alert = recompute_site_alert(session, "site-a", None, now=now)
        enqueue_entity(session, "fused_alert", alert)
        if alert.incident_id:
            incident = session.get(Incident, alert.incident_id)
            assert incident is not None
            enqueue_entity(session, "incident", incident)
        for record in session.exec(select(ActuationRecord)).all():
            enqueue_entity(session, "actuation_record", record)
        session.commit()

    with Session(edge_engine) as edge_session, Session(central_engine) as central_session:
        first = await flush_sync(edge_session=edge_session, central_session=central_session)
        second = await flush_sync(edge_session=edge_session, central_session=central_session)

    assert first["failed"] == 0
    assert first["flushed"] >= 7
    assert second == {"queued": 0, "flushed": 0, "failed": 0}
    with Session(central_engine) as session:
        assert session.exec(select(FusedAlert)).first().level == "red"
        assert len(session.exec(select(FusedAlert)).all()) == 1
        assert len(session.exec(select(SyncQueueItem)).all()) == 0
        assert session.exec(select(Incident)).first().lifecycle_state == "escalated"
        assert len(session.exec(select(ActuationRecord)).all()) == 3
