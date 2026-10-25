"""Production numbers from the AWS deployment, read back from CloudWatch.

Runs CloudWatch Logs Insights over the agent-cycle events the app writes
(one JSON event per cycle) and counts the S3 evidence archive. Writes
eval/results/cloud_ops.json for scripts/make_headline.py.

    python3 scripts/cloud_ops_report.py [--days 7] [--stack nadisaathi]

Needs AWS credentials for the account that runs the stack. The account id is
never written to the output.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "eval" / "results" / "cloud_ops.json"

QUERIES = {
    "totals": 'filter event = "agent_cycle" | stats count(*) as cycles, count_distinct(site) as sites, '
              'count_distinct(run) as runs, sum(frames) as frames_total',
    "stages": 'filter event = "agent_cycle" and ispresent(ms.total) | stats avg(ms.total) as total_avg, '
              'pct(ms.total, 50) as total_p50, pct(ms.total, 95) as total_p95, avg(ms.register) as register, '
              'avg(ms.warp) as warp, avg(ms.quality) as quality, avg(ms.median) as median, avg(ms.E1_edge) as e1, '
              'avg(ms.E2_temporal) as e2, avg(ms.E3_colour) as e3, avg(ms.fuse) as fuse, avg(ms.redact) as redact, '
              'avg(ms.overlay) as overlay',
    "registration": 'filter event = "agent_cycle" | stats count(*) as cycles, avg(inliers) as avg_inliers by registration',
    "second_opinion": 'filter event = "agent_cycle" and ispresent(second_opinion.model) | stats count(*) as calls, '
                      'pct(second_opinion.latency_ms, 50) as latency_p50, sum(second_opinion.cost_usd) as usd by second_opinion.model as model',
    "branches": 'filter event = "agent_cycle" and ispresent(branches.0) | stats count(*) as cycles by branches.0 as branch',
}


def run_query(logs, group: str, query: str, days: int) -> list[dict]:
    end = int(time.time())
    qid = logs.start_query(logGroupName=group, startTime=end - days * 86400, endTime=end, queryString=query, limit=100)["queryId"]
    for _ in range(60):
        r = logs.get_query_results(queryId=qid)
        if r["status"] in {"Complete", "Failed", "Cancelled", "Timeout"}:
            break
        time.sleep(1)
    rows = []
    for rec in r.get("results", []):
        row = {}
        for f in rec:
            if f["field"].startswith("@"):
                continue
            try:
                row[f["field"]] = float(f["value"])
            except ValueError:
                row[f["field"]] = f["value"]
        rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--stack", default="nadisaathi")
    ap.add_argument("--region", default="us-east-1")
    a = ap.parse_args()
    cf = boto3.client("cloudformation", region_name=a.region)
    res = {r["LogicalResourceId"]: r["PhysicalResourceId"] for r in cf.describe_stack_resources(StackName=a.stack)["StackResources"]}
    group, bucket = res["LogGroup"], res["Bucket"]
    logs = boto3.client("logs", region_name=a.region)
    out: dict = {"meta": {"label": "REAL AWS deployment: CloudWatch Logs Insights over agent-cycle events, S3 evidence archive",
                          "generated_by": "scripts/cloud_ops_report.py", "generated_at": datetime.now(timezone.utc).isoformat(),
                          "window_days": a.days, "region": a.region, "log_group": group}}
    for name, q in QUERIES.items():
        out[name] = run_query(logs, group, q, a.days)
    s3 = boto3.client("s3", region_name=a.region)
    n, token = 0, None
    while True:
        kw = {"Bucket": bucket, "Prefix": "cycles/"}
        if token:
            kw["ContinuationToken"] = token
        r = s3.list_objects_v2(**kw)
        n += r.get("KeyCount", 0)
        token = r.get("NextContinuationToken")
        if not token:
            break
    out["s3_cycle_objects"] = n
    cw = boto3.client("cloudwatch", region_name=a.region)
    alarms = cw.describe_alarms(AlarmNamePrefix=f"{a.stack}-")["MetricAlarms"]
    out["alarms"] = sorted(x["AlarmName"].removeprefix(f"{a.stack}-") for x in alarms)
    out["stack_resources"] = len(res)
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "meta"}, indent=1)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
