"""Pre-render the atmosphere images (technical specification §8.10, visual system: atmosphere).

    uv run python scripts/theme/gen_atmosphere.py

Writes into src/roundtable_souls/ui/assets/atmosphere/ (Pillow only, no numpy; the PNGs are committed, so a build
never needs this):
    bloom-dark-a.png      gold #F9C043, radial, alpha peaking at 6 % (ceiling 8: at 8 the bloom was pointable), radius 700 px, centre at 1/3 of the
                          image so the whole falloff fits (placed near the inset's top-left corner)
    bloom-dark-b.png      ember #BD6707 at 4 % (spec 5), centre at 2/3 (bottom-right)
    bloom-light-a.png     moonlight #63B5F5 at 5 % (spec 7 / frost bloom 6: over the L97 page a blue tint shows per % far more than gold on dark; top-left, also the "frost bloom" of v2.5 C at the inset corner)
    bloom-light-b.png     white (bottom-right). v2.5 F gives it no number; over the L97 page a white bloom at the 8 %
                          ceiling moves lightness by 0.2 (invisible), so it peaks at 35 %: perceptually weaker than
                          the gold one on dark
    vignette-1024.png     black at the corners (8 % ceiling), transparent in the middle; stretched over the page in the
                          dark theme only

All blooms are 1024 px RGBA with a smoothstep falloff and a +-0.5 alpha dither against banding (an 8 % peak is only
20 alpha levels). Regenerate after changing a colour or a ceiling; the QML never scales the blooms (sourceSize kept).
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "src" / "roundtable_souls" / "ui" / "assets" / "atmosphere"
SIZE = 1024
BLOOM_RADIUS = 700

GOLD = (0xF9, 0xC0, 0x43)
EMBER = (0xBD, 0x67, 0x07)
MOONLIGHT = (0x63, 0xB5, 0xF5)
WHITE = (0xFF, 0xFF, 0xFF)
BLACK = (0, 0, 0)

CEILING_BLOOM = 0.08
CEILING_VIGNETTE = 0.08


def _falloff(t: float) -> float:
    """1 at the centre, 0 at t >= 1, smoothstep-shaped (a soft plateau, no hard edge)."""
    if t >= 1.0:
        return 0.0
    return 1.0 - (3.0 * t * t - 2.0 * t * t * t)


def bloom(
    colour: tuple[int, int, int], peak: float, centre: tuple[float, float], radius: int = BLOOM_RADIUS
) -> Image.Image:
    rng = random.Random(7)
    cx, cy = centre[0] * (SIZE - 1), centre[1] * (SIZE - 1)
    alpha = bytearray(SIZE * SIZE)
    peak255 = peak * 255.0
    i = 0
    for y in range(SIZE):
        dy = (y - cy) ** 2
        for x in range(SIZE):
            t = math.sqrt((x - cx) ** 2 + dy) / radius
            a = peak255 * _falloff(t)
            if a > 0.0:
                a += rng.random() - 0.5  # dither
            alpha[i] = int(min(255, max(0, round(a))))
            i += 1
    img = Image.new("RGBA", (SIZE, SIZE), colour + (0,))
    img.putalpha(Image.frombytes("L", (SIZE, SIZE), bytes(alpha)))
    return img


def vignette(peak: float = CEILING_VIGNETTE, inner: float = 0.35) -> Image.Image:
    rng = random.Random(3)
    alpha = bytearray(SIZE * SIZE)
    peak255 = peak * 255.0
    i = 0
    for y in range(SIZE):
        ny = y / (SIZE - 1) * 2.0 - 1.0
        for x in range(SIZE):
            nx = x / (SIZE - 1) * 2.0 - 1.0
            d = math.sqrt(nx * nx + ny * ny) / math.sqrt(2.0)  # 0 centre, 1 corner
            t = (d - inner) / (1.0 - inner)
            if t <= 0.0:
                a = 0.0
            else:
                t = min(1.0, t)
                a = peak255 * ((3.0 * t * t - 2.0 * t * t * t) ** 1.5) + rng.random() - 0.5
            alpha[i] = int(min(255, max(0, round(a))))
            i += 1
    img = Image.new("RGBA", (SIZE, SIZE), BLACK + (0,))
    img.putalpha(Image.frombytes("L", (SIZE, SIZE), bytes(alpha)))
    return img


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = {
        "bloom-dark-a.png": lambda: bloom(GOLD, 0.06, (1 / 3, 1 / 3)),
        "bloom-dark-b.png": lambda: bloom(EMBER, 0.04, (2 / 3, 2 / 3)),
        "bloom-light-a.png": lambda: bloom(MOONLIGHT, 0.05, (1 / 3, 1 / 3)),
        "bloom-light-b.png": lambda: bloom(WHITE, 0.35, (2 / 3, 2 / 3)),
        "vignette-1024.png": vignette,
    }
    for name, make in jobs.items():
        img = make()
        path = OUT / name
        img.save(path, optimize=True)
        a = img.getchannel("A")
        print(
            f"{path}  {img.size[0]}x{img.size[1]}  alpha max {a.getextrema()[1]}/255  {path.stat().st_size // 1024} KB"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
