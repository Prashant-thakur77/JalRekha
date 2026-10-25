from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from jalrekha.agent import cloudlog
from jalrekha.api.routers import cloud_ops
from jalrekha.main import app


def test_cloud_views_are_cloud_only_and_queries_are_fixed():
    c = TestClient(app)
    assert c.get("/api/cloud/logs").status_code == 503  # AWS is off in tests
    ids = {q["id"] for q in c.get("/api/cloud/insights").json()}
    assert {"opencv_stages", "decisions", "second_opinion"} <= ids
    assert c.get("/api/cloud/insights/drop-table").status_code == 404


def test_account_ids_are_scrubbed():
    out = cloud_ops._scrub({"arn": "arn:aws:states:us-east-1:123456789012:stateMachine:x", "n": [123456789012], "t": "1234567890123"})
    assert "123456789012" not in json.dumps(out["arn"]) and out["t"] == "1234567890123"


def test_cycle_event_carries_opencv_timings_and_no_secrets():
    row = SimpleNamespace(trace_id="tr_x", site_id="s", cycle=3, scenario_run_id=None, started_at=datetime(2026, 10, 25, 12),
                          branches='["D3"]', summary="second opinion agrees: 4.10 m")
    md = {"reading": {"stage_m": 4.1, "sigma_m": 0.03, "per_estimator_m": {"E1_edge": 4.09}}, "usable": True,
          "quality": {"ok": True, "reasons": []}, "registration": {"method": "orb", "inliers": 88}, "frames": 5,
          "timings_ms": {"register": 12.3456, "total": 80.1}}
    steps = [{"tool": "verify_with_vlm", "kind": "tool", "model": "claude:claude-opus-5-5", "latency_ms": 3000, "cost_usd_est": 0.008}]
    ev = cloudlog.cycle_event(row, md, steps, 300, "watch")
    assert ev["ms"]["register"] == 12.35 and ev["branches"] == ["D3"] and ev["second_opinion"]["model"].startswith("claude")
    assert cloudlog.archive_prefix(ev) == "cycles/s/2026-10-25/tr_x"
    cloudlog.emit_cycle(ev)  # disabled without AWS: must be a no-op
    assert cloudlog.flush() == 0
