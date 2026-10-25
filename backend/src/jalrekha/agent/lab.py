"""Vision Lab for agent traces: rebuild one cycle's input frames and explain its OpenCV run.

Scenario frames are procedural and seeded, so they are regenerated exactly from
the scenario and the cycle time stored on the trace (``SIM_START + T``). The
real-camera replay reads the archived frame whose timestamp is the cycle time.
Frames uploaded by a live camera are not kept, so those cycles cannot be rebuilt.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from typing import Any

import cv2
import numpy as np
from sqlmodel import Session, select

from jalrekha.agent import runner, scenarios
from jalrekha.agent.models import AgentTrace
from jalrekha.models.domain import Site
from jalrekha.vision.explain import agreeing, explain
from jalrekha.vision.pipeline import MeasureOptions

CACHE_SIZE = 24
# The two cameras the lab page offers: a scenario site and the real USGS camera.
LAB_SITES: tuple[tuple[str, str], ...] = (("koshi-chatara-cam", "scenario"), ("hancock-usgs-cam", "real"))

_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_LOCK = threading.Lock()


class LabUnavailable(Exception):
    """This trace cannot be rebuilt; the message is shown to the user."""


def _step(steps: list[dict], tool: str) -> dict | None:
    return next((s for s in steps if s.get("tool") == tool), None)


def _scenario_for(row: AgentTrace) -> scenarios.Scenario | None:
    run = scenarios.RUNS.get(row.scenario_run_id or "")
    if run and run.get("scenario_id") in scenarios.SCENARIOS:
        return scenarios.SCENARIOS[run["scenario_id"]]
    # Scenarios that share a camera share its seed, hydrograph and events, so any of them rebuilds the frames.
    return next((sc for sc in scenarios.SCENARIOS.values() if sc.site_id == row.site_id), None)


def rebuild_frames(row: AgentTrace) -> tuple[list[np.ndarray], dict[str, Any]]:
    """The frames this cycle measured, plus a description of where they came from."""
    steps = json.loads(row.steps_json or "[]")
    meas_step = _step(steps, "measure_stage")
    if meas_step is None:
        raise LabUnavailable("this cycle has no camera measurement to rebuild")
    n = int((meas_step.get("input") or {}).get("frames") or 1)
    truth = json.loads(row.measurement_json or "{}").get("truth_stage_m")

    rr = next((r for r in scenarios.REAL_REPLAYS.values() if r.site_id == row.site_id), None)
    if rr is not None:
        rows, _cfg = scenarios._real_frames(rr)
        ts = row.started_at.strftime("%Y-%m-%dT%H:%M:%S")
        hit = next((r for r in rows if r["timestamp_utc"].replace("Z", "") == ts), None)
        img = cv2.imread(hit["abs_path"]) if hit else None
        if img is None:
            raise LabUnavailable("the archived camera frame for this cycle was not found")
        return [img], {"kind": "real", "replay_id": rr.id, "title": rr.title, "label": rr.label,
                       "frame": hit["image_path"], "gauge_stage_m": round(float(hit["stage_m"]), 3)}

    if row.site_id == scenarios.REDTEAM_SITE:
        base = scenarios.SCENARIOS["koshi-night-rise"]
        sc = scenarios.Scenario(id="redteam", title="Red-team sandbox", description="", basin=base.basin, site_id=row.site_id,
                                seed=base.seed, offset_m=base.offset_m, warning_m=base.warning_m, danger_m=base.danger_m,
                                stage=base.stage, duration_min=base.duration_min)
        t_min = scenarios.redteam_minute()
    else:
        sc = _scenario_for(row)
        if sc is None:
            raise LabUnavailable("frames from this camera are not archived; only scenario and real-camera replays can be rebuilt")
        t_min = (row.started_at - scenarios.SIM_START).total_seconds() / 60.0
        if not -1e-6 <= t_min <= sc.duration_min + 1e-6:
            raise LabUnavailable("this cycle's time is outside its scenario, so its frames cannot be rebuilt")
    frames, truth_now, tag, _ev = scenarios.frames_at(sc, t_min, n)
    if truth is not None and abs(round(truth_now, 3) - float(truth)) > 1e-3:
        raise LabUnavailable("could not rebuild this cycle's frames: the scenario level does not match the trace")
    return frames, {"kind": "scenario", "scenario_id": sc.id, "title": sc.title, "label": scenarios.LABEL,
                    "t_min": round(t_min, 2), "event": tag, "truth_stage_m": round(truth_now, 3)}


def _neighbours(session: Session, row: AgentTrace) -> dict[str, str | None]:
    base = select(AgentTrace.trace_id).where(AgentTrace.site_id == row.site_id)
    prev = session.exec(base.where(AgentTrace.created_at < row.created_at).order_by(AgentTrace.created_at.desc())).first()
    nxt = session.exec(base.where(AgentTrace.created_at > row.created_at).order_by(AgentTrace.created_at)).first()
    return {"prev": prev, "next": nxt}


def _build(session: Session, row: AgentTrace) -> dict[str, Any]:
    frames, source = rebuild_frames(row)
    try:
        ctx = runner.load_context(session, row.site_id)
    except runner.AgentError as exc:
        raise LabUnavailable(str(exc)) from exc
    lab = explain(frames, ctx.calib, ctx.reference, MeasureOptions(burst_dt_s=0.5))

    meas = json.loads(row.measurement_json or "{}")
    steps = json.loads(row.steps_json or "[]")
    fu = lab["fusion"]
    rd = {"stage_m": fu["fused_m"], "sigma_m": fu["sigma_m"], "agree": fu["agree_all_used"], "used": fu["used"],
          "per_estimator_m": fu["per_estimator_m"]}
    agreed, rsigma = runner.consensus(rd)
    members = fu["used"] if (fu["agree_all_used"] and len(fu["used"]) >= 2) else agreeing(fu["per_estimator_m"], fu["fused_m"])
    fu["consensus"] = {
        "rule": "at least 2 of 3 estimators within 10 cm of each other and of the fused value",
        "agreed": agreed, "members": members if agreed else [],
        "sigma_m": None if rsigma is None else round(rsigma, 4),
        "recorded": meas.get("consensus"),
    }
    kal = _step(steps, "kalman_filter")
    fu["kalman"] = {
        "filtered_stage_m": meas.get("filtered_stage_m"), "rate_m_per_h": meas.get("rate_m_per_h"),
        "detail": (kal or {}).get("output") or None,
    }
    meas_step = _step(steps, "measure_stage") or {}
    lab["timing"]["cycle_ms"] = (meas_step.get("output") or {}).get("timings_ms")
    lab["source"] = source
    lab["check"] = {
        "recorded_stage_m": meas.get("stage_m"), "rebuilt_stage_m": lab["summary"]["stage_m"],
        "recorded_registration": meas.get("registration"),
        "match": (meas.get("stage_m") is None and lab["summary"]["stage_m"] is None)
        or (meas.get("stage_m") is not None and lab["summary"]["stage_m"] is not None
            and abs(meas["stage_m"] - lab["summary"]["stage_m"]) <= 0.005),
    }
    site = session.get(Site, row.site_id)
    lab["trace"] = {
        "trace_id": row.trace_id, "site_id": row.site_id, "site_name": site.name if site else row.site_id,
        "cycle": row.cycle, "started_at": row.started_at.isoformat() + "Z", "summary": row.summary,
        "branches": json.loads(row.branches or "[]"), "scenario_run_id": row.scenario_run_id,
        "truth_stage_m": meas.get("truth_stage_m"), "warning_m": ctx.warning_m, "danger_m": ctx.danger_m,
    }
    return lab


def explain_trace(session: Session, trace_id: str) -> dict[str, Any]:
    """Vision Lab payload for one trace (cached per trace id, newest 24 kept)."""
    row = session.get(AgentTrace, trace_id)
    if row is None:
        raise LabUnavailable("unknown trace")
    with _LOCK:
        lab = _CACHE.get(trace_id)
        if lab is not None:
            _CACHE.move_to_end(trace_id)
    if lab is None:
        lab = _build(session, row)
        with _LOCK:
            _CACHE[trace_id] = lab
            while len(_CACHE) > CACHE_SIZE:
                _CACHE.popitem(last=False)
    # Neighbours change as new cycles arrive, so they are never cached.
    return {**lab, "neighbours": _neighbours(session, row)}


def latest_trace_ids(session: Session, site_id: str | None, limit: int = 8) -> list[str]:
    q = select(AgentTrace.trace_id)
    q = q.where(AgentTrace.site_id == site_id) if site_id else q.where(AgentTrace.site_id != scenarios.REDTEAM_SITE)
    return list(session.exec(q.order_by(AgentTrace.created_at.desc()).limit(limit)).all())


def explain_latest(session: Session, site_id: str | None) -> dict[str, Any]:
    """The newest cycle of a site that can be rebuilt."""
    ids = latest_trace_ids(session, site_id)
    if not ids:
        raise LabUnavailable("no agent cycles for this site yet; run a replay first")
    last: LabUnavailable | None = None
    for tid in ids:
        try:
            return explain_trace(session, tid)
        except LabUnavailable as exc:
            last = exc
    raise LabUnavailable(str(last) if last else "no cycle of this site can be rebuilt")


def lab_sites(session: Session) -> list[dict[str, Any]]:
    out = []
    for site_id, kind in LAB_SITES:
        site = session.get(Site, site_id)
        rows = session.exec(select(AgentTrace).where(AgentTrace.site_id == site_id).order_by(AgentTrace.created_at.desc()).limit(1)).all()
        count = len(session.exec(select(AgentTrace.trace_id).where(AgentTrace.site_id == site_id)).all())
        out.append({
            "site_id": site_id, "kind": kind, "name": site.name if site else None, "cycles": count,
            "latest_trace_id": rows[0].trace_id if rows else None,
            "latest_at": rows[0].started_at.isoformat() + "Z" if rows else None,
        })
    return out
