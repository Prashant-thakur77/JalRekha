"""Crop the full-page UI screenshots into README-sized views (docs/screenshots/readme/)."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(sys.argv[1])
UI = ROOT / "docs/screenshots/ui"
OUT = ROOT / "docs/screenshots/readme"
OUT.mkdir(exist_ok=True)

CROPS = {  # name: (source, top, height)
    "hero": ("home-1440-light", 0, 900),
    "live": ("live-1440-dark", 700, 900),
    "vision": ("vision-1440-light", 0, 900),
    "vision-estimators": ("vision-1440-light", 3190, 840),
    "vision-registration": ("vision-1440-light", 1640, 960),
    "rivers": ("rivers-1440-light", 110, 900),
    "relief": ("relief-1440-light", 270, 900),
    "story": ("story-1440-light", 0, 900),
    "cloud": ("cloud-1440-dark", 90, 900),
    "cloud-insights": ("cloud-1440-dark", 1430, 1110),
}
JPEG = {"hero", "story", "relief"}
for name, (src, top, h) in CROPS.items():
    im = Image.open(UI / f"{src}.png").convert("RGB")
    c = im.crop((0, top, im.width, top + h))
    if name in JPEG:
        c.save(OUT / f"{name}.jpg", quality=86, optimize=True, progressive=True)
    else:
        c.save(OUT / f"{name}.png", optimize=True)

# approvals: the card is centred, so crop it tighter (960x600, same 16:10 shape)
im = Image.open(UI / "approvals-1440-light.png").convert("RGB")
im.crop((240, 1000, 1200, 1600)).save(OUT / "approvals.png", optimize=True)

# phone composite: three 390 px views on one 1440x900 canvas
phones = [("home-390-light", 0), ("live-390-dark", 0), ("approvals-390-light", 900)]
canvas = Image.new("RGB", (1440, 900), (233, 233, 228))
gap = (1440 - 3 * 390) // 4
d = ImageDraw.Draw(canvas)
for i, (src, top) in enumerate(phones):
    im = Image.open(UI / f"{src}.png").convert("RGB").crop((0, top, 390, top + 844))
    x = gap + i * (390 + gap)
    canvas.paste(im, (x, 28))
    d.rectangle((x - 1, 27, x + 390, 28 + 844), outline=(160, 160, 155))
canvas.save(OUT / "phone.png", optimize=True)
print("ok")
