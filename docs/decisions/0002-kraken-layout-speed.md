# 0002 Faster Kraken layouts 4/4 and 4/6

**Status:** not adopted (2026-10-01). The launcher keeps writing 6/6. **Evidence:** E-004, E-005.

## What is known

- 4/4 and 4/6 (Oodle payload level 4, header byte 4 or 6) loaded in game on Windows with launcher-merged menu text
  and player animations (E-005). Nothing else was tested in those layouts in game.
- Level 4 compresses faster than level 6. The only measurement is a full Revive build: about 90 s with large files at
  level 4 against 267 s at 6/6 (E-004). That compares two settings, not two equal writers, and the gain falls almost
  entirely on the 88 MB effects archive, which was not among the files tested in game in 4/4 or 4/6.
- The files come out larger at level 4; by how much was not measured.

## Decision

No change. Compression settings stay as they are through Phase 1. Adopting a faster layout is a performance change
that needs its own decision.

## Would need, before adopting

- the effects archive in the chosen layout tested in game (the file the speed gain is for);
- an equal-settings timing on the same inputs, and the size difference;
- the Deck result for that layout, or an explicit Windows-only scope;
- the owner's choice between 4/4 (header matches payload) and 4/6 (header matches the game's own files).
