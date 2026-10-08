# Theme tokens

`tokens.json` is the one source of the launcher's visual system (technical specification §8.10): the colour
roles of the three themes (dark, light and Tarnished, the olive dark variant), spacing, radius, type, fonts, motion,
geometry and the atmosphere ceilings. Everything else is generated from it.

| File | What it is |
| --- | --- |
| `tokens.json` | The source. W3C design-tokens shape; colours in hex or OKLCH, references, and `$extensions.roundtable` (`alpha`, `dL`, `composite`) |
| `gen_theme.py` | Writes `src/roundtable_souls/ui/theme_tokens.py` (plain Python data, read by `ui/theme.py`) and `src/roundtable_souls/ui/qml/Theme/Theme.qml` with its `qmldir` |
| `colour.py` | The sRGB / OKLCH and contrast maths, shared by the generator and the contrast test |
| `gen_atmosphere.py` | Renders the bloom and vignette PNGs into `src/roundtable_souls/ui/assets/atmosphere/` (Pillow) |
| `gen_grain.py` | Renders the blue-noise grain tiles into the same folder (Pillow and NumPy) |

## Changing a colour (or any token)

1. Edit `tokens.json`. Never edit `theme_tokens.py` or `Theme.qml` by hand: the next run overwrites them, and CI
   fails while they disagree with `tokens.json`.
2. Regenerate: `uv run python scripts/theme/gen_theme.py`
3. Check contrast: `uv run pytest tests/unit/test_theme_contrast.py`. To see every pair and its ratio:
   `uv run python tests/unit/test_theme_contrast.py`. If a pair fails, change the token, not the test.
4. Commit `tokens.json` together with the regenerated files.

`uv run python scripts/theme/gen_theme.py --dump` prints every colour role per theme with its OKLCH values.

## The gates

CI (`.github/workflows/test.yml`, and the release workflow's lint step) runs:

- `uv run python scripts/theme/gen_theme.py --check`: exits 1 when a generated file is stale; writes nothing.
- `tests/unit/test_theme_contrast.py`, with the rest of the tests: text at least 4.5:1 on every background it sits
  on; tertiary text, icons, component borders and the focus ring at least 3:1; hairlines 1.3 to 1.6:1; translucent
  colours composited over their real background first, the acrylic tint included.

## The images

The PNGs are committed, so a build never needs Pillow or NumPy. Regenerate them only after changing what they
encode (a bloom colour or ceiling, the grain's reference surface):

    uv run python scripts/theme/gen_atmosphere.py
    uv run --with numpy python scripts/theme/gen_grain.py
