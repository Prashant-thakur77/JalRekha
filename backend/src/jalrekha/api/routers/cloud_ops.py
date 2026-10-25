"""Read-only views of the AWS deployment for the app's Cloud page.

Live CloudWatch Logs (agent-cycle events and the app log), fixed CloudWatch
Logs Insights queries, CloudWatch metrics (OpenCV stage timings, agent cycles,
host CPU and memory) and the state of the other services the stack uses.

Everything is cached for a few seconds so many viewers cost a handful of AWS
calls. Account ids are removed from every string before it leaves the server.
Only fixed queries run; nothing a visitor types reaches CloudWatch.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query

from jalrekha.agent import cloud, cloudlog

router = APIRouter(prefix="/cloud", tags=["cloud"])

_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_LOCK = threading.Lock()
_ACCOUNT = re.compile(r"(?<![0-9])[0-9]{12}(?![0-9])")


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return _ACCOUNT.sub("…", value)
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _cached(key: str, ttl_s: float, fn: Callable[[], Any]) -> Any:
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < ttl_s:
            return hit[1]
    value = _scrub(fn())
    with _CACHE_LOCK:
        _CACHE[key] = (now, value)
    return value


def _require_aws():
    if not cloud.aws_enabled() or not cloudlog.log_group():
        raise HTTPException(503, "AWS views are available on the cloud deployment only")


def _iso(ms: int | float | None) -> str | None:
    return None if ms is None else datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def _console(path: str) -> str:
    return f"https://{cloud.region_name()}.console.aws.amazon.com/{path}"


# ------------------------------------------------------------------ logs
@router.get("/logs")
def logs(source: str = Query("cycles", pattern="^(cycles|app)$"), minutes: int = Query(30, ge=1, le=1440),
         limit: int = Query(40, ge=1, le=200)) -> dict[str, Any]:
    _require_aws()

    def fetch() -> dict[str, Any]:
        client = cloud.client("logs")
        kw: dict[str, Any] = {"logGroupName": cloudlog.log_group(), "limit": 10000,
                              "startTime": int((time.time() - minutes * 60) * 1000)}
        if source == "cycles":
            kw["logStreamNamePrefix"] = "agent-cycles/"
        else:
            kw["filterPattern"] = "-\"GET /api/health\" -\"GET /api/cloud\""
        events: list[dict[str, Any]] = []
        token = None
        for _ in range(5):  # newest events are on the last pages
            if token:
                kw["nextToken"] = token
            r = client.filter_log_events(**kw)
            events.extend(r.get("events", []))
            token = r.get("nextToken")
            if not token:
                break
        events = sorted(events, key=lambda e: e["timestamp"], reverse=True)[:limit]
        out = []
        for e in events:
            item: dict[str, Any] = {"at": _iso(e["timestamp"]), "stream": e.get("logStreamName", "").split("/")[-1]}
            if source == "cycles":
                try:
                    item["event"] = json.loads(e["message"])
                except json.JSONDecodeError:
                    item["message"] = e["message"][:500]
            else:
                item["message"] = e["message"][:500]
            out.append(item)
        return {"source": source, "log_group": cloudlog.log_group(), "events": out,
                "console_url": _console(f"cloudwatch/home?region={cloud.region_name()}#logsV2:log-groups")}

    return _cached(f"logs:{source}:{minutes}:{limit}", 3, fetch)


# --------------------------------------------------------------- insights
INSIGHTS: dict[str, tuple[str, str]] = {
    "opencv_stages": ("OpenCV stage timing per site, last 24 h",
                      'filter event = "agent_cycle" | stats count(*) as cycles, avg(ms.total) as total_ms, '
                      'pct(ms.total, 95) as total_p95_ms, avg(ms.register) as register_ms, avg(ms.quality) as quality_ms, '
                      'avg(ms.E1_edge) as e1_ms, avg(ms.E2_temporal) as e2_ms, avg(ms.E3_colour) as e3_ms, '
                      'avg(ms.redact) as redact_ms by site'),
    "decisions": ("Agent branches taken, last 24 h",
                  'filter event = "agent_cycle" and ispresent(branches.0) | stats count(*) as cycles by branches.0 as branch '
                  '| sort cycles desc'),
    "registration": ("How frames were aligned to the reference, last 24 h",
                     'filter event = "agent_cycle" | stats count(*) as cycles, avg(inliers) as avg_inliers, '
                     'avg(ms.register) as register_ms by registration'),
    "second_opinion": ("Claude second opinions: calls, latency and cost, last 24 h",
                       'filter event = "agent_cycle" and ispresent(second_opinion.model) | stats count(*) as calls, '
                       'avg(second_opinion.latency_ms) as avg_latency_ms, sum(second_opinion.cost_usd) as cost_usd '
                       'by second_opinion.model as model'),
    "quality": ("Frames rejected by the quality gate, last 24 h",
                'filter event = "agent_cycle" and ispresent(quality_reasons.0) | stats count(*) as frames by quality_reasons.0 as reason '
                '| sort frames desc'),
}


@router.get("/insights")
def insights_index() -> list[dict[str, str]]:
    return [{"id": k, "title": v[0], "query": v[1]} for k, v in INSIGHTS.items()]


@router.get("/insights/{query_id}")
def insights(query_id: str) -> dict[str, Any]:
    if query_id not in INSIGHTS:
        raise HTTPException(404, "unknown query")
    _require_aws()
    title, query = INSIGHTS[query_id]

    def run() -> dict[str, Any]:
        client = cloud.client("logs")
        end = int(time.time())
        q = client.start_query(logGroupName=cloudlog.log_group(), startTime=end - 86400, endTime=end,
                               queryString=query, limit=50)
        t0 = time.monotonic()
        res: dict[str, Any] = {"status": "Running"}
        while time.monotonic() - t0 < 12:
            res = client.get_query_results(queryId=q["queryId"])
            if res["status"] in {"Complete", "Failed", "Cancelled", "Timeout"}:
                break
            time.sleep(0.5)
        rows = [{f["field"]: f["value"] for f in r if not f["field"].startswith("@")} for r in res.get("results", [])]
        stats = res.get("statistics", {})
        return {"id": query_id, "title": title, "query": query, "status": res["status"], "rows": rows,
                "scanned_bytes": stats.get("bytesScanned"), "records_matched": stats.get("recordsMatched"),
                "ran_at": datetime.now(timezone.utc).isoformat(), "duration_s": round(time.monotonic() - t0, 2)}

    return _cached(f"insights:{query_id}", 60, run)


# ---------------------------------------------------------------- metrics
def _instance() -> dict[str, Any] | None:
    ec2 = cloud.client("ec2")
    stack = os.environ.get("NADISAATHI_STACK", "nadisaathi")
    r = ec2.describe_instances(Filters=[{"Name": "tag:aws:cloudformation:stack-name", "Values": [stack]},
                                        {"Name": "instance-state-name", "Values": ["running"]}])
    for res in r.get("Reservations", []):
        for i in res.get("Instances", []):
            return i
    return None


@router.get("/metrics")
def metrics(hours: int = Query(3, ge=1, le=48)) -> dict[str, Any]:
    _require_aws()

    def fetch() -> dict[str, Any]:
        cw = cloud.client("cloudwatch")
        inst = _instance()
        period = 300 if hours <= 6 else 900
        queries = []
        for i, stage in enumerate(cloudlog.STAGES):
            queries.append({"Id": f"s{i}", "Label": f"stage:{stage}", "ReturnData": True, "MetricStat": {
                "Metric": {"Namespace": "NadiSaathi", "MetricName": "StageMs", "Dimensions": [{"Name": "Stage", "Value": stage}]},
                "Period": period, "Stat": "Average"}})
        queries.append({"Id": "cycles", "Label": "agent_cycles", "ReturnData": True, "MetricStat": {
            "Metric": {"Namespace": "NadiSaathi", "MetricName": "AgentCycles", "Dimensions": [{"Name": "Service", "Value": "agent"}]},
            "Period": period, "Stat": "Sum"}})
        if inst:
            queries.append({"Id": "cpu", "Label": "cpu_percent", "ReturnData": True, "MetricStat": {
                "Metric": {"Namespace": "AWS/EC2", "MetricName": "CPUUtilization",
                           "Dimensions": [{"Name": "InstanceId", "Value": inst["InstanceId"]}]},
                "Period": period, "Stat": "Average"}})
            queries.append({"Id": "mem", "Label": "mem_percent", "ReturnData": True, "MetricStat": {
                "Metric": {"Namespace": "CWAgent", "MetricName": "mem_used_percent",
                           "Dimensions": [{"Name": "InstanceId", "Value": inst["InstanceId"]}]},
                "Period": period, "Stat": "Average"}})
        end = datetime.now(timezone.utc)
        r = cw.get_metric_data(MetricDataQueries=queries, StartTime=end - timedelta(hours=hours), EndTime=end,
                               ScanBy="TimestampAscending")
        series = {}
        for m in r.get("MetricDataResults", []):
            series[m["Label"]] = [{"t": t.isoformat(), "v": round(v, 3)} for t, v in zip(m["Timestamps"], m["Values"])]
        return {"hours": hours, "period_s": period, "series": series,
                "console_url": _console(f"cloudwatch/home?region={cloud.region_name()}#dashboards:name="
                                        f"{os.environ.get('NADISAATHI_STACK', 'nadisaathi')}")}

    return _cached(f"metrics:{hours}", 30, fetch)


# --------------------------------------------------------------- services
def _safe(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return {"ok": True, **fn()}
    except Exception as exc:  # one service failing must not hide the others
        return {"ok": False, "error": type(exc).__name__}


@router.get("/services")
def services() -> dict[str, Any]:
    _require_aws()
    stack = os.environ.get("NADISAATHI_STACK", "nadisaathi")
    bucket = os.environ.get("NADISAATHI_S3_BUCKET")
    topic = os.environ.get("NADISAATHI_SNS_TOPIC_ARN", "")

    def ec2() -> dict[str, Any]:
        i = _instance() or {}
        return {"instance_type": i.get("InstanceType"), "architecture": i.get("Architecture"), "ami": i.get("ImageId"),
                "zone": (i.get("Placement") or {}).get("AvailabilityZone"),
                "launched": i["LaunchTime"].isoformat() if i.get("LaunchTime") else None,
                "platform": i.get("PlatformDetails")}

    def stack_info() -> dict[str, Any]:
        cf = cloud.client("cloudformation")
        s = cf.describe_stacks(StackName=stack)["Stacks"][0]
        res = cf.describe_stack_resources(StackName=stack)["StackResources"]
        kinds: dict[str, int] = {}
        for x in res:
            kinds[x["ResourceType"]] = kinds.get(x["ResourceType"], 0) + 1
        return {"name": stack, "status": s["StackStatus"],
                "updated": (s.get("LastUpdatedTime") or s["CreationTime"]).isoformat(),
                "resources": len(res), "resource_types": dict(sorted(kinds.items()))}

    def s3() -> dict[str, Any]:
        c = cloud.client("s3")
        counts = {}
        for prefix in ("cycles/", "cap/", "deploy/"):
            r = c.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1000)
            counts[prefix.rstrip("/")] = r.get("KeyCount", 0)
        latest = c.list_objects_v2(Bucket=bucket, Prefix="cycles/", MaxKeys=1000).get("Contents", [])
        latest = sorted(latest, key=lambda o: o["LastModified"], reverse=True)[:3]
        return {"objects": counts, "latest": [{"key": o["Key"], "bytes": o["Size"], "at": o["LastModified"].isoformat()} for o in latest],
                "lifecycle": "cycle evidence kept 90 days"}

    def sns() -> dict[str, Any]:
        a = cloud.client("sns").get_topic_attributes(TopicArn=topic)["Attributes"]
        return {"subscriptions_confirmed": int(a.get("SubscriptionsConfirmed", 0)),
                "subscriptions_pending": int(a.get("SubscriptionsPending", 0))}

    def sfn() -> dict[str, Any]:
        c = cloud.client("stepfunctions")
        account = topic.split(":")[4] if topic.count(":") >= 5 else ""
        arn = f"arn:aws:states:{cloud.region_name()}:{account}:stateMachine:{stack}-approval-escalation"
        ex = c.list_executions(stateMachineArn=arn, maxResults=5).get("executions", [])
        return {"recent": [{"name": e["name"], "status": e["status"], "started": e["startDate"].isoformat()} for e in ex]}

    def budget() -> dict[str, Any]:
        account = topic.split(":")[4] if topic.count(":") >= 5 else ""
        b = cloud.client("budgets").describe_budget(AccountId=account, BudgetName=f"{stack}-monthly")["Budget"]
        spend = b.get("CalculatedSpend", {})
        return {"limit_usd": float(b["BudgetLimit"]["Amount"]),
                "actual_usd": float(spend.get("ActualSpend", {}).get("Amount", 0)),
                "forecast_usd": float(spend.get("ForecastedSpend", {}).get("Amount", 0)) if spend.get("ForecastedSpend") else None}

    def logs_info() -> dict[str, Any]:
        c = cloud.client("logs")
        g = c.describe_log_groups(logGroupNamePrefix=cloudlog.log_group())["logGroups"][0]
        return {"group": g["logGroupName"], "retention_days": g.get("retentionInDays"), "stored_bytes": g.get("storedBytes")}

    def alarms() -> dict[str, Any]:
        r = cloud.client("cloudwatch").describe_alarms(AlarmNamePrefix=f"{stack}-", MaxRecords=50)
        items = [{"name": a["AlarmName"].removeprefix(f"{stack}-"), "state": a["StateValue"]} for a in r.get("MetricAlarms", [])]
        return {"alarms": items, "in_alarm": sum(a["state"] == "ALARM" for a in items)}

    def fetch() -> dict[str, Any]:
        from jalrekha.adapters import claude as claude_adapter

        return {
            "region": cloud.region_name(),
            "ec2": _safe(ec2), "cloudformation": _safe(stack_info), "s3": _safe(s3), "sns": _safe(sns),
            "step_functions": _safe(sfn), "budget": _safe(budget), "cloudwatch_logs": _safe(logs_info), "cloudwatch_alarms": _safe(alarms),
            "polly": {"ok": cloud.tts_enabled(), "voices": ["Kajal (hi-IN, en-IN, neural)"]},
            "api_gateway": {"ok": True, "kind": "HTTP API, VPC link to the instance (port 8000 not public)"},
            "claude": {"ok": claude_adapter.available(), "model": claude_adapter.MODEL},
            "console_url": _console(f"cloudformation/home?region={cloud.region_name()}#/stacks"),
        }

    return _cached("services", 20, fetch)


# --------------------------------------------------------------- evidence
def _evidence_prefix(trace_id: str) -> str:
    if not re.fullmatch(r"tr_[0-9a-f]{6,32}", trace_id):
        raise HTTPException(404, "unknown trace")
    from sqlmodel import Session, select

    from jalrekha.agent.models import AgentTrace
    from jalrekha.db.database import edge_engine

    with Session(edge_engine) as session:
        row = session.exec(select(AgentTrace).where(AgentTrace.trace_id == trace_id)).first()
    if row is None:
        raise HTTPException(404, "unknown trace")
    return f"cycles/{row.site_id}/{row.started_at.isoformat()[:10]}/{trace_id}"


@router.get("/evidence/{trace_id}")
def evidence(trace_id: str) -> dict[str, Any]:
    """Where a cycle's evidence sits in S3. Files are served through the app (the bucket name holds the account id)."""
    _require_aws()
    prefix = _evidence_prefix(trace_id)
    s3, bucket = cloud.client("s3"), os.environ.get("NADISAATHI_S3_BUCKET")
    out: dict[str, Any] = {"trace_id": trace_id, "key": prefix}
    for ext in ("json", "jpg"):
        try:
            head = s3.head_object(Bucket=bucket, Key=f"{prefix}.{ext}")
            out[ext] = {"bytes": head["ContentLength"], "stored": head["LastModified"].isoformat(),
                        "url": f"/api/cloud/evidence/{trace_id}/file.{ext}"}
        except Exception:
            out[ext] = None
    return out


@router.get("/evidence/{trace_id}/file.{ext}")
def evidence_file(trace_id: str, ext: str):
    from fastapi.responses import Response

    _require_aws()
    if ext not in {"json", "jpg"}:
        raise HTTPException(404, "unknown file")
    prefix = _evidence_prefix(trace_id)
    try:
        obj = cloud.client("s3").get_object(Bucket=os.environ.get("NADISAATHI_S3_BUCKET"), Key=f"{prefix}.{ext}")
    except Exception as exc:
        raise HTTPException(404, "not archived") from exc
    return Response(obj["Body"].read(), media_type="application/json" if ext == "json" else "image/jpeg",
                    headers={"Cache-Control": "public, max-age=3600"})
