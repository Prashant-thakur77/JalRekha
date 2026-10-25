from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


def _json_get(url: str, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _json_post(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_multipart(url: str, fields: dict[str, str], files: dict[str, Path], timeout: float) -> dict[str, Any]:
    boundary = f"----node-{uuid.uuid4().hex}"
    body = bytearray()

    def add_line(value: str = "") -> None:
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")

    for name, value in fields.items():
        add_line(f"--{boundary}")
        add_line(f'Content-Disposition: form-data; name="{name}"')
        add_line()
        add_line(value)

    for name, path in files.items():
        filename = path.name
        add_line(f"--{boundary}")
        add_line(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"')
        content_type = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "video/x-msvideo"
        add_line(f"Content-Type: {content_type}")
        add_line()
        body.extend(path.read_bytes())
        body.extend(b"\r\n")

    add_line(f"--{boundary}--")

    request = urllib.request.Request(
        url,
        data=bytes(body),
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _build_synthetic_clip(path: Path, width: int, height: int, _fps: float, _duration_s: float) -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), (190, 205, 215))
    draw = ImageDraw.Draw(image)
    waterline_y = int(height * 0.42)
    draw.rectangle((0, waterline_y, width - 1, height - 1), fill=(75, 65, 45))
    draw.line((0, int(height * 0.36), width - 1, int(height * 0.36)), fill=(245, 245, 245), width=2)
    draw.line((0, int(height * 0.62), width - 1, int(height * 0.62)), fill=(70, 180, 70), width=2)
    draw.text((14, 14), "synthetic node multimodal frame", fill=(30, 30, 30))
    image.save(path, format="JPEG", quality=88)


def _capture_clip(path: Path, args: argparse.Namespace) -> None:
    if args.capture_command:
        command = args.capture_command.format(
            output=str(path),
            duration=args.duration,
            duration_ms=int(args.duration * 1000),
            width=args.width,
            height=args.height,
            fps=args.fps,
            camera=args.camera,
        )
        subprocess.run(shlex.split(command), check=True)
        return

    command = [
        "ffmpeg",
        "-y",
        "-f",
        "v4l2",
        "-framerate",
        str(args.fps),
        "-video_size",
        f"{args.width}x{args.height}",
        "-t",
        str(args.duration),
        "-i",
        args.camera,
        "-c:v",
        "mjpeg",
        str(path),
    ]
    subprocess.run(command, check=True)


def _print_runtime(api_base: str, timeout: float) -> None:
    health = _json_get(f"{api_base}/health", timeout)
    runtime = _json_get(f"{api_base}/settings/runtime", timeout)
    llm = runtime.get("llm", {})
    node = runtime.get("node", {})
    print(
        json.dumps(
            {
                "health": health,
                "llm": {
                    "reachable": llm.get("reachable"),
                    "model": llm.get("model"),
                    "detail": llm.get("detail"),
                },
                "node": node,
            },
            ensure_ascii=True,
            indent=2,
        )
    )


def _print_analysis_summary(result: dict[str, Any]) -> None:
    observation = result.get("observation", {})
    alert = result.get("alert", {})
    runner = observation.get("runner") or {}
    print(
        json.dumps(
            {
                "site_id": observation.get("site_id"),
                "frames_analyzed": observation.get("frames_analyzed"),
                "waterline_ratio": observation.get("waterline_ratio"),
                "assessment_level": observation.get("assessment_level"),
                "assessment_score": observation.get("assessment_score"),
                "runner": runner,
                "fallback_used": observation.get("fallback_used"),
                "alert_level": alert.get("level"),
                "local_alarm_triggered": alert.get("local_alarm_triggered"),
                "evidence_frame_url": observation.get("evidence_frame_url"),
            },
            ensure_ascii=True,
            indent=2,
        )
    )


def _default_output_path(synthetic: bool) -> Path:
    suffix = "synthetic.jpg" if synthetic else "camera.avi"
    return Path(tempfile.gettempdir()) / f"node-{int(time.time())}-{suffix}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Raspberry Pi fixed JalRekha Node probe.")
    parser.add_argument("--api-base", default=os.environ.get("JALREKHA_API_BASE", "http://127.0.0.1:8000/api"))
    parser.add_argument("--site-id", default=os.environ.get("JALREKHA_SITE_ID", "puente-arroyo-01"))
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--duration", type=float, default=12.0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=float, default=4.0)
    parser.add_argument("--camera", default=os.environ.get("JALREKHA_CAMERA", "/dev/video0"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--synthetic", action="store_true", help="Generate a rising-water test clip instead of using a camera.")
    parser.add_argument("--sample-site", action="store_true", help="Run the backend's bundled sample clip for --site-id.")
    parser.add_argument(
        "--capture-command",
        help=(
            "Optional capture command template. Available fields: {output}, {duration}, "
            "{duration_ms}, {width}, {height}, {fps}, {camera}."
        ),
    )
    args = parser.parse_args()

    api_base = args.api_base.rstrip("/")
    try:
        _print_runtime(api_base, args.timeout)

        if args.sample_site:
            result = _json_post(f"{api_base}/sites/{urllib.parse.quote(args.site_id)}/sample-node-analysis", args.timeout)
            _print_analysis_summary(result)
            return 0

        output = args.output or _default_output_path(args.synthetic)
        output.parent.mkdir(parents=True, exist_ok=True)
        if args.synthetic:
            _build_synthetic_clip(output, args.width, args.height, args.fps, args.duration)
        else:
            _capture_clip(output, args)

        if not output.exists() or output.stat().st_size <= 0:
            raise RuntimeError(f"Clip was not created or is empty: {output}")

        print(f"clip={output} bytes={output.stat().st_size}", file=sys.stderr)
        result = _post_multipart(
            f"{api_base}/node/analyze",
            fields={"site_id": args.site_id},
            files={"video": output},
            timeout=args.timeout,
        )
        _print_analysis_summary(result)
        return 0
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code}: {detail}", file=sys.stderr)
    except Exception as exc:
        print(f"node probe failed: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
