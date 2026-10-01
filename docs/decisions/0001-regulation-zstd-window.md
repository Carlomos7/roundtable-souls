# 0001 regulation.bin is compressed with a 64 KB zstd window

**Status:** in use since 3.13.2 (2026-10-01).

## Decision

`regulation.bin` is compressed with zstd at level 9, a 64 KB window (`window_log` 16) and no content size in the
frame header (`compress_regulation_body` in `src/roundtable_souls/mods/paramfile.py`). A unit test parses the
written frame and fails if the window is larger than 64 KB, the content size is present, or a block holds more than
64 KB of input.

## Why

Elden Ring 1.17.1 crashed at start on regulation files compressed with zstd's defaults, even when the parameters
inside were the game's own, unchanged. Tested in game on Windows, one change at a time:

| regulation.bin | Result |
|---|---|
| the game's own contents, only re-encrypted | loads |
| zstd defaults (128 KB blocks, content size in the header) | crash |
| as above without the content size | crash |
| the game's own frame header: 64 MB window, level 21 | crash |
| 64 MB window with a block flushed every 64 KB | crash |
| 64 KB window, no content size | loads, and parameter changes take effect |

So the game's decoder needs the window itself to be at most 64 KB, not only small blocks. Regulation editors in
common use write the same frame.

Versions 3.6.0 to 3.13.1 compressed combined parameters with zstd's defaults. The crash was reproduced with that
writer on 1.17.1; the older versions themselves were inspected, not run in game.

## Not decided here

The compression level. Level 9 is kept from the earlier writer; a higher level was not tested in game with this
window.

## Reopen if

A game update changes the regulation's own frame, or a later game version rejects this one.
