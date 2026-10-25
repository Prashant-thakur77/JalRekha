"""Bridge between the node pipeline and jalrekha.vision.

On a Raspberry Pi running LiteRT-LM in the API process, importing NumPy into
that process corrupts the Vulkan runtime (ANALYSIS.md section 10.1). There,
set JALREKHA_VISION_MODE=subprocess and the measurement runs in a fresh
interpreter via ``python -m jalrekha.vision.cli``. On the cloud worker
(Graviton/COOL) the default is in-process.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from jalrekha.core.settings import get_settings
from jalrekha.services.storage import get_upload_dir

_LOGGER = logging.getLogger(__name__)


@dataclass
class VisionResult:
    measurement: dict
    overlay_path: str | None
    redacted_path: str | None

    @property
    def usable(self) -> bool:
        return bool(self.measurement.get("usable"))

    @property
    def stage_m(self) -> float | None:
        return self.measurement.get("reading", {}).get("stage_m")

    @property
    def sigma_m(self) -> float | None:
        return self.measurement.get("reading", {}).get("sigma_m")


def vision_mode() -> str:
    explicit = os.environ.get("JALREKHA_VISION_MODE")
    if explicit:
        return explicit.strip().lower()
    return "subprocess" if get_settings().node_provider == "litert" and _on_pi() else "inprocess"


def _on_pi() -> bool:
    try:
        return "raspberry pi" in Path("/proc/device-tree/model").read_text(errors="ignore").lower()
    except OSError:
        return False


def extract_burst(video_path: str, *, frames: int = 5, fps: float = 2.0) -> list[str]:
    """Last ~frames/fps seconds of a clip as PNGs (the burst for estimator E2)."""
    path = Path(video_path)
    if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
        return [str(path)]
    ffmpeg = shutil.which(get_settings().ffmpeg_bin)
    if ffmpeg is None:
        return []
    out_dir = Path(tempfile.mkdtemp(prefix="burst-"))
    seconds = max(1.0, frames / fps + 0.5)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-sseof", f"-{seconds:.1f}", "-i", str(path),
           "-vf", f"fps={fps}", "-frames:v", str(frames), str(out_dir / "b-%02d.png")]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    got = sorted(out_dir.glob("b-*.png"))
    if res.returncode != 0 or not got:
        # Short clips: -sseof can overshoot the start; fall back to the first frames.
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
               "-vf", f"fps={fps}", "-frames:v", str(frames), str(out_dir / "b-%02d.png")]
        subprocess.run(cmd, capture_output=True, text=True, check=False)
        got = sorted(out_dir.glob("b-*.png"))
    return [str(p) for p in got]


def measure_paths(
    frame_paths: list[str],
    gauge_json: str,
    reference_path: str | None,
    *,
    burst_dt_s: float = 0.5,
    allow_heavy: bool = True,
) -> VisionResult | None:
    if not frame_paths:
        return None
    request = {
        "frames": frame_paths,
        "gauge": json.loads(gauge_json),
        "reference": reference_path,
        "burst_dt_s": burst_dt_s,
        "allow_heavy": allow_heavy,
        "out_dir": str(get_upload_dir()),
        "tag": uuid4().hex[:12],
    }
    try:
        if vision_mode() == "subprocess":
            proc = subprocess.run(
                [sys.executable, "-m", "jalrekha.vision.cli"],
                input=json.dumps(request), capture_output=True, text=True, timeout=120, check=False,
            )
            if proc.returncode != 0:
                _LOGGER.warning("vision subprocess failed: %s", proc.stderr[-400:])
                return None
            payload = json.loads(proc.stdout)
        else:
            from jalrekha.vision.cli import run_request

            payload = run_request(request)
    except Exception as exc:  # the node must keep working without CV
        _LOGGER.warning("vision measurement failed: %s", exc)
        return None
    return VisionResult(payload["measurement"], payload.get("overlay_path"), payload.get("redacted_path"))


def stage_series_rate(history: list[tuple[datetime, float, float]]) -> dict | None:
    """Kalman-filtered stage and rise rate over recent readings (in-process: pure OpenCV)."""
    if vision_mode() == "subprocess":
        return None
    from jalrekha.vision.temporal import filter_series

    out = filter_series(history)
    return None if out is None else out.to_dict()
