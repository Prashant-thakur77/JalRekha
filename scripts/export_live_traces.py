"""Export one replay from the live AWS deployment: the real USGS Hancock camera, with Claude
second opinions called live. Writes docs/traces/hancock-real-flood-live.jsonl and docs/traces/LIVE.md.

    python3 scripts/export_live_traces.py [--run RUN_ID] [--api https://.../api]
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "traces"
API = "https://gaq7chhmb2.execute-api.us-east-1.amazonaws.com/api"


def get(api: str, path: str):
    with urllib.request.urlopen(f"{api}{path}", timeout=60) as r:
        return json.load(r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=API)
    ap.add_argument("--run", default=None, help="scenario run id (default: the latest Hancock replay)")
    a = ap.parse_args()
    run = a.run or get(a.api, "/agent/traces?site_id=hancock-usgs-cam&limit=1")[0]["scenario_run_id"]
    rows = sorted(get(a.api, f"/agent/traces?run_id={run}&limit=500"), key=lambda t: t["cycle"])
    full = [get(a.api, f"/agent/traces/{t['trace_id']}") for t in rows]
    (OUT / "hancock-real-flood-live.jsonl").write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in full))
    lines = ["# Live traces from the AWS deployment (REAL CAMERA REPLAY)", "",
             f"Run `{run}` on the deployed stack: {len(full)} archived USGS HIVIS frames from the Hancock staff-gauge camera, "
             "measured by the OpenCV pipeline on Graviton4, with the agent calling Claude for a second opinion whenever its "
             "estimators could not confirm each other. Warning and danger marks on this gauge are illustrative. "
             "Exported by `scripts/export_live_traces.py` from the public API; every cycle is also an event in CloudWatch Logs "
             "and an evidence file in S3.", "", "| Cycle | Camera | Truth | Second opinion | Model | Latency | Cost | Result |",
             "|---|---|---|---|---|---|---|---|"]
    calls = 0
    for t in full:
        m = t.get("measurement") or {}
        for s in t.get("steps", []):
            if s.get("tool") == "verify_with_vlm" and s.get("kind") != "decision":
                calls += 1
                parsed = (s.get("output") or {}).get("parsed") or {}
                guard = next((g for g in t["steps"] if g.get("tool") == "compare_cv_vlm"), {})
                accepted = (guard.get("guard") or {}).get("accepted")
                stage = m.get("stage_m")
                opinion = "abstained" if parsed.get("stage_m") is None else f"{parsed['stage_m']} m"
                lines.append(f"| {t['cycle']} | {stage if stage is None else f'{stage:.2f} m'} | "
                             f"{m.get('truth_stage_m', '–')} m | {opinion} | {s.get('model')} | "
                             f"{(s.get('latency_ms') or 0) / 1000:.1f} s | ${s.get('cost_usd_est') or 0:.4f} | "
                             f"{'confirmed' if accepted else 'held for a person' if accepted is False else t['summary'][:60]} |")
    lines += ["", f"{calls} second opinions in {len(full)} cycles."]
    (OUT / "LIVE.md").write_text("\n".join(lines) + "\n")
    print(f"{run}: {len(full)} cycles, {calls} second opinions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
