"""The colour maths the theme generator and the contrast test share: sRGB <-> OKLCH (no numpy), compositing, WCAG
contrast and the hex forms. One module, so a token change cannot pass one and fail the other."""

from __future__ import annotations

import math

Rgba = tuple[float, float, float, float]  # 0..1 each, sRGB (gamma) + alpha


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    c = min(1.0, max(0.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _cbrt(x: float) -> float:
    return math.copysign(abs(x) ** (1 / 3), x)


def srgb_to_oklab(r: float, g: float, b: float) -> tuple[float, float, float]:
    r, g, b = _srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b)
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = _cbrt(l), _cbrt(m), _cbrt(s)
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def oklab_to_linear_srgb(L: float, a: float, b: float) -> tuple[float, float, float]:
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_**3, m_**3, s_**3
    return (
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )


def srgb_to_oklch(r: float, g: float, b: float) -> tuple[float, float, float]:
    L, a, bb = srgb_to_oklab(r, g, b)
    c = math.hypot(a, bb)
    h = math.degrees(math.atan2(bb, a)) % 360 if c > 1e-6 else 0.0
    return L, c, h


def oklch_to_srgb(L: float, C: float, H: float) -> tuple[float, float, float]:
    """OKLCH to sRGB with gamut mapping: lightness and hue are kept, chroma is reduced until the colour fits."""
    L = min(1.0, max(0.0, L))

    def convert(c: float) -> tuple[float, float, float]:
        a, b = c * math.cos(math.radians(H)), c * math.sin(math.radians(H))
        return oklab_to_linear_srgb(L, a, b)

    def in_gamut(rgb: tuple[float, float, float]) -> bool:
        return all(-0.0005 <= v <= 1.0005 for v in rgb)

    rgb = convert(C)
    if not in_gamut(rgb):
        lo, hi = 0.0, C
        for _ in range(32):
            mid = (lo + hi) / 2
            if in_gamut(convert(mid)):
                lo = mid
            else:
                hi = mid
        rgb = convert(lo)
    r, g, b = (_linear_to_srgb(v) for v in rgb)
    return r, g, b


def shift_lightness(color: Rgba, dL: float) -> Rgba:
    L, C, H = srgb_to_oklch(*color[:3])
    r, g, b = oklch_to_srgb(L + dL, C, H)
    return (r, g, b, color[3])


def composite(fg: Rgba, bg: Rgba) -> Rgba:
    """fg over an opaque bg, in sRGB gamma space (how Qt blends)."""
    a = fg[3]
    r, g, b = (fg[i] * a + bg[i] * (1 - a) for i in range(3))
    return (r, g, b, 1.0)


def luminance(c: Rgba) -> float:
    r, g, b = (_srgb_to_linear(v) for v in c[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: Rgba, b: Rgba) -> float:
    """WCAG 2.x contrast ratio of two opaque colours."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def parse_hex(s: str) -> Rgba:
    s = s.lstrip("#")
    if len(s) == 6:
        s += "FF"
    if len(s) != 8:
        raise ValueError(f"bad hex colour {s!r}")
    r, g, b, a = (int(s[i : i + 2], 16) / 255 for i in (0, 2, 4, 6))
    return (r, g, b, a)


def to_hex(c: Rgba) -> str:
    """#RRGGBB, or #RRGGBBAA when translucent (CSS order; see qt_hex for QML / QColor)."""
    r, g, b = (round(min(1.0, max(0.0, v)) * 255) for v in c[:3])
    if c[3] >= 0.9995:
        return f"#{r:02X}{g:02X}{b:02X}"
    return f"#{r:02X}{g:02X}{b:02X}{round(c[3] * 255):02X}"


def qt_hex(c: Rgba) -> str:
    """#RRGGBB, or #AARRGGBB when translucent (what QML's color type and QColor parse)."""
    r, g, b = (round(min(1.0, max(0.0, v)) * 255) for v in c[:3])
    if c[3] >= 0.9995:
        return f"#{r:02X}{g:02X}{b:02X}"
    return f"#{round(c[3] * 255):02X}{r:02X}{g:02X}{b:02X}"
