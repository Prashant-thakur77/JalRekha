"""Every number the film says or shows, read from the repository's result files at build time."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_K = json.loads((ROOT / "eval" / "results" / "headline.json").read_text())["keys"]


def k(name: str) -> str:
    v = str(_K[name])
    return v[:-2] if v.endswith(".0") else v


def num(name: str) -> float:
    return float(k(name).strip("$%×").replace(",", ""))


F = {
    "real_mae_cm": k("real_full_mae_cm"),            # OpenCV on real USGS staff-gauge cameras
    "real_frames": k("real_n"),
    "b0_on_subset_cm": k("real_b0_on_subset_cm"),    # the method we started from, on the frames it could read
    "guard_caught": k("guard_caught"),
    "guard_bad": k("guard_bad"),
    "lead_min": k("ag_lead_median_min"),
    "suite_success": k("ag_success"),
    "false_alert_runs": k("ag_false_alert_runs"),
    "opencv_ms": k("ops_total_p50_ms"),              # production median, CloudWatch Logs Insights
    "cycles": k("ops_cycles"),
    "orb_inliers": k("ops_orb_inliers"),
    "claude_calls": k("ops_claude_calls"),
    "s3_objects": k("ops_s3_objects"),
    "stack_resources": k("ops_stack_resources"),
    "graviton_saving": k("BC_cost_saving"),
    "usd_1m": k("B_usd_1m"),
    "roads_hit": k("pt_road_hit"),
    "roads_pos": k("pt_road_pos"),
    "uptime": k("soak_uptime"),
}

if __name__ == "__main__":
    print(json.dumps(F, indent=1))
