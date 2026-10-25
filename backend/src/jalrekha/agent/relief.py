"""Relief requests after the warning: parse, de-duplicate, prioritise, route for approval.

Rules-first parsing in English, Hindi, Nepali, Maithili and Bhojpuri (all
Devanagari languages share most flood vocabulary). Requests keep minimal
personal data: no names, phone numbers are never stored, only the text, a
coarse location and the parsed fields.
"""

from __future__ import annotations

import difflib
import json
import math
import re
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from jalrekha.agent.models import ApprovalRequest, ReliefRequest
from jalrekha.regions import region_for_point
from jalrekha.regions.profile import haversine_km

NEED_WORDS: dict[str, list[str]] = {
    "rescue": ["rescue", "trapped", "stuck", "roof", "boat", "drown", "save us", "बचाओ", "बचाव", "फँसे", "फंसे", "फसे", "छत", "नाव", "डूब", "उद्धार", "बचाउनुहोस्", "फसेका", "डुङ्गा", "बचाउ", "डुबल", "फँसल", "बचावऽ"],
    "medical": ["medical", "medicine", "injured", "doctor", "pregnant", "sick", "snake", "दवा", "दवाई", "घायल", "डॉक्टर", "डाक्टर", "गर्भवती", "बीमार", "बिरामी", "औषधि", "सर्पदंश", "साँप", "सांप", "बेमार", "दबाई"],
    "water": ["drinking water", "clean water", "water bottle", "पीने का पानी", "पीने के पानी", "पिउने पानी", "खानेपानी", "पिए के पानी", "पीबाक पानि", "पीने लायक"],
    "food": ["food", "ration", "rice", "hungry", "milk", "खाना", "भोजन", "राशन", "खाद्य", "भूखे", "भोक", "चामल", "चावल", "दूध", "खाए", "खाइक", "दाल"],
    "shelter": ["shelter", "tent", "tarpaulin", "house collapsed", "आश्रय", "शरण", "तिरपाल", "टेंट", "घर गिर", "घर ढह", "बास", "पाल", "घर भत्कियो"],
}
NEED_WEIGHT = {"rescue": 1.0, "medical": 0.85, "water": 0.6, "shelter": 0.55, "food": 0.5, "other": 0.3}
CRITICAL_WORDS = ["urgent", "emergency", "now", "immediately", "dying", "तुरंत", "तुरन्त", "तुरुन्त", "जल्दी", "छिटो", "आपात", "अभी", "मर", "बहुत खतरा", "झट"]
VULNERABLE_WORDS = ["child", "children", "baby", "elderly", "old", "pregnant", "disabled", "बच्चे", "बच्चा", "बालबालिका", "शिशु", "बुजुर्ग", "बूढ़े", "वृद्ध", "गर्भवती", "अपाङ्ग", "विकलांग", "बच्चा सब", "बुढ़", "बूढ़"]
PEOPLE_WORDS = r"(people|persons|person|ppl|log|लोग|लोक|जना|व्यक्ति|आदमी|सदस्य|मानिस|गोटे|प्राणी)"
FAMILY_WORDS = r"(families|family|परिवार|घर|घरपरिवार)"
DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
URGENCY_W = {"critical": 1.0, "high": 0.8, "medium": 0.55, "low": 0.35}


def parse(text: str) -> dict[str, Any]:
    t = (text or "").translate(DEVA_DIGITS)
    low = t.lower()
    scores = {need: sum(1 for w in words if w in low) for need, words in NEED_WORDS.items()}
    need = max(scores, key=lambda k: (scores[k], NEED_WEIGHT[k])) if any(scores.values()) else "other"
    people = None
    m = re.search(r"(\d{1,4})\s*" + PEOPLE_WORDS, low)
    if m:
        people = int(m.group(1))
    else:
        f = re.search(r"(\d{1,3})\s*" + FAMILY_WORDS, low)
        if f:
            people = int(f.group(1)) * 5  # assumption: 5 people per household, labelled in the response
        else:
            n = re.search(r"\b(\d{1,3})\b", low)
            people = int(n.group(1)) if n and int(n.group(1)) < 500 else None
    vulnerable = any(w in low for w in VULNERABLE_WORDS)
    critical = any(w in low for w in CRITICAL_WORDS)
    if need == "rescue" and (critical or vulnerable):
        urgency = "critical"
    elif need in {"rescue", "medical"} or critical:
        urgency = "high"
    elif need in {"water", "food", "shelter"}:
        urgency = "medium"
    else:
        urgency = "low"
    priority = NEED_WEIGHT[need] * URGENCY_W[urgency] * (1 + math.log2(1 + (people or 1)) / 6) + (0.15 if vulnerable else 0.0)
    return {"need": need, "people": people, "urgency": urgency, "vulnerable": vulnerable,
            "priority": round(min(priority, 1.5), 3), "household_assumption": bool(people and not m and re.search(FAMILY_WORDS, low))}


def find_duplicate(session: Session, rr: ReliefRequest, window_h: float = 3.0) -> ReliefRequest | None:
    since = rr.created_at - timedelta(hours=window_h)
    candidates = session.exec(
        select(ReliefRequest).where(ReliefRequest.created_at >= since).where(ReliefRequest.need == rr.need)
        .where(ReliefRequest.duplicate_of == None).where(ReliefRequest.id != rr.id)  # noqa: E711
        .order_by(ReliefRequest.created_at)
    ).all()
    for c in candidates:
        near = (rr.lat is not None and c.lat is not None and haversine_km(rr.lat, rr.lng, c.lat, c.lng) <= 0.5)
        same_place = near or (rr.site_id and rr.site_id == c.site_id)
        sim = difflib.SequenceMatcher(None, rr.text.lower(), c.text.lower()).ratio()
        if (same_place and sim >= 0.45) or sim >= 0.8:
            return c
    return None


def submit(session: Session, *, text: str, lang: str = "en", lat: float | None = None, lng: float | None = None,
           site_id: str | None = None, channel: str = "app", people: int | None = None) -> ReliefRequest:
    p = parse(text)
    reg = region_for_point(lat, lng) if lat is not None and lng is not None else None
    rr = ReliefRequest(text=text.strip()[:600], lang=lang, channel=channel, need=p["need"], people=people or p["people"],
                       urgency=p["urgency"], priority=p["priority"], lat=None if lat is None else round(lat, 3),
                       lng=None if lng is None else round(lng, 3), site_id=site_id, region_id=reg.id if reg else None)
    session.add(rr)
    session.flush()
    dup = find_duplicate(session, rr)
    if dup is not None:
        rr.duplicate_of = dup.id
        rr.status = "duplicate"
        # A repeat report raises the original's priority a little (more people asking).
        dup.priority = round(min(dup.priority + 0.05, 1.5), 3)
        session.add(dup)
    else:
        role = "ddma_control_room" if rr.region_id == "in" else "ward_focal"
        ap = ApprovalRequest(
            action="dispatch_relief", region_id=rr.region_id or "np", role=role, level="watch", dedupe_key=f"relief:{rr.id}",
            title=f"Relief: {rr.need} for {rr.people or '?'} people ({rr.urgency})",
            rationale=f"Parsed from a {channel} report in {lang}. Priority {rr.priority}. Approve to dispatch a team.",
            payload_json=json.dumps({"relief_id": rr.id, "text": rr.text, "team": None, "messages": []}, ensure_ascii=False),
            evidence_json=json.dumps([{"label": "Parsed need", "value": f"{rr.need}, {rr.people} people, {rr.urgency}", "source": f"relief #{rr.id} (rules parser)"}]),
        )
        session.add(ap)
    session.commit()
    session.refresh(rr)
    return rr


def to_api(rr: ReliefRequest) -> dict[str, Any]:
    return {"id": rr.id, "created_at": rr.created_at.isoformat() + "Z", "text": rr.text, "lang": rr.lang, "channel": rr.channel,
            "need": rr.need, "people": rr.people, "urgency": rr.urgency, "priority": rr.priority, "lat": rr.lat, "lng": rr.lng,
            "site_id": rr.site_id, "region_id": rr.region_id, "duplicate_of": rr.duplicate_of, "status": rr.status,
            "parsed_by": rr.parsed_by, "team": rr.team}


def seed_board(session: Session) -> None:
    """Illustrative route/shelter rows (labelled as such) so the board is not empty in a fresh deploy."""
    from jalrekha.agent.models import RouteStatus, Shelter

    if session.exec(select(RouteStatus)).first() is None:
        for rid, name, reg, lat, lng in [
            ("rt-koshi-east-embankment", "Koshi east embankment road (Supaul)", "in", 26.35, 86.95),
            ("rt-nh27-kosi-bridge", "East-West Highway approach, Kosi bridge (Supaul)", "in", 26.32, 86.83),
            ("rt-chatara-barahachhetra", "Chatara-Barahachhetra road (Sunsari)", "np", 26.83, 87.15),
            ("rt-saptari-hanumannagar", "Hanumannagar road near the barrage (Saptari)", "np", 26.54, 86.94),
        ]:
            session.add(RouteStatus(id=rid, name=name, region_id=reg, lat=lat, lng=lng, status="unknown", source="illustrative seed"))
    if session.exec(select(Shelter)).first() is None:
        for sid, name, reg, unit, lat, lng, cap in [
            ("sh-supaul-highschool", "Government high school (illustrative)", "in", "Supaul", 26.12, 86.60, 400),
            ("sh-saharsa-community-hall", "Community hall (illustrative)", "in", "Saharsa", 25.88, 86.60, 250),
            ("sh-sunsari-ward-office", "Ward office and school (illustrative)", "np", "Sunsari", 26.70, 87.15, 180),
            ("sh-saptari-school", "Secondary school on high ground (illustrative)", "np", "Saptari", 26.60, 86.75, 300),
        ]:
            session.add(Shelter(id=sid, name=name, region_id=reg, admin_unit=unit, lat=lat, lng=lng, capacity=cap))
    session.commit()
