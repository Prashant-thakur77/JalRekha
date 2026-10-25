from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx


def _record_clip(source: str, target: Path, clip_seconds: float, fps: float) -> None:
    ffmpeg_setting = os.environ.get("JALREKHA_FFMPEG_BIN", "ffmpeg")
    ffmpeg = shutil.which(ffmpeg_setting) or (ffmpeg_setting if Path(ffmpeg_setting).exists() else None)
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required; install it or set JALREKHA_FFMPEG_BIN before running the guard")

    input_args = ["-i", source]
    if source.startswith("/dev/video"):
        input_args = ["-f", "v4l2", "-framerate", str(max(1, int(fps))), "-i", source]

    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *input_args,
        "-t",
        str(max(1.0, clip_seconds)),
        "-r",
        str(max(1, int(fps))),
        "-an",
        "-c:v",
        "mjpeg",
        str(target),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not target.exists() or target.stat().st_size == 0:
        detail = (result.stderr or result.stdout or "unknown ffmpeg error").strip()
        raise RuntimeError(f"ffmpeg clip recording failed: {detail}")


def _submit_clip(api_base: str, site_id: str, clip_path: Path, timeout: float) -> dict:
    with clip_path.open("rb") as handle:
        files = {"video": (clip_path.name, handle, "video/x-msvideo")}
        data = {"site_id": site_id}
        with httpx.Client(timeout=timeout) as client:
            response = client.post(f"{api_base.rstrip('/')}/node/analyze", data=data, files=files)
            response.raise_for_status()
            return response.json()


def main() -> None:
    api_base = os.environ.get("JALREKHA_API_BASE", "http://127.0.0.1:8000/api")
    site_id = os.environ.get("JALREKHA_GUARD_SITE_ID", "silverado-fixed-cam-usgs")
    source = os.environ.get("JALREKHA_CAMERA_SOURCE", "/dev/video0")
    interval_seconds = float(os.environ.get("JALREKHA_GUARD_INTERVAL_SECONDS", "300"))
    clip_seconds = float(os.environ.get("JALREKHA_GUARD_CLIP_SECONDS", "12"))
    fps = float(os.environ.get("JALREKHA_GUARD_FPS", "2"))
    timeout = float(os.environ.get("JALREKHA_GUARD_TIMEOUT_SECONDS", "600"))

    print(
        "JalRekha Node multimodal guard started "
        f"site_id={site_id} source={source!r} interval={interval_seconds}s clip={clip_seconds}s"
    )
    while True:
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="node-guard-") as tmp:
            clip_path = Path(tmp) / "guard.avi"
            try:
                _record_clip(source, clip_path, clip_seconds, fps)
                payload = _submit_clip(api_base, site_id, clip_path, timeout)
                observation = payload.get("observation", {})
                alert = payload.get("alert", {})
                print(
                    "guard analysis ok "
                    f"frames={observation.get('frames_analyzed')} "
                    f"runner={observation.get('runner', {}).get('mode')} "
                    f"level={alert.get('level')} score={alert.get('score')}"
                )
            except Exception as exc:
                print(f"guard analysis failed: {exc}")

        elapsed = time.monotonic() - started
        time.sleep(max(1.0, interval_seconds - elapsed))


if __name__ == "__main__":
    main()
