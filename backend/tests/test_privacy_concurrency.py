from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from jalrekha.vision import models, privacy


def test_redact_is_safe_under_concurrent_requests_of_different_sizes():
    # Regression: the shared YuNet detector was resized by one thread while another ran it.
    if models.model_path("face_yunet") is None:
        pytest.skip("YuNet weights not available")
    rng = np.random.default_rng(0)
    imgs = [rng.integers(0, 255, (h, w, 3), dtype=np.uint8) for h, w in [(480, 640), (1080, 1440), (720, 1280), (900, 600)] * 4]
    with ThreadPoolExecutor(max_workers=6) as ex:
        reports = list(ex.map(lambda im: privacy.redact(im)[1], imgs))
    assert all(r.face_detector == "yunet" for r in reports)


def test_registration_and_flow_are_safe_under_concurrent_cycles():
    # Regression: concurrent replays shared one ALIKED/LightGlue pair and one ORB/DIS object; the
    # process died with a native double free. Run heavy registration and DIS from several threads.
    import cv2

    from jalrekha.vision import register, waterline

    rng = np.random.default_rng(1)
    ref = cv2.GaussianBlur(rng.integers(0, 255, (360, 480, 3), dtype=np.uint8), (5, 5), 0)
    shifted = [np.roll(ref, s, axis=1) for s in (3, 7, 11, 15)]
    strips = [rng.integers(0, 255, (200, 40, 3), dtype=np.uint8) for _ in range(3)]

    def cycle(cur):
        r = register.register(cur, ref, force_heavy=register.aliked_available())
        e = waterline.temporal_texture(strips)
        return r.method, e.name

    with ThreadPoolExecutor(max_workers=4) as ex:
        out = list(ex.map(cycle, shifted * 2))
    assert len(out) == 8 and all(name == "E2_temporal" for _, name in out)
