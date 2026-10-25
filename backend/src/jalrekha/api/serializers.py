from __future__ import annotations

import json
from typing import Any

from jalrekha.models.domain import HydrometSnapshot, NodeObservation, Site
from jalrekha.schemas.api import ExternalSnapshotResponse
from jalrekha.services.storage import public_asset_url_for_path


def site_payload(site: Site) -> dict[str, Any]:
    payload = site.model_dump()
    payload["sample_video_url"] = public_asset_url_for_path(site.sample_video_path)
    payload["sample_frame_url"] = public_asset_url_for_path(site.sample_frame_path)
    return payload


def parse_json_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def parse_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def publicize_artifact_refs(refs: dict[str, Any]) -> dict[str, Any]:
    payload = dict(refs)
    for key in ("manifest_path", "evidence_frame_path"):
        if isinstance(payload.get(key), str):
            payload[f"{key.removesuffix('_path')}_url"] = public_asset_url_for_path(payload[key])
    if isinstance(payload.get("selected_frame_paths"), list):
        payload["selected_frame_urls"] = [
            public_asset_url_for_path(str(path))
            for path in payload["selected_frame_paths"]
            if isinstance(path, str)
        ]
    return payload


def serialize_observation(observation: NodeObservation) -> dict[str, Any]:
    payload = observation.model_dump(mode="json")
    payload["evidence_frame_url"] = public_asset_url_for_path(observation.evidence_frame_path)
    payload["artifact_id"] = observation.assessment_artifact_id
    payload["runner"] = {
        "name": observation.runner_name,
        "mode": observation.runner_mode,
    }
    payload["reasoning_steps"] = parse_json_list(observation.reasoning_steps)
    payload["critical_evidence"] = parse_json_object(observation.critical_evidence)
    payload["artifact_refs"] = publicize_artifact_refs(parse_json_object(observation.artifact_refs))
    return payload


def serialize_external_snapshot(snapshot: HydrometSnapshot) -> ExternalSnapshotResponse:
    return ExternalSnapshotResponse(
        site_id=snapshot.site_id,
        signal_score=snapshot.signal_score,
        summary=snapshot.summary,
        precipitation_mm=snapshot.precipitation_mm,
        precipitation_probability=snapshot.precipitation_probability,
        river_discharge=snapshot.river_discharge,
        river_discharge_max=snapshot.river_discharge_max,
        river_discharge_trend=snapshot.river_discharge_trend,
    )

