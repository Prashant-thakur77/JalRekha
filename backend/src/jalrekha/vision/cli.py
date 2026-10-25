"""JSON-in/JSON-out entry point so the pipeline can run out of process.

    echo '{"frames": [...], "gauge": {...}, "reference": "...", "out_dir": "..."}' \
        | python -m jalrekha.vision.cli
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2

from jalrekha.vision.gauge import GaugeCalibration
from jalrekha.vision.pipeline import MeasureOptions, measure


def run_request(req: dict) -> dict:
    frames = [cv2.imread(p, cv2.IMREAD_COLOR) for p in req["frames"]]
    frames = [f for f in frames if f is not None]
    if not frames:
        raise ValueError("no readable frames")
    gauge = GaugeCalibration.from_dict(req["gauge"])
    ref = None
    if req.get("reference") and Path(req["reference"]).exists():
        ref = cv2.imread(req["reference"], cv2.IMREAD_COLOR)
    # Frames may arrive at a different resolution from the calibration reference.
    target = ref.shape[1::-1] if ref is not None else gauge.reference_size
    if target and tuple(frames[0].shape[1::-1]) != tuple(target):
        frames = [cv2.resize(f, tuple(target), interpolation=cv2.INTER_AREA) for f in frames]
    m = measure(
        frames,
        gauge,
        ref,
        MeasureOptions(burst_dt_s=float(req.get("burst_dt_s", 0.5)), allow_heavy_registration=bool(req.get("allow_heavy", True))),
    )
    out: dict = {"measurement": m.to_dict(), "overlay_path": None, "redacted_path": None}
    out_dir = req.get("out_dir")
    if out_dir:
        tag = req.get("tag", "m")
        if m.overlay_bgr is not None:
            p = Path(out_dir) / f"cv-overlay-{tag}.jpg"
            cv2.imwrite(str(p), m.overlay_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
            out["overlay_path"] = str(p)
        if m.redacted_bgr is not None:
            p = Path(out_dir) / f"cv-redacted-{tag}.jpg"
            cv2.imwrite(str(p), m.redacted_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
            out["redacted_path"] = str(p)
    return out


def main() -> int:
    req = json.loads(sys.stdin.read())
    json.dump(run_request(req), sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
