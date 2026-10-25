#!/usr/bin/env python3
"""P3 — scripted connectivity-loss demo.

Runs the full narrative: online report -> flip offline -> queued report ->
sample node analysis (fires local siren) -> flip online -> queue drains.
Prints a reproducible timeline with timestamps to stdout.

Usage:
    python3 scripts/demo_connectivity.py            # against default http://127.0.0.1:8000
    API_BASE=http://127.0.0.1:8001 python3 scripts/demo_connectivity.py

Requires: backend running, seed applied, and (optionally) an audio player
(`aplay`, `paplay`, `afplay`, or `ffplay`) for the siren WAV.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000/api").rstrip("/")
SITE_ID = os.environ.get("DEMO_SITE", "silverado-fixed-cam-usgs")
SIREN_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "audio" / "siren.wav"


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log(step: str, msg: str) -> None:
    print(f"[{ts()}] {step:14s} | {msg}", flush=True)


def set_connectivity(online: bool) -> None:
    with httpx.Client(timeout=10) as client:
        r = client.post(f"{API_BASE}/settings/connectivity", json={"is_online": online})
        r.raise_for_status()
    log("connectivity", f"backend is_online={online}")


def submit_report(label: str, transcript: str) -> dict:
    with httpx.Client(timeout=30) as client:
        r = client.post(
            f"{API_BASE}/reports",
            data={
                "site_id": SITE_ID,
                "reporter_name": f"Demo-{label}",
                "reporter_role": "brigadista",
                "transcript_text": transcript,
                "offline_created": label == "offline",
            },
            files={},
        )
        r.raise_for_status()
    payload = r.json()
    alert = payload["alert"]
    log(
        f"report:{label}",
        f"id={payload['report']['id']} alert_level={alert['level']} score={alert['score']:.2f}",
    )
    return payload


def run_sample_analysis() -> dict:
    with httpx.Client(timeout=60) as client:
        r = client.post(f"{API_BASE}/sites/{SITE_ID}/sample-node-analysis")
        r.raise_for_status()
    payload = r.json()
    alert = payload["alert"]
    log("node-analysis", f"alert_level={alert['level']} score={alert['score']:.2f}")
    return payload


def play_siren() -> None:
    if not SIREN_PATH.exists():
        log("siren", "WAV missing, skipping")
        return
    for cmd in (["aplay", "-q"], ["paplay"], ["afplay"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd + [str(SIREN_PATH)], check=False, timeout=5)
                log("siren", f"played via {cmd[0]}")
                return
            except Exception:
                continue
    log("siren", "no audio player found (install aplay/paplay/ffplay)")


def flush() -> dict:
    with httpx.Client(timeout=30) as client:
        r = client.post(f"{API_BASE}/sync/flush")
        r.raise_for_status()
    payload = r.json()
    log("sync:flush", f"queued={payload['queued']} flushed={payload['flushed']} failed={payload['failed']}")
    return payload


def main() -> int:
    log("start", f"API_BASE={API_BASE} SITE_ID={SITE_ID}")
    try:
        with httpx.Client(timeout=5) as client:
            h = client.get(f"{API_BASE}/health")
            h.raise_for_status()
    except Exception as exc:
        log("error", f"backend not reachable: {exc}")
        return 1

    set_connectivity(True)
    submit_report("online", "Agua en cauce normal, solo subida leve.")
    time.sleep(0.5)

    set_connectivity(False)
    submit_report("offline", "El agua ya paso la marca critica y cortamos la ruta.")
    time.sleep(0.5)

    payload = run_sample_analysis()
    if payload["alert"]["level"] in {"orange", "red"}:
        play_siren()
    time.sleep(0.5)

    set_connectivity(True)
    flush()

    log("done", "Demo completed. Inspect /api/alerts, edge.db, central.db.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
