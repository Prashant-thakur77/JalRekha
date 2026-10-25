from __future__ import annotations

from jalrekha.services.historical_context import (
    HistoricalContextDocument,
    ensure_context_db,
    render_historical_context,
    retrieve_historical_context,
    upsert_historical_context,
    validate_context_citations,
)


def test_historical_context_uses_local_sqlite(tmp_path):
    db_path = tmp_path / "context.sqlite"
    ensure_context_db(db_path)

    hits = retrieve_historical_context(
        "silverado-fixed-cam-usgs",
        current_level=0.76,
        path=db_path,
    )

    assert hits
    assert hits[0].source in {"historical_event", "civil_defense_manual"}
    assert "bridge" in render_historical_context(hits).lower()
    assert f"ctx:{hits[0].id}" in render_historical_context(hits)


def test_historical_context_supports_fts_ingest(tmp_path):
    db_path = tmp_path / "context.sqlite"
    hit = upsert_historical_context(
        HistoricalContextDocument(
            site_id="site-a",
            source="manual",
            title="Pump station threshold",
            summary="If pump station water reaches 0.66, close the east gate.",
            threshold_level=0.66,
            jurisdiction="municipal",
            source_uri="manual://pump",
        ),
        path=db_path,
    )

    hits = retrieve_historical_context("site-a", current_level=0.65, query="pump gate", path=db_path)
    assert hits[0].id == hit.id
    assert hits[0].rank > 0.8
    assert validate_context_citations(f"Use [ctx:{hit.id}]", hits)
    assert not validate_context_citations("[ctx:999] bad citation", hits)
