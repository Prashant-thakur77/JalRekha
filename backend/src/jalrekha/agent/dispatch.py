"""Human decisions on approvals, and what happens after an approve.

Nothing public leaves the system without a person's approval. On approve,
the channels run in order: SMS (SNS, verified test numbers only in the
pilot), voice (the Polly/espeak audio drafted with the alert), CAP (written to
the local CAP feed and, in the cloud, to S3). Each channel reports its own
status, which is stored on the approval and shown in the inbox.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from jalrekha.agent import cloud, messages
from jalrekha.agent.models import ApprovalRequest, ReliefRequest, RouteStatus
from jalrekha.regions import role_label
from jalrekha.services.storage import get_upload_dir


def operator_pin() -> str | None:
    """Shared PIN. Local development defaults to 2468; with JALREKHA_PROTECT_WRITES=1 (cloud)
    there is no default: without a configured PIN no shared PIN is accepted (fail closed)."""
    pin = os.environ.get("JALREKHA_OPERATOR_PIN")
    if pin:
        return pin
    return None if os.environ.get("JALREKHA_PROTECT_WRITES") == "1" else "2468"


_FAILS: dict[str, list[float]] = {}
LOCKOUT_FAILS = 5
LOCKOUT_WINDOW_S = 600


GLOBAL_LOCKOUT_FAILS = 30  # across all clients: a rotating-address guesser is stopped too


def locked_out(client: str) -> bool:
    import time

    now = time.time()
    recent = [t for t in _FAILS.get(client, []) if now - t < LOCKOUT_WINDOW_S]
    _FAILS[client] = recent
    total = sum(1 for ts in _FAILS.values() for t in ts if now - t < LOCKOUT_WINDOW_S)
    return len(recent) >= LOCKOUT_FAILS or total >= GLOBAL_LOCKOUT_FAILS


def operator_pins() -> dict[str, str]:
    """Per-operator PINs from JALREKHA_OPERATOR_PINS="Name A:1234,Name B:5678" (SSM in the cloud).
    The single shared JALREKHA_OPERATOR_PIN still works and is recorded as "operator (shared PIN)"."""
    out: dict[str, str] = {}
    for item in os.environ.get("JALREKHA_OPERATOR_PINS", "").split(","):
        if ":" in item:
            name, pin = item.rsplit(":", 1)
            if name.strip() and pin.strip():
                out[pin.strip()] = name.strip()[:80]
    return out


def pin_identity(pin: str | None) -> str | None:
    """Which operator a PIN belongs to (constant-time comparisons), or None."""
    if pin is None:
        return None
    who = None
    for known, name in operator_pins().items():
        if hmac.compare_digest(str(pin), known):
            who = name
    shared = operator_pin()
    if who is None and shared and hmac.compare_digest(str(pin), shared):
        who = "operator (shared PIN)"
    return who


def check_pin(pin: str | None, client: str = "local") -> bool:
    """5 wrong PINs from one client in 10 minutes lock it out."""
    import time

    ok = pin_identity(pin) is not None
    if not ok:
        _FAILS.setdefault(client, []).append(time.time())
    return ok


def camera_key_ok(key: str | None) -> bool:
    expected = os.environ.get("NADISAATHI_CAMERA_KEY")
    if not expected:
        return True  # local development: no key configured
    return key is not None and hmac.compare_digest(str(key), expected)


def approval_to_api(ap: ApprovalRequest) -> dict[str, Any]:
    return {
        "id": ap.id, "created_at": ap.created_at.isoformat() + "Z", "updated_at": ap.updated_at.isoformat() + "Z",
        "status": ap.status, "action": ap.action, "site_id": ap.site_id, "region_id": ap.region_id, "role": ap.role, "role_label": role_label(ap.role),
        "level": ap.level, "title": ap.title, "rationale": ap.rationale, "trace_id": ap.trace_id,
        "scenario_run_id": ap.scenario_run_id,
        "payload": json.loads(ap.payload_json or "{}"), "evidence": json.loads(ap.evidence_json or "[]"),
        "decided_by": ap.decided_by, "decided_at": ap.decided_at.isoformat() + "Z" if ap.decided_at else None,
        "decision_note": ap.decision_note, "dispatch": json.loads(ap.dispatch_json) if ap.dispatch_json else None,
    }


def decide(session: Session, ap: ApprovalRequest, decision: str, operator: str, note: str | None,
           edited: list[dict[str, str]] | None) -> ApprovalRequest:
    if ap.status != "pending":
        raise ValueError(f"approval {ap.id} is already {ap.status}")
    payload = json.loads(ap.payload_json or "{}")
    if edited:
        by_lang = {e["lang"]: e["text"].strip() for e in edited if e.get("text")}
        for msg in payload.get("messages", []):
            if msg["lang"] in by_lang and by_lang[msg["lang"]] != msg["text"]:
                msg["original_text"] = msg["text"]
                msg["text"] = by_lang[msg["lang"]][:400]
                seg = messages.sms_segments(msg["text"])
                msg.update(chars=len(msg["text"]), segments=seg["segments"], encoding=seg["encoding"], edited_by_human=True)
        ap.payload_json = json.dumps(payload, ensure_ascii=False)
    ap.decided_by = (operator or "operator")[:80]
    ap.decided_at = datetime.utcnow()
    ap.decision_note = (note or "")[:500] or None
    ap.updated_at = datetime.utcnow()
    if decision == "reject":
        ap.status = "rejected"
        ap.dispatch_json = json.dumps({"status": "not sent (rejected by a human)"})
    else:
        ap.status = "approved"
        ap.dispatch_json = json.dumps(_dispatch(session, ap, payload), ensure_ascii=False)
    session.add(ap)
    session.commit()
    session.refresh(ap)
    return ap


def _dispatch(session: Session, ap: ApprovalRequest, payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"at": datetime.utcnow().isoformat() + "Z", "channels": []}
    msgs = payload.get("messages") or []
    if ap.action in {"send_sms", "cross_border_notify", "publish_cap", "all_clear"} and msgs:
        # One SMS per language; recipients are verified test numbers in the pilot.
        for msg in msgs:
            res = cloud.send_sms(msg["text"])
            out["channels"].append({**res, "lang": msg["lang"], "segments": msg.get("segments")})
        audio = [a for a in payload.get("audio") or [] if a.get("url")]
        out["channels"].append({"channel": "voice", "status": "ready" if audio else "unavailable",
                                "files": [a["url"] for a in audio],
                                "note": "IVR/voice-call integration is a deployment step; audio files are generated per language"})
    if payload.get("cap_xml"):
        cap_dir = get_upload_dir() / "cap"
        cap_dir.mkdir(parents=True, exist_ok=True)
        name = f"approval-{ap.id}-{hashlib.sha1(payload['cap_xml'].encode()).hexdigest()[:8]}.xml"
        (cap_dir / name).write_text(payload["cap_xml"], encoding="utf-8")
        s3 = cloud.client("s3")
        bucket = os.environ.get("NADISAATHI_S3_BUCKET")
        status = "written to local CAP feed"
        if s3 is not None and bucket:
            try:
                s3.put_object(Bucket=bucket, Key=f"cap/{name}", Body=payload["cap_xml"].encode(), ContentType="application/xml")
                status += f" + s3://{bucket}/cap/{name}"
            except Exception as exc:
                status += f" (S3 failed: {type(exc).__name__})"
        out["channels"].append({"channel": "cap", "status": status, "url": f"/uploads/cap/{name}"})
    if ap.action == "publish_route_status":
        rid = payload.get("route_id")
        route = session.get(RouteStatus, rid) if rid else None
        if route is not None:
            route.status, route.verified, route.source = payload.get("status", route.status), True, f"approval #{ap.id}"
            route.updated_at = datetime.utcnow()
            session.add(route)
            out["channels"].append({"channel": "route_board", "status": f"{route.name} marked {route.status} (verified)"})
    if ap.action == "dispatch_relief":
        rr = session.get(ReliefRequest, payload.get("relief_id")) if payload.get("relief_id") else None
        if rr is not None:
            rr.status, rr.team, rr.decided_by, rr.decided_at = "dispatched", payload.get("team"), ap.decided_by, datetime.utcnow()
            session.add(rr)
            out["channels"].append({"channel": "relief", "status": f"request #{rr.id} dispatched"})
    if ap.action in {"recalibrate", "review_reading"}:
        out["channels"].append({"channel": "field", "status": "acknowledged; field check scheduled by the operator"})
    out["channels"].append(cloud.notify_operators(f"NadiSaathi: {ap.action} approved", ap.title))
    return out


def list_approvals(session: Session, status: str | None) -> list[ApprovalRequest]:
    q = select(ApprovalRequest)
    if status and status != "all":
        q = q.where(ApprovalRequest.status == status)
    return list(session.exec(q.order_by(ApprovalRequest.updated_at.desc())).all())
