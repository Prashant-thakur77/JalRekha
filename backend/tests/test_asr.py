from __future__ import annotations

from io import BytesIO
from pathlib import Path

import anyio
import pytest
from fastapi import BackgroundTasks, UploadFile
from sqlmodel import Session, SQLModel

from jalrekha.api import deps
from jalrekha.api.routers.volunteer import create_report
from jalrekha.core import settings as settings_module
from jalrekha.db.database import central_engine, edge_engine, init_db
from jalrekha.models.domain import Site
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


def test_asr_missing_file_returns_none():
    """The real adapter must not raise on a bad path; it logs and returns None
    so the caller can keep going with whatever transcript_text was supplied."""
    assert deps.asr_client.transcribe("/definitely-not-a-real-path.wav") is None


def test_create_report_uses_asr_when_transcript_empty(monkeypatch: pytest.MonkeyPatch):
    """When the volunteer uploads audio with no typed transcript, the ASR
    adapter is invoked and its result becomes the effective transcript."""

    monkeypatch.setattr(
        deps.asr_client,
        "transcribe",
        lambda _path: "el agua paso la marca y tapo la calle",
    )

    async def run_flow():
        audio = UploadFile(filename="note.wav", file=BytesIO(b"fake-audio-bytes"))
        with Session(edge_engine) as edge_session:
            return await create_report(
                background_tasks=BackgroundTasks(),
                site_id="test-site",
                reporter_name="Volunteer",
                reporter_role="brigadista",
                transcript_text="",
                offline_created=False,
                photo=None,
                audio=audio,
                session=edge_session,
            )

    payload = anyio.run(run_flow)
    report = payload["report"]
    parsed = payload["parsed"]
    assert "marca" in (report.transcript_text or "").lower()
    assert parsed.water_level_category == "critical"
    assert parsed.summary


def test_create_report_keeps_typed_transcript_when_provided(
    monkeypatch: pytest.MonkeyPatch,
):
    """If the volunteer typed a transcript, the ASR adapter is not invoked
    even when audio is also uploaded."""

    calls: list[str] = []

    def _spy(path):  # type: ignore[no-untyped-def]
        calls.append(str(path))
        return "should-not-be-used"

    monkeypatch.setattr(deps.asr_client, "transcribe", _spy)

    async def run_flow():
        audio = UploadFile(filename="note.wav", file=BytesIO(b"fake-audio-bytes"))
        with Session(edge_engine) as edge_session:
            return await create_report(
                background_tasks=BackgroundTasks(),
                site_id="test-site",
                reporter_name="Volunteer",
                reporter_role="brigadista",
                transcript_text="ya paso la marca critica",
                offline_created=False,
                photo=None,
                audio=audio,
                session=edge_session,
            )

    payload = anyio.run(run_flow)
    assert calls == []
    assert payload["report"].transcript_text == "ya paso la marca critica"
