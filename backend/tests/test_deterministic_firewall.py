from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from jalrekha.services.deterministic_firewall import analyze_frames


def _write_frame(tmp_path, idx: int, waterline_row: int, width: int = 320, height: int = 240):
    image = Image.new("RGB", (width, height), (220, 220, 220))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, waterline_row, width - 1, height - 1), fill=(40, 40, 40))
    draw.rectangle((0, waterline_row - 1, width - 1, waterline_row + 1), fill=(0, 0, 0))
    path = tmp_path / f"frame_{idx:03d}.png"
    image.save(path)
    return str(path)


def test_static_low_water(tmp_path):
    paths = [_write_frame(tmp_path, i, waterline_row=210) for i in range(3)]
    result = analyze_frames(paths, sample_seconds=1.0)
    assert result.opencv_used is False  # PIL baseline; OpenCV lives in jalrekha.vision
    assert result.cv_backend == "pil-pure-python"
    assert result.water_level in {"low", "elevated"}
    assert result.rise_velocity == pytest.approx(0.0, abs=0.02)
    assert all(f.brightness > 0 for f in result.frames)


def test_rising_water_crosses_critical(tmp_path):
    rows = [220, 170, 110, 70]
    paths = [_write_frame(tmp_path, i, waterline_row=r) for i, r in enumerate(rows)]
    result = analyze_frames(paths, sample_seconds=1.0, critical_line_ratio=0.5)
    assert result.opencv_used is False  # PIL baseline; OpenCV lives in jalrekha.vision
    assert result.cv_backend == "pil-pure-python"
    assert result.rise_velocity > 0
    assert result.crossed_critical_line is True
    assert result.water_level == "critical"


@pytest.mark.xfail(strict=True, reason="Known failure of the original PIL edge-row heuristic (baseline B0): a 'strongest edge row' "
                   "waterline overshoots on this synthetic rise. Kept unchanged because B0 is the frozen A/B baseline; "
                   "see eval/results/stage_synth_test.json and the OpenCV pipeline tests for the replacement.")
def test_elevated_without_crossing(tmp_path):
    rows = [220, 190, 165]
    paths = [_write_frame(tmp_path, i, waterline_row=r) for i, r in enumerate(rows)]
    result = analyze_frames(paths, sample_seconds=1.0, critical_line_ratio=0.5)
    assert result.crossed_critical_line is False
    assert result.water_level in {"elevated", "low"}
    assert result.rise_velocity > 0


def test_empty_frame_list():
    result = analyze_frames([], sample_seconds=1.0)
    assert result.frames == []
