# 0002 Merged Oodle files stay at level 6 (6/6)

**Status:** in use since 3.13.1 (2026-09-30). Faster layouts considered and not adopted (2026-10-01).

## Decision

Files the launcher writes with Oodle (Kraken) are compressed at level 6 with level 6 in the DCX header, the layout
the game's own files use. Regression tests keep it there.

## Alternatives considered

Level 4 compresses faster. Two level-4 layouts, 4/4 (header says 4) and 4/6 (header says 6), loaded in game on
Windows (Elden Ring 1.17.1) with launcher-merged menu text and player animations, as did 6/6 and a zlib (DFLT)
version of the same files.

They were not adopted because the evidence does not reach the case they would help:

- The time saved falls almost entirely on the largest archive, the 88 MB common effects (about two and a half
  minutes at level 6). That archive was not tested in game in either level-4 layout.
- The only timing compares a whole build at two settings (about 90 s against 267 s); it is not an equal-settings
  comparison of two writers, and the size cost of level 4 was not measured.
- Nothing has been tested on the Steam Deck.

## Would need, before adopting

- the effects archive in the chosen layout loading in game;
- an equal-settings timing on the same inputs, and the size difference;
- a Steam Deck result for that layout, or a stated Windows-only scope;
- a choice between 4/4 (the header matches the payload) and 4/6 (the header matches the game's own files).
