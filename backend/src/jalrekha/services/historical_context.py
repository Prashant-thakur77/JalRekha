from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from jalrekha.core.settings import get_settings


DEFAULT_CONTEXT_ROWS = [
    (
        "silverado-fixed-cam-usgs",
        "historical_event",
        "2015 flood analogue",
        "When the bridge marker reached 0.78, low access roads were cut within roughly 45 minutes.",
        0.78,
        "demo",
        "2015-01-01",
        None,
        "seed://silverado/2015-flood",
    ),
    (
        "silverado-fixed-cam-usgs",
        "civil_defense_manual",
        "Evacuation trigger",
        "If water is rising fast and the bridge mark is above 0.70, prepare evacuation messaging before overtopping.",
        0.70,
        "demo",
        "2026-01-01",
        None,
        "seed://silverado/manual",
    ),
    (
        "test-site",
        "civil_defense_manual",
        "Local action threshold",
        "Critical volunteer reports plus a rising fixed-node signal require CAP draft review and radio notification.",
        0.60,
        "test",
        "2026-01-01",
        None,
        "seed://test-site/manual",
    ),
]


@dataclass(frozen=True)
class HistoricalContextHit:
    id: int
    source: str
    title: str
    summary: str
    threshold_level: float | None
    jurisdiction: str | None
    effective_from: str | None
    effective_to: str | None
    source_uri: str | None
    rank: float


@dataclass(frozen=True)
class HistoricalContextDocument:
    site_id: str
    source: str
    title: str
    summary: str
    threshold_level: float | None = None
    jurisdiction: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    source_uri: str | None = None


def context_db_path() -> Path:
    settings = get_settings()
    return settings.data_dir / "historical_context.sqlite"


def ensure_context_db(path: Path | None = None) -> Path:
    db_path = path or context_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_context (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                threshold_level REAL,
                jurisdiction TEXT,
                effective_from TEXT,
                effective_to TEXT,
                source_uri TEXT
            )
            """
        )
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(historical_context)").fetchall()}
        for name, column_type in {
            "jurisdiction": "TEXT",
            "effective_from": "TEXT",
            "effective_to": "TEXT",
            "source_uri": "TEXT",
        }.items():
            if name not in existing_columns:
                conn.execute(f"ALTER TABLE historical_context ADD COLUMN {name} {column_type}")
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS historical_context_fts
            USING fts5(title, summary, source, content='historical_context', content_rowid='id')
            """
        )
        count = conn.execute("SELECT COUNT(*) FROM historical_context").fetchone()[0]
        if count == 0:
            conn.executemany(
                """
                INSERT INTO historical_context
                    (site_id, source, title, summary, threshold_level, jurisdiction, effective_from, effective_to, source_uri)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                DEFAULT_CONTEXT_ROWS,
            )
        fts_count = conn.execute("SELECT COUNT(*) FROM historical_context_fts").fetchone()[0]
        if fts_count == 0:
            conn.execute(
                """
                INSERT INTO historical_context_fts(rowid, title, summary, source)
                SELECT id, title, summary, source FROM historical_context
                """
            )
        conn.commit()
    return db_path


def upsert_historical_context(
    document: HistoricalContextDocument,
    *,
    path: Path | None = None,
) -> HistoricalContextHit:
    db_path = ensure_context_db(path)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO historical_context
                (site_id, source, title, summary, threshold_level, jurisdiction, effective_from, effective_to, source_uri)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document.site_id,
                document.source,
                document.title,
                document.summary,
                document.threshold_level,
                document.jurisdiction,
                document.effective_from,
                document.effective_to,
                document.source_uri,
            ),
        )
        rowid = int(cursor.lastrowid)
        conn.execute(
            "INSERT INTO historical_context_fts(rowid, title, summary, source) VALUES (?, ?, ?, ?)",
            (rowid, document.title, document.summary, document.source),
        )
        conn.commit()
    hits = retrieve_historical_context(document.site_id, query=document.title, limit=1, path=db_path)
    return hits[0]


def _query_terms(values: Iterable[str | None]) -> str:
    terms: list[str] = []
    for value in values:
        if not value:
            continue
        for token in str(value).replace("_", " ").replace("-", " ").split():
            token = "".join(ch for ch in token if ch.isalnum())
            if len(token) >= 3:
                terms.append(token)
    return " OR ".join(terms[:8])


def retrieve_historical_context(
    site_id: str,
    *,
    current_level: float | None = None,
    query: str | None = None,
    limit: int = 2,
    path: Path | None = None,
) -> list[HistoricalContextHit]:
    db_path = ensure_context_db(path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        match = _query_terms([query])
        if match:
            rows = conn.execute(
                """
                SELECT h.id, h.source, h.title, h.summary, h.threshold_level,
                       h.jurisdiction, h.effective_from, h.effective_to, h.source_uri,
                       bm25(historical_context_fts) AS lexical_rank
                FROM historical_context_fts
                JOIN historical_context h ON h.id = historical_context_fts.rowid
                WHERE h.site_id = ? AND historical_context_fts MATCH ?
                ORDER BY lexical_rank ASC,
                    CASE
                        WHEN h.threshold_level IS NULL THEN 999
                        ELSE ABS(h.threshold_level - ?)
                    END ASC,
                    h.id ASC
                LIMIT ?
                """,
                (site_id, match, current_level if current_level is not None else 0.0, limit),
            ).fetchall()
            if rows:
                return [_hit_from_row(row, current_level) for row in rows]
        rows = conn.execute(
            """
            SELECT id, source, title, summary, threshold_level,
                   jurisdiction, effective_from, effective_to, source_uri,
                   0.0 AS lexical_rank
            FROM historical_context
            WHERE site_id = ?
            ORDER BY
                CASE
                    WHEN threshold_level IS NULL THEN 999
                    ELSE ABS(threshold_level - ?)
                END ASC,
                id ASC
            LIMIT ?
            """,
            (site_id, current_level if current_level is not None else 0.0, limit),
        ).fetchall()
    return [_hit_from_row(row, current_level) for row in rows]


def _hit_from_row(row: sqlite3.Row, current_level: float | None) -> HistoricalContextHit:
    threshold = row["threshold_level"]
    distance = abs(float(threshold) - float(current_level)) if threshold is not None and current_level is not None else 1.0
    lexical_rank = abs(float(row["lexical_rank"] or 0.0))
    rank = round(max(0.0, min(1.0, 1.0 - min(distance, 1.0) * 0.55 - min(lexical_rank, 10.0) * 0.02)), 4)
    return HistoricalContextHit(
        id=int(row["id"]),
        source=str(row["source"]),
        title=str(row["title"]),
        summary=str(row["summary"]),
        threshold_level=threshold,
        jurisdiction=row["jurisdiction"],
        effective_from=row["effective_from"],
        effective_to=row["effective_to"],
        source_uri=row["source_uri"],
        rank=rank,
    )


def render_historical_context(hits: list[HistoricalContextHit]) -> str:
    return " ".join(f"[ctx:{hit.id} {hit.source} {hit.title}] {hit.summary}" for hit in hits)


def validate_context_citations(summary: str, hits: list[HistoricalContextHit]) -> bool:
    if not hits:
        return True
    allowed = {f"ctx:{hit.id}" for hit in hits}
    cited = {part.split("]", 1)[0] for part in summary.split("[") if part.startswith("ctx:")}
    return not cited or bool(cited.intersection(allowed))
