"""Build the Windows icon from a square mark.

Windows 11 applies its own rounded mask. A pre-cut circle sits small inside that
plate, so the artwork is a full-bleed square. Each ICO size is drawn on its own
(not a shrink of 256): 16 and 20 keep ring + disc, 24 adds four rays, larger
sizes use all eight. Frames are PNG inside the ICO. Sizes follow the current
shell ladder: 16, 20, 24, 32, 40, 48, 64, 128, 256.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parents[1] / "src" / "roundtable_souls" / "assets"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
PREVIEW = 512

DARK = {"plate": (10, 6, 4, 255), "ink": (249, 192, 67, 255)}
LIGHT = {"plate": (214, 234, 242, 255), "ink": (7, 92, 139, 255)}


def _mark(size: int, plate, ink) -> Image.Image:
    scale = 8 if size <= 24 else 4
    n = size * scale
    im = Image.new("RGBA", (n, n), plate)
    d = ImageDraw.Draw(im)
    cx = cy = (n - 1) / 2
    # Live area ~ 68% so the Win11 corner mask does not clip the ring.
    outer = n * 0.34
    stroke = max(scale, round(n * 0.045))
    disc = max(scale, n * 0.055)
    ring_box = [cx - outer, cy - outer, cx + outer, cy + outer]
    d.ellipse(ring_box, outline=ink, width=stroke)
    d.ellipse([cx - disc, cy - disc, cx + disc, cy + disc], fill=ink)
    if size >= 24:
        rays = 4 if size < 32 else 8
        inner = disc + stroke * 1.15
        tip = outer - stroke * 1.35
        for i in range(rays):
            a = math.radians(i * (360 / rays) - 90)
            x0, y0 = cx + inner * math.cos(a), cy + inner * math.sin(a)
            x1, y1 = cx + tip * math.cos(a), cy + tip * math.sin(a)
            d.line([(x0, y0), (x1, y1)], fill=ink, width=stroke, joint="curve")
    return im.resize((size, size), Image.Resampling.LANCZOS)


def _set(theme: dict) -> list[Image.Image]:
    return [_mark(s, theme["plate"], theme["ink"]) for s in SIZES]


def write_ico(frames: list[Image.Image], dest: Path) -> None:
    sizes = [(im.width, im.height) for im in frames]
    master = max(frames, key=lambda im: im.width)
    extras = [im for im in frames if im is not master]
    master.save(dest, format="ICO", sizes=sizes, append_images=extras)


def main() -> None:
    dark = _set(DARK)
    write_ico(dark, HERE / "icon.ico")
    _mark(PREVIEW, DARK["plate"], DARK["ink"]).save(HERE / "logo-dark.png")
    _mark(PREVIEW, LIGHT["plate"], LIGHT["ink"]).save(HERE / "logo-light.png")
    print("wrote", HERE / "icon.ico", "and square logo-dark.png / logo-light.png")


if __name__ == "__main__":
    main()
