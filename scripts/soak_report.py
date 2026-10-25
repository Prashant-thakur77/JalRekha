"""Reliability of the deployed endpoint, from CloudWatch (no synthetic numbers).

The keep-warm Lambda probes GET /api/health every 5 minutes and records
NadiSaathi/HealthOk and HealthLatencyMs; the backend records AgentCycles and
StageMs. This script reads them for the whole life of the stack and writes
eval/results/soak.json (hours observed, uptime, latency p50/p95, cycles).

    python3 scripts/soak_report.py
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "eval" / "results" / "soak.json"


def aws(*args: str) -> dict:
    out = subprocess.run(["aws", *args, "--output", "json"], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def series(metric: str, stat: str, start: datetime, end: datetime, dims: list[dict] | None = None, period: int = 300) -> list[tuple[str, float]]:
    pts: list[tuple[str, float]] = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(hours=24), end)
        q = ["cloudwatch", "get-metric-statistics", "--namespace", "NadiSaathi", "--metric-name", metric,
             "--start-time", cur.isoformat(), "--end-time", nxt.isoformat(), "--period", str(period), "--statistics", stat]
        if dims:
            q += ["--dimensions", *[f"Name={d['Name']},Value={d['Value']}" for d in dims]]
        for p in aws(*q)["Datapoints"]:
            pts.append((p["Timestamp"], p[stat]))
        cur = nxt
    return sorted(pts)


def pct(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * q / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 1)


def main() -> int:
    stack = aws("cloudformation", "describe-stacks", "--stack-name", "nadisaathi")["Stacks"][0]
    created = datetime.fromisoformat(stack["CreationTime"].replace("Z", "+00:00"))
    end = datetime.now(timezone.utc)
    ok = series("HealthOk", "Minimum", created, end)
    lat = series("HealthLatencyMs", "Average", created, end)
    cycles = series("AgentCycles", "Sum", created, end, [{"Name": "Service", "Value": "agent"}])
    stage = series("StageMs", "Average", created, end, [{"Name": "Service", "Value": "agent"}])
    probes = len(ok)
    up = sum(1 for _, v in ok if v >= 1)
    hours = round((end - created).total_seconds() / 3600, 1)
    res = {
        "meta": {"label": "REAL deployed endpoint (API Gateway -> EC2 c8g.xlarge), CloudWatch metrics", "generated_by": "scripts/soak_report.py",
                 "generated_at": end.isoformat(), "stack_created": created.isoformat(),
                 "probe": "keep-warm Lambda GET /api/health every 5 min (min of HealthOk per 5-min period)"},
        "hours_observed": hours,
        "health_probes": probes,
        "health_probes_ok": up,
        "uptime": round(up / probes, 4) if probes else None,
        "health_latency_ms_p50": pct([v for _, v in lat], 50),
        "health_latency_ms_p95": pct([v for _, v in lat], 95),
        "agent_cycles_total": int(sum(v for _, v in cycles)),
        "stage_ms_mean_of_5min_means": round(sum(v for _, v in stage) / len(stage), 1) if stage else None,
        "failed_probe_times": [t for t, v in ok if v < 1][:50],
    }
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "failed_probe_times"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
