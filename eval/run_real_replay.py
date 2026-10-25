"""The agent on a REAL camera: USGS HIVIS Hancock staff-gauge frames (88 daytime frames, July-Aug 2026).

Runs the real-camera replay headless and scores what the agent did against
the gauge: accuracy of the readings it used, how often it held a reading,
whether it raised alerts on the quiet days, when it sounded the danger siren
relative to the first frame above the danger mark, and when it proposed the
all-clear. Warning/danger marks are illustrative (14 ft / 17 ft on this
staff gauge), not official flood categories.

    cd backend && uv run python ../eval/run_real_replay.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("JALREKHA_DATA_DIR", tempfile.mkdtemp(prefix="real-replay-"))
os.environ["NADISAATHI_AWS_ENABLED"] = "0"
os.environ["NADISAATHI_TTS_ENABLED"] = "0"
sys.path.insert(0, str(ROOT / "backend" / "src"))

import numpy as np  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from jalrekha.agent import scenarios  # noqa: E402
from jalrekha.agent.models import ApprovalRequest  # noqa: E402
from jalrekha.db.database import edge_engine, init_db  # noqa: E402


def main() -> int:
    init_db()
    rr = scenarios.REAL_REPLAYS["hancock-real-flood"]
    rec = scenarios.run_real_replay(rr, delay_s=0)
    if rec["status"] != "done":
        raise SystemExit(rec["error"])
    with Session(edge_engine) as s:
        rows = scenarios.latest_trace_rows(s, rec["run_id"])
        aps = s.exec(select(ApprovalRequest).where(ApprovalRequest.scenario_run_id == rec["run_id"])).all()
    cycles, used_err, held, alerts_quiet = [], [], 0, 0
    siren_at = first_danger_frame = first_warning_frame = all_clear_at = None
    for r in rows:
        m = json.loads(r.measurement_json)
        steps = json.loads(r.steps_json)
        truth, stage = m.get("truth_stage_m"), m.get("stage_m")
        is_held = "held" in r.summary
        held += int(is_held)
        t = r.started_at.isoformat() + "Z"
        if truth is not None and truth >= rr.danger_m and first_danger_frame is None:
            first_danger_frame = t
        if truth is not None and truth >= rr.warning_m and first_warning_frame is None:
            first_warning_frame = t
        if not is_held and stage is not None and truth is not None and m.get("usable"):
            used_err.append(abs(stage - truth))
        for st in steps:
            if st["tool"] == "trigger_siren" and (st.get("output") or {}).get("fired") and siren_at is None:
                siren_at = t
            if st["tool"] == "draft_alert" and (st.get("input") or {}).get("kind") == "all_clear" and all_clear_at is None:
                all_clear_at = t
            if st["tool"] == "draft_alert" and (st.get("input") or {}).get("kind") != "all_clear" and truth is not None and truth < rr.warning_m - 0.3:
                alerts_quiet += 1
        cycles.append({"t": t, "truth_m": truth, "stage_m": stage, "held": is_held, "branches": json.loads(r.branches), "summary": r.summary[:160]})
    e = np.array(used_err)
    res = {
        "meta": {"label": rr.label, "generated_by": "eval/run_real_replay.py", "generated_at": datetime.now(timezone.utc).isoformat(),
                 "site": rr.hivis_site, "warning_m": rr.warning_m, "danger_m": rr.danger_m,
                 "note": "Archived hourly daytime frames: the agent's cadence decisions cannot resample the archive, and the steep rise happened overnight with no frames."},
        "frames": len(rows), "held_cycles": held, "held_fraction": round(held / max(len(rows), 1), 4),
        "used_readings": int(len(e)), "used_mae_cm": round(float(e.mean()) * 100, 2) if len(e) else None,
        "used_median_cm": round(float(np.median(e)) * 100, 2) if len(e) else None,
        "first_frame_above_warning": first_warning_frame, "first_frame_above_danger": first_danger_frame, "siren_at": siren_at,
        "siren_on_first_danger_frame": siren_at is not None and siren_at == first_danger_frame,
        "all_clear_proposed_at": all_clear_at, "alert_drafts_on_quiet_frames": alerts_quiet,
        "approvals": sorted({(a.action) for a in aps}), "cycles": cycles,
    }
    out = ROOT / "eval" / "results" / "real_replay.json"
    out.write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "cycles"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
