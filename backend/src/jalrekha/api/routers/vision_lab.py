"""Vision Lab: what OpenCV did for one agent cycle, stage by stage (vision/explain.py)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from jalrekha.agent import lab
from jalrekha.db.database import get_session

router = APIRouter(tags=["vision"])


@router.get("/vision/lab/sites")
def vision_lab_sites(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return lab.lab_sites(session)


@router.get("/vision/lab/latest")
def vision_lab_latest(site_id: str | None = None, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return lab.explain_latest(session, site_id)
    except lab.LabUnavailable as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/vision/lab/{trace_id}")
def vision_lab_trace(trace_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return lab.explain_trace(session, trace_id)
    except lab.LabUnavailable as exc:
        raise HTTPException(404, str(exc)) from exc
