"""Structured agent-cycle events in CloudWatch Logs, and per-stage OpenCV metrics.

Every agent cycle becomes one JSON event in the stack log group, stream
``agent-cycles/<host>``. The message is pure JSON, so CloudWatch Logs Insights
discovers its fields (``ms.register``, ``branches.0``, ``stage_m`` ...) without
parsing. The OpenCV stage timings also go to CloudWatch metrics (namespace
NadiSaathi, dimension Stage) so the dashboard and the app can chart them, and
the event plus its redacted overlay are archived in S3 as the evidence record
(``cycles/<site>/<date>/<trace>.json|.jpg``).

Events are buffered and flushed from one background thread; nothing here can
slow down or fail an agent cycle. Disabled when AWS is off (tests, local dev).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from typing import Any

from jalrekha.agent import cloud

_LOGGER = logging.getLogger(__name__)
_LOCK = threading.Lock()
_BUFFER: list[dict[str, Any]] = []
_THREAD: threading.Thread | None = None
_STREAM_READY = False
FLUSH_EVERY_S = 2.0
STAGES = ("register", "warp", "quality", "median", "E1_edge", "E2_temporal", "E3_colour", "fuse", "redact", "overlay", "total")


def log_group() -> str | None:
    return os.environ.get("NADISAATHI_LOG_GROUP") or None


def stream_name() -> str:
    return f"agent-cycles/{socket.gethostname()}"


def enabled() -> bool:
    return cloud.aws_enabled() and log_group() is not None


def cycle_event(row, md: dict, steps: list[dict], cadence_s: int | None, mode: str | None) -> dict[str, Any]:
    """The JSON document for one cycle. Only facts already in the trace; no secrets, no account ids."""
    reading = md.get("reading") or {}
    reg = md.get("registration") or {}
    q = md.get("quality") or {}
    vlm = next((s for s in steps if s.get("tool") == "verify_with_vlm" and s.get("kind") != "decision"), None)
    return {
        "event": "agent_cycle",
        "trace_id": row.trace_id,
        "site": row.site_id,
        "cycle": row.cycle,
        "run": row.scenario_run_id,
        "at": row.started_at.isoformat() + "Z",
        "branches": json.loads(row.branches),
        "summary": row.summary[:300],
        "stage_m": reading.get("stage_m"),
        "sigma_m": reading.get("sigma_m"),
        "usable": md.get("usable"),
        "quality_ok": q.get("ok"),
        "quality_reasons": q.get("reasons", []),
        "registration": reg.get("method"),
        "inliers": reg.get("inliers"),
        "estimators_m": reading.get("per_estimator_m"),
        "frames": md.get("frames"),
        "ms": {k: round(float(v), 2) for k, v in (md.get("timings_ms") or {}).items()},
        "second_opinion": None if vlm is None else {"model": vlm.get("model"), "latency_ms": vlm.get("latency_ms"),
                                                    "cost_usd": vlm.get("cost_usd_est")},
        "cadence_s": cadence_s,
        "mode": mode,
    }


def archive_prefix(event: dict[str, Any]) -> str:
    return f"cycles/{event['site']}/{event['at'][:10]}/{event['trace_id']}"


def emit_cycle(event: dict[str, Any]) -> None:
    if not enabled():
        return
    if os.environ.get("NADISAATHI_S3_BUCKET"):
        event["s3_key"] = archive_prefix(event) + ".json"
        threading.Thread(target=_archive, args=(dict(event),), daemon=True).start()
    with _LOCK:
        _BUFFER.append({"timestamp": int(time.time() * 1000), "message": json.dumps(event, ensure_ascii=False, default=str)})
        _ensure_thread()
    ms = event.get("ms") or {}
    metrics = [{"MetricName": "StageMs", "Value": float(ms[s]), "Unit": "Milliseconds",
                "Dimensions": [{"Name": "Stage", "Value": s}]} for s in STAGES if s in ms]
    if metrics:
        _put_metric_data(metrics)


def _archive(event: dict[str, Any]) -> None:
    """Evidence archive in S3: the cycle event and its redacted overlay (faces and plates already blurred)."""
    s3 = cloud.client("s3")
    if s3 is None:
        return
    bucket, prefix = os.environ["NADISAATHI_S3_BUCKET"], archive_prefix(event)
    try:
        s3.put_object(Bucket=bucket, Key=prefix + ".json", ContentType="application/json",
                      Body=json.dumps(event, ensure_ascii=False, default=str).encode())
        from jalrekha.services.storage import get_upload_dir

        overlay = get_upload_dir() / "agent" / event["site"] / f"{event['trace_id']}-overlay.jpg"
        if overlay.is_file():
            s3.put_object(Bucket=bucket, Key=prefix + ".jpg", ContentType="image/jpeg", Body=overlay.read_bytes())
    except Exception as exc:
        _LOGGER.debug("cycle archive failed: %s", exc)


def _put_metric_data(metrics: list[dict[str, Any]]) -> None:
    cw = cloud.client("cloudwatch")
    if cw is None:
        return

    def _send() -> None:
        try:
            for i in range(0, len(metrics), 20):
                cw.put_metric_data(Namespace="NadiSaathi", MetricData=metrics[i:i + 20])
        except Exception as exc:  # metrics are best effort
            _LOGGER.debug("stage metrics failed: %s", exc)

    threading.Thread(target=_send, daemon=True).start()


def _ensure_thread() -> None:
    global _THREAD
    if _THREAD is None or not _THREAD.is_alive():
        _THREAD = threading.Thread(target=_loop, name="cloudlog", daemon=True)
        _THREAD.start()


def _loop() -> None:
    while True:
        time.sleep(FLUSH_EVERY_S)
        try:
            flush()
        except Exception as exc:
            _LOGGER.warning("cloudlog flush failed: %s", exc)


def flush() -> int:
    """Send buffered events. Returns how many were sent."""
    global _STREAM_READY
    with _LOCK:
        batch, _BUFFER[:] = list(_BUFFER), []
    if not batch:
        return 0
    logs = cloud.client("logs")
    if logs is None:
        return 0
    if not _STREAM_READY:
        try:
            logs.create_log_stream(logGroupName=log_group(), logStreamName=stream_name())
        except logs.exceptions.ResourceAlreadyExistsException:
            pass
        _STREAM_READY = True
    batch.sort(key=lambda e: e["timestamp"])
    logs.put_log_events(logGroupName=log_group(), logStreamName=stream_name(), logEvents=batch)
    return len(batch)
