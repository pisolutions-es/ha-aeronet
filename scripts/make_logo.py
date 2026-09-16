"""Generate logo.png (480x240) for the NASA AERONET integration.

Reproducible: run from the repo root with Pillow installed
(e.g. `python3 -m venv .venv && .venv/bin/pip install pillow`, then
`.venv/bin/python scripts/make_logo.py`).

Motif: sun + aerosol haze layers over a sun-photometer station, NASA blue
palette, 'AERONET' wordmark. No external assets are used — pure drawing.
"""
from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFilter

W, H = 480, 240

# NASA-ish palette.
BLUE_DEEP = (11, 31, 64)       # night-sky blue base
BLUE_MID = (18, 55, 110)
BLUE_SKY = (28, 86, 166)
BLUE_NASA = (18, 59, 140)      # NASA ribbon blue
ORANGE = (248, 138, 24)        # NASA meatball accent orange
GOLD = (255, 196, 64)
HAZE = (140, 180, 226)
WHITE = (255, 255, 255)


def _font(size: int):
    from PIL import ImageFont

    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> None:
    img = Image.new("RGB", (W, H), BLUE_DEEP)
    draw = ImageDraw.Draw(img)

    # --- Sky: vertical gradient deep blue -> lighter horizon blue.
    for y in range(H):
        t = y / (H - 1)
        r = int(BLUE_DEEP[0] + (BLUE_SKY[0] - BLUE_DEEP[0]) * t * 0.9)
        g = int(BLUE_DEEP[1] + (BLUE_SKY[1] - BLUE_DEEP[1]) * t * 0.9)
        b = int(BLUE_DEEP[2] + (BLUE_SKY[2] - BLUE_DEEP[2]) * t * 0.9)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # --- Sun with soft glow, upper-left third.
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    sx, sy, sr = 118, 86, 26
    gd.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=GOLD)
    gd.ellipse([sx - sr - 10, sy - sr - 10, sx + sr + 10, sy + sr + 10],
               fill=(60, 44, 10))
    glow = glow.filter(ImageFilter.GaussianBlur(14))
    img = Image.blend(img, Image.blend(img, glow, 0.9), 0.55)
    draw = ImageDraw.Draw(img)
    draw.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=GOLD)
    # Rays.
    for k in range(12):
        a = math.radians(k * 30 + 8)
        r1, r2 = sr + 6, sr + 16
        draw.line(
            [(sx + r1 * math.cos(a), sy + r1 * math.sin(a)),
             (sx + r2 * math.cos(a), sy + r2 * math.sin(a))],
            fill=GOLD, width=3)

    # --- Aerosol haze layers: translucent horizontal bands across the sky.
    haze = Image.new("RGB", (W, H), BLUE_DEEP)
    hd = ImageDraw.Draw(haze)
    bands = [(120, 12, 0.55), (138, 9, 0.42), (152, 7, 0.30), (163, 5, 0.20)]
    for by, bh, _a in bands:
        for x in range(0, W, 2):
            wob = 3.2 * math.sin(x / 46.0 + by)
            hd.line([(x, by + wob), (x + 1, by + wob + bh)], fill=HAZE)
    haze = haze.filter(ImageFilter.GaussianBlur(2.2))
    img = Image.blend(img, haze, 0.34)
    draw = ImageDraw.Draw(img)

    # --- Horizon / ground.
    ground_y = 196
    draw.rectangle([0, ground_y, W, H], fill=(9, 22, 44))
    draw.line([(0, ground_y), (W, ground_y)], fill=(90, 140, 200), width=2)

    # --- Sun-photometer station on the right of the horizon.
    px = 356
    # tripod
    draw.line([(px, ground_y), (px - 14, ground_y + 30)], fill=WHITE, width=3)
    draw.line([(px, ground_y), (px + 14, ground_y + 30)], fill=WHITE, width=3)
    draw.line([(px, ground_y), (px, ground_y + 30)], fill=WHITE, width=3)
    # head pointing at the sun
    ang = math.atan2(sy - (ground_y - 12), sx - px)
    hx = px + 20 * math.cos(ang)
    hy = (ground_y - 12) + 20 * math.sin(ang)
    draw.ellipse([px - 7, ground_y - 19, px + 7, ground_y - 5], fill=WHITE)
    draw.line([(px, ground_y - 12), (hx, hy)], fill=WHITE, width=5)
    draw.ellipse([hx - 5, hy - 5, hx + 5, hy + 5], fill=ORANGE)
    # sight line to the sun (dashed)
    steps = 14
    for i in range(2, steps - 1):
        t = i / steps
        x1 = hx + (sx - hx) * t
        y1 = hy + (sy - hy) * t
        x2 = hx + (sx - hx) * (t + 0.03)
        y2 = hy + (sy - hy) * (t + 0.03)
        draw.line([(x1, y1), (x2, y2)], fill=(255, 224, 150), width=2)

    # --- Wordmark.
    font_big = _font(52)
    font_small = _font(15)
    text = "AERONET"
    tb = draw.textbbox((0, 0), text, font=font_big)
    tw = tb[2] - tb[0]
    tx, ty = (W - tw) // 2, 186
    # subtle shadow
    draw.text((tx + 2, ty + 2), text, font=font_big, fill=(4, 12, 28))
    draw.text((tx, ty), text, font=font_big, fill=WHITE)
    sub = "NASA AEROSOL NETWORK  ·  HOME ASSISTANT"
    sb = draw.textbbox((0, 0), sub, font=font_small)
    sw = sb[2] - sb[0]
    draw.text(((W - sw) // 2, ty + 58), sub, font=font_small,
              fill=(150, 190, 235))

    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "logo.png")
    img.save(out, "PNG")
    print(f"wrote {out} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
