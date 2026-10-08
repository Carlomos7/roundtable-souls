"""Contrast checks for scripts/theme/tokens.json (technical specification §8.10, the contrast gate): every text /
background pair in the dark, light and Tarnished themes >= 4.5:1, 3:1 for de-emphasised text, icons, component
borders and the focus ring, and the hairline between 1.3:1 and 1.6:1. Reads tokens.json, never the generated files.

    uv run pytest tests/unit/test_theme_contrast.py
    uv run python tests/unit/test_theme_contrast.py      (prints every pair and its ratio)

Translucent colours are composited over their background first (sRGB, like Qt), then the WCAG 2.x relative
luminance formula gives the ratio. The acrylic pairs use the tint applied (card at 70% dark / 80% light over what is
behind). If a pair fails, fix tokens.json, not the test.

Deliberate scope notes
- text.tertiary (50%) is checked at 3:1 (captions, timestamps: de-emphasised large-ish type), text.disabled is
  reported only (WCAG exempts inactive controls).
- border.edge (the inset corner / menu-bar seam) and border.hairline are decorative separators, not component
  boundaries: a 3:1 edge against the bar would be an OKLCH L~0.52 stripe around the page, which contradicts the
  decided "edge = white 10%". The 3:1 rule is applied to the borders that identify a component: the focus ring, the
  error border, the toggle outline. The edge is checked to read at least as clearly as a hairline (>= 1.3:1).
"""

from __future__ import annotations

import sys
from functools import cache
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "theme"))

from colour import Rgba, composite, contrast  # noqa: E402  # pyright: ignore[reportMissingImports]
from gen_theme import load_tokens, resolve_all, theme_colors  # noqa: E402  # pyright: ignore[reportMissingImports]

THEMES = ("dark", "tarnished", "light")  # tarnished = dark + the olive overrides
AA = 4.5
LARGE = 3.0
HAIR_LO, HAIR_HI = 1.3, 1.6

Need = float | tuple[float, float] | None
Pair = tuple[str, float, Need]


@cache
def roles(theme: str) -> dict[str, Rgba]:
    toks = load_tokens()
    resolve_all(toks)
    return theme_colors(theme, toks)


def flat(*layers: Rgba) -> Rgba:
    """The stack itself flattened (deepest last; the last layer must be opaque)."""
    bg = layers[-1]
    for layer in reversed(layers[:-1]):
        bg = composite(layer, bg)
    return bg


def over(fg: Rgba, *layers: Rgba) -> Rgba:
    """Flatten fg over a stack of layers."""
    return composite(fg, flat(*layers))


def ratio(fg: Rgba, *layers: Rgba) -> float:
    return contrast(over(fg, *layers), flat(*layers))


def _alpha(c: Rgba, a: float) -> Rgba:
    return (c[0], c[1], c[2], a)


# ---------------------------------------------------------------------------------------------------- the pairs
def _backgrounds(t: dict[str, Rgba]) -> dict[str, tuple[Rgba, ...]]:
    """Every background text sits on, as layer stacks (deepest last)."""
    card, page, bar = t["surfaceCard"], t["surfacePage"], t["surfaceBar"]
    return {
        "chrome": (t["surfaceChrome"],),
        "bar": (bar,),
        "page": (page,),
        "card": (card,),
        "row": (t["surfaceRow"],),
        "pressed": (t["surfacePressed"],),
        "row hover (fill.hover over card)": (t["fillHover"], card),
        "input (fill.input over card)": (t["fillInput"], card),
        "ghost button (fill.ghost over card)": (t["fillGhost"], card),
        "ghost hover (fill.ghostHover over card)": (t["fillGhostHover"], card),
        "selected (accent.soft over card)": (t["accentSoft"], card),
        "selected (accent.soft over bar)": (t["accentSoft"], bar),
        "acrylic over page": (t["surfaceAcrylic"], page),
        "acrylic over bar": (t["surfaceAcrylic"], bar),
        "acrylic over card": (t["surfaceAcrylic"], card),
    }


def text_pairs(theme: str) -> list[Pair]:
    """(label, ratio, minimum) for every text role on every background it sits on."""
    t = roles(theme)
    out: list[Pair] = []
    for bg_name, stack in _backgrounds(t).items():
        out.append((f"textPrimary on {bg_name}", ratio(t["textPrimary"], *stack), AA))
        out.append((f"textSecondary on {bg_name}", ratio(t["textSecondary"], *stack), AA))
        out.append((f"textTertiary on {bg_name}", ratio(t["textTertiary"], *stack), LARGE))
        out.append((f"textIcon on {bg_name}", ratio(t["textIcon"], *stack), LARGE))
        out.append((f"accent (links, selected text) on {bg_name}", ratio(t["accent"], *stack), AA))
    for a in ("accent", "accentHover", "accentPress"):
        out.append((f"textOnAccent on {a}", ratio(t["textOnAccent"], t[a]), AA))
    for s in ("Success", "Warning", "Danger", "Info"):
        fg, bg = t[f"status{s}"], t[f"status{s}Bg"]
        for surf in ("surfaceCard", "surfacePage"):
            out.append((f"status{s} on its bg over {surf}", ratio(fg, bg, t[surf]), AA))
            out.append((f"status{s} plain on {surf}", ratio(fg, t[surf]), AA))
        # tag text: the level colour at 90% over the card, no fill
        out.append((f"tag text status{s} 90% on card", ratio(_alpha(fg, 0.9), t["surfaceCard"]), AA))
    out.append(("tag text primary 90% on card", ratio(_alpha(t["textPrimary"], 0.9), t["surfaceCard"]), AA))
    out.append(("toast text on acrylic over page", ratio(t["textPrimary"], t["surfaceAcrylic"], t["surfacePage"]), AA))
    out.append(
        ("dialog hint on acrylic over page", ratio(t["textSecondary"], t["surfaceAcrylic"], t["surfacePage"]), AA)
    )
    out.append(("badge text (white) on statusBadge", ratio((1, 1, 1, 1), t["statusBadge"]), AA))
    return out


def border_pairs(theme: str) -> list[Pair]:
    """Component borders and the focus ring against their neighbours: >= 3:1."""
    t = roles(theme)
    out: list[Pair] = []
    card, page, bar = t["surfaceCard"], t["surfacePage"], t["surfaceBar"]
    neighbours = {
        "card": (card,),
        "page": (page,),
        "bar": (bar,),
        "input over card": (t["fillInput"], card),
        "row hover over card": (t["fillHover"], card),
        "acrylic over page": (t["surfaceAcrylic"], page),
    }
    for n, stack in neighbours.items():
        out.append((f"focus ring (accent) beside {n}", contrast(t["accent"], flat(*stack)), LARGE))
        out.append((f"error border (statusDanger) beside {n}", contrast(t["statusDanger"], flat(*stack)), LARGE))
    out.append(("focus ring on the Launch pill (textOnAccent on accent)", ratio(t["textOnAccent"], t["accent"]), LARGE))
    out.append(("toggle off outline (textSecondary) on card", ratio(t["textSecondary"], card), LARGE))
    out.append(("toggle on (accent) beside card", contrast(t["accent"], card), LARGE))
    return out


def hairline_pairs(theme: str) -> list[Pair]:
    """Hairlines read at 1.3-1.6:1 against the surface they divide; the edge at least as clearly as a hairline."""
    t = roles(theme)
    out: list[Pair] = []
    for surf in ("surfaceCard", "surfacePage"):
        out.append((f"borderHairline on {surf}", ratio(t["borderHairline"], t[surf]), (HAIR_LO, HAIR_HI)))
    out.append(("borderTag over card", ratio(t["borderTag"], t["surfaceCard"]), (1.15, HAIR_HI)))
    for surf in ("surfaceBar", "surfacePage"):
        out.append((f"borderEdge beside {surf}", ratio(t["borderEdge"], t[surf]), (HAIR_LO, 2.6)))
    return out


def info_pairs(theme: str) -> list[Pair]:
    """Reported, not asserted."""
    t = roles(theme)
    return [
        ("textDisabled on card", ratio(t["textDisabled"], t["surfaceCard"]), None),
        ("textDisabled on page", ratio(t["textDisabled"], t["surfacePage"]), None),
        ("hairline on row (hover)", contrast(t["borderHairline"], t["surfaceRow"]), None),
        ("accentHover vs accent (hover visible?)", contrast(t["accentHover"], t["accent"]), None),
        ("accentPress vs accent", contrast(t["accentPress"], t["accent"]), None),
    ]


def _passes(r: float, need: Need) -> bool:
    if need is None:
        return True
    if isinstance(need, tuple):
        return need[0] <= r <= need[1]
    return r >= need


# ---------------------------------------------------------------------------------------------------- pytest
@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("pairs", [text_pairs, border_pairs, hairline_pairs], ids=["text", "borders", "hairlines"])
def test_contrast(theme, pairs):
    failures = [f"{label}: {r:.2f} (needs {need})" for label, r, need in pairs(theme) if not _passes(r, need)]
    assert not failures, "\n".join(failures)


def test_themes_share_their_roles():
    """Every theme defines the same colour roles, so a role used in one theme exists in all."""
    names = [set(roles(theme)) for theme in THEMES]
    assert names[0] == names[1] == names[2]


# ---------------------------------------------------------------------------------------------------- script
def main() -> int:
    bad = 0
    for theme in THEMES:
        print(f"\n[{theme}]")
        mins: dict[str, float] = {}
        groups = (
            ("text", text_pairs(theme)),
            ("borders", border_pairs(theme)),
            ("hairlines", hairline_pairs(theme)),
            ("info", info_pairs(theme)),
        )
        for group, pairs in groups:
            print(f"  -- {group}")
            for label, r, need in pairs:
                ok = _passes(r, need)
                bad += 0 if ok else 1
                if isinstance(need, float):
                    mins[group] = min(mins.get(group, 99.0), r)
                mark = "    " if need is None else ("ok  " if ok else "FAIL")
                needs = "" if need is None else (f"[{need[0]}-{need[1]}]" if isinstance(need, tuple) else f">= {need}")
                print(f"  {mark} {r:5.2f} {needs:10s} {label}")
        print("  min ratios: " + ", ".join(f"{g} {m:.2f}" for g, m in mins.items()))
    print(f"\n{bad} failing pair(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
