"""Procedural staff-gauge scenes with exact ground truth (labelled SYNTHETIC).

A "site" is a seed: background, gauge geometry, water colour and camera are
fixed per seed, so splitting by seed gives held-out scenes. Each call renders
a short burst (default 5 frames, 0.5 s apart) at a given true stage, with
optional degradations. Used for unit tests and robustness sweeps; real
held-out sites come from datasets/ (see eval/README.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from jalrekha.vision.gauge import GaugeCalibration, GaugeMark

W, H = 960, 540


@dataclass
class Degradation:
    rain: float = 0.0  # 0..1 streak density
    fog: float = 0.0  # 0..1 blend to grey
    night: float = 0.0  # 0..1 darkening + sensor noise
    shake_px: float = 0.0  # max translation per frame
    blur: float = 0.0  # Gaussian sigma
    glare: float = 0.0  # 0..1 specular blob on the gauge
    jpeg_q: int = 0  # 0 = off, else JPEG quality
    still_water: bool = False

    def label(self) -> str:
        parts = [f"{k}={v}" for k, v in self.__dict__.items() if v not in (0, 0.0, False)]
        return ",".join(parts) or "clean"


@dataclass
class SynthSite:
    seed: int
    gauge_x: float
    gauge_top_y: float
    px_per_m: float
    gauge_len_m: float
    angle_deg: float
    gauge_w: int
    face: tuple[int, int, int]
    water: tuple[int, int, int]
    background: np.ndarray = field(repr=False)

    def stage_to_y(self, stage_m: float, x: float | None = None) -> float:
        # Axis is tilted by angle_deg; y at the gauge axis.
        return self.gauge_top_y + (self.gauge_len_m - stage_m) * self.px_per_m * np.cos(np.radians(self.angle_deg))

    def axis_point(self, stage_m: float) -> tuple[float, float]:
        d = (self.gauge_len_m - stage_m) * self.px_per_m
        a = np.radians(self.angle_deg)
        return self.gauge_x + d * np.sin(a), self.gauge_top_y + d * np.cos(a)

    def calibration(self, click_err_px: float = 1.0, rng: np.random.Generator | None = None) -> GaugeCalibration:
        rng = rng or np.random.default_rng(self.seed + 7)
        stages = [self.gauge_len_m - 0.1, self.gauge_len_m / 2, 0.1]
        marks = []
        for s in stages:
            x, y = self.axis_point(s)
            marks.append(GaugeMark(x + rng.normal(0, click_err_px), y + rng.normal(0, click_err_px), round(s, 3)))
        return GaugeCalibration(
            marks=marks,
            strip_half_width_px=self.gauge_w * 0.42,
            reference_size=(W, H),
            warning_m=round(self.gauge_len_m * 0.6, 2),
            danger_m=round(self.gauge_len_m * 0.8, 2),
        )


def make_site(seed: int) -> SynthSite:
    rng = np.random.default_rng(seed)
    gauge_len = float(rng.uniform(2.0, 4.5))
    px_per_m = float(rng.uniform(70, min(130, 440 / gauge_len)))
    top_y = float(rng.uniform(30, H - 40 - gauge_len * px_per_m))
    bg = _background(rng)
    face = (int(rng.integers(215, 250)),) * 3 if rng.random() < 0.6 else (40, int(rng.integers(190, 225)), 235)
    water = tuple(int(v) for v in rng.choice([[60, 90, 120], [70, 100, 95], [55, 75, 90], [95, 120, 125]]) + rng.integers(-12, 12, 3))
    return SynthSite(
        seed=seed,
        gauge_x=float(rng.uniform(220, W - 220)),
        gauge_top_y=top_y,
        px_per_m=px_per_m,
        gauge_len_m=gauge_len,
        angle_deg=float(rng.uniform(-4, 4)),
        gauge_w=int(rng.integers(30, 44)),
        face=face,
        water=water,  # BGR
        background=bg,
    )


def _background(rng: np.random.Generator) -> np.ndarray:
    img = np.zeros((H, W, 3), np.float32)
    sky = np.array(rng.choice([[200, 180, 150], [170, 170, 165], [215, 200, 185]]), np.float32)
    bank = np.array(rng.choice([[70, 110, 95], [60, 90, 120], [90, 110, 120]]), np.float32)
    horizon = int(rng.uniform(0.15, 0.35) * H)
    for y in range(H):
        t = np.clip((y - horizon) / 40.0, 0, 1)
        img[y] = sky * (1 - t) + bank * t
    noise = cv2.resize(rng.normal(0, 1, (H // 8, W // 8)).astype(np.float32), (W, H), interpolation=cv2.INTER_CUBIC)
    fine = rng.normal(0, 1, (H, W)).astype(np.float32)
    img += (noise * 18 + fine * 6)[..., None]
    # a concrete pier behind the gauge region and a few structures for ORB to lock onto
    for _ in range(int(rng.integers(4, 9))):
        x0, y0 = int(rng.uniform(0, W - 80)), int(rng.uniform(0, H * 0.6))
        x1, y1 = x0 + int(rng.uniform(20, 140)), y0 + int(rng.uniform(20, 160))
        c = rng.uniform(80, 200, 3)
        cv2.rectangle(img, (x0, y0), (x1, y1), c.tolist(), -1)
        cv2.rectangle(img, (x0, y0), (x1, y1), (c * 0.6).tolist(), 2)
    return np.clip(img, 0, 255).astype(np.uint8)


def _draw_gauge(img: np.ndarray, site: SynthSite) -> None:
    """Staff gauge in the E pattern: 5 cm black blocks alternating sides, metre numbers."""
    gw = site.gauge_w
    L = int(site.gauge_len_m * site.px_per_m)
    board = np.full((L, gw, 3), site.face, np.uint8)
    cm5 = site.px_per_m * 0.05
    n = int(site.gauge_len_m / 0.05)
    for i in range(n):
        if i % 2:
            continue
        y0 = int(L - (i + 1) * cm5)
        y1 = int(L - i * cm5)
        half = (i // 2) % 2
        x0, x1 = (2, gw // 2) if half == 0 else (gw // 2, gw - 2)
        colour = (20, 20, 20) if (i // 20) % 2 == 0 else (30, 30, 190)
        cv2.rectangle(board, (x0, max(0, y0)), (x1, max(0, y1 - 1)), colour, -1)
    for m in range(int(site.gauge_len_m) + 1):
        y = int(L - m * site.px_per_m)
        cv2.line(board, (0, min(L - 1, y)), (gw, min(L - 1, y)), (20, 20, 160), 2)
    cv2.rectangle(board, (0, 0), (gw - 1, L - 1), (40, 40, 40), 1)
    a = np.radians(site.angle_deg)
    src = np.float32([[0, 0], [gw, 0], [0, L]])
    top_left = np.array([site.gauge_x - gw / 2 * np.cos(a), site.gauge_top_y + gw / 2 * np.sin(a)])
    dst = np.float32(
        [
            top_left,
            top_left + np.array([gw * np.cos(a), -gw * np.sin(a)]),
            top_left + np.array([L * np.sin(a), L * np.cos(a)]),
        ]
    )
    m = cv2.getAffineTransform(src, dst)
    warped = cv2.warpAffine(board, m, (W, H), flags=cv2.INTER_LINEAR)
    mask = cv2.warpAffine(np.full((L, gw), 255, np.uint8), m, (W, H), flags=cv2.INTER_NEAREST)
    img[mask > 0] = warped[mask > 0]


def render_burst(
    site: SynthSite,
    stage_m: float,
    *,
    n: int = 5,
    dt: float = 0.5,
    t0: float = 0.0,
    deg: Degradation | None = None,
    rng: np.random.Generator | None = None,
) -> list[np.ndarray]:
    deg = deg or Degradation()
    rng = rng or np.random.default_rng(site.seed * 1000 + int(stage_m * 1000))
    base = site.background.copy()
    _draw_gauge(base, site)
    frames = []
    xs = np.arange(W, dtype=np.float32)
    amp = 0.0 if deg.still_water else float(rng.uniform(1.5, 4.0))
    k1, k2 = rng.uniform(0.02, 0.05), rng.uniform(0.08, 0.15)
    for i in range(n):
        t = t0 + i * dt
        img = base.astype(np.float32)
        wy = site.stage_to_y(stage_m)
        surface = wy + amp * np.sin(k1 * xs + 2.1 * t) + 0.5 * amp * np.sin(k2 * xs - 3.3 * t)
        yy = np.arange(H, dtype=np.float32)[:, None]
        water_mask = yy >= surface[None, :]
        # reflection: mirror the scene above the surface, rippled
        depth = np.clip(yy - surface[None, :], 0, None)
        mx = (xs[None, :] + (0 if deg.still_water else 3.0) * np.sin(0.15 * yy + 4.0 * t)).astype(np.float32)
        my = np.clip(surface[None, :] - depth, 0, H - 1).astype(np.float32)
        refl = cv2.remap(base, np.broadcast_to(mx, (H, W)).copy(), np.broadcast_to(my, (H, W)).copy(), cv2.INTER_LINEAR)
        tex = np.zeros((H, W), np.float32)
        if not deg.still_water:
            tex = (
                9 * np.sin(0.09 * xs[None, :] + 0.35 * yy + 5.0 * t)
                + 6 * np.sin(0.21 * xs[None, :] - 0.6 * yy - 7.0 * t + i)
                + rng.normal(0, 4, (H, W))
            ).astype(np.float32)
        water = np.array(site.water, np.float32)[None, None, :] + tex[..., None]
        water = 0.75 * water + 0.25 * refl.astype(np.float32)
        img = np.where(water_mask[..., None], water, img)
        # thin darker meniscus band at the waterline
        band = (np.abs(yy - surface[None, :]) < 1.5)[..., None]
        img = np.where(band, img * 0.7, img)
        img = np.clip(img, 0, 255).astype(np.uint8)
        img = _degrade(img, deg, rng, site)
        frames.append(img)
    return frames


def _degrade(img: np.ndarray, deg: Degradation, rng: np.random.Generator, site: SynthSite) -> np.ndarray:
    out = img.astype(np.float32)
    if deg.glare > 0:
        gx, gy = site.axis_point(site.gauge_len_m * rng.uniform(0.3, 0.8))
        glare = np.zeros(out.shape[:2], np.float32)
        cv2.ellipse(glare, (int(gx), int(gy)), (int(25 + 60 * deg.glare), int(15 + 40 * deg.glare)), 0, 0, 360, 1.0, -1)
        glare = cv2.GaussianBlur(glare, (0, 0), 12)
        out = out + glare[..., None] * 255 * deg.glare
    if deg.fog > 0:
        out = out * (1 - deg.fog) + 190 * deg.fog
    if deg.rain > 0:
        streaks = np.zeros(out.shape[:2], np.float32)
        for _ in range(int(1500 * deg.rain)):
            x, y = rng.integers(0, W), rng.integers(0, H)
            ln = rng.integers(8, 22)
            cv2.line(streaks, (int(x), int(y)), (int(x + ln * 0.25), int(y + ln)), 1.0, 1)
        streaks = cv2.GaussianBlur(streaks, (3, 3), 0)
        out = out * (1 - 0.35 * streaks[..., None]) + 220 * 0.35 * streaks[..., None]
    if deg.night > 0:
        out = out * (1 - 0.88 * deg.night) + rng.normal(0, 14 * deg.night, out.shape)
    if deg.blur > 0:
        out = cv2.GaussianBlur(out, (0, 0), deg.blur)
    if deg.shake_px > 0:
        tx, ty = rng.uniform(-deg.shake_px, deg.shake_px, 2)
        rot = rng.uniform(-0.6, 0.6) * min(1.0, deg.shake_px / 10)
        m = cv2.getRotationMatrix2D((W / 2, H / 2), rot, 1.0)
        m[:, 2] += (tx, ty)
        out = cv2.warpAffine(out, m, (W, H), borderMode=cv2.BORDER_REFLECT)
    out = np.clip(out, 0, 255).astype(np.uint8)
    if deg.jpeg_q:
        ok, enc = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, int(deg.jpeg_q)])
        out = cv2.imdecode(enc, cv2.IMREAD_COLOR)
    return out


def reference_frame(site: SynthSite) -> np.ndarray:
    """Calibration reference: low water, clean, no shake."""
    return render_burst(site, site.gauge_len_m * 0.15, n=1, deg=Degradation(), rng=np.random.default_rng(site.seed))[0]
