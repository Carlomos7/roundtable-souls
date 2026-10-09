"""Regenerates the grain textures: grain-dark.png and grain-light.png in src/roundtable_souls/ui/assets/atmosphere/.

Why it is built this way:
  - BLUE noise, not white noise. White noise has energy at every scale, so neighbouring pixels clump into blotches
    that read as dirt; blue noise (void and cluster, Ulichney 1993) pushes the energy to the finest scale, so at a
    normal viewing distance it averages out to a smooth surface and only masks banding. It also tiles without seams
    at 64 px. Never blur grain: blurring makes it lower frequency, which is exactly what makes it visible.
  - ZERO MEAN on the theme's surface. A white speck at alpha a moves a dark pixel up by a*(255-bg); a black one
    moves it down by a*bg. On a near-black page those differ ~9x, so equal alphas would lift the page grey. Each
    texture is balanced for its theme's reference surface: the weaker side's alpha is scaled down so a speck moves
    the surface the same number of levels up as down.
  - Uniform ranks (each threshold used once) give an even spread of strengths, no rare bright pops.

    uv run --with numpy python scripts/theme/gen_grain.py   (NumPy is not a project dependency; about one second)
"""

from pathlib import Path

import numpy as np  # pyright: ignore[reportMissingImports]  (run with --with numpy)
from PIL import Image

N = 64  # tile size; blue noise tiles cleanly at 64 (Peters, "Free blue noise textures")
SIGMA = 1.9  # void-and-cluster gaussian, the usual value
REF_DARK = 24  # the dark theme's page / bar level (Theme: #191A14 page, #13140F bar)
REF_LIGHT = 240  # the light theme's page level


def gaussian_kernel(n: int, sigma: float) -> np.ndarray:
    d = np.minimum(np.arange(n), n - np.arange(n))  # toroidal distance from 0
    g = np.exp(-(d[:, None] ** 2 + d[None, :] ** 2) / (2 * sigma * sigma))
    return g


def void_and_cluster(n: int, sigma: float, seed: int = 1729) -> np.ndarray:
    """Returns an n x n array of ranks 0..n*n-1 with a blue-noise distribution."""
    rng = np.random.default_rng(seed)
    k = gaussian_kernel(n, sigma)

    def energy_of(mask):
        return np.real(np.fft.ifft2(np.fft.fft2(mask) * np.fft.fft2(k)))

    def splat(e, y, x, sign):
        e += sign * np.roll(np.roll(k, y, 0), x, 1)

    total = n * n
    # 1. initial binary pattern: ~10 % random points, relaxed until the tightest cluster is the largest void
    mask = np.zeros((n, n), bool)
    mask.flat[rng.choice(total, total // 10, replace=False)] = True
    e = energy_of(mask.astype(float))
    while True:
        cy, cx = np.unravel_index(np.argmax(np.where(mask, e, -np.inf)), e.shape)
        mask[cy, cx] = False
        splat(e, cy, cx, -1)
        vy, vx = np.unravel_index(np.argmin(np.where(mask, np.inf, e)), e.shape)
        if (vy, vx) == (cy, cx):
            mask[cy, cx] = True
            splat(e, cy, cx, 1)
            break
        mask[vy, vx] = True
        splat(e, vy, vx, 1)
    ranks = np.zeros((n, n), int)
    ones = int(mask.sum())
    # 2. ranks below the initial pattern: remove the tightest cluster each time
    m, en = mask.copy(), e.copy()
    for r in range(ones - 1, -1, -1):
        y, x = np.unravel_index(np.argmax(np.where(m, en, -np.inf)), en.shape)
        m[y, x] = False
        splat(en, y, x, -1)
        ranks[y, x] = r
    # 3. ranks above it: fill the largest void each time
    m, en = mask.copy(), e.copy()
    for r in range(ones, total):
        y, x = np.unravel_index(np.argmin(np.where(m, np.inf, en)), en.shape)
        m[y, x] = True
        splat(en, y, x, 1)
        ranks[y, x] = r
    return ranks


def texture(ranks: np.ndarray, ref: int) -> Image.Image:
    s = (ranks + 0.5) / ranks.size * 2 - 1  # uniform in (-1, 1), blue-noise arranged
    up, down = 255 - ref, ref  # levels a full-alpha white / black speck moves the surface
    weak = min(up, down)
    a_white = np.abs(s) * (weak / up)  # balanced: both sides move the surface by |s| * weak levels
    a_black = np.abs(s) * (weak / down)
    v = np.where(s >= 0, 255, 0)
    a = np.where(s >= 0, a_white, a_black) * 255
    return Image.fromarray(np.dstack([v, v, v, np.round(a)]).astype(np.uint8), "RGBA")


if __name__ == "__main__":
    here = Path(__file__).resolve().parents[2] / "src" / "roundtable_souls" / "ui" / "assets" / "atmosphere"
    r = void_and_cluster(N, SIGMA)
    assert sorted(r.flat) == list(range(N * N))
    texture(r, REF_DARK).save(here / "grain-dark.png", optimize=True)
    texture(r, REF_LIGHT).save(here / "grain-light.png", optimize=True)
    print("wrote grain-dark.png, grain-light.png")
