#!/usr/bin/env python3
"""Fetch upstream/downstream river-gauge pairs from USGS NWIS for the lead-time evaluation.

Data: USGS NWIS instantaneous values, parameter 00065 (gauge height, feet above
the local gauge datum), https://waterservices.usgs.gov/nwis/iv/ . Fetched one
site-year at a time with a pause between requests; raw responses are cached
(gzipped) outside the repo so a re-run does not hit the service again.
Optional: NWS flood categories (action/minor/moderate/major stage) for each
gauge from the NOAA National Water Prediction Service API
(https://api.water.noaa.gov/nwps/v1/gauges/<usgs id>), with a datum check
against the latest USGS reading.

Output (datasets/usgs_hydro_pairs/):
  sites/<site>.csv.gz   timestamp_utc,stage_m,qualifiers on a 15-min UTC grid
  pairs.json            pairs, site metadata, coverage checks, NWS categories
  README.md             sources, licence, fetch date

Usage (from repo root):
    cd backend && uv run python ../eval/fetch_hydro_pairs.py
    # options: --out DIR, --cache DIR, --pause S, --min-coverage F

Downloaded files are data only; nothing downloaded is executed.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import math
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
NWIS_IV = "https://waterservices.usgs.gov/nwis/iv/"
NWPS = "https://api.water.noaa.gov/nwps/v1/gauges/"
FT_TO_M = 0.3048
START = date(2021, 1, 1)
END = date(2026, 10, 1)  # inclusive
TRAIN_END = date(2023, 12, 31)
UA = {"User-Agent": "NadiSaathi-leadtime-eval/1.0 (research; contact via repository)"}

# Upstream -> downstream on the same main stem. Chosen for hours of travel
# time and frequent high water; verified for 00065 coverage below.
PAIRS: list[dict] = [
    {"id": "delaware_callicoon_montague", "river": "Delaware River", "up": "01427510", "down": "01438500"},
    {"id": "delaware_montague_trenton", "river": "Delaware River", "up": "01438500", "down": "01463500"},
    {"id": "susquehanna_conklin_wilkesbarre", "river": "Susquehanna River", "up": "01503000", "down": "01536500"},
    {"id": "susquehanna_wilkesbarre_harrisburg", "river": "Susquehanna River", "up": "01536500", "down": "01570500"},
    {"id": "potomac_hancock_pointofrocks", "river": "Potomac River", "up": "01613000", "down": "01638500"},
    {"id": "potomac_pointofrocks_littlefalls", "river": "Potomac River", "up": "01638500", "down": "01646500"},
    {"id": "juniata_huntingdon_newport", "river": "Juniata River", "up": "01559000", "down": "01567000"},
    {"id": "wabash_lafayette_terrehaute", "river": "Wabash River", "up": "03335500", "down": "03341500"},
]


def get(client: httpx.Client, url: str, params: dict | None = None) -> httpx.Response:
    last = None
    for attempt in range(5):
        try:
            r = client.get(url, params=params)
            if r.status_code == 200:
                return r
            last = r
            if r.status_code not in (429, 500, 502, 503, 504):
                r.raise_for_status()
        except httpx.TransportError:
            if attempt == 4:
                raise
        time.sleep(3 * (attempt + 1))
    assert last is not None
    last.raise_for_status()
    return last


def fetch_year(client: httpx.Client, cache: Path, site: str, year: int, pause: float) -> dict:
    """Raw NWIS JSON for one site-year (cached gzipped)."""
    f = cache / f"{site}_{year}.json.gz"
    if f.exists():
        return json.loads(gzip.decompress(f.read_bytes()))
    a = date(year, 1, 1)
    b = min(date(year, 12, 31), END)
    r = get(client, NWIS_IV, {"format": "json", "sites": site, "parameterCd": "00065",
                              "startDT": a.isoformat(), "endDT": b.isoformat(), "siteStatus": "all"})
    f.write_bytes(gzip.compress(r.content))
    time.sleep(pause)
    return r.json()


def parse(raw: dict) -> tuple[list[tuple[datetime, float, str]], dict]:
    """Longest value block (a site may have more than one sensor) and site info."""
    best: list[tuple[datetime, float, str]] = []
    info: dict = {}
    for ts in raw.get("value", {}).get("timeSeries", []):
        si = ts["sourceInfo"]
        loc = si.get("geoLocation", {}).get("geogLocation", {})
        info = {"name": si.get("siteName"), "lat": loc.get("latitude"), "lon": loc.get("longitude")}
        nodata = float(ts["variable"].get("noDataValue", -999999.0))
        for blk in ts["values"]:
            vals = []
            for v in blk["value"]:
                try:
                    x = float(v["value"])
                except (TypeError, ValueError):
                    continue
                if x == nodata or x <= -999:
                    continue
                t = datetime.fromisoformat(v["dateTime"]).astimezone(timezone.utc)
                vals.append((t, x, ",".join(v.get("qualifiers", []))))
            if len(vals) > len(best):
                best = vals
    return best, info


def to_grid(vals: list[tuple[datetime, float, str]]) -> dict[datetime, tuple[float, str]]:
    """15-min UTC grid: per bin, the reading at the bin start if present, else the first one."""
    out: dict[datetime, tuple[float, str]] = {}
    for t, x, q in sorted(vals):
        b = t.replace(minute=t.minute - t.minute % 15, second=0, microsecond=0)
        if b not in out or t == b:
            out[b] = (x, q)
    return out


def slots(a: date, b: date) -> int:
    return ((b - a).days + 1) * 96


def nws_categories(client: httpx.Client, site: str, latest_ft: tuple[datetime, float] | None) -> dict | None:
    try:
        r = client.get(NWPS + site, timeout=30)
        if r.status_code != 200:
            return None
        g = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    cats = (g.get("flood") or {}).get("categories") or {}
    stages = {k: (v or {}).get("stage") for k, v in cats.items()}
    stages = {k: v for k, v in stages.items() if isinstance(v, (int, float)) and v > -999}
    obs = ((g.get("status") or {}).get("observed") or {})
    out = {"lid": g.get("lid"), "name": g.get("name"), "units": (g.get("flood") or {}).get("stageUnits"),
           "stages_ft": stages, "source": NWPS + site,
           "nwps_observed_ft": obs.get("primary"), "nwps_observed_time": obs.get("validTime")}
    # Datum check: NWPS observed stage vs the USGS reading nearest that time.
    if latest_ft is not None and isinstance(obs.get("primary"), (int, float)):
        out["usgs_latest_ft"] = latest_ft[1]
        out["usgs_latest_time"] = latest_ft[0].isoformat()
        out["datum_diff_ft"] = round(obs["primary"] - latest_ft[1], 3)
    return out


def latest_usgs(client: httpx.Client, site: str, when: str | None) -> tuple[datetime, float] | None:
    try:
        r = get(client, NWIS_IV, {"format": "json", "sites": site, "parameterCd": "00065", "period": "P2D"})
        vals, _ = parse(r.json())
    except httpx.HTTPError:
        return None
    if not vals:
        return None
    if when:
        t = datetime.fromisoformat(when.replace("Z", "+00:00"))
        return min(((v[0], v[1]) for v in vals), key=lambda v: abs((v[0] - t).total_seconds()))
    return vals[-1][0], vals[-1][1]


def haversine_km(a: dict, b: dict) -> float | None:
    if None in (a.get("lat"), a.get("lon"), b.get("lat"), b.get("lon")):
        return None
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dl = math.radians(b["lon"] - a["lon"])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * 6371.0 * math.asin(math.sqrt(h)), 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "datasets" / "usgs_hydro_pairs"))
    ap.add_argument("--cache", default=os.path.join(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")),
                                                    "nadisaathi", "usgs_nwis_iv"))
    ap.add_argument("--pause", type=float, default=1.0, help="seconds between NWIS requests")
    ap.add_argument("--min-coverage", type=float, default=0.80,
                    help="minimum fraction of hours with data, in TRAIN and in TEST, for a site to be used")
    args = ap.parse_args()
    out, cache = Path(args.out), Path(args.cache)
    (out / "sites").mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0)

    sites = sorted({p[k] for p in PAIRS for k in ("up", "down")})
    meta: dict[str, dict] = {}
    with httpx.Client(timeout=180, follow_redirects=True, headers=UA) as client:
        for site in sites:
            vals: list = []
            info: dict = {}
            for year in range(START.year, END.year + 1):
                v, i = parse(fetch_year(client, cache, site, year, args.pause))
                vals += v
                info = info or i
            grid = to_grid(vals)
            lo = datetime(START.year, START.month, START.day, tzinfo=timezone.utc)
            hi = datetime(END.year, END.month, END.day, tzinfo=timezone.utc) + timedelta(days=1)
            keys = sorted(k for k in grid if lo <= k < hi)
            # Coverage = fraction of hours with at least one reading (some sites report every 30 min).
            hours = {k.replace(minute=0) for k in keys}
            n_tr = sum(1 for h in hours if h.date() <= TRAIN_END)
            n_te = len(hours) - n_tr
            cov_tr = n_tr / (slots(START, TRAIN_END) / 4)
            cov_te = n_te / (slots(TRAIN_END + timedelta(days=1), END) / 4)
            steps = sorted({int((b - a).total_seconds() // 60) for a, b in zip(keys[:-1], keys[1:]) if (b - a) <= timedelta(hours=1)})
            buf = io.StringIO()
            w = csv.writer(buf, lineterminator="\n")
            w.writerow(["timestamp_utc", "stage_m", "qualifiers"])
            for k in keys:
                x, q = grid[k]
                w.writerow([k.strftime("%Y-%m-%dT%H:%MZ"), f"{x * FT_TO_M:.4f}", q])
            # mtime=0 keeps the gzip bytes reproducible across re-runs.
            (out / "sites" / f"{site}.csv.gz").write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))
            ok = cov_tr >= args.min_coverage and cov_te >= args.min_coverage
            meta[site] = {**info, "n_15min": len(keys), "coverage_train": round(cov_tr, 4),
                          "coverage_test": round(cov_te, 4), "usable": ok,
                          "cadence_min_seen": steps[:4],
                          "first": keys[0].isoformat() if keys else None, "last": keys[-1].isoformat() if keys else None,
                          "nwis_url": f"{NWIS_IV}?format=json&sites={site}&parameterCd=00065"}
            print(f"{site} {info.get('name')}: {len(keys)} pts, coverage train {cov_tr:.3f} test {cov_te:.3f}"
                  f" {'OK' if ok else 'DROP'}", flush=True)
        for site in sites:
            g = nws_categories(client, site, None)
            if g is not None and g.get("nwps_observed_time"):
                g = nws_categories(client, site, latest_usgs(client, site, g["nwps_observed_time"]))
            meta[site]["nws"] = g
            time.sleep(args.pause / 2)

    pairs_out = []
    for p in PAIRS:
        up, dn = meta[p["up"]], meta[p["down"]]
        usable = up["usable"] and dn["usable"]
        pairs_out.append({**p, "up_name": up.get("name"), "down_name": dn.get("name"),
                          "straight_line_km": haversine_km(up, dn), "usable": usable,
                          "dropped_reason": None if usable else "00065 coverage below threshold"})
    doc = {
        "schema": "nadisaathi-usgs-hydro-pairs-v1",
        "fetched_at_utc": fetched_at.isoformat(),
        "period": {"start": START.isoformat(), "end": END.isoformat(), "train_end": TRAIN_END.isoformat()},
        "parameter": "00065 gauge height, converted ft -> m (x 0.3048), local gauge datum (not comparable across sites)",
        "grid": "15-min UTC; per bin the reading at the bin start, else the first reading in the bin",
        "min_coverage": args.min_coverage,
        "source": "USGS NWIS instantaneous values, https://waterservices.usgs.gov/nwis/iv/",
        "nws_source": "NOAA NWPS gauge API, https://api.water.noaa.gov/nwps/v1/gauges/<usgs id> (flood categories, ft)",
        "licence": "U.S. public domain, credit U.S. Geological Survey (gauge data); NWS flood categories are U.S. Government work",
        "pairs": pairs_out,
        "sites": meta,
    }
    (out / "pairs.json").write_text(json.dumps(doc, indent=1))
    write_readme(out, doc)
    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"wrote {out} ({total / 1e6:.1f} MB); usable pairs: {sum(p['usable'] for p in pairs_out)}/{len(pairs_out)}")
    return 0


def write_readme(out: Path, doc: dict) -> None:
    rows = []
    for p in doc["pairs"]:
        rows.append(f"| {p['id']} | {p['river']} | {p['up']} {p['up_name']} | {p['down']} {p['down_name']} | "
                    f"{p['straight_line_km']} | {'yes' if p['usable'] else 'no (' + str(p['dropped_reason']) + ')'} |")
    srows = []
    for s, m in sorted(doc["sites"].items()):
        n = m.get("nws") or {}
        st = n.get("stages_ft") or {}
        srows.append(f"| {s} | {m.get('name')} | {m['n_15min']} | {m['coverage_train']:.3f} | {m['coverage_test']:.3f} | "
                     f"{st.get('action', '-')} | {st.get('minor', '-')} | {n.get('datum_diff_ft', '-')} |")
    text = f"""# USGS river-gauge pairs for the lead-time evaluation

Upstream/downstream pairs of USGS stream gauges on the same main stem, used by
`eval/run_leadtime.py` to measure how much earlier a downstream community is
warned when the alert rule also watches the upstream gauge.

These are **U.S. rivers**. Public multi-year gauge series for the Nepal/India
rivers the system targets are not available, so this measures the mechanism on
real U.S. data. It does not measure performance in Nepal or India.

- **Source:** USGS National Water Information System (NWIS), instantaneous values,
  parameter `00065` (gauge height), {doc['source']}
- **Flood categories (optional):** {doc['nws_source']}
- **Licence:** U.S. public domain. Credit: U.S. Geological Survey.
- **Fetched:** {doc['fetched_at_utc']} (UTC)
- **Period:** {doc['period']['start']} to {doc['period']['end']} (TRAIN to {doc['period']['train_end']}, TEST after)
- **Rebuild:** `cd backend && uv run python ../eval/fetch_hydro_pairs.py` (raw NWIS JSON is cached under `~/.cache/nadisaathi/usgs_nwis_iv/`)

## Files

| file | content |
|---|---|
| `sites/<site>.csv.gz` | gzipped CSV, `timestamp_utc,stage_m,qualifiers`, 15-min UTC grid |
| `pairs.json` | pairs, site names/coordinates, coverage checks, NWS categories and datum check |

`stage_m` = NWIS gauge height in feet x 0.3048, above the **local gauge datum**;
values are not elevations and cannot be compared between sites. Qualifiers are
the NWIS codes (`A` approved, `P` provisional, `e` estimated, ...). Missing
15-min slots are simply absent (ice, equipment, gaps).

A site is used only if at least {doc['min_coverage']:.0%} of the hours have at least
one reading in both TRAIN and TEST (some gauges report every 30 min; those slots
in between are absent, not interpolated). A pair is dropped if either site fails.

## Pairs

| pair | river | upstream | downstream | straight-line km | used |
|---|---|---|---|---|---|
{chr(10).join(rows)}

## Sites

`datum diff` = NWPS observed stage minus the USGS reading at the same time (ft);
near 0 means the NWS flood categories are on the USGS gauge datum.

| site | name | 15-min points | hourly coverage TRAIN | hourly coverage TEST | NWS action ft | NWS minor ft | datum diff ft |
|---|---|---|---|---|---|---|---|
{chr(10).join(srows)}
"""
    (out / "README.md").write_text(text)


if __name__ == "__main__":
    sys.exit(main())
