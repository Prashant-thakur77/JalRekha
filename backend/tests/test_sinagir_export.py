from __future__ import annotations

import anyio
from fastapi import BackgroundTasks
from sqlmodel import Session

from jalrekha.api.routers.alerts import export_alert_sinagir
from jalrekha.api.routers.volunteer import create_report
from jalrekha.db.database import edge_engine


REQUIRED_EVENT_KEYS = {
    "external_id",
    "observed_at",
    "site",
    "hazard_type",
    "severity",
    "trigger_source",
    "summary",
    "explanation",
    "reasoning",
    "local_actuation",
    "origin_system",
}


def test_sinagir_export_shape():
    async def run():
        with Session(edge_engine) as s:
            payload = await create_report(
                background_tasks=BackgroundTasks(),
                site_id="test-site",
                reporter_name="t",
                reporter_role="t",
                transcript_text="paso la marca critica y cortamos la ruta",
                offline_created=False,
                photo=None,
                audio=None,
                session=s,
            )
            alert_id = payload["alert"].id
        with Session(edge_engine) as s:
            return await export_alert_sinagir(alert_id=alert_id, session=s)

    out = anyio.run(run)
    assert out["schema"] == "sinagir-ready-v1"
    assert "disclaimer" in out
    event = out["event"]
    assert REQUIRED_EVENT_KEYS.issubset(event.keys())
    assert event["hazard_type"] == "inundacion"
    assert event["severity"]["level"] in {"green", "yellow", "orange", "red"}
    assert isinstance(event["explanation"], list)
    assert isinstance(event["reasoning"], dict)
    assert "chain" in event["reasoning"]
