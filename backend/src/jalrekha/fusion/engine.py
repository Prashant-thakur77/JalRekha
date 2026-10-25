from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Literal


Severity = Literal["none", "info", "minor", "moderate", "severe"]


@dataclass(frozen=True)
class Signal:
    source_id: str
    observed_at: datetime
    lat: float
    lon: float
    score: float
    severity: Severity = "info"
    summary: str = ""


@dataclass(frozen=True)
class Decision:
    severity: Severity
    score: float
    trigger_source: str
    needs_validation: bool
    rules: list[str] = field(default_factory=list)
    summary: str = ""


def _distance_m(a: Signal, b: Signal) -> float:
    radius = 6371000.0
    d_lat = radians(b.lat - a.lat)
    d_lon = radians(b.lon - a.lon)
    lat1 = radians(a.lat)
    lat2 = radians(b.lat)
    h = sin(d_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(d_lon / 2) ** 2
    return 2 * radius * asin(sqrt(h))


def _rank(severity: Severity) -> int:
    return {"none": 0, "info": 1, "minor": 2, "moderate": 3, "severe": 4}[severity]


def _severity_from_score(score: float) -> Severity:
    if score >= 0.82:
        return "severe"
    if score >= 0.62:
        return "moderate"
    if score >= 0.35:
        return "minor"
    if score > 0:
        return "info"
    return "none"


def fuse(
    node_signals: list[Signal],
    citizen_reports: list[Signal],
    *,
    radius_m: float = 500.0,
    window_minutes: int = 10,
) -> Decision:
    if not node_signals and not citizen_reports:
        return Decision("none", 0.0, "none", False, ["no_evidence"], "Sin evidencia reciente")

    best_node = max(node_signals, key=lambda s: s.score, default=None)
    best_report = max(citizen_reports, key=lambda s: s.score, default=None)
    window = timedelta(minutes=window_minutes)
    matched = False
    if best_node and best_report:
        matched = any(
            abs(node.observed_at - report.observed_at) <= window and _distance_m(node, report) <= radius_m
            for node in node_signals
            for report in citizen_reports
        )

    if matched:
        score = min(1.0, max(best_node.score, best_report.score) + 0.18)
        severity = max((_severity_from_score(score), best_node.severity, best_report.severity), key=_rank)
        return Decision(severity, round(score, 4), "fused", False, ["cross_source_match"], "Nodo y reporte ciudadano coinciden")

    if best_node and not citizen_reports:
        score = min(best_node.score, 0.72)
        severity = _severity_from_score(score)
        if _rank(severity) > _rank("moderate"):
            severity = "moderate"
        return Decision(severity, round(score, 4), "node", False, ["node_only_cap_moderate"], best_node.summary)

    if best_report and not node_signals:
        return Decision("info", round(min(best_report.score, 0.34), 4), "citizen", True, ["citizen_only_needs_validation"], best_report.summary)

    strongest = max([*(node_signals or []), *(citizen_reports or [])], key=lambda s: s.score)
    return Decision("minor", round(min(strongest.score, 0.45), 4), "mixed_unmatched", True, ["sources_unmatched"], strongest.summary)
