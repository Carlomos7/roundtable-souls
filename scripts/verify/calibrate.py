"""Calibrate the checkers on files known to work in game (the game's own), before trusting what they say about ours.

For each file, every available reader (the launcher's, Soulstruct's, pyooz) is run on the game's own copy: a reader
that refuses a file the game loads says nothing about the launcher's output for that kind of file.

    uv run --with soulstruct python scripts/verify/calibrate.py [--game DIR] [--out DIR] [--file REL ...]
"""

from __future__ import annotations

import json
import sys
import time

import _common
import _readers

FILES = (
    "msg/engus/menu_dlc02.msgbnd.dcx",
    "menu/hi/01_common.sblytbnd.dcx",
    "chr/c0000_a00_lo.anibnd.dcx",
    "chr/c0000_a00_hi.anibnd.dcx",
    "sfx/sfxbnd_commoneffects.ffxbnd.dcx",
)


def calibrate(game, dec, files) -> dict:
    """{rel: {reader: "opens (n files)" | "refuses: why" | "same bytes" | ...}} for the game's own copies."""
    from roundtable_souls.mods import formats, gamearchive

    readers = {"launcher": _readers.ours(dec), "soulstruct": _readers.soulstruct()}
    ooz = _readers.pyooz()
    out = {}
    for rel in files:
        raw = gamearchive.read(game, rel)
        if raw is None:
            out[rel] = {"game": "the game's archives have no such file"}
            continue
        row = {"header_byte_0x30": raw[0x30], "kind": raw[0x28:0x2C].decode(errors="replace")}
        for name, read in readers.items():
            if read is None:
                row[name] = "not installed"
                continue
            try:
                row[name] = f"opens ({len(read(raw))} files)"
            except _readers.CannotRead as e:
                row[name] = f"refuses: {e}"
        if ooz is None:
            row["pyooz"] = "not installed"
        else:
            try:
                row["pyooz"] = "same bytes" if ooz(raw) == formats.unpack(raw, dec)[0] else "different bytes"
            except _readers.CannotRead as e:
                row["pyooz"] = f"fails: {e}"
        out[rel] = row
    return out


def main() -> int:
    p = _common.parser((__doc__ or "").split("\n\n")[0])
    p.add_argument("--file", action="append", help="a game file to calibrate on (repeatable); default: a few kinds")
    args = p.parse_args()
    game = _common.game_dir(args.game)
    out = _common.output_dir(args.out, "calibrate", game)
    _common.sandbox_launcher(out, game)
    from roundtable_souls.gamefiles import find_oodle

    result = calibrate(game, find_oodle(game), args.file or FILES)
    for rel, row in result.items():
        print(rel)
        for k, v in row.items():
            print(f"  {k}: {v}")
    report = {
        "made": time.strftime("%Y-%m-%d %H:%M:%S"),
        "commit": _common.commit(),
        "soulstruct": _readers.soulstruct_version(),
        "files": result,
    }
    (out / "calibrate.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"report: {out / 'calibrate.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
