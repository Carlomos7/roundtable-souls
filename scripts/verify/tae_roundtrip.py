"""Check that the launcher's TAE code (formats/tae.py) reads and writes animation events without losing anything.

For every TAE inside the animation archives checked (the game's own chr/c0000.anibnd.dcx, any --chr, and any --file):
  1. it reads and is written back byte for byte ("identical"); the game's own files are laid out as the writer lays
     them out, and so are the copies of the mods examined so far;
  2. a file that does not come back byte for byte has to read back to the same model (the file header, every
     animation's header, file name, events in stored order with their parameter bytes, and event groups); that is
     reported per file, not a failure on its own;
  3. an edited copy reads back as edited: an event's parameters changed, an event removed, an animation added (a copy
     of the first, under a free ID) and the event bank changed, in one file per archive.
Uses our own reader; not independently validated (there is no other reader of Elden Ring's TAE in Python:
Soulstruct reads only the older 0x1000C layout and has no writer). An edited copy's events whose data moved within
a 16-byte boundary may come back with more zero padding after their parameters; that is listed, never counted as
the same.

    uv run python scripts/verify/tae_roundtrip.py [--game DIR] [--out DIR] [--chr c2010 ...] [--all-chr] [--file ANIBND ...]
"""

from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path

import _common

from roundtable_souls import formats


def model(t) -> tuple:
    tae = formats.tae
    return tae.header_key(t), [tae.animation_key(a) for a in t.animations], [a.file_name for a in t.animations]


def edited(t):
    """A copy with one change of each kind the merge makes."""
    e = copy.deepcopy(t)
    e.event_bank = -1 if t.event_bank != -1 else 37
    with_events = [a for a in e.animations if a.events]
    if with_events:
        a = with_events[0]
        a.events[0].params = bytes(len(a.events[0].params))
        if len(a.events) > 1:
            last = len(a.events) - 1
            for g in a.groups:
                g.members = [j for j in g.members if j != last]
            a.events.pop()
    if e.animations:
        added = copy.deepcopy(e.animations[0])
        added.id = max(x.id for x in e.animations) + 1
        e.animations.append(added)
    return e


def main() -> int:
    p = _common.parser((__doc__ or "").split("\n\n")[0])
    p.add_argument("--chr", action="append", default=[], help="another character's animations (e.g. c2010)")
    p.add_argument("--all-chr", action="store_true", help="every character the game has (cNNN0; takes a while)")
    p.add_argument("--file", action="append", type=Path, default=[], help="an animation archive (a mod's copy)")
    args = p.parse_args()
    game = _common.game_dir(args.game)
    out = _common.output_dir(args.out, "tae-roundtrip", game)
    _common.sandbox_launcher(out, game)

    from roundtable_souls.game import archives
    from roundtable_souls.game import oodle as game_oodle

    started = time.time()
    dec = game_oodle.find_oodle(game)
    names = ["c0000"] + args.chr + ([f"c{n:04d}" for n in range(10, 10000, 10)] if args.all_chr else [])
    sources: list[tuple[str, bytes]] = []
    for name in dict.fromkeys(names):
        data = archives.read(game, f"chr/{name}.anibnd.dcx")
        if data is not None:
            sources.append((f"game chr/{name}.anibnd.dcx", data))
        elif name in ["c0000", *args.chr]:
            print(f"the game has no chr/{name}.anibnd.dcx")
    sources += [(str(f), f.read_bytes()) for f in args.file]

    report: dict = {"commit": _common.commit(), "archives": {}}
    totals = {"identical": 0, "same model": 0, "failed": 0}
    for label, raw in sources:
        files = {}
        body = formats.dcx.unpack(raw, dec)[0]
        taes = [e for e in formats.bnd4.read_bnd4(body).entries if (e.name or "").lower().endswith(".tae")]
        for i, e in enumerate(taes):
            name = e.name.replace("\\", "/").rsplit("/", 1)[-1]
            try:
                t = formats.tae.read_tae(e.data)
                written = formats.tae.write_tae(t)
                if written == e.data:
                    verdict = "identical"
                elif model(formats.tae.read_tae(written)) == model(t):
                    verdict = "same model"
                else:
                    verdict = "failed: written file reads back differently"
                if i == 0:
                    ed = edited(t)
                    differ, padded = formats.tae.written_as(ed, formats.tae.read_tae(formats.tae.write_tae(ed)))
                    if differ:
                        verdict = f"failed: an edited copy reads back differently: {differ[:3]}"
                    files[f"{name} (edited)"] = "reads back as edited" + (
                        f"; padding added after {len(padded)} events' parameters: {padded[:3]}" if padded else ""
                    )
            except formats.FormatError as err:
                verdict = f"failed: {err}"
            files[name] = verdict
            totals["failed" if verdict.startswith("failed") else verdict] += 1
        report["archives"][label] = files
        counts = {v: sum(1 for x in files.values() if x == v) for v in set(files.values())}
        print(f"{label}: {len(taes)} TAE files; {counts}")
        for name, verdict in files.items():
            if verdict.startswith("failed"):
                print(f"  {name}: {verdict}")
    report["totals"] = totals
    (out / "result.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\n{totals}\ndone in {time.time() - started:.0f}s: {out}")
    return 1 if totals["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
