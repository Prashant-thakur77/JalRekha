"""Playwright recorder for Persona C escalada.

Launches Chromium headless at 1440x900, opens the operator dashboard, and fires
the 3 actos via direct HTTP calls to the backend. Records a webm of the entire
session. Convert to mp4 in post with ffmpeg if needed.

Usage:
  cd "$(git rev-parse --show-toplevel)"/scripts/demo_persona_c
  bash 00_reset.sh
  python3 record_demo.py --out /tmp/persona_c_demo.webm
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
from pathlib import Path

import httpx
from playwright.async_api import async_playwright


API = os.environ.get("API", "http://127.0.0.1:8000")
FRONTEND = os.environ.get("FRONTEND", "http://127.0.0.1:5173")
SITE = os.environ.get("SITE", "puente-arroyo-01")
SITE_LABEL = os.environ.get("SITE_LABEL", "Arroyo Bridge 01")

# Coherent geography: water moves from upstream (Act 1 routine JalRekha Volunteer report) to
# the bridge (Act 2 fixed camera), then overflows toward the low neighborhood.
# Each summary keeps the location explicit so the operator understands the
# downstream event trajectory.
ACT1 = {
    "site_id": SITE,
    "reporter_name": "Neighbor Mendez (upstream)",
    "reporter_role": "citizen",
    "transcript_text": "Upstream: heavy rain, but the channel is flowing normally with no risk yet.",
    "severity_score": 0.20,
    "water_level_category": "low",
    "trend": "stable",
    "road_status": "open",
    "urgency": "low",
    "summary": "JalRekha Volunteer upstream: heavy rain, channel flowing normally with no overflow.",
}

ACT2 = {
    "site_id": SITE,
    "severity_score": 0.52,
    "waterline_ratio": 0.62,
    "rise_velocity": 0.05,
    "crossed_critical_line": False,
    "confidence": 0.81,
    "assessment_level": "elevated",
    "temporal_summary": "Fixed bridge camera: water level exceeds the reference line without crossing the critical line.",
}

ACT3_REPORTS = [
    {
        "reporter_name": "Neighbor Lopez (near the bridge)",
        "reporter_role": "citizen",
        "transcript_text": "Near the bridge: water passed the painted mark.",
        "severity_score": 0.78, "water_level_category": "high", "trend": "rising",
        "road_status": "open", "homes_affected": False, "urgency": "critical",
        "summary": "JalRekha Volunteer bridge: water mark exceeded, level still rising.",
    },
    {
        "reporter_name": "Volunteer Sosa (central square)",
        "reporter_role": "brigade_member",
        "transcript_text": "Central square: streets are flooded and impassable.",
        "severity_score": 0.74, "water_level_category": "high", "trend": "rising",
        "road_status": "blocked", "homes_affected": False, "urgency": "critical",
        "summary": "JalRekha Volunteer square: roads cut off, traffic interrupted.",
    },
    {
        "reporter_name": "Neighbor Diaz (low neighborhood)",
        "reporter_role": "citizen",
        "transcript_text": "Low neighborhood: water is entering homes, families evacuated.",
        "severity_score": 0.88, "water_level_category": "critical", "trend": "rising",
        "road_status": "blocked", "homes_affected": True, "urgency": "critical",
        "summary": "JalRekha Volunteer low neighborhood: water inside homes, evacuation in progress.",
    },
]


async def post(client: httpx.AsyncClient, path: str, payload: dict) -> dict:
    r = await client.post(f"{API}{path}", json=payload, timeout=60)
    r.raise_for_status()
    return r.json()


async def emit_cap(client: httpx.AsyncClient, alert: dict) -> None:
    sev_map = {"red": "severe", "orange": "severe", "yellow": "moderate", "green": "minor"}
    payload = {
        "site_id": alert["site_id"],
        "lat": -32.9468,
        "lon": -60.6393,
        "severity": sev_map.get(alert["level"], "minor"),
        "headline": f"{alert['level'].upper()} alert at {SITE_LABEL}",
        "summary": alert["summary"],
        "instruction": "Activate Civil Defense protocol and evacuate flooded areas.",
        "areaDesc": SITE_LABEL,
    }
    r = await client.post(f"{API}/cap/emit", json=payload, timeout=30)
    r.raise_for_status()
    out = Path("/tmp") / f"cap_alert_{alert['id']}.xml"
    out.write_bytes(r.content)
    print(f"  CAP -> {out}")


async def run(out_path: Path, chromium_path: str | None) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    video_dir = out_path.parent / f"_video_tmp_{os.getpid()}"
    video_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        launch_kwargs = {
            "headless": True,
            "args": ["--no-sandbox", "--disable-dev-shm-usage"],
        }
        if chromium_path:
            launch_kwargs["executable_path"] = chromium_path
        browser = await pw.chromium.launch(**launch_kwargs)
        VIEW_W, VIEW_H = 1440, 900
        context = await browser.new_context(
            viewport={"width": VIEW_W, "height": VIEW_H},
            record_video_dir=str(video_dir),
            record_video_size={"width": VIEW_W, "height": VIEW_H},
        )
        page = await context.new_page()

        # Pre-inject Act 1 BEFORE opening the dashboard so the very first paint
        # already shows the live green alert (no DEMO_ALERT CRITICO fallback).
        async with httpx.AsyncClient() as client:
            print("[rec] PRE-INJECT verde (baseline)")
            r0 = await post(client, "/api/demo/inject-volunteer-report", ACT1)
            print(f"  -> {r0['alert']['level']} score={r0['alert']['score']}")

        print(f"[rec] open {FRONTEND}")
        await page.goto(FRONTEND, wait_until="networkidle")
        await page.wait_for_timeout(5000)

        async def refresh():
            await page.reload(wait_until="networkidle")
            await page.wait_for_timeout(1500)

        async def scroll_to(y: int, steps: int = 12, dwell: int = 1200):
            """Smooth scroll to absolute y over `steps` increments, then dwell."""
            current = await page.evaluate("window.scrollY")
            delta = (y - current) / max(1, steps)
            for i in range(steps):
                await page.evaluate(f"window.scrollTo({{top: {current + delta * (i + 1)}, behavior: 'instant'}})")
                await page.wait_for_timeout(80)
            await page.wait_for_timeout(dwell)

        async def dump_dom_check(label: str) -> dict:
            """Pull live tile + banner text from DOM for consistency check."""
            data = await page.evaluate("""() => {
                const pick = (sel) => Array.from(document.querySelectorAll(sel)).map(e => e.innerText.replace(/\\s+/g,' ').trim());
                return {
                    banner: pick('header, [class*="risk"], [class*="Risk"]').slice(0, 3),
                    bigNums: pick('.text-3xl').slice(0, 6),
                    monoBadges: pick('.font-mono').slice(0, 12),
                };
            }""")
            print(f"[verify {label}] bigNums={data['bigNums']} mono={data['monoBadges'][:6]}")
            return data

        async with httpx.AsyncClient() as client:
            # === ACTO 1: baseline verde, ya pre-inyectado ===
            print("[rec] ACTO 1 verde (baseline already on screen)")
            await scroll_to(0, dwell=2500)              # banner verde + top
            await dump_dom_check("act1_top")
            await scroll_to(420, dwell=2000)            # tiles fusion
            await dump_dom_check("act1_fusion")

            # === ACTO 2: camara fija detecta cota elevada ===
            print("[rec] ACTO 2 amarillo")
            r2 = await post(client, "/api/demo/inject-node-observation", ACT2)
            print(f"  -> {r2['alert']['level']} score={r2['alert']['score']}")
            await refresh()
            await scroll_to(0, dwell=2000)              # banner pasa a amarillo
            await scroll_to(420, dwell=2200)            # tile camara sube
            await dump_dom_check("act2_fusion")
            await scroll_to(760, dwell=2000)            # camera evidence frame
            await dump_dom_check("act2_evidence")

            # === ACTO 3: 3 volunteer criticos ===
            print("[rec] ACTO 3 rojo")
            for i, rep in enumerate(ACT3_REPORTS, 1):
                rep_full = {"site_id": SITE, **rep}
                r3 = await post(client, "/api/demo/inject-volunteer-report", rep_full)
                print(f"  R{i} -> {r3['alert']['level']} score={r3['alert']['score']}")
                await refresh()
                await scroll_to(0, dwell=1400)          # banner rojo
                await scroll_to(420, dwell=1600)        # tiles
                await scroll_to(1180, dwell=1400)       # Gemma reasoning
                await dump_dom_check(f"act3_r{i}")

            # === ACTO 4: razonamiento + traza + acciones operador ===
            await scroll_to(1450, dwell=2500)           # audit trace
            await dump_dom_check("act4_audit")
            await scroll_to(0, dwell=1200)              # back to top, right column
            # right column has CAP + actions; viewport 1440 wide shows both cols
            await scroll_to(300, dwell=2500)            # CAP card + action rail

            print("[rec] ACTO 4 CAP emit")
            alerts = (await client.get(f"{API}/api/alerts", timeout=30)).json()
            target = next(a for a in alerts if a["site_id"] == SITE)
            await emit_cap(client, target)
            await refresh()
            await scroll_to(300, dwell=2200)
            await dump_dom_check("act4_cap")
            await scroll_to(1900, dwell=2500)           # final timeline
            await dump_dom_check("act4_timeline")
            await scroll_to(0, dwell=2000)              # close on banner critico

        # finalize: close page -> video flushed
        video = page.video
        await context.close()
        await browser.close()
        if video is not None:
            src = Path(await video.path())
            if src.exists():
                shutil.move(str(src), str(out_path))
                print(f"[rec] saved {out_path} ({out_path.stat().st_size/1024:.1f} KB)")
        for leftover in video_dir.glob("*"):
            leftover.unlink()
        video_dir.rmdir()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="/tmp/persona_c_demo.webm")
    p.add_argument("--chromium", default=None, help="Path to system chromium binary")
    args = p.parse_args()
    out = Path(args.out)
    try:
        asyncio.run(run(out, args.chromium))
    except Exception as exc:
        print(f"[rec] FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
