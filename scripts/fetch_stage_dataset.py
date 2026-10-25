#!/usr/bin/env python3
"""Fetch a small labelled river-camera stage dataset from USGS HIVIS + NWIS.

Images: USGS HIVIS (Hydrologic Imagery Visualization and Information System)
webcams, public S3 bucket ``usgs-nims-images`` (``720/`` = 720px-wide copies of
the ``overlay/`` images, which carry a text banner with the local time).
Labels: USGS NWIS instantaneous gauge height (parameter 00065, feet above the
local gauge datum) from https://waterservices.usgs.gov/nwis/iv/.

Each image is labelled with the gauge reading nearest in time, kept only if the
gap is <= --tolerance-min minutes. Only daytime images (local hour in
[--day-start, --day-end)) are kept; the rest are dropped before download.

Usage (Python 3.10, stdlib + httpx):
    python scripts/fetch_stage_dataset.py --out datasets/usgs_hivis_stage
    python scripts/fetch_stage_dataset.py --variant overlay   # full-res (~600 KB/img)

Downloaded files are data only; nothing downloaded is executed.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

S3 = "https://usgs-nims-images.s3.amazonaws.com/"
NIMS = "https://api.waterdata.usgs.gov/nims/v0/"
NWIS_IV = "https://waterservices.usgs.gov/nwis/iv/"
FT_TO_M = 0.3048

# camId, NWIS site, first day, last day (UTC, inclusive). Windows bracket a
# storm hydrograph found by ranking ~800 camera-equipped gauges by
# peak/median discharge over Jul-Oct 2026.
SITES: list[tuple[str, str, str, str]] = [
    ("NY_East_Branch_Delaware_River_at_Hancock_Staff", "01421500", "2026-07-26", "2026-08-02"),
    ("NY_Genesee_River_at_Avon_Staff_Gage", "04228500", "2026-09-01", "2026-09-08"),
    ("NY_Owasco_Inlet_below_Aurora_Street_at_Moravia_Staff", "04235299", "2026-08-31", "2026-09-07"),
    ("IL_Vermilion_River_near_Danville", "03339000", "2026-08-12", "2026-08-20"),
    ("IN_White_River_at_Michigan_Street_at_Indianapolis", "03352953", "2026-08-12", "2026-08-19"),
    ("TX_White_Rk_Ck_at_Greenville_Ave_Dallas", "08057200", "2026-09-28", "2026-10-05"),
]

KEY_TS = re.compile(r"___(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})Z\.jpg$")


def get(client: httpx.Client, url: str, **params) -> httpx.Response:
    for attempt in range(4):
        try:
            r = client.get(url, params=params or None)
            if r.status_code == 200:
                return r
            if r.status_code not in (429, 500, 502, 503, 504):
                r.raise_for_status()
        except httpx.TransportError:
            if attempt == 3:
                raise
        time.sleep(2 * (attempt + 1))
    r.raise_for_status()
    return r


def camera_meta(client: httpx.Client, cam: str) -> dict:
    data = get(client, NIMS + "cameras", camId=cam).json()
    return data[0] if data else {}


def list_keys(client: httpx.Client, variant: str, cam: str, day: date) -> list[str]:
    keys: list[str] = []
    token = None
    while True:
        params = {"list-type": "2", "prefix": f"{variant}/{cam}/{cam}___{day.isoformat()}"}
        if token:
            params["continuation-token"] = token
        text = get(client, S3, **params).text
        keys += re.findall(r"<Key>([^<]+)</Key>", text)
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", text)
        if not m:
            return keys
        token = m.group(1)


def gauge_series(client: httpx.Client, site: str, start: date, end: date) -> list[tuple[datetime, float, str]]:
    r = get(client, NWIS_IV, format="json", sites=site, parameterCd="00065",
            startDT=(start - timedelta(days=1)).isoformat(), endDT=(end + timedelta(days=1)).isoformat(),
            siteStatus="all")
    best: list[tuple[datetime, float, str]] = []
    for ts in r.json()["value"]["timeSeries"]:
        for blk in ts["values"]:  # several blocks when a site has >1 sensor; keep the longest
            vals = []
            for v in blk["value"]:
                x = float(v["value"])
                if x <= -999:  # NWIS no-data sentinel
                    continue
                t = datetime.fromisoformat(v["dateTime"]).astimezone(timezone.utc)
                vals.append((t, x, ",".join(v.get("qualifiers", []))))
            if len(vals) > len(best):
                best = vals
    best.sort()
    return best


def nearest(series, t):
    lo, hi = 0, len(series)
    while lo < hi:
        mid = (lo + hi) // 2
        if series[mid][0] < t:
            lo = mid + 1
        else:
            hi = mid
    cands = [series[i] for i in (lo - 1, lo) if 0 <= i < len(series)]
    return min(cands, key=lambda s: abs((s[0] - t).total_seconds())) if cands else None


def even_subsample(items: list, n: int) -> list:
    if len(items) <= n:
        return items
    step = (len(items) - 1) / (n - 1)
    return [items[round(i * step)] for i in range(n)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="datasets/usgs_hivis_stage")
    ap.add_argument("--variant", default="720", choices=["720", "overlay", "thumbnail"])
    ap.add_argument("--tolerance-min", type=float, default=10.0)
    ap.add_argument("--max-per-site", type=int, default=120)
    ap.add_argument("--day-start", type=int, default=8, help="local hour, inclusive")
    ap.add_argument("--day-end", type=int, default=19, help="local hour, exclusive")
    args = ap.parse_args()

    out = Path(args.out)
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "gauge").mkdir(exist_ok=True)
    rows, site_rows, summary = [], [], {}

    with httpx.Client(timeout=120, headers={"User-Agent": "JalRekha-dataset-fetch/1.0"}) as client:
        for cam, site, d0s, d1s in SITES:
            d0, d1 = date.fromisoformat(d0s), date.fromisoformat(d1s)
            meta = camera_meta(client, cam)
            tz = ZoneInfo(meta.get("tz") or "UTC")
            series = gauge_series(client, site, d0, d1)
            with open(out / "gauge" / f"{site}_00065.csv", "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["timestamp_utc", "stage_ft", "stage_m", "qualifiers"])
                for t, x, q in series:
                    w.writerow([t.strftime("%Y-%m-%dT%H:%M:%SZ"), x, round(x * FT_TO_M, 4), q])

            keys, day = [], d0
            while day <= d1:
                keys += list_keys(client, args.variant, cam, day)
                day += timedelta(days=1)
            cand, n_night, n_nomatch = [], 0, 0
            for k in sorted(keys):
                m = KEY_TS.search(k)
                if not m:
                    continue
                t = datetime.strptime(m.group(1), "%Y-%m-%dT%H-%M-%S").replace(tzinfo=timezone.utc)
                lt = t.astimezone(tz)
                if not (args.day_start <= lt.hour < args.day_end):
                    n_night += 1
                    continue
                g = nearest(series, t)
                dt = abs((g[0] - t).total_seconds()) if g else 1e9
                if dt > args.tolerance_min * 60:
                    n_nomatch += 1
                    continue
                cand.append((k, t, lt, g, dt))
            chosen = even_subsample(cand, args.max_per_site)

            img_dir = out / "images" / cam
            img_dir.mkdir(exist_ok=True)
            for k, t, lt, g, dt in chosen:
                fn = k.rsplit("/", 1)[1]
                dest = img_dir / fn
                url = S3 + k
                if not dest.exists():
                    dest.write_bytes(get(client, url).content)
                rows.append({
                    "site_id": cam,
                    "image_path": f"images/{cam}/{fn}",
                    "timestamp_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "stage_m": round(g[1] * FT_TO_M, 4),
                    "stage_ft": g[1],
                    "gauge_site": site,
                    "match_gap_min": round(dt / 60, 2),
                    "source_url": url,
                    "gauge_timestamp_utc": g[0].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "qualifiers": g[2],
                    "local_time": lt.isoformat(),
                })
            st = [c[3][1] for c in chosen]
            summary[cam] = {
                "nwis_site": site, "window_utc": [d0s, d1s], "images_listed": len(keys),
                "dropped_night": n_night, "dropped_no_gauge_match": n_nomatch, "kept": len(chosen),
                "stage_ft_min": min(st) if st else None, "stage_ft_max": max(st) if st else None,
                "gauge_points": len(series),
            }
            site_rows.append({
                "site_id": cam, "nwis_site": site, "name": meta.get("camDesc", ""),
                "lat": meta.get("lat", ""), "lng": meta.get("lng", ""), "tz": meta.get("tz", ""),
                "hivis_url": f"https://apps.usgs.gov/hivis/camera/{cam}",
                "nwis_url": f"https://waterdata.usgs.gov/monitoring-location/USGS-{site}/",
            })
            print(f"{cam}: kept {len(chosen)} (listed {len(keys)}, night {n_night}, "
                  f"no-match {n_nomatch}) stage {summary[cam]['stage_ft_min']}-{summary[cam]['stage_ft_max']} ft",
                  file=sys.stderr)

    fields = list(rows[0].keys())
    with open(out / "labels.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    with open(out / "sites.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(site_rows[0].keys()))
        w.writeheader()
        w.writerows(site_rows)
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"wrote {len(rows)} labelled images to {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
