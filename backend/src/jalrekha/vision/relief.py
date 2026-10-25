"""Phone-photo inundation check for the relief layer (roads, bridges, lanes).

1. Privacy first: faces and plates are blurred (YuNet) before anything else.
2. Water mask: GrabCut seeded from texture and position. Flood water in
   phone photos is a low-texture, fairly uniform region in the lower part of
   the frame; the top band is seeded as background.
3. Depth (optional): the user taps the top and the base of a reference
   object of known height (default 1.0 m road bollard). The waterline is
   where the water mask starts along that segment; depth = submerged
   fraction x object height, with an error band from a +/-3 px tap error.
4. Passability: depth >= ROAD_UNSAFE_M -> "no"; water present but no depth
   -> "unknown". Always ``needs_review=True``: a person decides.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np

from jalrekha.vision import privacy

ROAD_UNSAFE_M = 0.30  # configurable assumption, see docs/MODEL_CARDS.md
TAP_ERR_PX = 3.0
WORK_SIDE = 640


@dataclass
class PhotoCheck:
    water_fraction: float
    lower_water_fraction: float
    waterline_y: int | None
    submerged_frac: float | None
    est_depth_m: float | None
    depth_pm_m: float | None
    passable: str
    confidence: float
    needs_review: bool
    faces_blurred: int
    plates_blurred: int
    method: str
    notes: list[str]

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("water_fraction", "lower_water_fraction", "submerged_frac", "est_depth_m", "depth_pm_m", "confidence"):
            if d[k] is not None:
                d[k] = round(float(d[k]), 3)
        return d


def water_mask(img: np.ndarray) -> tuple[np.ndarray, float]:
    """Returns (mask uint8 0/255 at the input size, separation score 0..1)."""
    h, w = img.shape[:2]
    s = WORK_SIDE / max(h, w)
    small = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else img.copy()
    sh, sw = small.shape[:2]
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    lap = np.abs(cv2.Laplacian(cv2.GaussianBlur(gray, (5, 5), 0), cv2.CV_32F))
    tex = cv2.blur(lap, (15, 15))
    smooth = tex < np.percentile(tex, 35)
    gc = np.full((sh, sw), cv2.GC_PR_BGD, np.uint8)
    lower = np.zeros_like(smooth)
    lower[int(sh * 0.55):, :] = True
    gc[smooth & lower] = cv2.GC_PR_FGD
    gc[: int(sh * 0.12), :] = cv2.GC_BGD
    gc[int(sh * 0.88):, int(sw * 0.3): int(sw * 0.7)][smooth[int(sh * 0.88):, int(sw * 0.3): int(sw * 0.7)]] = cv2.GC_FGD
    if not (gc == cv2.GC_PR_FGD).any() and not (gc == cv2.GC_FGD).any():
        return np.zeros((h, w), np.uint8), 0.0
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(small, gc, None, bgd, fgd, 4, cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        return np.zeros((h, w), np.uint8), 0.0
    m = np.where((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    # Keep components touching the lower third (water is connected to the foreground).
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
    keep = np.zeros_like(m)
    for i in range(1, n):
        x, y, ww, hh, area = stats[i]
        if y + hh >= sh * 0.66 and area >= 0.01 * sh * sw:
            keep[lab == i] = 255
    lab_img = cv2.cvtColor(small, cv2.COLOR_BGR2Lab).astype(np.float32)
    if keep.any() and (keep == 0).any():
        a, b = lab_img[keep > 0].mean(0), lab_img[keep == 0].mean(0)
        sa, sb = lab_img[keep > 0].std(0).mean(), lab_img[keep == 0].std(0).mean()
        sep = float(np.clip(np.linalg.norm(a - b) / (sa + sb + 1e-6) / 2.0, 0, 1))
    else:
        sep = 0.0
    return cv2.resize(keep, (w, h), interpolation=cv2.INTER_NEAREST), sep


def _waterline_along(mask: np.ndarray, top: tuple[float, float], base: tuple[float, float]) -> float | None:
    """Fraction along top->base where the mask turns to water for good (0 = top, 1 = base)."""
    n = 200
    xs = np.linspace(top[0], base[0], n)
    ys = np.linspace(top[1], base[1], n)
    h, w = mask.shape
    vals = np.array([mask[int(np.clip(y, 0, h - 1)), int(np.clip(x, 0, w - 1))] > 0 for x, y in zip(xs, ys)])
    if not vals.any():
        return None
    # first index after which >= 80% of the remaining samples are water
    for i in range(n):
        if vals[i] and vals[i:].mean() >= 0.8:
            return i / (n - 1)
    return None


def check_photo(img: np.ndarray, ref_top: tuple[float, float] | None = None, ref_base: tuple[float, float] | None = None,
                ref_height_m: float = 1.0) -> tuple[PhotoCheck, np.ndarray]:
    redacted, red = privacy.redact(img)
    mask, sep = water_mask(redacted)
    h = mask.shape[0]
    wf = float((mask > 0).mean())
    lwf = float((mask[h // 2:] > 0).mean())
    notes: list[str] = []
    waterline_y = submerged = depth = pm = None
    if ref_top is not None and ref_base is not None:
        frac = _waterline_along(mask, ref_top, ref_base)
        seg_px = float(np.hypot(ref_base[0] - ref_top[0], ref_base[1] - ref_top[1]))
        if frac is None:
            submerged, depth, pm = 0.0, 0.0, ref_height_m * TAP_ERR_PX * 2 / max(seg_px, 1.0)
            notes.append("no water found along the reference object")
        elif seg_px < 20:
            notes.append("reference object too small in the image (< 20 px)")
        else:
            submerged = 1.0 - frac
            depth = submerged * ref_height_m
            pm = ref_height_m * (TAP_ERR_PX * 2 + 2) / seg_px
            waterline_y = int(ref_top[1] + frac * (ref_base[1] - ref_top[1]))
    else:
        notes.append("no reference object tapped: depth not estimated")
    if depth is not None:
        passable = "no" if depth - (pm or 0) >= ROAD_UNSAFE_M else ("yes" if depth + (pm or 0) < 0.1 and lwf < 0.2 else "unknown")
    else:
        passable = "unknown" if lwf >= 0.15 else ("yes" if lwf < 0.05 else "unknown")
    conf = float(np.clip(0.3 + 0.5 * sep + (0.2 if depth is not None else 0.0), 0, 0.95))
    res = PhotoCheck(wf, lwf, waterline_y, submerged, depth, pm, passable, conf, True,
                     (red.faces or 0) if red else 0, (red.plates or 0) if red else 0, "grabcut-texture-seeded", notes)
    ov = redacted.copy()
    tint = ov.copy()
    tint[mask > 0] = (255, 120, 0)
    ov = cv2.addWeighted(tint, 0.35, ov, 0.65, 0)
    if ref_top is not None and ref_base is not None:
        cv2.line(ov, tuple(map(int, ref_top)), tuple(map(int, ref_base)), (0, 255, 255), 2)
        if waterline_y is not None:
            cv2.circle(ov, (int(ref_top[0] + (ref_base[0] - ref_top[0]) * (1 - (submerged or 0))), waterline_y), 6, (0, 0, 255), -1)
    label = f"water {lwf * 100:.0f}% (lower half)" + (f" | depth {depth:.2f}+/-{pm:.2f} m" if depth is not None else "") + f" | {passable}"
    cv2.rectangle(ov, (0, 0), (ov.shape[1], 30), (0, 0, 0), -1)
    cv2.putText(ov, label, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    return res, ov
