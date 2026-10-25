"""Agent scenario suite: the perception-driven agent vs a rule-only baseline.

Variants are procedural scenes (labelled SYNTHETIC) with exact truth:
held-out gauge scenes (seeds not used to set any threshold), flood and
no-flood hydrographs, and degradations (rain/fog, night, glare, camera knock)
placed at different times. Both systems see exactly the same frames at the
times they ask for them.

  agent     : jalrekha.agent.runner (quality gate D1, registration D2, consensus /
              second opinion D3/D7, Kalman rate + adaptive cadence D4,
              projected-crossing drafts D5, guarded siren D6, falling D9)
  baseline  : "rule-only": same OpenCV measurement, no quality gate, no
              consensus check, no Kalman, fixed 10-min cadence; drafts an alert
              when the raw reading >= warning and sounds the siren when
              raw >= danger. (What a simple threshold camera would do.)

Metrics per system:
  false_alert_runs   no-flood runs where any alert draft or siren happened
  false_sirens       sirens while the true stage was below danger - 0.10 m
  missed_sirens      flood runs that reached danger without a siren
  alert_lead_min     minutes between the first alert draft and the true
                     crossing of the warning level (positive = earlier)
  decision_cycles, ms per cycle

    cd backend && uv run python ../eval/run_agent_suite.py --out ../eval/results/agent_suite.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("JALREKHA_DATA_DIR", tempfile.mkdtemp(prefix="agent-suite-"))
os.environ["NADISAATHI_AWS_ENABLED"] = "0"
os.environ["NADISAATHI_TTS_ENABLED"] = "0"
sys.path.insert(0, str(ROOT / "backend" / "src"))

import numpy as np  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from jalrekha.agent import policy, scenarios  # noqa: E402
from jalrekha.agent.models import AgentTrace, ApprovalRequest  # noqa: E402
from jalrekha.agent.scenarios import Event, Scenario, hydrograph  # noqa: E402
from jalrekha.db.database import edge_engine, init_db  # noqa: E402
from jalrekha.services.actuators import RECORDED_CALLS  # noqa: E402
from jalrekha.vision import synth  # noqa: E402
from jalrekha.vision.gauge import GaugeCalibration, GaugeMark  # noqa: E402
from jalrekha.vision.pipeline import MeasureOptions, measure  # noqa: E402

# Held-out gauge scenes: tall gauges from seeds never used for tuning (train seeds were 0-9).
SEEDS = [316, 330, 419, 440, 501, 535]
# Seeds added after the post-gap fix, never used to develop or tune the agent.
UNSEEN_SEEDS = [363, 452, 511]
SIM0 = datetime(2026, 8, 14, 18, 0, 0)


def variants() -> list[Scenario]:
    out = []
    for i, seed in enumerate(SEEDS + UNSEEN_SEEDS):
        g = synth.make_site(seed).gauge_len_m
        off = 2.5
        warn, danger = round(off + g * 0.62, 2), round(off + g * 0.82, 2)
        base = off + g * 0.12
        t_ev = 20 + 15 * i
        # Flood: crosses warning and danger, with weather and a camera knock during the rise.
        out.append(Scenario(
            id=f"flood-{seed}", title="flood", description="", basin="koshi", site_id="koshi-chatara-cam", seed=seed,
            offset_m=off, warning_m=warn, danger_m=danger, stage=hydrograph(base, off + g * 0.93, off + g * 0.5, 40 + 5 * i, 260, 420),
            duration_min=360,
            events=[Event(t_ev, t_ev + 12, {"rain": 1.0, "fog": 0.85}, "rain squall"),
                    Event(140 + 4 * i, 146 + 4 * i, {"shake_px": 30}, "gust"),
                    Event(190 + 3 * i, 196 + 3 * i, {"glare": 1.0}, "glare")],
            adversarial_at_danger=(i % 2 == 0),
        ))
        # Hard no-flood case: river steady 0.30 m below the warning level while the camera
        # suffers glare, a knock, rain/fog and darkness. A single bad reading can cross the line.
        near = warn - 0.30
        out.append(Scenario(
            id=f"near-{seed}", title="quiet", description="", basin="koshi", site_id="koshi-chatara-cam", seed=seed,
            offset_m=off, warning_m=warn, danger_m=danger, stage=hydrograph(near, near + 0.03, near, 60, 120, 240),
            duration_min=240,
            events=[Event(30, 55, {"glare": 1.0}, "glare"),
                    Event(80, 95, {"shake_px": 40}, "camera knock"),
                    Event(120, 145, {"rain": 1.0, "fog": 0.85}, "rain squall"),
                    Event(170, 195, {"night": 0.9}, "dusk")],
        ))
        # Hard no-flood case: the camera mount is knocked while the river sits 0.5 m below the
        # warning level. A misregistered frame can put the "waterline" on the wrong object.
        steady = warn - 0.50
        out.append(Scenario(
            id=f"moved-{seed}", title="quiet", description="", basin="koshi", site_id="koshi-chatara-cam", seed=seed,
            offset_m=off, warning_m=warn, danger_m=danger, stage=hydrograph(steady, steady + 0.02, steady, 60, 120, 200),
            duration_min=180,
            events=[Event(60, 120, {"pan": {"dx": 760 + 30 * (i % 3), "dy": 40, "rot_deg": 28, "scale": 1.0}}, "mount knocked")],
        ))
        # No flood: steady river, bad weather and night (false-alarm test).
        out.append(Scenario(
            id=f"quiet-{seed}", title="quiet", description="", basin="koshi", site_id="koshi-chatara-cam", seed=seed,
            offset_m=off, warning_m=warn, danger_m=danger, stage=hydrograph(base, base + 0.08, base + 0.03, 60, 150, 300),
            duration_min=240,
            events=[Event(30, 70, {"night": 0.85, "rain": 0.7}, "dusk storm"),
                    Event(100, 120, {"fog": 0.92}, "dense fog"),
                    Event(150, 165, {"glare": 1.0}, "glare"),
                    Event(180, 200, {"rain": 1.0, "fog": 0.85}, "rain squall")],
        ))
    return out


def truth_cross(sc: Scenario, level: float) -> float | None:
    t = 0.0
    while t <= sc.duration_min:
        if sc.stage(t) >= level:
            return t
        t += 0.5
    return None


def run_agent(sc: Scenario) -> dict:
    scenarios.SCENARIOS[sc.id] = sc
    RECORDED_CALLS.clear()
    t0 = time.perf_counter()
    rec = scenarios.run_scenario(sc.id, delay_s=0)
    wall = time.perf_counter() - t0
    with Session(edge_engine) as s:
        rows = s.exec(select(AgentTrace).where(AgentTrace.scenario_run_id == rec["run_id"]).order_by(AgentTrace.started_at)).all()
        aps = s.exec(select(ApprovalRequest).where(ApprovalRequest.scenario_run_id == rec["run_id"])).all()
    first_alert = None
    sirens = []
    branches: dict[str, int] = {}
    for r in rows:
        steps = json.loads(r.steps_json)
        t_min = (r.started_at - SIM0).total_seconds() / 60
        truth = json.loads(r.measurement_json).get("truth_stage_m")
        for st in steps:
            d = st.get("decision") or {}
            if d.get("branch"):
                branches[d["branch"]] = branches.get(d["branch"], 0) + 1
            if st["tool"] == "draft_alert" and first_alert is None and (st.get("input") or {}).get("kind") != "all_clear":
                first_alert = t_min
            if st["tool"] == "trigger_siren" and (st.get("output") or {}).get("fired"):
                sirens.append((t_min, truth))
    cycle_log = [{"t_min": round((r.started_at - SIM0).total_seconds() / 60, 1), "branches": json.loads(r.branches),
                  "summary": r.summary[:200], "trace_id": r.trace_id} for r in rows]
    return {"cycle_log": cycle_log, "cycles": len(rows), "first_alert_min": first_alert, "sirens": sirens, "branches": branches,
            "approvals": sorted({a.action for a in aps}), "ms_per_cycle": round(wall / max(len(rows), 1) * 1000, 1),
            "status": rec["status"], "error": rec["error"]}


def run_baseline(sc: Scenario) -> dict:
    ss = synth.make_site(sc.seed)
    base = ss.calibration(click_err_px=1.0)
    calib = GaugeCalibration(marks=[GaugeMark(m.x, m.y, round(m.stage_m + sc.offset_m, 3)) for m in base.marks],
                             strip_half_width_px=base.strip_half_width_px, reference_size=base.reference_size,
                             warning_m=sc.warning_m, danger_m=sc.danger_m)
    ref = synth.reference_frame(ss)
    t, first_alert, sirens, cycles = 0.0, None, [], 0
    t0 = time.perf_counter()
    siren_on = False
    while t <= sc.duration_min:
        frames, truth, _, _ = scenarios.frames_at(sc, t, 5)
        m = measure(frames, calib, ref, MeasureOptions(allow_heavy_registration=False, redact=False, draw_overlay=False))
        v = m.reading.stage_m
        cycles += 1
        if v is not None and v >= sc.warning_m and first_alert is None:
            first_alert = t
        if v is not None and v >= sc.danger_m and not siren_on:
            sirens.append((t, round(truth, 3)))
            siren_on = True
        t += 10.0
    return {"cycles": cycles, "first_alert_min": first_alert, "sirens": sirens,
            "ms_per_cycle": round((time.perf_counter() - t0) / max(cycles, 1) * 1000, 1)}


def run_baseline_projection(sc: Scenario) -> dict:
    """Stronger baseline: the agent's own Kalman projection rule, but no quality gate,
    no estimator-consensus check, no second opinion and a fixed 10-minute cadence."""
    from jalrekha.vision.temporal import filter_series

    ss = synth.make_site(sc.seed)
    base = ss.calibration(click_err_px=1.0)
    calib = GaugeCalibration(marks=[GaugeMark(m.x, m.y, round(m.stage_m + sc.offset_m, 3)) for m in base.marks],
                             strip_half_width_px=base.strip_half_width_px, reference_size=base.reference_size,
                             warning_m=sc.warning_m, danger_m=sc.danger_m)
    ref = synth.reference_frame(ss)
    t, first_alert, sirens, cycles, hist = 0.0, None, [], 0, []
    t0 = time.perf_counter()
    siren_on = False
    while t <= sc.duration_min:
        frames, truth, _, _ = scenarios.frames_at(sc, t, 5)
        m = measure(frames, calib, ref, MeasureOptions(allow_heavy_registration=False, redact=False, draw_overlay=False))
        v = m.reading.stage_m
        cycles += 1
        if v is not None:
            hist.append((SIM0 + timedelta(minutes=t), v, m.reading.sigma_m or 0.03))
        f = filter_series(hist[-36:]) if len(hist) >= 2 else None
        rate = f.rate_m_per_h if f else None
        level = f.stage_m if f else v
        projected = (rate is not None and rate >= policy.R_FAST_M_PER_H and level is not None and level < sc.warning_m
                     and (sc.warning_m - level) / rate <= policy.CROSS_HORIZON_H)
        if first_alert is None and v is not None and (v >= sc.warning_m or projected):
            first_alert = t
        if v is not None and v >= sc.danger_m and not siren_on:
            sirens.append((t, round(truth, 3)))
            siren_on = True
        t += 10.0
    return {"cycles": cycles, "first_alert_min": first_alert, "sirens": sirens,
            "ms_per_cycle": round((time.perf_counter() - t0) / max(cycles, 1) * 1000, 1)}


def score(sc: Scenario, r: dict) -> dict:
    flood = sc.title == "flood"
    t_warn = truth_cross(sc, sc.warning_m)
    t_danger = truth_cross(sc, sc.danger_m)
    false_sirens = sum(1 for _, truth in r["sirens"] if truth is not None and truth < sc.danger_m - 0.10)
    out = {"variant": sc.id, "flood": flood, "t_true_warning_min": t_warn, "t_true_danger_min": t_danger,
           "first_alert_min": r["first_alert_min"], "sirens": len(r["sirens"]), "false_sirens": false_sirens,
           "cycles": r["cycles"], "ms_per_cycle": r["ms_per_cycle"]}
    if flood:
        out["alert_lead_min"] = None if r["first_alert_min"] is None or t_warn is None else round(t_warn - r["first_alert_min"], 1)
        out["missed_alert"] = r["first_alert_min"] is None
        out["missed_siren"] = t_danger is not None and not r["sirens"]
    else:
        out["false_alert"] = r["first_alert_min"] is not None or bool(r["sirens"])
    for k in ("branches", "approvals"):
        if k in r:
            out[k] = r[k]
    return out


def summarise(rows: list[dict]) -> dict:
    fl = [r for r in rows if r["flood"]]
    qu = [r for r in rows if not r["flood"]]
    leads = [r["alert_lead_min"] for r in fl if r.get("alert_lead_min") is not None]
    return {
        "flood_runs": len(fl), "quiet_runs": len(qu),
        "false_alert_runs": sum(1 for r in qu if r["false_alert"]),
        "false_sirens": sum(r["false_sirens"] for r in rows),
        "missed_alerts": sum(1 for r in fl if r["missed_alert"]),
        "missed_sirens": sum(1 for r in fl if r["missed_siren"]),
        "alert_lead_min_median": None if not leads else round(statistics.median(leads), 1),
        "alert_lead_min_values": leads,
        "decision_cycles": sum(r["cycles"] for r in rows),
        "ms_per_cycle_median": round(statistics.median([r["ms_per_cycle"] for r in rows]), 1),
        "success_runs": sum(1 for r in fl if not r["missed_alert"] and not r["missed_siren"] and r["false_sirens"] == 0)
        + sum(1 for r in qu if not r["false_alert"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "eval" / "results" / "agent_suite.json"))
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    init_db()
    vs = variants()
    if a.quick:
        vs = vs[:2]
    agent_rows, base_rows, proj_rows, splits = [], [], [], []
    t0 = time.perf_counter()
    for sc in vs:
        ra = run_agent(sc)
        if ra["status"] != "done":
            raise SystemExit(f"{sc.id}: {ra['error']}")
        rb = run_baseline(sc)
        rp = run_baseline_projection(sc)
        agent_rows.append(score(sc, ra))
        base_rows.append(score(sc, rb))
        proj_rows.append(score(sc, rp))
        # Where the plans split: the no-gates system alerts on a no-flood run and the agent does not.
        if sc.title == "quiet" and (rp["first_alert_min"] is not None or rp["sirens"]) and ra["first_alert_min"] is None:
            t_b = rp["first_alert_min"] if rp["first_alert_min"] is not None else rp["sirens"][0][0]
            near = min(ra["cycle_log"], key=lambda c: abs(c["t_min"] - t_b))
            splits.append({"variant": sc.id, "no_gates_alert_min": t_b, "agent_cycle": near})
        print(f"{sc.id:12s} agent: alert@{ra['first_alert_min']} sirens={len(ra['sirens'])}  |  threshold: alert@{rb['first_alert_min']} sirens={len(rb['sirens'])}"
              f"  |  projection-no-gates: alert@{rp['first_alert_min']} sirens={len(rp['sirens'])}", flush=True)
    pol = (ROOT / "backend" / "src" / "jalrekha" / "agent" / "policy.py").read_bytes()
    result = {
        "meta": {"label": "SYNTHETIC scenario suite (procedural staff-gauge scenes, exact truth; held-out gauge seeds)",
                 "generated_by": "eval/run_agent_suite.py", "generated_at": datetime.now(timezone.utc).isoformat(),
                 "seeds": SEEDS, "unseen_seeds": UNSEEN_SEEDS, "variants": len(vs), "policy_sha256": hashlib.sha256(pol).hexdigest(),
                 "baseline": "rule-only: raw reading thresholds, no quality gate / consensus / Kalman, fixed 10-min cadence",
                 "baseline_projection_no_gates": "the agent's Kalman projection rule on every raw reading: no quality gate, no consensus check, no second opinion, fixed 10-min cadence",
                 "note": "The suite revealed a scenario-caching bug during development (fixed); the hard near-warning variants were added after the first fresh-eyes review.",
                 "wall_s": round(time.perf_counter() - t0, 1)},
        "summary": {"agent": summarise(agent_rows), "baseline_rule_only": summarise(base_rows),
                    "baseline_projection_no_gates": summarise(proj_rows)},
        "summary_unseen_seeds": {
            "seeds": UNSEEN_SEEDS,
            "agent": summarise([r for r in agent_rows if int(r["variant"].split("-")[1]) in UNSEEN_SEEDS]),
            "baseline_rule_only": summarise([r for r in base_rows if int(r["variant"].split("-")[1]) in UNSEEN_SEEDS]),
            "baseline_projection_no_gates": summarise([r for r in proj_rows if int(r["variant"].split("-")[1]) in UNSEEN_SEEDS]),
        },
        "runs": {"agent": agent_rows, "baseline_rule_only": base_rows, "baseline_projection_no_gates": proj_rows},
        "plan_splits": splits,
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(result, indent=1))
    print(json.dumps(result["summary"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
