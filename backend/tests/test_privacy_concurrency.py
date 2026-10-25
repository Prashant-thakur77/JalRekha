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
