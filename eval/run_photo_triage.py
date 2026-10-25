"""Claude volunteer-photo triage on real Indian flood photos (Wikimedia Commons, licensed).

Same path as the live relief/volunteer photo check: faces and plates are blurred
with YuNet first, then Claude describes the photo with the PHOTO_SCHEMA. Labels
come from the photo kind in credits.json and are only used where they are clear:
the 7 flooded-road photos plus the flooded Mathura underpass are positives for
"road or bridge flooded"; every photo shows water. n is small (20), so this is a
sanity check on real Indian scenes, not an accuracy claim.

    cd backend && uv run python ../eval/run_photo_triage.py
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

import cv2  # noqa: E402

from jalrekha.adapters import claude  # noqa: E402
from jalrekha.vision import privacy  # noqa: E402

PHOTOS = ROOT / "datasets" / "india_flood_photos"
CREDITS = ROOT / "frontend" / "public" / "images" / "india" / "credits.json"
OUT = ROOT / "eval" / "results" / "photo_triage.json"
ROAD_POSITIVE_EXTRA = {"mathura-underpass-bus-2016"}


def one(p: dict) -> dict:
    img = cv2.imread(str(PHOTOS / "originals" / Path(p["original_file"]).name))
    if max(img.shape[:2]) > 1568:
        s = 1568 / max(img.shape[:2])
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    img, _ = privacy.redact(img)
    ok, jpeg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    road_pos = p["kind"] == "flooded-road" or p["id"] in ROAD_POSITIVE_EXTRA
    try:
        r = claude.describe_flood_photo(jpeg.tobytes())
    except claude.ClaudeUnavailable as exc:
        return {"id": p["id"], "kind": p["kind"], "error": str(exc)}
    d = r.data or {}
    return {"id": p["id"], "kind": p["kind"], "road_flooded_expected": road_pos,
            "water_visible": d.get("water_visible"), "road_or_bridge_flooded": d.get("road_or_bridge_flooded"),
            "people_in_danger_visible": d.get("people_in_danger_visible"), "confidence": d.get("confidence"),
            "description": d.get("description"), "latency_ms": round(r.latency_ms, 1), "cost_usd_est": r.cost_usd_est}


def main() -> int:
    if not claude.available():
        print("ANTHROPIC_API_KEY not set; nothing measured")
        return 1
    photos = json.loads(CREDITS.read_text())
    if not (PHOTOS / "originals").is_dir():
        print("originals missing: run python3 scripts/fetch_india_flood_photos.py first")
        return 1
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=5) as ex:
        rows = list(ex.map(one, photos))
    ok = [r for r in rows if "error" not in r]
    pos = [r for r in ok if r["road_flooded_expected"]]
    res = {
        "meta": {"label": "REAL photos: 20 licensed Wikimedia Commons flood photos from India and Nepal (see docs/PHOTO_CREDITS.md)",
                 "model": f"claude:{claude.MODEL}", "generated_by": "eval/run_photo_triage.py",
                 "generated_at": datetime.now(timezone.utc).isoformat(), "wall_s": round(time.perf_counter() - t0, 1),
                 "note": "small n; labels from photo kind only where clear; faces/plates blurred before upload"},
        "photos": len(ok), "errors": len(rows) - len(ok),
        "water_visible_rate": round(sum(bool(r["water_visible"]) for r in ok) / max(1, len(ok)), 3),
        "road_flooded_positives": len(pos),
        "road_flooded_recall": round(sum(bool(r["road_or_bridge_flooded"]) for r in pos) / max(1, len(pos)), 3),
        "latency_ms_p50": sorted(r["latency_ms"] for r in ok)[len(ok) // 2] if ok else None,
        "cost_usd_per_photo_est": round(sum(r["cost_usd_est"] for r in ok) / max(1, len(ok)), 5),
        "rows": rows,
    }
    OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=1))
    for r in ok:
        print(f"{r['id']:36s} water={r['water_visible']!s:5s} road={r['road_or_bridge_flooded']!s:5s} exp={r['road_flooded_expected']!s:5s} | {r['description'][:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
