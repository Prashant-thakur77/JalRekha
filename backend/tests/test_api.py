from __future__ import annotations

import json
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

import anyio
import httpx
import pytest
from fastapi import BackgroundTasks, UploadFile
from PIL import Image, ImageDraw
from sqlmodel import Session, SQLModel, select

from jalrekha.api import deps
from jalrekha.api.routers.node import analyze_node
from jalrekha.api.routers.sync import flush_sync
from jalrekha.api.routers.volunteer import create_report
from jalrekha.core import settings as settings_module
from jalrekha.db.database import central_engine, edge_engine, init_db
from jalrekha.main import app
from jalrekha.models.domain import NodeAssessmentArtifact, FusedAlert, NodeObservation, Site, SiteCalibration, SyncQueueItem, VolunteerReport
from jalrekha.models.domain import HydrometSnapshot
from jalrekha.services.storage import get_upload_dir

init_db()


async def api_request(method: str, url: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, url, **kwargs)



def request(method: str, url: str, **kwargs) -> httpx.Response:
    async def _call() -> httpx.Response:
        return await api_request(method, url, **kwargs)

    return anyio.run(_call)


@pytest.fixture(autouse=True)
def reset_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JALREKHA_UPLOAD_DIR", str(tmp_path / "uploads"))
    settings_module.get_settings.cache_clear()
    deps.is_online = True
    monkeypatch.setattr(deps.llm_client, "structure_observation", lambda *_args, **_kwargs: None)

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
                name="Puente Test",
                region="Zona Demo",
                lat=-32.95,
                lng=-60.64,
                description="Sitio usado para pruebas",
                is_active=True,
            )
        )
        session.commit()

    yield

    for file_path in upload_dir.iterdir():
        if file_path.is_file():
            file_path.unlink()



def _build_test_image(path: Path) -> None:
    image = Image.new("RGB", (320, 240), (200, 210, 220))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 132, 319, 239), fill=(90, 70, 40))
    draw.line((0, 95, 319, 95), fill=(245, 245, 245), width=2)
    image.save(path, format="JPEG")



def test_health():
    response = request("GET", "/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"



def test_connectivity():
    response = request("POST", "/api/settings/connectivity", json={"is_online": False})
    assert response.status_code == 200
    assert response.json() == {"is_online": False}

    response = request("POST", "/api/settings/connectivity", json={"is_online": True})
    assert response.status_code == 200
    assert response.json() == {"is_online": True}



def test_report_and_sync():
    async def run_flow():
        with Session(edge_engine) as edge_session:
            payload = await create_report(
                background_tasks=BackgroundTasks(),
                site_id="test-site",
                reporter_name="Test User",
                reporter_role="Tester",
                transcript_text="El agua paso la marca critica y la calle esta cortada",
                offline_created=True,
                photo=None,
                audio=None,
                session=edge_session,
            )
            report_id = payload["report"].id
            assert payload["parsed"].parser_source == "rules"
            assert payload["alert"].level in {"orange", "red"}

        with Session(edge_engine) as edge_session, Session(central_engine) as central_session:
            sync_payload = await flush_sync(edge_session=edge_session, central_session=central_session)
            return report_id, sync_payload

    report_id, sync_payload = anyio.run(run_flow)
    assert sync_payload["queued"] >= 3
    assert sync_payload["flushed"] == sync_payload["queued"]
    assert sync_payload["failed"] == 0

    with Session(edge_engine) as session:
        queue_items = session.exec(select(SyncQueueItem)).all()
        assert len(queue_items) == sync_payload["queued"]
        assert all(item.status == "synced" for item in queue_items)

        edge_report = session.get(VolunteerReport, report_id)
        assert edge_report is not None
        assert edge_report.sync_status == "synced"

    with Session(central_engine) as session:
        central_report = session.get(VolunteerReport, report_id)
        assert central_report is not None
        assert central_report.sync_status == "synced"
        central_alert = session.exec(select(FusedAlert)).first()
        assert central_alert is not None
        assert central_alert.sync_status == "synced"



def test_report_uploads_are_persisted():
    async def run_flow():
        photo = UploadFile(filename="river.jpg", file=BytesIO(b"fake-image-bytes"))
        audio = UploadFile(filename="note.wav", file=BytesIO(b"fake-audio-bytes"))
        with Session(edge_engine) as edge_session:
            return await create_report(
                background_tasks=BackgroundTasks(),
                site_id="test-site",
                reporter_name="Upload User",
                reporter_role="Tester",
                transcript_text="Foto y audio cargados",
                offline_created=False,
                photo=photo,
                audio=audio,
                session=edge_session,
            )

    payload = anyio.run(run_flow)["report"]
    photo_path = Path(payload.photo_path)
    audio_path = Path(payload.audio_path)
    assert photo_path.exists()
    assert audio_path.exists()
    assert photo_path.parent == get_upload_dir()
    assert audio_path.parent == get_upload_dir()



def test_node_analysis_with_image_media(tmp_path: Path):
    video_path = tmp_path / "synthetic.jpg"
    _build_test_image(video_path)

    async def run_flow():
        with video_path.open("rb") as handle:
            upload = UploadFile(filename=video_path.name, file=handle)
            with Session(edge_engine) as edge_session:
                return await analyze_node(site_id="test-site", video=upload, session=edge_session)

    payload = anyio.run(run_flow)
    assert payload["observation"]["frames_analyzed"] == 1
    assert payload["observation"]["evidence_frame_url"].startswith("/uploads/")
    assert payload["observation"]["assessment_mode"] == "gemma4-multimodal-v1"
    assert payload["observation"]["artifact_id"] is not None
    assert payload["observation"]["runner"]["mode"] in {
        "litert-multimodal-temporal",
        "ollama-multimodal-temporal",
        "multimodal-unavailable-fallback",
    }
    assert payload["observation"]["temporal_summary"]
    assert isinstance(payload["observation"]["reasoning_steps"], list)
    assert isinstance(payload["observation"]["artifact_refs"], dict)
    assert payload["alert"].level in {"yellow", "orange", "red"}

    with Session(edge_engine) as session:
        observation = session.exec(select(NodeObservation)).first()
        assert observation is not None
        assert observation.video_path is not None
        assert observation.sync_status == "pending"
        assert observation.assessment_artifact_id is not None
        artifact = session.get(NodeAssessmentArtifact, observation.assessment_artifact_id)
        assert artifact is not None
        assert artifact.frames_analyzed == 1
        assert artifact.bundle_json
        assert artifact.verdict_json


def test_sample_node_analysis_endpoint(tmp_path: Path):
    video_path = tmp_path / "sample.jpg"
    _build_test_image(video_path)

    with Session(edge_engine) as session:
        session.add(
            Site(
                id="sample-site",
                name="Site with bundled clip",
                region="Zona Demo",
                lat=-32.96,
                lng=-60.65,
                description="Sitio con sample video",
                sample_video_path=str(video_path),
                sample_video_source_url="https://example.com/fixed-cam",
                sample_frame_path=None,
                is_active=True,
            )
        )
        session.add(
            SiteCalibration(
                site_id="sample-site",
                roi_polygon=json.dumps([[0, 40], [320, 40], [320, 220], [0, 220]], ensure_ascii=True),
                critical_line=json.dumps([[0, 95], [320, 95]], ensure_ascii=True),
                reference_line=json.dumps([[0, 155], [320, 155]], ensure_ascii=True),
                notes="synthetic calibration",
            )
        )
        session.commit()

    response = request("POST", "/api/sites/sample-site/sample-node-analysis")
    assert response.status_code == 200
    payload = response.json()
    assert payload["observation"]["frames_analyzed"] == 1
    assert payload["observation"]["evidence_frame_url"].startswith("/uploads/")
    assert payload["observation"]["artifact_id"] is not None
    assert payload["observation"]["assessment_mode"] == "gemma4-multimodal-v1"
    assert payload["sample_video_source_url"] == "https://example.com/fixed-cam"


def test_external_snapshot_refresh_serializes_response(monkeypatch: pytest.MonkeyPatch):
    snapshot = HydrometSnapshot(
        site_id="test-site",
        signal_score=0.42,
        summary="rain now 2.0 mm, 12h precip prob 60%",
        precipitation_mm=2.0,
        precipitation_probability=60.0,
        river_discharge=12.0,
        river_discharge_max=18.0,
        river_discharge_trend=1.5,
    )

    monkeypatch.setattr(deps.external_data_service, "fetch_snapshot", lambda _site: snapshot)

    response = request("POST", "/api/sites/test-site/external-snapshot/refresh")
    assert response.status_code == 200
    payload = response.json()
    assert payload["site_id"] == "test-site"
    assert payload["signal_score"] == 0.42
    assert payload["summary"] == "rain now 2.0 mm, 12h precip prob 60%"


def test_site_experimental_context_and_forecast_endpoints():
    response = request("PUT", "/api/sites/test-site/experimental-settings", json={
        "historical_context_enabled": True,
        "forecast_enabled": True,
        "forecast_critical_threshold": 0.7,
    })
    assert response.status_code == 200
    assert response.json()["historical_context_enabled"] is True

    response = request("POST", "/api/sites/test-site/historical-context", json={
        "source": "manual",
        "title": "Bridge access road",
        "summary": "At 0.69 the bridge access road floods before the main crossing.",
        "threshold_level": 0.69,
        "jurisdiction": "municipal",
        "source_uri": "manual://bridge-access",
    })
    assert response.status_code == 200
    stored = response.json()["stored"]
    assert stored["source_uri"] == "manual://bridge-access"

    response = request("GET", "/api/sites/test-site/historical-context?water_level=0.68&query=bridge")
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["hits"]
    assert payload["hits"][0]["id"] == stored["id"]

    now = datetime.utcnow()
    with Session(edge_engine) as session:
        session.add(
            NodeObservation(
                site_id="test-site",
                source_type="test",
                started_at=now - timedelta(minutes=30),
                ended_at=now - timedelta(minutes=30),
                frames_analyzed=1,
                waterline_ratio=0.45,
                rise_velocity=0.0,
                crossed_critical_line=False,
                confidence=0.8,
                decision_trace="{}",
                severity_score=0.2,
            )
        )
        session.add(
            NodeObservation(
                site_id="test-site",
                source_type="test",
                started_at=now,
                ended_at=now,
                frames_analyzed=1,
                waterline_ratio=0.62,
                rise_velocity=0.0,
                crossed_critical_line=False,
                confidence=0.8,
                decision_trace="{}",
                severity_score=0.4,
            )
        )
        session.commit()

    response = request("GET", "/api/sites/test-site/forecast")
    assert response.status_code == 200
    forecast = response.json()["forecast"]
    assert forecast["critical_threshold"] == 0.7
    assert forecast["status"] in {"ok", "degraded"}
    assert forecast["projected_points"]
