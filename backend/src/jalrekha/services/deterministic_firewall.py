"""Deterministic computer-vision firewall executed before the multimodal LLM.

This implementation is pure-Python on top of PIL.ImageStat / ImageFilter.
NumPy import and subprocess fork were both empirically observed to corrupt
the in-process LiteRT-LM Vulkan runtime on this hardware ("Invalid Buffer"
storm and silent runner fallback), so this module avoids both.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageFilter, ImageOps, ImageStat

logger = logging.getLogger(__name__)


@dataclass
class FrameMetrics:
    index: int
    timestamp_s: float
    brightness: float
    contrast: float
    edge_strength: float
    motion_score: float
    waterline_y: int
    waterline_ratio: float


@dataclass
class FirewallResult:
    opencv_used: bool
    cv_backend: str = "pil-pure-python"
    frames: list[FrameMetrics] = field(default_factory=list)
    waterline_ratio: float = 0.0
    rise_velocity: float = 0.0
    crossed_critical_line: bool = False
    confidence: float = 0.0
    water_level: str = "unknown"
    notes: list[str] = field(default_factory=list)

    def to_dict(self, *, include_frames: bool = True) -> dict:
        payload = {
            "opencv_used": self.opencv_used,
            "cv_backend": self.cv_backend,
            "waterline_ratio": round(self.waterline_ratio, 4),
            "rise_velocity": round(self.rise_velocity, 4),
            "crossed_critical_line": self.crossed_critical_line,
            "confidence": round(self.confidence, 3),
            "water_level": self.water_level,
            "notes": self.notes,
        }
        if include_frames:
            payload["frames"] = [
                {
                    "index": f.index,
                    "timestamp_s": f.timestamp_s,
                    "brightness": round(f.brightness, 2),
                    "contrast": round(f.contrast, 2),
                    "edge_strength": round(f.edge_strength, 3),
                    "motion_score": round(f.motion_score, 3),
                    "waterline_y": f.waterline_y,
                    "waterline_ratio": round(f.waterline_ratio, 4),
                }
                for f in self.frames
            ]
        return payload


def _classify(ratio: float, rise_velocity: float, crossed: bool) -> str:
    if crossed or ratio >= 0.55 or rise_velocity >= 0.10:
        return "critical"
    if ratio >= 0.30 or rise_velocity >= 0.03:
        return "elevated"
    return "low"


def _empty_result(frame_paths: Sequence[str], sample_seconds: float, reason: str) -> FirewallResult:
    frames = [
        FrameMetrics(
            index=i,
            timestamp_s=round(i * sample_seconds, 2),
            brightness=-1.0,
            contrast=-1.0,
            edge_strength=-1.0,
            motion_score=-1.0,
            waterline_y=-1,
            waterline_ratio=-1.0,
        )
        for i in range(len(frame_paths))
    ]
    return FirewallResult(opencv_used=False, cv_backend="disabled", frames=frames, notes=[reason])


def _row_edge_density(edge_img: Image.Image) -> list[float]:
    width, height = edge_img.size
    pixels = edge_img.load()
    row_sums: list[int] = [0] * height
    for y in range(height):
        s = 0
        for x in range(width):
            s += pixels[x, y]
        row_sums[y] = s
    denom = max(1, width * 255)
    return [s / denom for s in row_sums]


def analyze_frames(
    frame_paths: Sequence[str],
    sample_seconds: float,
    *,
    critical_line_ratio: float = 0.5,
) -> FirewallResult:
    if not frame_paths:
        return FirewallResult(opencv_used=False, notes=["no frames"])
    if os.environ.get("JALREKHA_DISABLE_FIREWALL", "").lower() in {"1", "true", "yes"}:
        return _empty_result(frame_paths, sample_seconds, "disabled via JALREKHA_DISABLE_FIREWALL")

    metrics: list[FrameMetrics] = []
    prev_gray_pixels: list[int] | None = None
    prev_size: tuple[int, int] | None = None
    for idx, path in enumerate(frame_paths):
        try:
            with Image.open(path) as raw:
                gray = ImageOps.exif_transpose(raw).convert("L")
                gray.load()
        except Exception as exc:
            metrics.append(
                FrameMetrics(
                    index=idx,
                    timestamp_s=round(idx * sample_seconds, 2),
                    brightness=-1.0,
                    contrast=-1.0,
                    edge_strength=-1.0,
                    motion_score=-1.0,
                    waterline_y=-1,
                    waterline_ratio=-1.0,
                )
            )
            logger.warning("deterministic_firewall could not load frame %s: %s", path, exc)
            continue

        width, height = gray.size
        stat = ImageStat.Stat(gray)
        brightness = float(stat.mean[0])
        contrast = float(stat.stddev[0])

        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_strength = float(ImageStat.Stat(edges).mean[0]) / 255.0

        row_density = _row_edge_density(edges)
        if row_density and max(row_density) > 0.02:
            waterline_y = max(range(len(row_density)), key=row_density.__getitem__)
        else:
            waterline_y = -1
        waterline_ratio = (height - waterline_y) / height if waterline_y > 0 else 0.0

        current_pixels = list(gray.getdata())
        if prev_gray_pixels is not None and prev_size == gray.size:
            n = len(current_pixels)
            total = sum(abs(current_pixels[i] - prev_gray_pixels[i]) for i in range(n))
            motion_score = (total / n) / 255.0 if n else 0.0
        else:
            motion_score = 0.0
        prev_gray_pixels = current_pixels
        prev_size = gray.size
        gray.close()

        metrics.append(
            FrameMetrics(
                index=idx,
                timestamp_s=round(idx * sample_seconds, 2),
                brightness=brightness,
                contrast=contrast,
                edge_strength=edge_strength,
                motion_score=motion_score,
                waterline_y=int(waterline_y),
                waterline_ratio=float(waterline_ratio),
            )
        )

    valid_ratios = [m.waterline_ratio for m in metrics if m.waterline_ratio > 0.0]
    last_ratio = valid_ratios[-1] if valid_ratios else 0.0
    first_ratio = valid_ratios[0] if valid_ratios else 0.0
    duration_s = max(sample_seconds * max(1, len(valid_ratios) - 1), 1.0)
    rise_velocity = (last_ratio - first_ratio) / duration_s
    crossed = last_ratio >= critical_line_ratio
    water_level = _classify(last_ratio, rise_velocity, crossed)
    valid_count = sum(1 for m in metrics if m.waterline_y > 0)
    confidence = valid_count / max(1, len(metrics))

    # This baseline is PIL only. It used to report opencv_used=True, which was
    # false; the OpenCV 5 pipeline lives in jalrekha.vision.
    result = FirewallResult(
        opencv_used=False,
        cv_backend="pil-pure-python",
        frames=metrics,
        waterline_ratio=last_ratio,
        rise_velocity=rise_velocity,
        crossed_critical_line=crossed,
        confidence=confidence,
        water_level=water_level,
    )
    logger.info(
        "deterministic_firewall waterline_ratio=%.3f rise_velocity=%.4f crossed=%s water_level=%s frames=%d backend=pil-pure-python",
        last_ratio,
        rise_velocity,
        crossed,
        water_level,
        len(metrics),
    )
    return result
