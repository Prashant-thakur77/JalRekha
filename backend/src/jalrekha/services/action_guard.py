from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError

from jalrekha.schemas.tools import TOOL_MODELS


_LOGGER = logging.getLogger(__name__)
_RATE_BUCKETS: dict[tuple[str, str], deque[datetime]] = defaultdict(deque)
ARGENTINA_BOUNDS = {"min_lon": -73.6, "max_lon": -53.6, "min_lat": -55.2, "max_lat": -21.7}
SEVERITY_RANK = {"info": 0, "minor": 1, "moderate": 2, "severe": 3}


@dataclass(frozen=True)
class GuardResult:
    accepted: bool
    tool_name: str | None
    arguments: dict[str, Any]
    reason: str
    needs_human: bool = False


def _iter_pairs(coords: Any):
    if isinstance(coords, (list, tuple)) and coords and isinstance(coords[0], (int, float)):
        yield float(coords[0]), float(coords[1])
    elif isinstance(coords, (list, tuple)):
        for item in coords:
            yield from _iter_pairs(item)


def _inside_operational_area(area: Any, bounds: dict[str, float] | None = None) -> bool:
    b = bounds or ARGENTINA_BOUNDS
    for lon, lat in _iter_pairs(area.get("coordinates")):
        if not (
            b["min_lon"] <= lon <= b["max_lon"]
            and b["min_lat"] <= lat <= b["max_lat"]
        ):
            return False
    return True


def _rate_limited(zone_id: str, tool_name: str, now: datetime, *, max_per_hour: int = 6) -> bool:
    bucket = _RATE_BUCKETS[(zone_id, tool_name)]
    cutoff = now - timedelta(hours=1)
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= max_per_hour:
        return True
    bucket.append(now)
    return False


def validate_tool_call(
    call: dict[str, Any],
    *,
    evidence: dict[str, Any] | None = None,
    now: datetime | None = None,
    bounds: dict[str, float] | None = None,
) -> GuardResult:
    """``bounds`` comes from the region profile; it defaults to the original Argentina box."""
    now = now or datetime.utcnow()
    evidence = evidence or {}
    name = call.get("name")
    args = call.get("arguments") or {}
    if name not in TOOL_MODELS or not isinstance(args, dict):
        _LOGGER.warning("tool rejected: unknown_or_malformed name=%s", name)
        return GuardResult(False, name if isinstance(name, str) else None, {}, "unknown_or_malformed", True)

    try:
        parsed = TOOL_MODELS[name].model_validate(args).model_dump()
    except ValidationError as exc:
        _LOGGER.warning("tool rejected: schema_validation_failed name=%s errors=%s", name, exc.errors())
        return GuardResult(False, name, {}, "schema_validation_failed", True)

    requested_rank = SEVERITY_RANK.get(str(parsed.get("severity")), 0)
    evidence_rank = SEVERITY_RANK.get(str(evidence.get("max_allowed_severity", "info")), 0)
    if requested_rank > evidence_rank:
        _LOGGER.warning("tool rejected: severity_exceeds_evidence name=%s", name)
        return GuardResult(False, name, parsed, "severity_exceeds_evidence", True)

    if name == "emit_cap" and not _inside_operational_area(parsed["area"], bounds):
        _LOGGER.warning("tool rejected: area_outside_operational_bounds")
        return GuardResult(False, name, parsed, "area_outside_operational_bounds", True)

    zone_id = str(parsed.get("zone_id") or evidence.get("zone_id") or parsed.get("node_id") or "default")
    if name in {"trigger_siren", "emit_cap"} and _rate_limited(zone_id, name, now):
        _LOGGER.warning("tool rejected: rate_limited zone=%s name=%s", zone_id, name)
        return GuardResult(False, name, parsed, "rate_limited", True)

    _LOGGER.info("tool accepted name=%s zone=%s", name, zone_id)
    return GuardResult(True, name, parsed, "accepted")


def guarded_model_action(model_call, prompt: str, *, evidence: dict[str, Any] | None = None, max_retries: int = 2) -> GuardResult:
    current_prompt = prompt
    last = GuardResult(False, None, {}, "no_model_call", True)
    for _attempt in range(max_retries + 1):
        raw_call = model_call(current_prompt)
        last = validate_tool_call(raw_call, evidence=evidence)
        if last.accepted:
            return last
        current_prompt = f"{prompt}\nReturn only a valid allowed tool call grounded in evidence. Previous rejection: {last.reason}"
    return GuardResult(False, last.tool_name, last.arguments, "max_retries_exceeded", True)
