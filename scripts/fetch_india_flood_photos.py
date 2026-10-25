#!/usr/bin/env python3
"""Re-download the India / India-Nepal flood photo set from Wikimedia Commons.

The list of photos lives in ``frontend/public/images/india/credits.json``. Each
entry carries the Commons file title, the original file URL, the expected
SHA-1 (as reported by the Commons API) and the licence. This script fetches
every original into ``datasets/india_flood_photos/originals/<id>.<ext>`` and
checks its SHA-1. With ``--web`` it also rebuilds the web copies
(``frontend/public/images/india/<id>-1600.webp`` and ``<id>-800.webp``,
EXIF stripped); that step needs Pillow, so run it from the backend env:

    python scripts/fetch_india_flood_photos.py               # originals only
    cd backend && uv run python ../scripts/fetch_india_flood_photos.py --web
    python scripts/fetch_india_flood_photos.py --force       # re-download all

Every photo is under a free licence (public domain, CC0, CC BY or CC BY-SA);
reusing them requires the attribution listed in credits.json and
docs/PHOTO_CREDITS.md. Downloaded files are data only; nothing is executed.
Stdlib + httpx (+ Pillow for --web).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
CREDITS = ROOT / "frontend" / "public" / "images" / "india" / "credits.json"
WEB_DIR = ROOT / "frontend" / "public" / "images" / "india"
USER_AGENT = (
    "NadiSaathiPhotoFetcher/1.0 "
    "(https://github.com/Prashant-thakur77/JalRekha; flood photo dataset) "
    f"httpx/{httpx.__version__}"
)
WEB_SIZES = (1600, 800)
WEB_QUALITY = 78


def sha1_of(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(client: httpx.Client, url: str, dest: Path, retries: int = 4) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            with client.stream("GET", url) as r:
                if r.status_code == 429 or r.status_code >= 500:
                    raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
                r.raise_for_status()
                with tmp.open("wb") as fh:
                    for chunk in r.iter_bytes():
                        fh.write(chunk)
            tmp.replace(dest)
            return
        except httpx.HTTPError as exc:
            if attempt == retries:
                tmp.unlink(missing_ok=True)
                raise
            wait = 5 * attempt
            print(f"    retry {attempt}/{retries - 1} in {wait}s ({exc})", file=sys.stderr)
            time.sleep(wait)


def build_web(src: Path, photo_id: str) -> list[tuple[str, int]]:
    from PIL import Image, ImageOps  # imported lazily: only needed for --web

    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        out = []
        for size in WEB_SIZES:
            copy = im.copy()
            copy.thumbnail((size, size), Image.LANCZOS)
            dest = WEB_DIR / f"{photo_id}-{size}.webp"
            # No exif/icc passed in, so the webp carries no metadata.
            copy.save(dest, "WEBP", quality=WEB_QUALITY, method=6)
            out.append((dest.name, dest.stat().st_size))
        return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--credits", type=Path, default=CREDITS)
    ap.add_argument("--force", action="store_true", help="re-download even if a verified copy exists")
    ap.add_argument("--web", action="store_true", help="also rebuild the 1600/800 px webp copies (needs Pillow)")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between downloads (be polite)")
    args = ap.parse_args()

    entries = json.loads(args.credits.read_text(encoding="utf-8"))
    client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=120, follow_redirects=True)
    failures = 0
    web_total = 0
    for e in entries:
        dest = ROOT / e["original_file"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        expected = e.get("sha1")
        if dest.exists() and not args.force and (not expected or sha1_of(dest) == expected):
            print(f"ok    {e['id']} (cached)")
        else:
            print(f"get   {e['id']} <- {e['original_url']}")
            try:
                download(client, e["original_url"], dest)
            except httpx.HTTPError as exc:
                print(f"FAIL  {e['id']}: {exc}", file=sys.stderr)
                failures += 1
                continue
            if expected and sha1_of(dest) != expected:
                print(f"FAIL  {e['id']}: SHA-1 mismatch (file changed on Commons?)", file=sys.stderr)
                failures += 1
                continue
            time.sleep(args.delay)
        if args.web:
            for name, size in build_web(dest, e["id"]):
                web_total += size
                print(f"      web {name} {size // 1024} KB")
    if args.web:
        print(f"web total: {web_total / 1e6:.2f} MB")
    print(f"{len(entries) - failures}/{len(entries)} photos ready; licences in {args.credits}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
