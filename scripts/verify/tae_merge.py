"""Merge the player's animation archive (chr/c0000.anibnd.dcx) of several mods as Combine does, and say what the TAE
rule did, animation by animation.

The inputs are animation archives in load order: each --input NAME=PATH (an archive, or a mod folder that has one),
or, without --input, the enabled packages of --profile that ship one. They are merged against the game's own archive
by the launcher's merger (the archive rule, and the TAE rule for an animation-event file several mods changed).
Nothing given is changed: the result goes to the output folder.

    uv run python scripts/verify/tae_merge.py --input bbdash=DIR --input revive=DIR [--compare FILE] [--package]

--compare FILE: an animation archive another tool merged from the same mods. Each TAE is compared with the result
animation by animation (the file header, and every animation: header, file name, events in stored order with their
parameter bytes exactly, event groups; an empty file name and none stored are the same), and every other inner file
byte for byte. The TAE comparison uses our own reader on both sides; it is not independently validated.
--package: also a package to play: the profile's packages (asset mods only, from their own folders; no DLL mods) with
the merged archive loaded last, a separate save (RoundtableTest.sl2), launch.cmd and CHECK.txt.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import _common

ANIBND = "chr/c0000.anibnd.dcx"
SAVE = "RoundtableTest.sl2"


def main() -> int:
    p = _common.parser((__doc__ or "").split("\n\n")[0])
    p.add_argument("--input", action="append", default=[], help="NAME=PATH, in load order (an archive or mod folder)")
    p.add_argument("--profile", type=Path, help="a me3 profile (its packages: inputs and, with --package, the mods)")
    p.add_argument("--compare", type=Path, help="an animation archive merged by another tool from the same mods")
    p.add_argument("--package", action="store_true", help="also build a package to check in game")
    args = p.parse_args()
    game = _common.game_dir(args.game)
    out = _common.output_dir(args.out, "tae-merge", game)
    _common.sandbox_launcher(out, game)

    from roundtable_souls import formats
    from roundtable_souls.game import archives
    from roundtable_souls.game import oodle as game_oodle
    from roundtable_souls.merging import merger
    from roundtable_souls.mods import profile as profile_tools

    started = time.time()
    dec = game_oodle.find_oodle(game)
    comp = game_oodle.oodle_compressor(game)
    profile = args.profile or (Path(_common.settings()["profile"]) if "profile" in _common.settings() else None)
    rows = []
    if profile and profile.is_file():
        ordered = profile_tools.me3_order(profile, profile.read_text(encoding="utf-8"))
        rows = [r | {"path": str(profile.parent / r["path"])} for r in ordered.rows if r.get("path")]
    inputs: list[tuple[str, Path]] = []
    for spec in args.input:
        name, _, path = spec.partition("=")
        path = Path(path)
        inputs.append((name, path / ANIBND if path.is_dir() else path))
    if not inputs:
        inputs = [(r["id"], Path(r["path"]) / ANIBND) for r in rows if (Path(r["path"]) / ANIBND).is_file()]
    if len(inputs) < 2:
        sys.exit("two or more animation archives are needed: pass --input NAME=PATH, or --profile")
    for name, path in inputs:
        if not path.is_file():
            sys.exit(f"{name}: {path} is not a file")

    vanilla = archives.read(game, ANIBND)
    if vanilla is None:
        sys.exit(f"the game's archives have no {ANIBND}")
    layers = [(name, path.read_bytes()) for name, path in inputs]
    merger.TAE_MERGING = True  # as in the launcher (in case it has been switched off there)
    result = merger.merge(vanilla, layers, dec, comp)
    merged = {e.name: e.data for e in formats.bnd4.read_bnd4(formats.dcx.unpack(result.data, dec)[0]).entries}

    report = {
        "commit": _common.commit(),
        "inputs": [
            {"name": n, "path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for n, p in inputs
        ],
        "merged": result.merged,
        "changed": result.changed,
        "clashes": result.clashes,
        "removed": result.removed,
        "notes": result.notes,
    }
    print(f"{ANIBND}: {'merged' if result.merged else 'not merged'}; {result.summary()}")
    for part, notes in result.notes.items():
        print(f"  {part.rsplit('/', 1)[-1]}:")
        for line in notes:
            print(f"    {line}")
    for part, who in result.clashes.items():
        print(f"  clash: {part.rsplit('/', 1)[-1]} ({' and '.join(who)}): the later one's is used")

    ok = True
    if args.compare:
        other = formats.bnd4.read_bnd4(formats.dcx.unpack(args.compare.read_bytes(), dec)[0])
        differ: dict[str, list[str]] = {}
        same_tae = same_other = 0
        theirs = {e.name: e.data for e in other.entries}
        for name in sorted(set(theirs) | set(merged), key=str):
            mine, their = merged.get(name), theirs.get(name)
            short = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
            if mine is None or their is None:
                differ[short] = [f"only in {'theirs' if mine is None else 'ours'}"]
            elif short.lower().endswith(".tae") and formats.tae.is_tae(mine):
                d = compare(formats.tae, mine, their)
                if d:
                    differ[short] = d
                else:
                    same_tae += 1
            elif mine != their:
                differ[short] = ["bytes differ"]
            else:
                same_other += 1
        report["compared_with"] = {
            "path": str(args.compare),
            "tae_same_by_meaning": same_tae,
            "other_identical": same_other,
            "differences": differ,
        }
        ok = not differ
        verdict = "the same, animation by animation" if ok else f"{len(differ)} inner files differ"
        print(f"compared with {args.compare.name}: {verdict} ({same_tae} TAE, {same_other} other inner files)")
        for name, lines in differ.items():
            print(f"  {name}: {lines[:8]}")

    dest = out / "mods" / "tae-merge-test" / ANIBND
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(result.data)
    if args.package:
        if not rows:
            sys.exit("--package needs --profile (its packages are the mods to play with)")
        package(out, rows, inputs, result)
    (out / "result.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\ndone in {time.time() - started:.0f}s: {out}")
    return 0 if ok else 1


def compare(tae, mine: bytes, theirs: bytes) -> list[str]:
    """What differs between two TAE files: the file header, and animations by ID (exactly) and their order."""
    a, b = tae.read_tae(mine), tae.read_tae(theirs)
    out = []
    if tae.header_key(a) != tae.header_key(b):
        out.append(f"file header: ours {tae.header_key(a)}, theirs {tae.header_key(b)}")
    ka = {x.id: tae.animation_key(x) for x in a.animations}
    kb = {x.id: tae.animation_key(x) for x in b.animations}
    out += [f"animation {i} only in ours" for i in ka if i not in kb]
    out += [f"animation {i} only in theirs" for i in kb if i not in ka]
    out += [f"animation {i} differs" for i in ka if i in kb and ka[i] != kb[i]]
    if not out and [x.id for x in a.animations] != [x.id for x in b.animations]:
        out.append("animations in another order")
    return out


def package(out: Path, rows: list[dict], inputs, result) -> None:
    lines = [
        "# Roundtable Souls in-game check: animation events merged by the launcher. Plays on a separate save; online"
        " off.",
        "# Asset mods only, from their own folders (read, never changed); no DLL mods.",
        'profileVersion = "v1"',
        f'savefile = "{SAVE}"',
        "start_online = false",
        "disable_arxan = true",
        "",
        '[[supports]]\ngame = "eldenring"',
        "",
    ]
    for r in rows:
        lines += ["[[packages]]", f'id = "{r["id"]}"', f"path = '{Path(r['path']).as_posix()}'", ""]
    lines += [
        "[[packages]]",
        'id = "tae-merge-test"',
        "path = 'mods/tae-merge-test'",
        "load_after = [" + ", ".join(f'{{ id = "{r["id"]}", optional = true }}' for r in rows) + "]",
        "",
    ]
    profile = out / "profile.me3"
    profile.write_text("\n".join(lines), encoding="utf-8")
    me3 = _common.me3_exe()
    (out / "launch.cmd").write_text(f'@echo off\r\n"{me3 or "me3"}" launch -g eldenring -p "{profile}"\r\n')
    names = " and ".join(name for name, _ in inputs)
    notes = "\n".join(f"   - {line}" for lines_ in result.notes.values() for line in lines_)
    (out / "CHECK.txt").write_text(
        f"In-game check: the player's animation events merged by the launcher from {names}\n"
        f"Made {time.strftime('%Y-%m-%d %H:%M')} by scripts/verify/tae_merge.py ({_common.commit()})\n\n"
        "What the merge did (result.json has all of it):\n"
        f"{notes}\n\n"
        "1. Close the game and Roundtable Souls.\n"
        f"2. Double-click launch.cmd. The game uses a separate save, {SAVE}; your characters are not loaded. Online\n"
        "   play stays off, and DLL mods (Seamless Co-op, Revive's DLLs, ...) are not loaded.\n"
        "3. Continue a character on this save, or start a throwaway one.\n"
        "4. Dash: the notes above list the animations each mod changed (bb-dash's are animation 0 and the evasion\n"
        "   animations 27000 to 27120). Dodge in every direction and backstep, at light and medium equip load; it\n"
        "   should look and feel as with the dash mod alone. Then walk, run, sprint, attack, use an item, open a door\n"
        "   and rest at a grace.\n"
        "5. Revive's downed and revive animations need its DLLs and co-op, which this package does not load; check\n"
        "   them in your own setup with the merged archive (mods/tae-merge-test) in place of Revive's merged copy.\n"
        "6. Note anything different: a missing or wrong animation, a stuck pose, sounds or effects at the wrong time,\n"
        "   a freeze or a crash. 'Everything as expected' is the result to note too.\n",
        encoding="utf-8",
    )
    print(f"  package: {out / 'launch.cmd'}\n  what to look for: {out / 'CHECK.txt'}")


if __name__ == "__main__":
    sys.exit(main())
