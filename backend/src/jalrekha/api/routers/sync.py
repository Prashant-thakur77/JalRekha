from __future__ import annotations

from datetime import datetime
from typing import Type

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import SQLModel, Session, func, select

from jalrekha.db.database import get_central_session, get_session
from jalrekha.models.domain import (
    NodeAssessmentArtifact,
    ActuationRecord,
    FusedAlert,
    HydrometSnapshot,
    Incident,
    NodeObservation,
    ParsedObservation,
    SyncQueueItem,
    VolunteerReport,
)


router = APIRouter(tags=["sync"])


@router.post("/sync/flush")
async def flush_sync(
    edge_session: Session = Depends(get_session),
    central_session: Session = Depends(get_central_session),
) -> dict[str, int]:
    items = edge_session.exec(
        select(SyncQueueItem)
        .where(SyncQueueItem.status == "pending")
        .order_by(SyncQueueItem.created_at)
    ).all()
    flushed = 0
    failed = 0

    model_map: dict[str, Type[SQLModel]] = {
        "volunteer_report": VolunteerReport,
        "parsed_observation": ParsedObservation,
        "fused_alert": FusedAlert,
        "incident": Incident,
        "actuation_record": ActuationRecord,
        "node_observation": NodeObservation,
        "hydromet_snapshot": HydrometSnapshot,
        "node_assessment_artifact": NodeAssessmentArtifact,
    }

    try:
        for item in items:
            item.attempts += 1
            item.updated_at = datetime.utcnow()
            model_cls = model_map.get(item.entity_type)
            if model_cls is None:
                item.status = "failed"
                item.last_error = f"Unknown entity type: {item.entity_type}"
                failed += 1
                continue

            edge_record = edge_session.get(model_cls, item.entity_id)
            if edge_record is None:
                item.status = "failed"
                item.last_error = f"Missing edge record id={item.entity_id}"
                failed += 1
                continue

            if hasattr(edge_record, "sync_status"):
                setattr(edge_record, "sync_status", "synced")
            central_existing = central_session.get(model_cls, item.entity_id)
            if central_existing is None:
                central_session.add(model_cls(**edge_record.model_dump()))
            else:
                for key, value in edge_record.model_dump().items():
                    if key == "id":
                        continue
                    setattr(central_existing, key, value)
                central_session.add(central_existing)
            item.status = "synced"
            item.last_error = None
            item.synced_at = datetime.utcnow()
            flushed += 1

        central_session.commit()
        edge_session.commit()
    except Exception as exc:
        central_session.rollback()
        edge_session.rollback()
        raise HTTPException(status_code=500, detail=f"Sync failed: {exc}") from exc

    return {"queued": len(items), "flushed": flushed, "failed": failed}


@router.get("/sync/status")
async def sync_status(edge_session: Session = Depends(get_session)) -> dict[str, int]:
    rows = edge_session.exec(
        select(SyncQueueItem.status, func.count(SyncQueueItem.id)).group_by(SyncQueueItem.status)
    ).all()
    counts = {"pending": 0, "synced": 0, "failed": 0}
    for status, count in rows:
        counts[str(status)] = int(count)
    return counts

