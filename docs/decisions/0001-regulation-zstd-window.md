# 0001 The regulation's zstd frame uses a 64 KB window

**Status:** adopted in 3.13.2 (2026-10-01). **Evidence:** E-011.

## Decision

`regulation.bin` is compressed with zstd at level 9, `window_log` 16 (a 64 KB window) and without the content-size
field in the frame header (`mods/paramfile.py`, `compress_regulation_body`). A unit test parses the written frame and
fails if the window exceeds 64 KB, the content size is present, or a block holds more than 64 KB of input.

## Why

Elden Ring 1.17.1 crashed at start on every regulation the launcher wrote with zstd's defaults, including the game's
own content written back unchanged. It also crashed on a 64 MB window with 64 KB blocks, so the window, not only the
block size, is the constraint. The 64 KB window loaded, with a parameter change taking effect. Regulation editors in
common use write this same frame.

## Not decided here

The compression level. Level 9 is kept from the earlier writer; a higher level was not tested in game with a 64 KB
window and gives a few percent smaller files at most.

## Reopen if

A game update changes the regulation's own frame, or a later game version rejects this one.
