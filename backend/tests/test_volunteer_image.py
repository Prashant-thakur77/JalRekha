from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest
from fastapi import BackgroundTasks, UploadFile
from sqlmodel import Session, SQLModel

from jalrekha.adapters.image_assessment import ImageAssessmentResult
from jalrekha.api import deps
from jalrekha.api.routers import volunteer as volunteer_router
from jalrekha.api.routers.volunteer import _enrich_with_image_assessment, create_report
from jalrekha.core import settings as settings_module
from jalrekha.db.database import central_engine, edge_engine, init_db
from jalrekha.models.domain import ParsedObservation, Site
from jalrekha.services.storage import get_upload_dir


init_db()


@pytest.fixture(autouse=True)
def _reset_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JALREKHA_UPLOAD_DIR", str(tmp_path / "uploads"))
    settings_module.get_settings.cache_clear()
    deps.is_online = True
    monkeypatch.setattr(deps.llm_client, "structure_observation", lambda *_a, **_k: None)
    for engine in (edge_engine, central_engine):
        with Session(engine) as session:
            for table in reversed(SQLModel.metadata.sorted_tables):
                session.exec(table.delete())
            session.commit()
    upload_dir = get_upload_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)
    for file_path in upload_dir.iterdir():
        if file_path.is_file():
            file_path.unlink()
    with Session(edge_engine) as session:
        session.add(
            Site(
                id="test-site",
                name="Test Site",
                region="Demo",
                lat=-32.95,
                lng=-60.64,
                description="for tests",
                is_active=True,
            )
        )
        session.commit()
    yield


def _make_assessment() -> ImageAssessmentResult:
    return ImageAssessmentResult(
        description_es="Se ve agua marrón cubriendo la calle y el cordón de un puente.",
        water_visible=True,
        infrastructure_at_risk=True,
        confidence=0.82,
        raw_model_output="{}",
        model_name="gemma4:e2b",
    )


def _stub_image_assessor(*, enabled: bool, assess_result):
    return SimpleNamespace(
        settings=SimpleNamespace(volunteer_image_enabled=enabled),
        assess=lambda _path: assess_result,
    )


def test_enrich_with_image_assessment_appends_to_decision_trace(
    monkeypatch: pytest.MonkeyPatch,
):
    with Session(edge_engine) as session:
        parsed = ParsedObservation(
            volunteer_report_id=999,
            water_level_category="critical",
            trend="rising",
            road_status="blocked",
            bridge_status="unknown",
            homes_affected=False,
            urgency="critical",
            confidence=0.7,
            structured_json="{}",
            decision_trace=json.dumps(["seed entry"]),
            parser_source="rules",
            severity_score=0.9,
            summary="seed",
        )
        session.add(parsed)
        session.commit()
        session.refresh(parsed)
        parsed_id = parsed.id

    monkeypatch.setattr(
        volunteer_router,
        "image_assessor",
        _stub_image_assessor(enabled=True, assess_result=_make_assessment()),
    )

    _enrich_with_image_assessment(parsed_id, "/tmp/fake-photo.jpg")

    with Session(edge_engine) as session:
        refreshed = session.get(ParsedObservation, parsed_id)
        assert refreshed is not None
        trace = json.loads(refreshed.decision_trace)
        assert any("image_description" in entry for entry in trace)
        assert any("image_flags" in entry and "water_visible=True" in entry for entry in trace)


def test_enrich_skipped_when_image_assessor_returns_none(monkeypatch: pytest.MonkeyPatch):
    with Session(edge_engine) as session:
        parsed = ParsedObservation(
            volunteer_report_id=998,
            water_level_category="medium",
            trend="stable",
            road_status="open",
            bridge_status="open",
            homes_affected=False,
            urgency="normal",
            confidence=0.6,
            structured_json="{}",
            decision_trace=json.dumps(["unchanged"]),
            parser_source="rules",
            severity_score=0.4,
            summary="seed",
        )
        session.add(parsed)
        session.commit()
        session.refresh(parsed)
        parsed_id = parsed.id

    monkeypatch.setattr(
        volunteer_router,
        "image_assessor",
        _stub_image_assessor(enabled=True, assess_result=None),
    )

    _enrich_with_image_assessment(parsed_id, "/tmp/fake-photo.jpg")

    with Session(edge_engine) as session:
        refreshed = session.get(ParsedObservation, parsed_id)
        assert refreshed is not None
        trace = json.loads(refreshed.decision_trace)
        assert trace == ["unchanged"]


def test_create_report_schedules_image_task_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        volunteer_router,
        "image_assessor",
        _stub_image_assessor(enabled=True, assess_result=_make_assessment()),
    )

    async def run_flow():
        photo = UploadFile(filename="puente.jpg", file=BytesIO(b"fake-jpg-bytes"))
        bg = BackgroundTasks()
        with Session(edge_engine) as session:
            payload = await create_report(
                background_tasks=bg,
                site_id="test-site",
                reporter_name="V",
                reporter_role="brigadista",
                transcript_text="reporte rapido",
                offline_created=False,
                photo=photo,
                audio=None,
                session=session,
            )
            return payload, bg

    payload, bg = anyio.run(run_flow)
    assert payload["report"].photo_path is not None
    enrich_tasks = [t for t in bg.tasks if t.func is _enrich_with_image_assessment]
    assert len(enrich_tasks) == 1


def test_create_report_skips_image_task_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        volunteer_router,
        "image_assessor",
        _stub_image_assessor(enabled=False, assess_result=_make_assessment()),
    )

    async def run_flow():
        photo = UploadFile(filename="puente.jpg", file=BytesIO(b"fake-jpg-bytes"))
        bg = BackgroundTasks()
        with Session(edge_engine) as session:
            await create_report(
                background_tasks=bg,
                site_id="test-site",
                reporter_name="V",
                reporter_role="brigadista",
                transcript_text="reporte rapido",
                offline_created=False,
                photo=photo,
                audio=None,
                session=session,
            )
            return bg

    bg = anyio.run(run_flow)
    assert bg.tasks == []
