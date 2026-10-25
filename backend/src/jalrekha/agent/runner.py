"""Perception-driven agent cycle: perceive -> assess -> plan -> guard -> act / ask -> trace.

One call of :func:`run_cycle` handles one burst of frames from one camera
site. The OpenCV 5 measurement decides the branch (D1-D9 in ``policy.py``),
and the branch changes the next tool call: capture cadence and burst length,
whether to pay for a VLM second opinion, whether to compute downstream ETAs
and draft cross-border alerts, whether the local siren may fire, and when to
propose an all-clear. Every step is written to a trace.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from sqlmodel import Session, select

from jalrekha.agent import cloud, cloudlog, guardrails, messages, policy
from jalrekha.agent.models import AgentSiteState, AgentTrace, ApprovalRequest, StageReadingRow
from jalrekha.models.domain import Site, SiteCalibration
from jalrekha.regions import basin_for_site, region, region_for_point, role_label
from jalrekha.services import action_guard
from jalrekha.services.actuators import LoggingAlarmActuator
from jalrekha.services.cap import build_cap_xml
from jalrekha.services.storage import get_upload_dir
from jalrekha.vision.gauge import GaugeCalibration
from jalrekha.vision.pipeline import MeasureOptions, measure
from jalrekha.vision.temporal import filter_series

_LOGGER = logging.getLogger(__name__)

# Last frame that registered cleanly, already warped into reference coordinates.
# When the full reference no longer matches (high water hides the low-water
# features), the agent re-registers against this keyframe instead (D2 chain).
KEYFRAMES: dict[str, tuple[np.ndarray, datetime]] = {}
KEYFRAME_MAX_AGE = timedelta(hours=1)


def consensus(rd: dict) -> tuple[bool, float | None]:
    """(agreed, robust_sigma_m). Agreed = at least two estimators within DISAGREE_M
    of each other and of the fused value. The robust sigma uses the agreeing
    pair only, so one outlier estimator does not inflate the uncertainty."""
    from jalrekha.vision.fuse import DISAGREE_M

    stage, sigma = rd.get("stage_m"), rd.get("sigma_m")
    if stage is None:
        return False, None
    if rd.get("agree") and len(rd.get("used") or []) >= 2:
        return True, sigma
    vals = [v for v in (rd.get("per_estimator_m") or {}).values() if v is not None]
    best = None
    for i, a in enumerate(vals):
        for b in vals[i + 1:]:
            if abs(a - b) <= DISAGREE_M and abs((a + b) / 2 - stage) <= DISAGREE_M:
                if best is None or abs(a - b) < best:
                    best = abs(a - b)
    if best is None:
        return False, sigma
    return True, float(max(0.01, best / 2 + 0.005))


# ----------------------------------------------------------------- tracing
@dataclass
class Trace:
    site_id: str
    cycle: int
    at: datetime
    trace_id: str = field(default_factory=lambda: "tr_" + uuid.uuid4().hex[:12])
    steps: list[dict[str, Any]] = field(default_factory=list)
    branches: list[str] = field(default_factory=list)
    summary_parts: list[str] = field(default_factory=list)
    measurement: dict[str, Any] = field(default_factory=dict)

    def step(self, kind: str, tool: str | None = None, *, input: Any = None, output: Any = None,
             decision: dict | None = None, latency_ms: float | None = None, cost_usd_est: float = 0.0,
             model: str | None = None, guard: dict | None = None) -> str:
        i = len(self.steps)
        self.steps.append({
            "i": i, "t": datetime.utcnow().isoformat() + "Z", "kind": kind, "tool": tool,
            "input": input or {}, "output": output or {}, "decision": decision,
            "latency_ms": None if latency_ms is None else round(latency_ms, 2),
            "cost_usd_est": round(cost_usd_est, 6), "model": model, "guard": guard,
        })
        if decision and decision.get("branch") and decision["branch"] not in self.branches:
            self.branches.append(decision["branch"])
        return f"{self.trace_id}#{i}"

    def say(self, text: str) -> None:
        self.summary_parts.append(text)


# ------------------------------------------------------------------ context
@dataclass
class SiteContext:
    site: Site
    calib: GaugeCalibration
    reference: np.ndarray | None
    region_id: str
    basin: Any
    node: Any

    @property
    def warning_m(self) -> float | None:
        return self.calib.warning_m if self.calib.warning_m is not None else getattr(self.node, "warning_m", None)

    @property
    def danger_m(self) -> float | None:
        return self.calib.danger_m if self.calib.danger_m is not None else getattr(self.node, "danger_m", None)


class AgentError(RuntimeError):
    pass


def load_context(session: Session, site_id: str) -> SiteContext:
    site = session.get(Site, site_id)
    if site is None:
        raise AgentError(f"unknown site {site_id}")
    cal = session.exec(
        select(SiteCalibration).where(SiteCalibration.site_id == site_id).order_by(SiteCalibration.created_at.desc())
    ).first()
    gauge = GaugeCalibration.from_json(cal.gauge_json if cal else None)
    if gauge is None:
        raise AgentError(f"site {site_id} has no staff-gauge calibration")
    ref = None
    if cal and cal.reference_frame_path and Path(cal.reference_frame_path).exists():
        ref = cv2.imread(cal.reference_frame_path, cv2.IMREAD_COLOR)
    bn = basin_for_site(site_id)
    basin, node = (bn if bn else (None, None))
    reg = region(node.region_id) if node else region_for_point(site.lat, site.lng)
    return SiteContext(site, gauge, ref, reg.id if reg else "np", basin, node)


def get_state(session: Session, site_id: str) -> AgentSiteState:
    st = session.get(AgentSiteState, site_id)
    if st is None:
        st = AgentSiteState(site_id=site_id)
        session.add(st)
    return st


def _save_image(img: np.ndarray | None, site_id: str, name: str) -> str | None:
    if img is None:
        return None
    d = get_upload_dir() / "agent" / site_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    cv2.imwrite(str(p), img, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return f"/uploads/agent/{site_id}/{name}"


def upsert_approval(session: Session, *, dedupe_key: str, **fields: Any) -> tuple[ApprovalRequest, bool]:
    existing = session.exec(
        select(ApprovalRequest).where(ApprovalRequest.dedupe_key == dedupe_key).where(ApprovalRequest.status == "pending")
    ).first()
    payload = fields.pop("payload", {})
    evidence = fields.pop("evidence", [])
    if existing is not None:
        for k, v in fields.items():
            setattr(existing, k, v)
        existing.payload_json = json.dumps(payload, ensure_ascii=False)
        existing.evidence_json = json.dumps(evidence, ensure_ascii=False)
        existing.updated_at = datetime.utcnow()
        session.add(existing)
        return existing, False
    ap = ApprovalRequest(dedupe_key=dedupe_key, payload_json=json.dumps(payload, ensure_ascii=False),
                         evidence_json=json.dumps(evidence, ensure_ascii=False), **fields)
    session.add(ap)
    session.flush()
    return ap, True


def _level(stage: float | None, rate: float | None, warning: float | None, danger: float | None) -> str:
    if stage is None:
        return "unknown"
    if danger is not None and stage >= danger:
        return "danger"
    if warning is not None and stage >= warning:
        return "warning"
    if rate is not None and rate >= policy.R_FAST_M_PER_H:
        return "watch"
    return "normal"


def _severity_for(level: str) -> str:
    return {"danger": "severe", "warning": "moderate", "watch": "minor"}.get(level, "info")


# --------------------------------------------------------------- main cycle
def run_cycle(
    session: Session,
    site_id: str,
    frames: list[np.ndarray],
    *,
    now: datetime | None = None,
    scenario_run_id: str | None = None,
    vlm: Any = None,
    truth_stage_m: float | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    now = now or datetime.utcnow()
    ctx = load_context(session, site_id)
    state = get_state(session, site_id)
    state.cycle += 1
    tr = Trace(site_id, state.cycle, now)
    profile = region(ctx.region_id)
    vlm = vlm or cloud.default_vlm()
    if note:
        tr.step("context", None, output={"note": note})

    # 1. PERCEIVE: OpenCV 5 measurement ------------------------------------
    t0 = time.perf_counter()
    kf = KEYFRAMES.get(site_id)
    m = None
    chained_from = None
    if state.heavy_last and kf is not None and now - kf[1] <= KEYFRAME_MAX_AGE:
        # Last cycle needed ALIKED+LightGlue against the reference: a cheap ORB match
        # against the last good keyframe (same water level, same light) usually suffices.
        m_fast = measure(frames, ctx.calib, kf[0], MeasureOptions(burst_dt_s=0.5, allow_heavy_registration=False))
        if m_fast.registration.ok:
            m = m_fast
            chained_from = {"reason": "fast path after a heavy registration", "keyframe_age_min": round((now - kf[1]).total_seconds() / 60, 1)}
    if m is None:
        m = measure(frames, ctx.calib, ctx.reference, MeasureOptions(burst_dt_s=0.5))
    state.heavy_last = "aliked_lightglue" in m.registration.tried and m.registration.ok and chained_from is None
    if chained_from is None and not m.registration.ok and kf is not None and now - kf[1] <= KEYFRAME_MAX_AGE:
        m2 = measure(frames, ctx.calib, kf[0], MeasureOptions(burst_dt_s=0.5, allow_heavy_registration=False))
        if m2.registration.ok:
            chained_from = {"failed_registration": m.registration.to_dict(), "keyframe_age_min": round((now - kf[1]).total_seconds() / 60, 1)}
            m = m2
    meas_ms = (time.perf_counter() - t0) * 1000
    gauge_visible = _gauge_in_view(m, ctx.calib, frames[-1].shape)
    md = m.to_dict()
    if not gauge_visible and md["registration"]["ok"]:
        md["registration"] = {**md["registration"], "ok": False, "method": "failed", "note": "gauge axis maps outside the current frame"}
        md["usable"] = False
    if m.registration.ok and gauge_visible and m.quality.ok and m.redacted_bgr is not None:
        KEYFRAMES[site_id] = (m.redacted_bgr.copy(), now)
    frame_url = _save_image(m.redacted_bgr if m.redacted_bgr is not None else frames[-1], site_id, f"{tr.trace_id}-frame.jpg")
    overlay_url = _save_image(m.overlay_bgr, site_id, f"{tr.trace_id}-overlay.jpg")
    rd = md["reading"]
    meas_ref = tr.step(
        "tool", "measure_stage",
        input={"frames": len(frames), "burst_frames_requested": state.burst_frames, "calibration_marks": len(ctx.calib.marks)},
        output={"stage_m": rd["stage_m"], "sigma_m": rd["sigma_m"], "agree": rd["agree"], "spread_m": rd["spread_m"],
                "confidence": rd["confidence"], "per_estimator_m": rd["per_estimator_m"],
                "quality_ok": md["quality"]["ok"], "quality_reasons": md["quality"]["reasons"],
                "registration": md["registration"], "surface_motion": md["surface_motion"],
                "faces_blurred": (md.get("redaction") or {}).get("faces", 0),
                "plates_blurred": (md.get("redaction") or {}).get("plates", 0),
                "timings_ms": md["timings_ms"], "opencv": md["opencv_version"]},
        latency_ms=meas_ms, model=f"opencv-{md['opencv_version']}",
    )
    tr.measurement = {
        "stage_m": rd["stage_m"], "sigma_m": rd["sigma_m"], "usable": md["usable"], "agree": rd["agree"],
        "confidence": rd["confidence"], "estimators": rd["per_estimator_m"],
        "quality": {"ok": md["quality"]["ok"], "reasons": md["quality"]["reasons"]},
        "registration": md["registration"]["method"], "overlay_url": overlay_url, "frame_url": frame_url,
        "timings_ms": {"total": round(meas_ms, 1)}, "truth_stage_m": truth_stage_m,
    }
    state.last_overlay_url, state.last_frame_url, state.last_measured_at = overlay_url, frame_url, now
    state.last_quality = "ok" if md["quality"]["ok"] else ",".join(md["quality"]["reasons"]) or "failed"

    reg = md["registration"]
    # D2: registration rescue / failure ---------------------------------------
    if chained_from is not None:
        tr.step("decision", "register_keyframe_chain", output={**chained_from, "chained": reg}, decision={
            "branch": "D2", "reason": "no reliable match against the calibration reference; re-registered against the last good keyframe",
            "before": {"registration": "failed vs reference"}, "after": {"registration": f"{reg['method']} vs keyframe", "inliers": reg["inliers"]}})
        tr.say("view shifted: lined up against the last good frame instead")
    if "aliked_lightglue" in reg.get("tried", []):
        if reg["ok"]:
            tr.step("decision", "register_heavy", output=reg, decision={
                "branch": "D2", "reason": "ORB could not align the frame to the calibration reference; ALIKED+LightGlue (OpenCV 5) re-registered it",
                "before": {"registration": "orb"}, "after": {"registration": "aliked_lightglue", "inliers": reg["inliers"]}})
            tr.say("view shifted: re-aligned with the slower feature matcher")
    if not reg["ok"]:
        before = {"mode": state.mode}
        state.mode = "degraded"
        tr.step("decision", "flag_recalibration", output=reg, decision={
            "branch": "D2", "reason": "No reliable alignment to the calibration frame (camera moved?); readings not trusted",
            "before": before, "after": {"mode": "degraded", "auto_actions": "suspended"}})
        ap, _ = upsert_approval(session, dedupe_key=f"{site_id}:recalibrate", action="recalibrate", site_id=site_id,
                                region_id=ctx.region_id, role=_approver(profile, "send_sms"), level="watch",
                                title=f"{ctx.site.name}: camera moved, recalibration needed",
                                rationale="Registration failed with ORB and ALIKED+LightGlue. Automatic actions at this site are suspended until a person re-clicks the gauge marks.",
                                payload={"messages": []}, evidence=[{"label": "Registration", "value": f"failed after {reg['tried']}", "source": meas_ref}],
                                trace_id=tr.trace_id, scenario_run_id=scenario_run_id)
        tr.step("approval", "request_approval", output={"approval_id": ap.id, "action": "recalibrate"})
        tr.say("camera moved off the gauge: readings paused, recalibration requested")
        return _finish(session, tr, state, md, None, scenario_run_id, ctx)

    # D1: quality gate ---------------------------------------------------------
    if state.mode == "degraded":
        state.mode = "watch"
        tr.step("decision", "clear_degraded", decision={"branch": "D2", "reason": "registration recovered", "before": {"mode": "degraded"}, "after": {"mode": "watch"}})
    if not md["quality"]["ok"]:
        state.cycles_since_bad = 0
        state.rise_streak = 0
        state.bad_quality_streak += 1
        before = {"burst_frames": state.burst_frames}
        state.burst_frames = policy.BURST_BOOST
        reason = f"quality gate failed ({', '.join(md['quality']['reasons'])}); this frame cannot raise or lower an alert"
        if before["burst_frames"] != state.burst_frames:
            tr.step("decision", "request_burst", decision={"branch": "D1", "reason": reason,
                                                            "before": before, "after": {"burst_frames": state.burst_frames}})
        else:
            tr.step("assess", "quality_gate", output={"usable": False, "reason": reason, "burst_frames": state.burst_frames})
        if state.bad_quality_streak == policy.PHOTO_REQUEST_STREAK:
            tr.step("tool", "request_volunteer_photo", input={"role": "community_gauge_reader", "site_id": site_id},
                    output={"status": "requested", "channel": "app/sms"},
                    decision={"branch": "D1", "reason": f"{state.bad_quality_streak} bad frames in a row",
                              "before": {"human_eyes": False}, "after": {"human_eyes": "requested"}})
        why = ", ".join(QUALITY_WORDS.get(r, r.replace("_", " ")) for r in md["quality"]["reasons"])
        more = f"; next burst {state.burst_frames} frames" if state.burst_frames != before["burst_frames"] else ""
        tr.say(f"unusable frame ({why}): not used{more}")
        _record_reading(session, site_id, now, rd, False, tr)
        return _finish(session, tr, state, md, None, scenario_run_id, ctx)
    if state.bad_quality_streak:
        state.bad_quality_streak = 0
        state.burst_frames = policy.BURST_NORMAL

    state.cycles_since_bad = min(state.cycles_since_bad + 1, 99)
    stage, sigma = rd["stage_m"], rd["sigma_m"]
    usable_for_alert = True

    # D3 / D7: second opinion only when needed ----------------------------------
    first_danger = ctx.danger_m is not None and stage is not None and stage >= ctx.danger_m and not state.siren_active
    agreed, rsigma = consensus(rd)
    vote = None
    if not agreed and stage is not None and (rd.get("per_estimator_m") or {}).get("E2_temporal") is None:
        vote = _snapshot_vote(session, site_id, now, stage)
        if vote is not None:
            agreed, rsigma = True, vote["sigma_m"]
            tr.step("assess", "snapshot_temporal_vote", output=vote)
    tr.measurement["consensus"] = {"two_of_three_within_10cm": agreed and vote is None, "snapshot_temporal_vote": vote is not None,
                                   "sigma_m": None if rsigma is None else round(rsigma, 4), "fused_sigma_m": rd["sigma_m"]}
    if agreed and rsigma is not None:
        sigma = rsigma
        rd = {**rd, "sigma_m": rsigma}
        tr.measurement["sigma_m"] = round(rsigma, 4)
        # Redraw the overlay with the uncertainty the agent actually uses, so the image and the card agree.
        if m.redacted_bgr is not None and overlay_url:
            from jalrekha.vision import overlay as _ov
            img = _ov.draw_debug(m.redacted_bgr, ctx.calib, rd["per_estimator_m"], stage, rsigma, md["quality"]["reasons"], md["registration"]["method"])
            _save_image(img, site_id, f"{tr.trace_id}-overlay.jpg")
    needs_second = (not agreed) or (rsigma is not None and rsigma > policy.SIGMA_MAX_M)
    if needs_second or first_danger:
        why = "no two estimators agree within 10 cm" if not agreed else (f"sigma {rsigma:.3f} m > {policy.SIGMA_MAX_M} m" if needs_second else "first danger-level reading: confirm before the siren")
        if needs_second:
            tr.step("decision", "verify_with_vlm", decision={
                "branch": "D3", "reason": why, "before": {"second_opinion": "not requested"}, "after": {"second_opinion": "requested"}})
        usable_for_alert = _second_opinion(tr, ctx, m, stage, rd, vlm, needs_second, session, profile, scenario_run_id, meas_ref,
                                           held_before=state.held_streak)

    # Record and filter -------------------------------------------------------------
    _record_reading(session, site_id, now, rd, usable_for_alert, tr)
    filt = _filter(session, site_id, now)
    f_stage = filt["stage_m"] if filt else stage
    rate = filt["rate_m_per_h"] if filt else None
    # Significant rise only: the lower end of the rate's confidence band must clear the threshold.
    rate_sig = None if rate is None else rate - policy.RATE_SIGNIFICANCE_Z * (filt.get("rate_sigma_m_per_h") or 0.0)
    kal_ref = tr.step("tool", "kalman_filter", input={"history_h": policy.HISTORY_HOURS},
                      output=filt or {"note": "not enough readings yet"}, model="cv2.KalmanFilter")
    state.last_stage_m, state.last_sigma_m, state.last_rate_m_per_h = f_stage, sigma, rate
    tr.measurement["rate_m_per_h"] = None if rate is None else round(rate, 3)
    tr.measurement["filtered_stage_m"] = None if f_stage is None else round(f_stage, 3)
    if f_stage is not None:
        state.peak_stage_m = max(state.peak_stage_m or f_stage, f_stage)
    warning, danger = ctx.warning_m, ctx.danger_m
    level = _level(f_stage, rate, warning, danger)
    t_cross_h = None
    if rate and rate > 0 and warning is not None and f_stage is not None and f_stage < warning:
        t_cross_h = (warning - f_stage) / rate
    tr.step("assess", "classify_level", output={"level": level, "stage_m": f_stage, "rate_m_per_h": rate,
                                                 "warning_m": warning, "danger_m": danger,
                                                 "hours_to_warning": None if t_cross_h is None else round(t_cross_h, 2)})

    if not usable_for_alert:
        state.held_streak += 1
        tr.say("reading held for a person to check")
        if state.held_streak >= 3:
            # Do not stay blind silently: three uncertain readings in a row go to a person.
            ap, created = upsert_approval(
                session, dedupe_key=f"{site_id}:review_reading", action="review_reading", site_id=site_id,
                region_id=ctx.region_id, role=_approver(profile, "send_sms"), level=level if level != "unknown" else "watch",
                title=f"{ctx.site.name}: camera reading uncertain for {state.held_streak} cycles",
                rationale="The OpenCV estimators disagree and no second opinion is available. Last camera value "
                          f"{stage:.2f} m (not used). Please check the frame or ask the gauge reader." if stage is not None else
                          "The OpenCV estimators disagree and no second opinion is available.",
                payload={"messages": [], "frame_url": tr.measurement.get("frame_url")},
                evidence=[{"label": "Held readings in a row", "value": str(state.held_streak), "source": meas_ref}],
                trace_id=tr.trace_id, scenario_run_id=scenario_run_id)
            tr.step("approval", "request_approval", output={"approval_id": ap.id, "action": "review_reading", "created": created},
                    decision={"branch": "D3", "reason": f"{state.held_streak} uncertain readings in a row",
                              "before": {"human_eyes": False}, "after": {"human_eyes": "requested"}} if created else None)
        return _finish(session, tr, state, md, filt, scenario_run_id, ctx)
    state.held_streak = 0

    evidence = [
        {"label": "Camera stage (OpenCV 5)", "value": f"{stage:.2f} m ± {sigma:.2f}" if stage is not None and sigma is not None else "n/a", "source": meas_ref},
        {"label": "Filtered stage / rise rate", "value": f"{f_stage:.2f} m, {rate:+.2f} m/h" if rate is not None else f"{f_stage}", "source": kal_ref},
    ]
    if warning is not None:
        evidence.append({"label": "Warning / danger level", "value": f"{warning} m / {danger} m", "source": "site calibration"})

    # D4: fast rise -> look more often + downstream ETA ---------------------------
    eta_list: list[dict] = []
    if rate_sig is not None and rate_sig >= policy.R_FAST_M_PER_H:
        state.falling_streak = 0
        if state.cadence_s != state.fast_cadence_s:
            before = {"cadence_s": state.cadence_s, "mode": state.mode}
            state.cadence_s = state.fast_cadence_s
            state.mode = "watch" if state.mode in {"normal", "degraded"} else state.mode
            tr.step("decision", "set_capture_cadence", decision={
                "branch": "D4", "reason": f"rise {rate:.2f} m/h (lower bound {rate_sig:.2f}) ≥ {policy.R_FAST_M_PER_H} m/h",
                "before": before, "after": {"cadence_s": state.cadence_s, "mode": state.mode}})
            tr.say(f"rising {rate:.2f} m/h: checks every {state.cadence_s // 60} min instead of {before['cadence_s'] // 60}")
        if ctx.basin is not None:
            t1 = time.perf_counter()
            eta_list = ctx.basin.downstream(ctx.node.id)
            eta_ref = tr.step("tool", "downstream_eta", input={"basin": ctx.basin.id, "from_node": ctx.node.id},
                              output={"downstream": [{"node": d["node_id"], "eta_h": d["eta_h"], "crosses_border": d["crosses_border"], "estimated": d["estimated"]} for d in eta_list]},
                              latency_ms=(time.perf_counter() - t1) * 1000)
            evidence.append({"label": "Downstream ETA bands", "value": "; ".join(f"{d['name']} {d['eta_h']['min']:.1f}-{d['eta_h']['max']:.1f} h" for d in eta_list[:4]), "source": eta_ref})

    # D5: warning reached / projected -> drafts for approval ------------------------
    significant = rate_sig is not None and rate_sig >= policy.R_FAST_M_PER_H
    state.rise_streak = state.rise_streak + 1 if significant else 0
    projected = t_cross_h is not None and t_cross_h <= policy.CROSS_HORIZON_H and significant
    if projected and state.cycles_since_bad <= policy.POST_GAP_CYCLES and state.rise_streak < policy.POST_GAP_RISE_STREAK:
        tr.step("decision", "hold_projection", decision={
            "branch": "D5", "reason": f"rise right after bad frames ({state.cycles_since_bad} cycle(s) ago): needs "
                                      f"{policy.POST_GAP_RISE_STREAK} significant cycles in a row, have {state.rise_streak}",
            "before": {"draft": "projected crossing"}, "after": {"draft": "wait for confirmation"}})
        projected = False
    falling = rate is not None and rate < 0
    if (level in {"warning", "danger"} and not (falling and level != "danger")) or projected:
        if state.mode != "alert":
            tr.step("decision", "draft_alerts", decision={
                "branch": "D5",
                "reason": (f"stage {f_stage:.2f} m ≥ warning {warning} m" if level in {"warning", "danger"}
                           else f"projected to cross warning {warning} m in {t_cross_h * 60:.0f} min"),
                "before": {"mode": state.mode}, "after": {"mode": "alert", "drafts": "local + downstream"}})
            state.mode = "alert"
        _draft_local(session, tr, ctx, profile, level, f_stage, rate, t_cross_h, evidence, scenario_run_id)
        if not falling:
            # A "rising fast" message must never carry a falling rate: once the river
            # turns, the downstream drafts keep the numbers from the rise.
            if not eta_list and ctx.basin is not None:
                eta_list = ctx.basin.downstream(ctx.node.id)
            _draft_downstream(session, tr, ctx, f_stage, rate, level, eta_list, evidence, scenario_run_id)

    # D6: danger + good quality -> local siren (autonomous, guarded) -----------------
    if level == "danger" and not state.siren_active and agreed and (rsigma or 0) <= policy.SIGMA_MAX_M:
        call = {"name": "trigger_siren", "arguments": {"zone_id": site_id, "severity": "severe",
                                                        "reason": f"Camera stage {f_stage:.2f} m above danger level {danger} m"}}
        g = action_guard.validate_tool_call(call, evidence={"max_allowed_severity": _severity_for(level), "zone_id": site_id},
                                            now=now, bounds=profile.bounds.as_guard_bounds() if profile else None)
        guard = {"accepted": g.accepted, "reason": g.reason}
        if g.accepted:
            LoggingAlarmActuator().fire(call["arguments"])
            state.siren_active = True
        tr.step("action", "trigger_siren", input=call["arguments"], output={"fired": g.accepted, "channel": "local siren (edge GPIO stub)"},
                guard=guard, decision={"branch": "D6", "reason": "danger level, quality OK, estimators agree (2 of 3 within 10 cm)",
                                        "before": {"siren": "off"}, "after": {"siren": "on" if g.accepted else "blocked by guard"}})
        tr.say(f"danger level {f_stage:.2f} m: local siren {'on' if g.accepted else 'blocked by the guard'}")

    # D9: falling after a peak -> cadence down, all-clear proposal --------------------
    calm = rate is not None and (rate <= policy.R_FALL_M_PER_H or (state.mode == "watch" and rate < policy.R_FAST_M_PER_H / 2))
    if calm:
        state.falling_streak += 1
    peaked_high = warning is not None and (state.peak_stage_m or 0) >= warning
    below = warning is None or (f_stage is not None and f_stage < warning)
    # Act only on a cycle with a valid reading: a held reading (rate None) never lowers cadence or proposes an all-clear.
    if calm and state.falling_streak >= policy.FALLING_CYCLES and (state.cadence_s != state.normal_cadence_s or (state.mode == "alert" and below)):
        before = {"cadence_s": state.cadence_s, "mode": state.mode}
        state.cadence_s = state.normal_cadence_s
        if peaked_high and below:
            _draft_all_clear(session, tr, ctx, profile, f_stage, rate, evidence, scenario_run_id)
            state.mode = "normal"
            state.siren_active = False
        elif not peaked_high:
            state.mode = "normal"
        if before != {"cadence_s": state.cadence_s, "mode": state.mode}:
            tr.step("decision", "set_capture_cadence" if before["cadence_s"] != state.cadence_s else "propose_all_clear", decision={
                "branch": "D9", "reason": f"falling for {state.falling_streak} cycles ({rate:+.2f} m/h)"
                + ("; below warning after a peak above it" if peaked_high and below else ""),
                "before": before, "after": {"cadence_s": state.cadence_s, "mode": state.mode}})
            parts = []
            if before["cadence_s"] != state.cadence_s:
                parts.append(f"cadence {before['cadence_s']}→{state.cadence_s} s")
            if peaked_high and below:
                parts.append("all-clear proposed")
            tr.say("falling: " + "; ".join(parts or ["mode " + state.mode]))

    if not tr.summary_parts:
        tr.say(f"{f_stage:.2f} m, {rate:+.2f} m/h, {level}" if rate is not None and f_stage is not None else f"{stage} m")
    return _finish(session, tr, state, md, filt, scenario_run_id, ctx)


# ---------------------------------------------------------------- helpers
def _snapshot_vote(session: Session, site_id: str, now: datetime, stage: float) -> dict | None:
    """Second vote for single-frame cameras: the two previous raw readings (usable or not)
    and this one all lie within SNAPSHOT_AGREE_M of each other inside the window."""
    since = now - timedelta(hours=policy.SNAPSHOT_WINDOW_H)
    prev = session.exec(
        select(StageReadingRow).where(StageReadingRow.site_id == site_id).where(StageReadingRow.at >= since)
        .where(StageReadingRow.at < now).where(StageReadingRow.stage_m != None)  # noqa: E711
        .order_by(StageReadingRow.at.desc()).limit(2)
    ).all()
    if len(prev) < 2:
        return None
    vals = [stage] + [p.stage_m for p in prev]
    if max(vals) - min(vals) > policy.SNAPSHOT_AGREE_M:
        return None
    return {"readings_m": [round(v, 3) for v in vals], "spread_m": round(max(vals) - min(vals), 3),
            "sigma_m": round(max(0.01, float(np.std(vals)) + 0.005), 4),
            "rule": f"3 consecutive snapshots within {policy.SNAPSHOT_AGREE_M:.2f} m inside {policy.SNAPSHOT_WINDOW_H:.0f} h"}


def _gauge_in_view(m, calib: GaugeCalibration, shape) -> bool:
    """Map the calibrated gauge ends back into the current frame; both must be inside it."""
    reg = m.registration
    if reg.method in {"identity", "failed"}:
        return True
    a = np.vstack([reg.matrix, [0.0, 0.0, 1.0]])
    try:
        inv = np.linalg.inv(a)
    except np.linalg.LinAlgError:
        return False
    h, w = shape[:2]
    for pt in (calib.top, calib.bottom):
        x, y, _ = inv @ np.array([pt[0], pt[1], 1.0])
        if not (0 <= x < w and 0 <= y < h):
            return False
    return True


QUALITY_WORDS = {
    "blurred": "blurred",
    "exposure_clipped": "over- or under-exposed",
    "glare_on_gauge": "glare on the gauge",
    "low_contrast_fog_or_occlusion": "fog, rain or something in front of the lens",
    "night_or_underexposed": "too dark",
}


def _approver(profile, action: str) -> str:
    if profile is None:
        return "operator"
    for r in profile.authority_roles:
        if action in r.approves:
            return r.id
    return profile.authority_roles[0].id


def _record_reading(session: Session, site_id: str, now: datetime, rd: dict, usable: bool, tr: Trace) -> None:
    session.add(StageReadingRow(site_id=site_id, at=now, stage_m=rd["stage_m"], sigma_m=rd["sigma_m"],
                                usable=bool(usable and rd["stage_m"] is not None), trace_id=tr.trace_id))
    session.flush()


def _filter(session: Session, site_id: str, now: datetime) -> dict | None:
    since = now - timedelta(hours=policy.HISTORY_HOURS)
    rows = session.exec(
        select(StageReadingRow).where(StageReadingRow.site_id == site_id).where(StageReadingRow.usable == True)  # noqa: E712
        .where(StageReadingRow.at >= since).where(StageReadingRow.at <= now).order_by(StageReadingRow.at)
    ).all()
    if len(rows) < 2:
        return None
    out = filter_series([(r.at, r.stage_m, r.sigma_m or 0.03) for r in rows])
    if out is None:
        return None
    d = out.to_dict()
    rows[-1].filtered_stage_m, rows[-1].rate_m_per_h = d["stage_m"], d["rate_m_per_h"]
    session.add(rows[-1])
    return d


def _second_opinion(tr: Trace, ctx: SiteContext, m, stage, rd, vlm, needs_second: bool, session, profile,
                    scenario_run_id, meas_ref: str, held_before: int = 0) -> bool:
    """Ask the VLM. Returns whether the CV reading may drive alerts."""
    lo, hi = ctx.calib.stage_range
    ok, jpeg = cv2.imencode(".jpg", m.redacted_bgr if m.redacted_bgr is not None else m.overlay_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    try:
        ans = vlm.ask_gauge(jpeg.tobytes(), lo, hi)
    except cloud.VLMUnavailable as exc:
        tr.step("fallback", "verify_with_vlm", output={"error": str(exc), "vlm_called": False},
                decision={"branch": "D3", "reason": "VLM unavailable: rule fallback",
                          "before": {"plan": "VLM second opinion"},
                          "after": {"plan": "use CV only if estimators agree; else hold and ask for a photo"}} if needs_second else None)
        if needs_second:
            if held_before == 0:  # one photo request per run of held readings, not one per cycle
                tr.step("tool", "request_volunteer_photo", input={"role": "community_gauge_reader"}, output={"status": "requested"})
                tr.say("readings disagree and no second opinion available: held, photo requested")
            else:
                tr.say(f"readings disagree and no second opinion available: held ({held_before + 1} in a row)")
            return False
        return True
    parsed = cloud.parse_gauge_answer(ans.raw_text)
    vref = tr.step("tool", "verify_with_vlm", input={"question": "read the staff gauge", "range_m": [lo, hi]},
                   output={"raw_text": ans.raw_text[:400], "parsed": parsed, "scripted": ans.scripted},
                   latency_ms=ans.latency_ms, cost_usd_est=ans.cost_usd_est, model=ans.model)
    cloud.put_metrics({"Escalations": 1})
    guard_reason = None
    if not parsed["ok"]:
        guard_reason = f"VLM reply rejected by schema guard ({parsed['reason']})"
    elif parsed["extra_text"]:
        inj = guardrails.looks_like_injection(ans.raw_text)
        guard_reason = ("VLM reply contained an instruction to the agent (prompt injection); ignored" if inj
                        else "VLM reply contained text outside the JSON answer; ignored")
    v = parsed.get("stage_m")
    ok_c, rs = consensus(rd)
    cv_confident = ok_c and (rs or 0) <= policy.SIGMA_MAX_M
    if guard_reason is None and v is not None and stage is not None and abs(v - stage) <= policy.VLM_CONFIRM_M:
        tr.step("guard", "compare_cv_vlm", output={"cv_m": stage, "vlm_m": v, "delta_m": round(v - stage, 3)},
                guard={"accepted": True, "reason": "VLM confirms the CV reading"})
        tr.say(f"second opinion agrees: {stage:.2f} m")
        return True
    contradiction = guard_reason is not None or (v is not None and stage is not None and abs(v - stage) > policy.VLM_CONTRADICTION_M)
    if contradiction and cv_confident:
        tr.step("guard", "compare_cv_vlm",
                output={"cv_m": stage, "vlm_m": v, "delta_m": None if v is None or stage is None else round(v - stage, 3)},
                guard={"accepted": False, "reason": guard_reason or "VLM contradicts the agreeing OpenCV estimators (2 of 3 within 10 cm)"},
                decision={"branch": "D7", "reason": "keep the measured value; unknown never means safe",
                          "before": {"source": "cv+vlm"}, "after": {"source": "cv", "human_review": "requested"}})
        ap, _ = upsert_approval(session, dedupe_key=f"{ctx.site.id}:review_reading", action="review_reading",
                                site_id=ctx.site.id, region_id=ctx.region_id, role=_approver(profile, "send_sms"), level="watch",
                                title=f"{ctx.site.name}: VLM disagreed with the camera measurement",
                                rationale=(guard_reason or "VLM reading differs from the CV reading") + ". The agent kept the OpenCV value; please look at the frame.",
                                payload={"messages": [], "frame_url": tr.measurement.get("frame_url"), "vlm_raw": ans.raw_text[:400]},
                                evidence=[{"label": "OpenCV stage", "value": f"{stage:.2f} m", "source": meas_ref},
                                          {"label": "VLM answer", "value": (str(v) if v is not None else "none"), "source": vref}],
                                trace_id=tr.trace_id, scenario_run_id=scenario_run_id)
        tr.step("approval", "request_approval", output={"approval_id": ap.id, "action": "review_reading"})
        tr.say("second opinion contradicted the camera or carried instructions: OpenCV reading kept, a person asked to check")
        return True
    if cv_confident and not needs_second:
        # Confident measurement, second opinion abstained or was unusable: an abstention is not a veto.
        tr.step("guard", "compare_cv_vlm", output={"cv_m": stage, "vlm_m": v},
                guard={"accepted": False, "reason": guard_reason or "VLM gave no reading; confident OpenCV value kept"})
        tr.say("second opinion could not read the gauge: confident OpenCV reading kept")
        return True
    # CV itself was unsure and the VLM does not confirm: hold.
    tr.step("guard", "compare_cv_vlm", output={"cv_m": stage, "vlm_m": v}, guard={"accepted": False, "reason": guard_reason or "no confirmation"},
            decision={"branch": "D3", "reason": "uncertain CV and no confirmation", "before": {"use_reading": True}, "after": {"use_reading": False}})
    tr.say("uncertain reading held")
    return False


def _lang_payload(profile, kind: str, facts: dict, langs: list[str] | None = None) -> dict:
    langs = langs or (profile.public_languages if profile else ["en"])
    msgs = messages.build_messages(kind, langs, facts)
    audio = []
    for msg in msgs:
        lang = profile.language(msg["lang"]) if profile else None
        a = cloud.synthesize(msg["text"], lang.tts if lang else None)
        audio.append({"lang": msg["lang"], **a})
    return {"messages": msgs, "audio": audio}


def _draft_local(session, tr: Trace, ctx: SiteContext, profile, level, f_stage, rate, t_cross_h, evidence, run_id) -> None:
    node = ctx.node
    place = node.name if node else ctx.site.name
    facts = {"river": ctx.basin.name if ctx.basin else "", "place": place, "stage_m": f_stage, "rate_m_per_h": rate,
             "warning_m": ctx.warning_m, "danger_m": ctx.danger_m,
             "cross_min": None if t_cross_h is None else t_cross_h * 60, "sender": messages.SENDER.get(ctx.region_id, "-NadiSaathi")}
    if level == "danger":
        kind = "danger"
    elif rate is None:
        return  # rise-rate messages wait for a second reading; the danger message does not need one
    elif level == "warning" or t_cross_h is None:
        kind = "local_above"
    else:
        kind = "local_rise"
    payload = _lang_payload(profile, kind, facts)
    target = (node.alert_targets[0] if node and node.alert_targets else {"role": _approver(profile, "send_sms"), "area": place})
    payload["recipients"] = target.get("area")
    ap, created = upsert_approval(
        session, dedupe_key=f"{ctx.site.id}:local:{'danger' if kind == 'danger' else 'warning'}", action="send_sms", site_id=ctx.site.id, region_id=ctx.region_id,
        role=target.get("role") or _approver(profile, "send_sms"), level=level,
        title=f"{place}: {'DANGER' if level == 'danger' else 'rising water'} {f_stage:.2f} m ({rate:+.2f} m/h)" if rate is not None else f"{place}: {f_stage:.2f} m",
        rationale="Local warning for riverside families at the camera site. Numbers from the OpenCV measurement and the Kalman filter.",
        payload=payload, evidence=evidence, trace_id=tr.trace_id, scenario_run_id=run_id,
    )
    tr.step("approval", "draft_alert", input={"kind": kind, "langs": [m["lang"] for m in payload["messages"]]},
            output={"approval_id": ap.id, "created": created, "segments": [m["segments"] for m in payload["messages"]],
                    "audio": [a["provider"] for a in payload["audio"]]})
    if created:
        cloud.notify_operators(f"NadiSaathi approval needed: {ap.title}", ap.rationale)
        tr.step("tool", "start_escalation_timer", input={"approval_id": ap.id, "wait_s": 900},
                output=cloud.start_escalation(ap.id, ap.title), model="aws-step-functions")


def _draft_downstream(session, tr: Trace, ctx: SiteContext, f_stage, rate, level, eta_list, evidence, run_id) -> None:
    if not eta_list or rate is None:
        return
    groups: dict[tuple, list[dict]] = {}
    for d in eta_list:
        for tgt in d.get("alert_targets") or []:
            groups.setdefault((tgt["region_id"], tgt["role"], d.get("admin_unit")), []).append({**d, "target": tgt})
    for (region_id, role, admin_unit), items in groups.items():
        items.sort(key=lambda d: d["eta_h"]["typ"])
        first = items[0]
        prof = region(region_id)
        facts = {"river": ctx.basin.name, "place": first["name"], "up": ctx.node.name, "up_country": ctx.node.country,
                 "rate_m_per_h": rate, "eta_min_h": first["eta_h"]["min"], "eta_max_h": first["eta_h"]["max"],
                 "sender": messages.SENDER.get(region_id, "-NadiSaathi")}
        payload = _lang_payload(prof, "downstream", facts)
        payload["eta"] = first["eta_h"]
        payload["eta_estimated"] = first["estimated"]
        payload["places"] = [{"name": i["name"], "eta_h": i["eta_h"]} for i in items]
        payload["recipients"] = first["target"].get("area")
        lang_codes = [prof.language(c).cap_language for c in prof.public_languages if prof.language(c)]
        node = ctx.basin.node(first["node_id"])
        cap_event = {
            "identifier": f"nadisaathi-{ctx.basin.id}-{first['node_id']}-{tr.trace_id}",
            "sender": prof.alert_format.get("cap_sender"), "web": prof.alert_format.get("cap_web"),
            "code": "NadiSaathi-pilot", "senderName": prof.alert_format.get("sender_name", "NadiSaathi"),
            "note": "Pilot decision-support draft; complements and never replaces official DHM/CWC/IMD/NDMA warnings.",
            "severity": _severity_for(level if level != "normal" else "watch"), "urgency": "Expected", "certainty": "Likely",
            "responseType": "Prepare", "status": "Exercise" if run_id else "Actual",
            "lat": node.lat, "lon": node.lng, "radius_m": 5000.0,
            "language": lang_codes[0] if lang_codes else "en-US",
            "headline": payload["messages"][0]["text"][:150], "description": payload["messages"][0]["text"],
            "instruction": "Move people, animals and documents to high ground. Follow official instructions.",
            "areaDesc": payload["recipients"] or first["name"], "site_id": first["node_id"], "geocode_name": "basin-node",
            "extra_infos": [{"language": lang_codes[i], "headline": msg["text"][:150], "description": msg["text"],
                             "instruction": msg["text"], "areaDesc": payload["recipients"] or first["name"]}
                            for i, msg in enumerate(payload["messages"][1:], start=1) if i < len(lang_codes)],
        }
        payload["cap_xml"] = build_cap_xml(cap_event)
        cross = first["crosses_border"]
        ap, created = upsert_approval(
            session, dedupe_key=f"{ctx.basin.id}:{ctx.node.id}:{region_id}:{role}:{admin_unit}",
            action="cross_border_notify" if cross else "publish_cap", site_id=ctx.site.id, region_id=region_id, role=role,
            level="warning" if level in {"warning", "danger"} else "watch",
            title=f"{ctx.basin.name.split(' / ')[0]} rise at {ctx.node.name}: {first['name']} in ~{first['eta_h']['min']:.0f}-{first['eta_h']['max']:.0f} h",
            rationale=(f"Upstream camera at {ctx.node.name} ({ctx.node.country}) measures {f_stage:.2f} m rising {rate:+.2f} m/h. "
                       f"Travel-time band along the river graph: " + "; ".join(f"{i['name']} {i['eta_h']['min']:.1f}-{i['eta_h']['max']:.1f} h" for i in items)
                       + (" (estimate: distance / wave celerity)" if first["estimated"] else "")),
            payload=payload, evidence=evidence, trace_id=tr.trace_id, scenario_run_id=run_id,
        )
        tr.step("approval", "draft_alert", input={"kind": "downstream", "region": region_id, "role": role, "admin_unit": admin_unit},
                output={"approval_id": ap.id, "created": created, "cross_border": cross, "eta_h": first["eta_h"],
                        "langs": [m["lang"] for m in payload["messages"]]})
        if created:
            tr.say(f"{'cross-border ' if cross else ''}alert drafted for {role_label(role)}, {admin_unit}: {first['name']} in {first['eta_h']['min']:.0f}-{first['eta_h']['max']:.0f} h")
            cloud.notify_operators(f"NadiSaathi approval needed: {ap.title}", ap.rationale)
            tr.step("tool", "start_escalation_timer", input={"approval_id": ap.id, "wait_s": 900},
                    output=cloud.start_escalation(ap.id, ap.title), model="aws-step-functions")


def _draft_all_clear(session, tr: Trace, ctx: SiteContext, profile, f_stage, rate, evidence, run_id) -> None:
    place = ctx.node.name if ctx.node else ctx.site.name
    facts = {"river": ctx.basin.name if ctx.basin else "", "place": place, "stage_m": f_stage, "rate_m_per_h": rate,
             "sender": messages.SENDER.get(ctx.region_id, "-NadiSaathi")}
    payload = _lang_payload(profile, "all_clear", facts)
    ap, _ = upsert_approval(session, dedupe_key=f"{ctx.site.id}:all_clear", action="all_clear", site_id=ctx.site.id,
                            region_id=ctx.region_id, role=_approver(profile, "all_clear"), level="normal",
                            title=f"{place}: water falling ({f_stage:.2f} m) — propose update/all-clear",
                            rationale="Falling for several cycles after a peak above the warning level. A human decides.",
                            payload=payload, evidence=evidence, trace_id=tr.trace_id, scenario_run_id=run_id)
    # Earlier rise drafts that were never approved are superseded by the all-clear proposal.
    for old in session.exec(select(ApprovalRequest).where(ApprovalRequest.site_id == ctx.site.id)
                            .where(ApprovalRequest.status == "pending").where(ApprovalRequest.action.in_(["send_sms", "cross_border_notify", "publish_cap"]))).all():
        old.status = "superseded"
        session.add(old)
    tr.step("approval", "draft_alert", input={"kind": "all_clear"}, output={"approval_id": ap.id})


def _finish(session: Session, tr: Trace, state: AgentSiteState, md: dict, filt: dict | None, run_id: str | None, ctx: SiteContext) -> dict:
    state.updated_at = datetime.utcnow()
    tr.step("plan", "next_capture", output={"cadence_s": state.cadence_s, "burst_frames": state.burst_frames, "mode": state.mode})
    session.add(state)
    row = AgentTrace(trace_id=tr.trace_id, site_id=tr.site_id, cycle=tr.cycle, started_at=tr.at,
                     branches=json.dumps(tr.branches), summary="; ".join(tr.summary_parts),
                     measurement_json=json.dumps(tr.measurement, ensure_ascii=False),
                     steps_json=json.dumps(tr.steps, ensure_ascii=False, default=str), scenario_run_id=run_id)
    session.add(row)
    session.commit()
    pending = len(session.exec(select(ApprovalRequest.id).where(ApprovalRequest.status == "pending")).all())
    cloud.put_metrics({"AgentCycles": 1, "FramesMeasured": md.get("frames", 1),
                       "StageMs": float(md.get("timings_ms", {}).get("total", 0.0)), "ApprovalsPending": pending})
    cloudlog.emit_cycle(cloudlog.cycle_event(row, md, tr.steps, state.cadence_s, state.mode))
    return trace_to_api(row)


def trace_to_api(row: AgentTrace, full: bool = True) -> dict:
    base = {"trace_id": row.trace_id, "site_id": row.site_id, "cycle": row.cycle,
            "started_at": row.started_at.isoformat() + "Z", "branches": json.loads(row.branches),
            "summary": row.summary, "scenario_run_id": row.scenario_run_id}
    steps = json.loads(row.steps_json)
    if not full:
        base["steps"] = len(steps)
        return base
    base["measurement"] = json.loads(row.measurement_json)
    base["steps"] = steps
    return base
