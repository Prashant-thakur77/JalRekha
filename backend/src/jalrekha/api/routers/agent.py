"""Regions, river graphs, the perception-driven agent, approvals, scenario replays, relief.

Contract: docs/API_AGENT.md.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from jalrekha.agent import dispatch, policy, relief, runner, scenarios
from jalrekha.agent.models import AgentSiteState, AgentTrace, ApprovalRequest, ReliefRequest, RouteStatus, Shelter, StageReadingRow
from jalrekha.core.settings import get_settings
from jalrekha.db.database import get_session
from jalrekha.models.domain import Site
from jalrekha.regions import basin_for_site, load_basins, load_regions, region
from jalrekha.services.storage import get_upload_dir

router = APIRouter(tags=["agent"])


def _iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.isoformat() + "Z"


def _client(request: Request | None) -> str:
    if request is None:
        return "local"
    # The rightmost X-Forwarded-For entry is added by API Gateway; earlier entries are client-supplied.
    fwd = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    return fwd[-1] if fwd else (request.client.host if request.client else "unknown")


def _require_pin(pin: str | None, request: Request | None = None) -> None:
    client = _client(request)
    if dispatch.locked_out(client):
        raise HTTPException(status_code=429, detail="too many wrong PINs; try again in 10 minutes")
    if not dispatch.check_pin(pin, client):
        raise HTTPException(status_code=401, detail="operator PIN required (X-Operator-Pin)")


# ------------------------------------------------------------- regions/rivers
@router.get("/regions")
def list_regions() -> list[dict[str, Any]]:
    return [r.summary() for r in load_regions().values()]


@router.get("/regions/{region_id}")
def get_region(region_id: str) -> dict[str, Any]:
    r = region(region_id)
    if r is None:
        raise HTTPException(404, "unknown region")
    return r.model_dump()


@router.get("/rivers")
def list_rivers() -> list[dict[str, Any]]:
    return [{"id": b.id, "name": b.name, "countries": b.countries, "nodes": len(b.nodes), "edges": len(b.edges)} for b in load_basins().values()]


@router.get("/rivers/{basin_id}")
def get_river(basin_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    b = load_basins().get(basin_id)
    if b is None:
        raise HTTPException(404, "unknown basin")
    out = b.to_api()
    for n in out["nodes"]:
        st = session.get(AgentSiteState, n["site_id"]) if n.get("site_id") else None
        n["live"] = None if st is None else {"stage_m": st.last_stage_m, "rate_m_per_h": st.last_rate_m_per_h, "mode": st.mode, "updated_at": _iso(st.updated_at)}
    return out


@router.get("/rivers/{basin_id}/eta")
def river_eta(basin_id: str, from_node: str, rate_m_per_h: float | None = None) -> dict[str, Any]:
    b = load_basins().get(basin_id)
    if b is None or b.node(from_node) is None:
        raise HTTPException(404, "unknown basin or node")
    return {"basin": basin_id, "from_node": from_node, "rate_m_per_h": rate_m_per_h, "computed_at": _iso(datetime.utcnow()),
            "downstream": b.downstream(from_node)}


# -------------------------------------------------------------------- agent
def _state_api(st: AgentSiteState) -> dict[str, Any]:
    bn = basin_for_site(st.site_id)
    return {"site_id": st.site_id, "mode": st.mode, "cadence_s": st.cadence_s, "burst_frames": st.burst_frames,
            "last_stage_m": st.last_stage_m, "last_sigma_m": st.last_sigma_m, "last_rate_m_per_h": st.last_rate_m_per_h,
            "last_quality": st.last_quality, "siren_active": st.siren_active, "cycle": st.cycle,
            "basin": bn[0].id if bn else None, "node_id": bn[1].id if bn else None, "region_id": bn[1].region_id if bn else None,
            "updated_at": _iso(st.updated_at)}


@router.get("/agent/state")
def agent_state(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_state_api(s) for s in session.exec(select(AgentSiteState)).all()]


@router.get("/agent/policy")
def agent_policy() -> dict[str, Any]:
    return {"autonomy": policy.AUTONOMY, "branches": policy.BRANCHES,
            "thresholds": {k: getattr(policy, k) for k in dir(policy) if k.isupper() and isinstance(getattr(policy, k), (int, float))}}


@router.post("/agent/cycle")
async def agent_cycle(site_id: str = Form(...), frames: list[UploadFile] = File(...), x_camera_key: str | None = Header(default=None),
                      session: Session = Depends(get_session)) -> dict[str, Any]:
    # A spoofed camera could otherwise drive the autonomous siren: cameras carry a key.
    if not dispatch.camera_key_ok(x_camera_key):
        raise HTTPException(status_code=401, detail="camera key required (X-Camera-Key)")
    imgs = []
    for f in frames[:12]:
        data = np.frombuffer(await f.read(), np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is not None:
            imgs.append(img)
    if not imgs:
        raise HTTPException(400, "no decodable frames")
    try:
        return runner.run_cycle(session, site_id, imgs)
    except runner.AgentError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/traces", include_in_schema=False)
@router.get("/agent/traces")
def list_traces(site_id: str | None = None, run_id: str | None = None, branch: str | None = None, limit: int = 50,
                session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    q = select(AgentTrace)
    if site_id:
        q = q.where(AgentTrace.site_id == site_id)
    if run_id:
        q = q.where(AgentTrace.scenario_run_id == run_id)
    if branch:
        q = q.where(AgentTrace.branches.contains(f'"{branch.upper()}"'))
    if not site_id:
        q = q.where(AgentTrace.site_id != scenarios.REDTEAM_SITE)  # sandbox tries only when asked for
    rows = session.exec(q.order_by(AgentTrace.created_at.desc()).limit(max(1, min(limit, 500)))).all()
    return [runner.trace_to_api(r, full=False) for r in rows]


@router.get("/agent/traces/{trace_id}")
def get_trace(trace_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    row = session.get(AgentTrace, trace_id)
    if row is None:
        raise HTTPException(404, "unknown trace")
    return runner.trace_to_api(row)


# ---------------------------------------------------------------- approvals
class DecisionBody(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    operator: str = Field(default="operator", max_length=80)
    note: str | None = Field(default=None, max_length=500)
    edited_messages: list[dict[str, str]] | None = None


@router.get("/approvals")
def list_approvals(status: str = "pending", run_id: str | None = None, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = dispatch.list_approvals(session, status)
    if run_id:
        rows = [a for a in rows if a.scenario_run_id == run_id]
    return [dispatch.approval_to_api(a) for a in rows]


@router.get("/approvals/{approval_id}")
def get_approval(approval_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    ap = session.get(ApprovalRequest, approval_id)
    if ap is None:
        raise HTTPException(404, "unknown approval")
    return dispatch.approval_to_api(ap)


@router.post("/approvals/{approval_id}/decision")
def decide_approval(approval_id: int, body: DecisionBody, request: Request, x_operator_pin: str | None = Header(default=None),
                    session: Session = Depends(get_session)) -> dict[str, Any]:
    _require_pin(x_operator_pin, request)
    ap = session.get(ApprovalRequest, approval_id)
    if ap is None:
        raise HTTPException(404, "unknown approval")
    try:
        who = dispatch.pin_identity(x_operator_pin)
        operator = body.operator if who == "operator (shared PIN)" else f"{who}"
        if who == "operator (shared PIN)" and body.operator and body.operator != "operator":
            operator = f"{body.operator} (shared PIN)"
        ap = dispatch.decide(session, ap, body.decision, operator, body.note, body.edited_messages)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return dispatch.approval_to_api(ap)


# ---------------------------------------------------------------- scenarios
class RunBody(BaseModel):
    speed: float = Field(default=1.0, ge=0.1, le=20.0)


@router.get("/scenarios")
def list_scenarios() -> list[dict[str, Any]]:
    return [s.to_api() for s in scenarios.SCENARIOS.values()] + [r.to_api() for r in scenarios.REAL_REPLAYS.values()]


@router.post("/scenarios/{scenario_id}/run")
def run_scenario(scenario_id: str, body: RunBody | None = None) -> dict[str, Any]:
    if scenario_id not in scenarios.SCENARIOS and scenario_id not in scenarios.REAL_REPLAYS:
        raise HTTPException(404, "unknown scenario")
    speed = (body.speed if body else 1.0) or 1.0
    return scenarios.start_scenario(scenario_id, delay_s=round(0.6 / speed, 3))


@router.get("/scenarios/runs/{run_id}")
def scenario_run(run_id: str) -> dict[str, Any]:
    rec = scenarios.run_status(run_id)
    if rec is None:
        raise HTTPException(404, "unknown run")
    return rec


class RedTeamBody(BaseModel):
    reply: str = Field(min_length=1, max_length=600)


_REDTEAM_HITS: dict[str, list[float]] = {}


@router.post("/agent/red-team")
def red_team(body: RedTeamBody, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Try to fool the guard: your text is used as the vision model's reply in one
    danger-level cycle at a sandbox camera (no recipients, nothing can be sent)."""
    import time as _t

    client = _client(request)
    now = _t.time()
    hits = [h for h in _REDTEAM_HITS.get(client, []) if now - h < 60]
    if len(hits) >= 10:
        raise HTTPException(429, "at most 10 red-team tries per minute")
    _REDTEAM_HITS[client] = hits + [now]
    return scenarios.redteam_cycle(session, body.reply)


@router.get("/sites/{site_id}/live")
def site_live(site_id: str, limit: int = 120, session: Session = Depends(get_session)) -> dict[str, Any]:
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(404, "unknown site")
    st = session.get(AgentSiteState, site_id)
    rows = session.exec(select(StageReadingRow).where(StageReadingRow.site_id == site_id)
                        .order_by(StageReadingRow.at.desc()).limit(max(1, min(limit, 1000)))).all()[::-1]
    warning = danger = None
    try:
        ctx = runner.load_context(session, site_id)
        warning, danger = ctx.warning_m, ctx.danger_m
    except runner.AgentError:
        pass
    last_trace = session.exec(select(AgentTrace).where(AgentTrace.site_id == site_id).order_by(AgentTrace.created_at.desc())).first()
    meas = json.loads(last_trace.measurement_json) if last_trace else {}
    return {
        "site": {"id": site.id, "name": site.name, "region": site.region, "lat": site.lat, "lng": site.lng},
        "warning_m": warning, "danger_m": danger,
        "latest": None if st is None else {
            "at": _iso(st.last_measured_at), "frame_url": st.last_frame_url, "overlay_url": st.last_overlay_url,
            "stage_m": st.last_stage_m, "sigma_m": st.last_sigma_m, "rate_m_per_h": st.last_rate_m_per_h,
            "quality_ok": st.last_quality == "ok", "quality_reasons": [] if st.last_quality == "ok" else (st.last_quality or "").split(","),
            "usable": meas.get("usable"), "raw_stage_m": meas.get("stage_m"), "truth_stage_m": meas.get("truth_stage_m"),
            "estimators": meas.get("estimators"), "trace_id": last_trace.trace_id if last_trace else None,
        },
        "series": [{"t": _iso(r.at), "stage_m": r.stage_m, "sigma_m": r.sigma_m, "usable": r.usable, "filtered_stage_m": r.filtered_stage_m} for r in rows],
        "agent": None if st is None else {"mode": st.mode, "cadence_s": st.cadence_s, "burst_frames": st.burst_frames, "siren_active": st.siren_active},
    }


# ------------------------------------------------------------------- relief
class ReliefBody(BaseModel):
    text: str = Field(min_length=3, max_length=600)
    lang: str = Field(default="en", max_length=8)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    site_id: str | None = None
    channel: str = Field(default="app", pattern="^(app|sms|voice)$")
    people: int | None = Field(default=None, ge=0, le=100000)


@router.post("/relief/requests")
def create_relief(body: ReliefBody, session: Session = Depends(get_session)) -> dict[str, Any]:
    rr = relief.submit(session, text=body.text, lang=body.lang, lat=body.lat, lng=body.lng, site_id=body.site_id,
                       channel=body.channel, people=body.people)
    return relief.to_api(rr)


@router.get("/relief/requests")
def list_relief(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = session.exec(select(ReliefRequest)).all()
    rows.sort(key=lambda r: (r.status != "pending_approval", -r.priority, r.created_at))
    return [relief.to_api(r) for r in rows]


class ReliefDecision(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    operator: str = Field(default="operator", max_length=80)
    team: str | None = Field(default=None, max_length=80)


@router.post("/relief/requests/{relief_id}/decision")
def decide_relief(relief_id: int, body: ReliefDecision, request: Request, x_operator_pin: str | None = Header(default=None),
                  session: Session = Depends(get_session)) -> dict[str, Any]:
    _require_pin(x_operator_pin, request)
    rr = session.get(ReliefRequest, relief_id)
    if rr is None:
        raise HTTPException(404, "unknown request")
    ap = session.exec(select(ApprovalRequest).where(ApprovalRequest.dedupe_key == f"relief:{relief_id}")).first()
    if ap is not None and ap.status == "pending":
        payload = json.loads(ap.payload_json)
        payload["team"] = body.team
        ap.payload_json = json.dumps(payload, ensure_ascii=False)
        dispatch.decide(session, ap, body.decision, body.operator, None, None)
    if body.decision == "reject":
        rr.status = "rejected"
    elif rr.status != "dispatched":
        rr.status, rr.team = "dispatched", body.team
    rr.decided_by, rr.decided_at = body.operator, datetime.utcnow()
    session.add(rr)
    session.commit()
    session.refresh(rr)
    return relief.to_api(rr)


@router.post("/relief/photo-check")
async def photo_check(
    photo: UploadFile = File(...),
    ref_top_x: float | None = Form(default=None), ref_top_y: float | None = Form(default=None),
    ref_bottom_x: float | None = Form(default=None), ref_bottom_y: float | None = Form(default=None),
    ref_height_m: float = Form(default=1.0), route_id: str | None = Form(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    from jalrekha.vision.relief import check_photo

    data = np.frombuffer(await photo.read(), np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "not an image")
    if max(img.shape[:2]) > 1600:
        s = 1600 / max(img.shape[:2])
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        scale = s
    else:
        scale = 1.0
    top = (ref_top_x * scale, ref_top_y * scale) if ref_top_x is not None and ref_top_y is not None else None
    base = (ref_bottom_x * scale, ref_bottom_y * scale) if ref_bottom_x is not None and ref_bottom_y is not None else None
    res, ov = check_photo(img, top, base, max(0.1, min(ref_height_m, 5.0)))
    d = get_upload_dir() / "relief"
    d.mkdir(parents=True, exist_ok=True)
    name = f"photo-{uuid4().hex[:10]}.jpg"
    cv2.imwrite(str(d / name), ov, [cv2.IMWRITE_JPEG_QUALITY, 82])
    out = {**res.to_dict(), "overlay_url": f"/uploads/relief/{name}"}
    # D8: a confident "blocked" result drafts a route-board update for human approval.
    if res.passable == "no" and route_id and session.get(RouteStatus, route_id) is not None:
        route = session.get(RouteStatus, route_id)
        ap, _ = runner.upsert_approval(
            session, dedupe_key=f"route:{route_id}:blocked", action="publish_route_status", region_id=route.region_id,
            role="ddma_control_room" if route.region_id == "in" else "ward_focal", level="warning",
            title=f"Mark '{route.name}' BLOCKED?", rationale=f"Photo check: water depth {res.est_depth_m:.2f} ± {res.depth_pm_m:.2f} m at the reference object (≥ 0.30 m unsafe).",
            payload={"route_id": route_id, "status": "blocked", "overlay_url": out["overlay_url"], "messages": []},
            evidence=[{"label": "Depth at reference object", "value": f"{res.est_depth_m:.2f} m", "source": "photo-check (OpenCV GrabCut)"}],
        )
        session.commit()
        out["approval_id"] = ap.id
        out["branch"] = "D8"
    return out


@router.get("/relief/routes")
def list_routes(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    relief.seed_board(session)
    return [{"id": r.id, "name": r.name, "region_id": r.region_id, "lat": r.lat, "lng": r.lng, "status": r.status,
             "verified": r.verified, "updated_at": _iso(r.updated_at), "source": r.source} for r in session.exec(select(RouteStatus)).all()]


@router.get("/relief/shelters")
def list_shelters(region_id: str | None = None, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    relief.seed_board(session)
    q = select(Shelter)
    if region_id:
        q = q.where(Shelter.region_id == region_id)
    return [{"id": s.id, "name": s.name, "region_id": s.region_id, "admin_unit": s.admin_unit, "lat": s.lat, "lng": s.lng,
             "capacity": s.capacity, "occupancy": s.occupancy, "source": s.source} for s in session.exec(q).all()]


# ------------------------------------------------------------------- sitrep
@router.get("/sitrep/{region_id}")
def sitrep(region_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    prof = region(region_id)
    if prof is None:
        raise HTTPException(404, "unknown region")
    numbers: list[dict[str, Any]] = []
    lines: list[str] = []
    for st in session.exec(select(AgentSiteState)).all():
        bn = basin_for_site(st.site_id)
        if not bn or st.last_stage_m is None:
            continue
        basin, node = bn
        relevant = node.region_id == region_id or any(d["region_id"] == region_id for d in basin.downstream(node.id))
        if not relevant:
            continue
        tr = session.exec(select(AgentTrace).where(AgentTrace.site_id == st.site_id).order_by(AgentTrace.created_at.desc())).first()
        src = tr.trace_id if tr else "agent state"
        rate = f"{st.last_rate_m_per_h:+.2f} m/h" if st.last_rate_m_per_h is not None else "rate n/a"
        lines.append(f"{basin.name.split(' / ')[0]} at {node.name} ({node.country}): {st.last_stage_m:.2f} m, {rate}, mode {st.mode}.")
        numbers += [{"value": f"{st.last_stage_m:.2f} m", "label": f"Stage at {node.name}", "source": src},
                    {"value": rate, "label": f"Rise rate at {node.name}", "source": src}]
        for d in basin.downstream(node.id):
            if d["region_id"] == region_id and st.mode in {"watch", "alert"}:
                lines.append(f"  Expected at {d['name']} in {d['eta_h']['min']:.1f}-{d['eta_h']['max']:.1f} h{' (estimate)' if d['estimated'] else ''}.")
                numbers.append({"value": f"{d['eta_h']['min']:.1f}-{d['eta_h']['max']:.1f} h", "label": f"ETA {d['name']}", "source": f"river graph {basin.id}"})
    pend = session.exec(select(ApprovalRequest).where(ApprovalRequest.region_id == region_id).where(ApprovalRequest.status == "pending")).all()
    rel = session.exec(select(ReliefRequest).where(ReliefRequest.region_id == region_id).where(ReliefRequest.status == "pending_approval")).all()
    lines.append(f"Pending approvals: {len(pend)}. Open relief requests: {len(rel)}.")
    numbers += [{"value": str(len(pend)), "label": "Pending approvals", "source": "approvals table"},
                {"value": str(len(rel)), "label": "Open relief requests", "source": "relief table"}]
    template_text = "\n".join(lines) or "No active sites."
    out = {"region_id": region_id, "generated_at": _iso(datetime.utcnow()), "text": template_text,
           "numbers": numbers, "model": "template", "fallback_used": False,
           "note": "Every number links to a trace, the river graph or a table."}
    from jalrekha.adapters import claude
    from jalrekha.agent import guardrails

    if claude.available() and numbers:
        lang = {"in": "Hindi", "np": "Nepali"}.get(region_id, "English")
        prompt = ("Write a situation summary for district disaster officials: three to five short sentences in English, "
                  f"then the same in {lang}. Use only the facts and numbers below; do not add any number that is not listed. "
                  "Plain words, no headings.\n" + json.dumps({"facts": lines, "numbers": numbers}, ensure_ascii=False))
        try:
            r = claude.call(prompt, effort="low", max_tokens=2048)
            check = guardrails.numbers_from_tools(r.text, [numbers, lines])
            if check["ok"]:
                out.update(text=r.text, model=f"claude:{r.model}", guard=check)
            else:
                out.update(fallback_used=True, guard=check,
                           note="Claude's draft contained numbers not found in the tool outputs; the template summary is shown.")
        except claude.ClaudeUnavailable as exc:
            out.update(fallback_used=True, note=f"Claude unavailable ({exc}); template summary shown.")
    return out


# ----------------------------------------------------------------- evidence
@router.get("/evidence")
def evidence() -> dict[str, Any]:
    p = get_settings().project_root / "eval" / "results" / "headline.json"
    if not p.exists():
        return {"generated_from": [], "items": [], "note": "run `make eval` to produce eval/results/headline.json"}
    return json.loads(p.read_text(encoding="utf-8"))
