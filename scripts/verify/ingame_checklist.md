# In-game checklist

For each package made by `ingame_package.py`, fill in one block and copy the results into
[docs/evidence-ledger.md](../../docs/evidence-ledger.md) (E-005 and E-006). A check not done stays **pending**; on the
Steam Deck, without one, every row is **pending: needs a Deck**.

## Before

- Close the game and Roundtable Souls.
- Build the package: `uv run python scripts/verify/ingame_package.py --layout <layout>`.
- Optional: `uv run --with soulstruct python scripts/verify/verify_output.py --package <out>/mods/combined-parameters`
  (0 validation failures expected; removals are notes).

## Playing it

Double-click `launch.cmd` in the package folder. It starts the game through me3 with only the test mods, on a
separate save (`RoundtableTest.sl2`, made by the game the first time); your characters are not loaded. Online play
stays off.

| # | Look for | Shows |
|---|---|---|
| 1 | The game starts and reaches the title screen | the files load at all |
| 2 | The title menu reads `NEW GAME [RS <layout> A]` and `SYSTEM [RS <layout> B]` | the merged menu text loaded, with both mods' changes |
| 3 | New Game, class selection: Vagabond Vigor 42, Warrior Vigor 43 (normally 15 and 11) | the combined parameters loaded |
| 4 | Optional, on a throwaway character: walk, run, roll, attack look normal | the merged player animation archive loaded |
| 5 | With `--anim-swap`: the swapped animation plays the other one's motion | an animation change applies |

A crash, an error message or normal text is a result too: write down what happened and at which step.

## Result block (copy per run)

```
Layout:            6/6 | 4/4 | 4/6 | dflt
Date:
Platform:          Windows | Steam Deck
Package commit:    (package.json "commit")
Regulation:        (package.json "game_regulation_version")
me3:               (package.json "me3")
1 starts:          pass | fail | pending
2 menu text:       pass | fail | pending
3 parameters:      pass | fail | pending
4 animations:      pass | fail | pending | not tried
5 animation swap:  pass | fail | not built
Notes:
```
