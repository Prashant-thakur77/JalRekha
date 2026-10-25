from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from jalrekha.vision import quality, register, synth, waterline
from jalrekha.vision.gauge import GaugeCalibration, GaugeMark
from jalrekha.vision.pipeline import MeasureOptions, measure
from jalrekha.vision.temporal import filter_series


def test_gauge_row_stage_round_trip():
    cal = GaugeCalibration(marks=[GaugeMark(100, 50, 3.0), GaugeMark(110, 350, 0.0)])
    for stage in (0.2, 1.5, 2.9):
        row = cal.stage_to_strip_row(stage)
        assert cal.strip_row_to_stage(row) == pytest.approx(stage, abs=1e-6)
    assert cal.metres_per_px() == pytest.approx(3.0 / np.hypot(10, 300))


def test_gauge_calibration_rejects_single_mark():
    with pytest.raises(ValueError):
        GaugeCalibration(marks=[GaugeMark(0, 0, 1.0)])


def test_step_fit_finds_change_point():
    prof = np.r_[np.full(60, 5.0), np.full(40, 1.0)] + np.random.default_rng(0).normal(0, 0.2, 100)
    row, sep = waterline.step_fit(prof, expect_upper_higher=+1)
    assert row == pytest.approx(60, abs=1)
    assert sep > 5


def test_step_fit_respects_direction():
    prof = np.r_[np.full(50, 1.0), np.full(50, 5.0)]
    row, _ = waterline.step_fit(prof, expect_upper_higher=+1)
    assert row is None


@pytest.mark.parametrize("seed", [11, 12, 13])
def test_pipeline_clean_synthetic_within_6cm(seed):
    site = synth.make_site(seed)
    cal = site.calibration()
    ref = synth.reference_frame(site)
    errors = []
    for frac in (0.3, 0.55, 0.8):
        truth = site.gauge_len_m * frac
        m = measure(synth.render_burst(site, truth), cal, ref, MeasureOptions(redact=False, draw_overlay=False))
        assert m.registration.ok
        assert m.reading.stage_m is not None
        errors.append(abs(m.reading.stage_m - truth))
    assert max(errors) < 0.06
    assert float(np.mean(errors)) < 0.04


def test_registration_recovers_camera_shake():
    site = synth.make_site(21)
    cal = site.calibration()
    ref = synth.reference_frame(site)
    truth = site.gauge_len_m * 0.5
    frames = synth.render_burst(site, truth, deg=synth.Degradation(shake_px=14))
    with_reg = measure(frames, cal, ref, MeasureOptions(redact=False, draw_overlay=False))
    no_reg = measure(frames, cal, ref, MeasureOptions(redact=False, draw_overlay=False, use_registration=False))
    assert with_reg.registration.method in {"orb", "aliked_lightglue"}
    assert with_reg.registration.drift_px > 1.0
    assert abs(with_reg.reading.stage_m - truth) <= abs(no_reg.reading.stage_m - truth) + 0.01


def test_quality_gate_flags_night_and_fog():
    site = synth.make_site(31)
    night = synth.render_burst(site, 1.0, n=1, deg=synth.Degradation(night=1.0))[0]
    fog = synth.render_burst(site, 1.0, n=1, deg=synth.Degradation(fog=0.9))[0]
    assert "night_or_underexposed" in quality.assess_quality(night).reasons
    cal = site.calibration()
    assert not quality.assess_quality(fog, cal.extract_strip(fog)).ok


def test_still_water_disables_temporal_estimator():
    site = synth.make_site(41)
    frames = synth.render_burst(site, 1.2, deg=synth.Degradation(still_water=True))
    cal = site.calibration()
    est = waterline.temporal_texture([cal.extract_strip(f) for f in frames])
    assert est.row is None
    assert est.detail["still_water"] is True


def test_kalman_recovers_linear_rise_rate():
    t0 = datetime(2026, 9, 27, 6, 0)
    rng = np.random.default_rng(3)
    readings = [(t0 + timedelta(minutes=5 * i), 1.0 + 0.6 * (5 * i / 60) + rng.normal(0, 0.02), 0.03) for i in range(16)]
    readings.append((t0 + timedelta(minutes=81), 4.0, 0.03))  # a splash / person in front of the gauge
    out = filter_series(readings)
    assert out is not None
    assert out.n_rejected == 1
    assert out.rate_m_per_h == pytest.approx(0.6, abs=0.15)


def test_registration_identity_without_reference():
    img = np.zeros((40, 40, 3), np.uint8)
    reg = register.register(img, None)
    assert reg.ok and reg.method == "identity"


def test_measurement_dict_is_json_ready():
    import json

    site = synth.make_site(51)
    m = measure(synth.render_burst(site, 1.0), site.calibration(), synth.reference_frame(site))
    payload = m.to_dict()
    json.dumps(payload)
    assert payload["schema"] == "jalrekha-measurement-v1"
    assert payload["opencv_version"].startswith("5.")
    assert payload["redaction"] is not None
