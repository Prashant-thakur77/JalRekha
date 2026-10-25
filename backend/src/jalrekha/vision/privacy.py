"""Redact faces and licence plates before any frame is stored or uploaded.

Primary detectors are OpenCV-zoo YuNet models run through cv.FaceDetectorYN
(OpenCV 5 DNN). OpenCV 5 no longer ships Haar cascades in the main module,
so there is no weaker detector to fall back to. If a detector's ONNX file is
absent, the caller gets ``keep_mask`` back and blurs everything outside the
gauge strip ("roi_only"), which is safe by construction. The report records
which mode ran so the privacy audit counts it.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import cv2
import numpy as np

from jalrekha.vision import models

_FACE = None
_PLATE = None
# The detectors are shared and stateful (input size, set input), so concurrent requests take turns.
_LOCK = threading.Lock()


@dataclass
class RedactionReport:
    faces: int | None
    plates: int | None
    face_detector: str
    plate_detector: str
    mode: str = "detect_and_blur"  # or "roi_only"
    boxes: list[list[int]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "faces": self.faces if self.faces is not None else "unavailable",
            "plates": self.plates if self.plates is not None else "unavailable",
            "face_detector": self.face_detector,
            "plate_detector": self.plate_detector,
            "mode": self.mode,
        }


def _yunet(key: str, size: tuple[int, int], score: float):
    path = models.model_path(key)
    if path is None:
        return None
    det = cv2.FaceDetectorYN_create(str(path), "", size, score, 0.3, 500)
    return det


def _detect_faces(img: np.ndarray) -> tuple[list[list[int]] | None, str]:
    global _FACE
    h, w = img.shape[:2]
    with _LOCK:
        if _FACE is None:
            _FACE = _yunet("face_yunet", (w, h), 0.6) or False
        if not _FACE:
            return None, "unavailable"
        _FACE.setInputSize((w, h))
        _, faces = _FACE.detect(img)
    boxes = [] if faces is None else [[int(v) for v in f[:4]] for f in faces]
    return boxes, "yunet"


def _detect_plates(img: np.ndarray) -> tuple[list[list[int]] | None, str]:
    """LPD-YuNet emits 4 corner points per plate; we blur their bounding box."""
    global _PLATE
    path = models.model_path("plate_yunet")
    if path is None:
        return None, "unavailable"
    # LPD-YuNet runs on a 320x240 BGR image (opencv_zoo lpd_yunet.py).
    h, w = img.shape[:2]
    blob = cv2.dnn.blobFromImage(cv2.resize(img, (320, 240)))
    with _LOCK:
        if _PLATE is None:
            _PLATE = cv2.dnn.readNet(str(path))
        _PLATE.setInput(blob)
        try:
            outs = _PLATE.forward(["loc", "conf", "iou"])
        except cv2.error:
            return None, "lpd_yunet_error"
    boxes = _decode_lpd(outs, w, h)
    return boxes, "lpd_yunet"


def _decode_lpd(outs, w: int, h: int, score_thr: float = 0.8) -> list[list[int]]:
    """LPD-YuNet decoder, ported from opencv_zoo's lpd_yunet.py (_decode)."""
    loc, conf, iou = (np.squeeze(o) for o in outs)
    priors = _lpd_priors(320, 240)
    if loc.ndim != 2 or priors.shape[0] != loc.shape[0]:
        return []
    scores = np.sqrt(conf[:, 1] * np.clip(iou.reshape(-1), 0.0, 1.0))
    keep = scores > score_thr
    if not keep.any():
        return []
    var0 = 0.1
    p = priors[keep]
    l = loc[keep]
    pts = [p[:, 0:2] + l[:, a:b] * var0 * p[:, 2:4] for a, b in ((4, 6), (6, 8), (10, 12), (12, 14))]
    pts = np.stack(pts, axis=1) * np.array([w, h])
    boxes = []
    for quad, s in zip(pts, scores[keep]):
        x0, y0 = quad.min(axis=0)
        x1, y1 = quad.max(axis=0)
        boxes.append([int(x0), int(y0), int(x1 - x0), int(y1 - y0), float(s)])
    if not boxes:
        return []
    idx = cv2.dnn.NMSBoxes([b[:4] for b in boxes], [b[4] for b in boxes], score_thr, 0.3)
    return [boxes[i][:4] for i in np.array(idx).ravel()]


def _lpd_priors(w: int, h: int) -> np.ndarray:
    feature_map_2th = [int(int((h + 1) / 2) / 2), int(int((w + 1) / 2) / 2)]
    feature_map_3th = [int(feature_map_2th[0] / 2), int(feature_map_2th[1] / 2)]
    feature_map_4th = [int(feature_map_3th[0] / 2), int(feature_map_3th[1] / 2)]
    feature_map_5th = [int(feature_map_4th[0] / 2), int(feature_map_4th[1] / 2)]
    feature_map_6th = [int(feature_map_5th[0] / 2), int(feature_map_5th[1] / 2)]
    feature_maps = [feature_map_3th, feature_map_4th, feature_map_5th, feature_map_6th]
    min_sizes = [[10, 16, 24], [32, 48], [64, 96], [128, 192, 256]]
    steps = [8, 16, 32, 64]
    priors = []
    for k, f in enumerate(feature_maps):
        for i in range(f[0]):
            for j in range(f[1]):
                for ms in min_sizes[k]:
                    cx = (j + 0.5) * steps[k] / w
                    cy = (i + 0.5) * steps[k] / h
                    priors.append([cx, cy, ms / w, ms / h])
    return np.array(priors, dtype=np.float32)


def _blur_boxes(img: np.ndarray, boxes: list[list[int]]) -> None:
    h, w = img.shape[:2]
    for x, y, bw, bh in boxes:
        pad = int(0.15 * max(bw, bh))
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(w, x + bw + pad), min(h, y + bh + pad)
        if x1 <= x0 or y1 <= y0:
            continue
        roi = img[y0:y1, x0:x1]
        k = max(15, (max(x1 - x0, y1 - y0) // 3) | 1)
        img[y0:y1, x0:x1] = cv2.GaussianBlur(roi, (k, k), 0)


def redact(img: np.ndarray, keep_mask: np.ndarray | None = None) -> tuple[np.ndarray, RedactionReport]:
    """Blur faces and plates. If either detector is unavailable and a
    ``keep_mask`` (uint8, 255 = keep) is given, blur everything outside it."""
    out = img.copy()
    faces, face_det = _detect_faces(out)
    plates, plate_det = _detect_plates(out)
    mode = "detect_and_blur"
    if (faces is None or plates is None) and keep_mask is not None:
        blurred = cv2.GaussianBlur(out, (0, 0), 15)
        out = np.where(keep_mask[..., None] > 0, out, blurred)
        mode = "roi_only"
    if faces:
        _blur_boxes(out, faces)
    if plates:
        _blur_boxes(out, plates)
    return out, RedactionReport(
        faces=None if faces is None else len(faces),
        plates=None if plates is None else len(plates),
        face_detector=face_det,
        plate_detector=plate_det,
        mode=mode,
        boxes=(faces or []) + (plates or []),
    )
