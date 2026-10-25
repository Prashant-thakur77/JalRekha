"""NadiSaathi tools over MCP, so another agent (Claude Code, Claude Desktop, any MCP client) can
watch the river, run the camera agent and read its evidence.

It talks to a running NadiSaathi over HTTP, by default the AWS deployment. Every tool is read-only
or starts a replay; none approves, edits or sends an alert. Public alerts stay with a named person
and a PIN in the app, by design.

    cd backend && uv run python -m jalrekha.mcp_server            # stdio
    NADISAATHI_API=http://127.0.0.1:8000/api uv run python -m jalrekha.mcp_server
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

API = os.environ.get("NADISAATHI_API", "https://gaq7chhmb2.execute-api.us-east-1.amazonaws.com/api").rstrip("/")
READ = ToolAnnotations(read_only_hint=True, open_world_hint=True)
logging.getLogger("httpx").setLevel(logging.WARNING)

server = MCPServer(
    name="nadisaathi",
    title="NadiSaathi river camera agent",
    instructions=(
        "NadiSaathi measures river stage in metres from staff-gauge cameras with OpenCV 5 and runs an agent that "
        "decides what to check next and drafts flood alerts for towns downstream (Nepal to India). Use river_status "
        "for the current reading, downstream_eta for arrival windows, explain_reading to see what OpenCV did in a "
        "cycle, and pending_alerts to see drafts waiting for a person. You cannot approve or send alerts: a named "
        "operator does that with a PIN in the app."
    ),
)


def _get(path: str, **params: Any) -> Any:
    r = httpx.get(f"{API}{path}", params={k: v for k, v in params.items() if v is not None}, timeout=30)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict[str, Any]) -> Any:
    r = httpx.post(f"{API}{path}", json=body, timeout=30)
    r.raise_for_status()
    return r.json()


@server.tool(annotations=READ)
def list_sites() -> list[dict[str, Any]]:
    """Camera sites the agent watches, with their latest stage, mode and capture cadence."""
    return [{k: s.get(k) for k in ("site_id", "basin", "node_id", "region_id", "mode", "cadence_s", "last_stage_m", "last_sigma_m",
                                   "last_rate_m_per_h", "last_quality", "siren_active", "updated_at")} for s in _get("/agent/state")]


@server.tool(annotations=READ)
def river_status(site_id: str = "koshi-chatara-cam") -> dict[str, Any]:
    """Latest OpenCV reading at a camera: stage (m) with its error, rise rate, warning and danger levels, image quality."""
    d = _get(f"/sites/{site_id}/live", limit=24)
    latest = d.get("latest") or {}
    return {
        "site": d.get("site"), "warning_m": d.get("warning_m"), "danger_m": d.get("danger_m"),
        "stage_m": latest.get("stage_m"), "sigma_m": latest.get("sigma_m"), "rate_m_per_h": latest.get("rate_m_per_h"),
        "quality_ok": latest.get("quality_ok"), "usable": latest.get("usable"), "estimators": latest.get("estimators"),
        "measured_at": latest.get("at"), "trace_id": latest.get("trace_id"), "agent": d.get("agent"),
        "recent": [{"t": p["t"], "stage_m": p["stage_m"], "usable": p["usable"]} for p in d.get("series", [])[-12:]],
    }


@server.tool(annotations=READ)
def downstream_eta(basin: str = "koshi", from_node: str = "chatara", rate_m_per_h: float | None = None) -> dict[str, Any]:
    """Arrival-time bands (hours, min-max) from an upstream point to each town downstream on the river graph."""
    d = _get(f"/rivers/{basin}/eta", from_node=from_node, rate_m_per_h=rate_m_per_h)
    return {"basin": basin, "from": from_node, "downstream": [
        {k: n.get(k) for k in ("node_id", "name", "country", "admin_unit", "crosses_border", "eta_h", "estimated")}
        for n in d.get("downstream", [])]}


@server.tool(annotations=READ)
def explain_reading(trace_id: str | None = None, site_id: str = "koshi-chatara-cam") -> dict[str, Any]:
    """What OpenCV did in one agent cycle: quality checks, registration, each waterline estimator, fusion and stage
    timings on the host. Leave trace_id empty for the site's latest cycle. Images are left out."""
    d = _get(f"/vision/lab/{trace_id}") if trace_id else _get("/vision/lab/latest", site_id=site_id)
    reg = d.get("registration") or {}
    prof = d.get("profiles") or {}
    return {
        "trace_id": (d.get("trace") or {}).get("trace_id"), "summary": {k: v for k, v in (d.get("summary") or {}).items() if "image" not in k},
        "quality": [{k: m.get(k) for k in ("key", "value", "threshold", "pass")} for m in (d.get("quality") or {}).get("metrics", [])],
        "registration": {k: reg.get(k) for k in ("method", "inliers", "residual_px", "drift_px", "ms", "tried")},
        "estimators": [{k: e.get(k) for k in ("name", "stage_m", "confidence", "separation", "used", "weight")} for e in prof.get("estimators", [])],
        "fusion": {k: v for k, v in (d.get("fusion") or {}).items() if k != "per_estimator_m"},
        "timing_ms": {s["name"]: s["ms"] for s in (d.get("timing") or {}).get("stages", [])},
        "host": {k: v for k, v in ((d.get("timing") or {}).get("host") or {}).items() if k in ("machine", "opencv", "cpu_count", "kleidicv")},
        "check": d.get("check"),
    }


@server.tool(annotations=READ)
def agent_trace(trace_id: str) -> dict[str, Any]:
    """One agent cycle step by step: the measurement, each decision branch (D1-D9) with before/after, tools called."""
    d = _get(f"/agent/traces/{trace_id}")
    return {"trace_id": d.get("trace_id"), "site_id": d.get("site_id"), "cycle": d.get("cycle"), "branches": d.get("branches"),
            "summary": d.get("summary"),
            "steps": [{k: s.get(k) for k in ("kind", "tool", "decision", "model", "latency_ms", "cost_usd_est")} for s in d.get("steps", [])]}


@server.tool(annotations=READ)
def pending_alerts() -> list[dict[str, Any]]:
    """Alert drafts waiting for a person to approve: what, for whom, why, and the evidence behind it."""
    return [{k: a.get(k) for k in ("id", "action", "role_label", "region_id", "title", "rationale", "created_at", "evidence")}
            for a in _get("/approvals", status="pending")[:20]]


@server.tool(annotations=READ)
def situation_report(region_id: str = "in") -> dict[str, Any]:
    """Short situation summary for a region ("in" India, "np" Nepal), with every number checked against the tools."""
    d = _get(f"/sitrep/{region_id}")
    return {k: d.get(k) for k in ("region_id", "text", "model", "fallback_used", "guard", "generated_at")}


@server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True))
def run_replay(scenario_id: str = "koshi-to-peak") -> dict[str, Any]:
    """Start a flood replay so the agent runs on a camera (scenarios: koshi-to-peak, koshi-night-rise,
    karnali-quiet-storm, bagmati-camera-moved, hancock-real-flood). Drafts it creates still need a person."""
    d = _post(f"/scenarios/{scenario_id}/run", {"speed": 10})
    return {k: d.get(k) for k in ("run_id", "scenario_id", "status", "site_id", "label")}


@server.tool(annotations=READ)
def replay_status(run_id: str) -> dict[str, Any]:
    """Progress of a replay started with run_replay: status, cycles done, approvals drafted."""
    d = _get(f"/scenarios/runs/{run_id}")
    return {k: d.get(k) for k in ("run_id", "scenario_id", "status", "step", "total", "approval_ids", "error")}


@server.tool(annotations=READ)
def cloud_insights(query_id: str = "opencv_stages") -> dict[str, Any]:
    """Fixed CloudWatch Logs Insights queries over the agent-cycle log on AWS (opencv_stages, decisions,
    registration, second_opinion, quality)."""
    d = _get(f"/cloud/insights/{query_id}")
    return {k: d.get(k) for k in ("title", "status", "rows", "records_matched", "ran_at")}


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
