"""ONNX models used by the vision pipeline: fetched at runtime, SHA-1 checked.

Weights are not redistributed in this repository. URLs and hashes are the
ones OpenCV itself uses (opencv_extra testdata/dnn/download_models.py and
opencv_zoo).
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelSpec:
    key: str
    filename: str
    url: str
    sha1: str
    licence: str


MODELS: dict[str, ModelSpec] = {
    "aliked": ModelSpec(
        "aliked",
        "aliked-n16rot-top1k-640.onnx",
        "https://raw.githubusercontent.com/YangGuanyuhan/lightglue_opencv_project/main/model/aliked-n16rot-top1k-640.onnx",
        "41faa7bf5d7eb68a2851471ba03aa20c9db30e4c",
        "ALIKED (BSD-3-Clause, Zhao et al.); ONNX export referenced by OpenCV 5 tests",
    ),
    "lightglue": ModelSpec(
        "lightglue",
        "aliked_lightglue.onnx",
        "https://raw.githubusercontent.com/YangGuanyuhan/lightglue_opencv_project/main/model/aliked_lightglue.onnx",
        "02723aa521990e57fe33d90b67977590c460e351",
        "LightGlue (Apache-2.0, Lindenberger et al.); ONNX export referenced by OpenCV 5 tests",
    ),
    "face_yunet": ModelSpec(
        "face_yunet",
        "face_detection_yunet_2023mar.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "acbe4b5976ade60c4b866a30d0720d71589c8bbc",
        "YuNet face detector, opencv_zoo (MIT)",
    ),
    "plate_yunet": ModelSpec(
        "plate_yunet",
        "license_plate_detection_lpd_yunet_2023mar.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/license_plate_detection_yunet/license_plate_detection_lpd_yunet_2023mar.onnx",
        "beb9124ae40e836b65d5bdc8dcb2c3433380e02b",
        "LPD-YuNet licence-plate detector, opencv_zoo (Apache-2.0)",
    ),
}


def models_dir() -> Path:
    env = os.environ.get("JALREKHA_CV_MODELS_DIR")
    if env:
        return Path(env)
    from jalrekha.core.settings import get_settings

    return get_settings().data_dir / "models" / "opencv"


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_VERIFIED: dict[str, Path] = {}


def model_path(key: str) -> Path | None:
    """Path to a verified local copy, or None if absent (never downloads)."""
    if key in _VERIFIED and _VERIFIED[key].exists():
        return _VERIFIED[key]
    spec = MODELS[key]
    from jalrekha.core.settings import get_settings

    # The data dir may be relocated (cloud host, tests); the repo copy is a fallback.
    for base in (models_dir(), get_settings().backend_root / "data" / "models" / "opencv"):
        path = base / spec.filename
        if path.exists() and _sha1(path) == spec.sha1:
            _VERIFIED[key] = path
            return path
    return None


def fetch(key: str) -> Path:
    spec = MODELS[key]
    target = models_dir() / spec.filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and _sha1(target) == spec.sha1:
        return target
    tmp = target.with_suffix(".part")
    urllib.request.urlretrieve(spec.url, tmp)
    digest = _sha1(tmp)
    if digest != spec.sha1:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"{spec.filename}: SHA-1 mismatch ({digest} != {spec.sha1})")
    tmp.replace(target)
    return target


if __name__ == "__main__":
    for k in MODELS:
        print(k, fetch(k))
