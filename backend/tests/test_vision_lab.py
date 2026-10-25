from __future__ import annotations

import base64
import json
from datetime import datetime

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from jalrekha.vision import synth, waterline
from jalrekha.vision.explain import MAX_IMAGE_BYTES, explain
from jalrekha.vision.pipeline import MeasureOptions, measure

SECTIONS = ("summary", "quality", "registration", "strip", "profiles", "fusion", "timing", "privacy")


def _scene(seed: int = 11, frac: float = 0.5, **deg):
    site = synth.make_site(seed)
    frames = synth.render_burst(site, site.gauge_len_m * frac, deg=synth.Degradation(**deg))
    return frames, site.calibration(), synth.reference_frame(site)


def _image_bytes(url: str) -> int:
    assert url.startswith("data:image/jpeg;base64,")
    return len(base64.b64decode(url.split(",", 1)[1]))


def test_explain_synthetic_scene_has_every_stage_and_matches_measure():
    frames, cal, ref = _scene(shake_px=6)
    lab = explain(frames, cal, ref)
    for key in SECTIONS:
        assert key in lab, key

    rows = lab["strip"]["rows"]
    assert rows == cal.extract_strip(frames[-1]).shape[0]
    assert len(lab["profiles"]["axis_m"]) == rows
    # The axis runs top (high stage) to bottom (low stage).
    assert lab["profiles"]["axis_m"][0] > lab["profiles"]["axis_m"][-1]

    plain = measure(frames, cal, ref)
    want = {e.name: e.row for e in plain.estimates}
    got = {e["name"]: e for e in lab["profiles"]["estimators"]}
    assert set(got) == {"E1_edge", "E2_temporal", "E3_colour"}
    for name, est in got.items():
        assert est["row"] == (None if want[name] is None else round(want[name], 2)), name
        assert est["signal"] is not None and len(est["signal"]) == rows, name
    assert lab["fusion"]["fused_m"] == pytest.approx(plain.reading.stage_m, abs=1e-4)
    assert lab["summary"]["stage_m"] == pytest.approx(plain.reading.stage_m, abs=1e-4)

    q = {m["key"]: m for m in lab["quality"]["metrics"]}
    assert set(q) == {"blur_var", "mean_luma", "clipped_frac", "glare_frac", "strip_contrast"}
    assert all(m["pass"] for m in q.values()) == lab["quality"]["ok"]

    reg = lab["registration"]
    assert reg["method"] == "orb" and reg["ok"]
    assert reg["inliers_shown"] == reg["inliers"]
    assert 0 < reg["inliers_drawn"] <= reg["inliers_shown"]

    names = [s["name"] for s in lab["timing"]["stages"]]
    assert names[:3] == ["register", "warp", "quality"] and "redact" in names
    assert lab["timing"]["total_ms"] >= sum(s["ms"] for s in lab["timing"]["stages"]) * 0.99
    host = lab["timing"]["host"]
    assert host["opencv"] == cv2.__version__ and host["machine"] and host["cpu_features"]

    assert lab["privacy"]["images_redacted"] is True
    images = [lab["quality"]["heatmap_image"], reg["matches_image"], reg["compare_image"],
              lab["strip"]["last_image"], lab["strip"]["median_image"], lab["summary"]["overlay_image"]]
    for url in images:
        assert 0 < _image_bytes(url) <= MAX_IMAGE_BYTES
    json.dumps(lab)  # the payload is plain JSON


def test_explain_single_frame_has_no_temporal_profile():
    frames, cal, ref = _scene(seed=12, frac=0.4)
    lab = explain(frames[-1:], cal, ref)
    e2 = next(e for e in lab["profiles"]["estimators"] if e["name"] == "E2_temporal")
    assert e2["row"] is None and e2["signal"] is None
    assert lab["strip"]["frames"] == 1


# ---- the waterline refactor must not change any estimator output -------------------
# Reference copies of the estimators as they were before they could return their profile.
def _old_edge_energy(strip_bgr):
    gray = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2GRAY) if strip_bgr.ndim == 3 else strip_bgr
    bad = waterline._saturated_rows(gray)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    gy = cv2.Scharr(gray, cv2.CV_32F, 0, 1)
    row_energy = waterline._repair_rows(np.abs(gy).mean(axis=1), bad)
    win = max(5, gray.shape[0] // 40)
    prof = np.log1p(waterline._smooth(row_energy, win * 2 + 1).ravel())
    row, sep = waterline.step_fit(prof, expect_upper_higher=+1)
    return row, sep, waterline._confidence(sep, 1.5)


def _old_colour_step(strip_bgr):
    lab = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2Lab).astype(np.float32)
    gray = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2GRAY)
    bad = waterline._saturated_rows(gray)
    rows = waterline._repair_rows(lab.mean(axis=1), bad)
    win = max(3, strip_bgr.shape[0] // 60)
    rows = waterline._smooth(rows, win * 2 + 1).reshape(-1, 3)
    row, sep = waterline.step_fit(rows, expect_upper_higher=+1)
    return row, sep, waterline._confidence(sep, 2.0)


@pytest.mark.parametrize("seed,deg", [(11, {}), (13, {"rain": 0.6}), (21, {"glare": 1.0}), (41, {"still_water": True})])
def test_waterline_outputs_unchanged_by_profile_refactor(seed, deg):
    frames, cal, _ref = _scene(seed=seed, frac=0.55, **deg)
    strips = [cal.extract_strip(f) for f in frames]
    still = np.median(np.stack(strips), axis=0).astype(np.uint8)

    e1, p1 = waterline.edge_energy_profile(still)
    assert waterline.edge_energy(still) == e1
    row, sep, conf = _old_edge_energy(still)
    assert e1.row == (None if row is None else float(row)) and e1.separation == sep and e1.confidence == conf
    assert p1.shape == (still.shape[0],)
    assert waterline.step_fit(p1, expect_upper_higher=+1)[0] == row

    e3, p3 = waterline.colour_step_profile(still)
    assert waterline.colour_step(still) == e3
    row, sep, conf = _old_colour_step(still)
    assert e3.row == (None if row is None else float(row)) and e3.separation == sep and e3.confidence == conf
    assert p3.shape == (still.shape[0], 3)

    e2, p2 = waterline.temporal_texture_profile(strips)
    again = waterline.temporal_texture(strips)
    assert (again.row, again.confidence, again.separation, again.detail) == (e2.row, e2.confidence, e2.separation, e2.detail)
    assert p2.shape == (still.shape[0], 2)
    short, none = waterline.temporal_texture_profile(strips[:2])
    assert short.row is None and none is None


def test_measure_capture_is_opt_in_and_changes_nothing():
    frames, cal, ref = _scene(seed=13)
    opts = MeasureOptions(redact=False, draw_overlay=False)
    cap: dict = {}
    a = measure(frames, cal, ref, opts)
    b = measure(frames, cal, ref, opts, capture=cap)
    assert a.reading.to_dict() == b.reading.to_dict()
    assert [e.to_dict() for e in a.estimates] == [e.to_dict() for e in b.estimates]
    assert set(cap) == {"aligned", "strips", "still", "profiles"}


# ---- endpoints ---------------------------------------------------------------------
@pytest.fixture(scope="module", autouse=True)
def _db():
    from jalrekha.db.database import init_db

    init_db()


def _client():
    from jalrekha.main import app

    return TestClient(app)


def test_lab_endpoint_404_for_unknown_trace():
    r = _client().get("/api/vision/lab/tr_doesnotexist")
    assert r.status_code == 404
    assert r.json()["detail"] == "unknown trace"


def test_lab_rebuilds_a_scenario_cycle_and_matches_the_trace():
    from jalrekha.agent import scenarios

    rec = scenarios.run_scenario("karnali-quiet-storm", delay_s=0, max_steps=2)
    assert rec["status"] == "done"
    client = _client()
    r = client.get(f"/api/vision/lab/{rec['trace_ids'][-1]}")
    assert r.status_code == 200, r.text
    lab = r.json()
    assert lab["source"]["kind"] == "scenario"
    assert lab["trace"]["trace_id"] == rec["trace_ids"][-1]
    assert lab["check"]["match"] is True
    assert lab["neighbours"]["prev"] == rec["trace_ids"][0]
    assert "consensus" in lab["fusion"] and "kalman" in lab["fusion"]
    latest = client.get("/api/vision/lab/latest", params={"site_id": "karnali-chisapani-cam"})
    assert latest.status_code == 200 and latest.json()["trace"]["trace_id"] == rec["trace_ids"][-1]
    sites = client.get("/api/vision/lab/sites").json()
    assert [s["site_id"] for s in sites] == ["koshi-chatara-cam", "hancock-usgs-cam"]


def test_lab_latest_404_for_a_site_without_cycles():
    r = _client().get("/api/vision/lab/latest", params={"site_id": "no-such-camera"})
    assert r.status_code == 404
    assert "run a replay first" in r.json()["detail"]


def test_lab_rebuilds_the_archived_real_camera_frame():
    from jalrekha.agent import lab, scenarios
    from jalrekha.agent.models import AgentTrace

    rr = scenarios.REAL_REPLAYS["hancock-real-flood"]
    rows, _cfg = scenarios._real_frames(rr)
    first = rows[0]
    ts = datetime.strptime(first["timestamp_utc"].replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
    row = AgentTrace(trace_id="tr_test_real", site_id=rr.site_id, started_at=ts,
                     steps_json=json.dumps([{"tool": "measure_stage", "input": {"frames": 1}}]))
    frames, src = lab.rebuild_frames(row)
    assert len(frames) == 1 and src["kind"] == "real"
    assert np.array_equal(frames[0], cv2.imread(first["abs_path"]))


def test_uploaded_camera_cycles_cannot_be_rebuilt():
    from jalrekha.agent import lab
    from jalrekha.agent.models import AgentTrace

    row = AgentTrace(trace_id="tr_test_upload", site_id="some-uploaded-cam", started_at=datetime(2026, 1, 1),
                     steps_json=json.dumps([{"tool": "measure_stage", "input": {"frames": 1}}]))
    with pytest.raises(lab.LabUnavailable, match="not archived"):
        lab.rebuild_frames(row)
