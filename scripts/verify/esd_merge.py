"""Merge talk scripts (ESD) of several mods with the launcher's ESD rule, and say what it did, state by state.

The inputs are talk archives (script/talk/m00_00_00_00.talkesdbnd.dcx) in load order: each --input NAME=PATH (an
archive, or a mod folder that has one), or, without --input, the enabled packages of --profile that ship one. They are
merged against the game's own archive as Combine does. Nothing given is changed: the result goes to the output folder.

    uv run python scripts/verify/esd_merge.py --input map=DIR --input revive=FILE [--compare FILE] [--package]

--compare FILE: a talk archive another tool merged from the same mods; each script is compared with the result by
meaning (the normal forms the rule compares), state by state, after new states are matched by content (another
tool may number them differently).
--package: also a package to play: the profile's packages (asset mods only, by their own folders; no DLL mods) with
the merged archive loaded last, a separate save (RoundtableTest.sl2), launch.cmd and CHECK.txt.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import _common

TALK = "script/talk/m00_00_00_00.talkesdbnd.dcx"
SAVE = "RoundtableTest.sl2"


def main() -> int:
    p = _common.parser((__doc__ or "").split("\n\n")[0])
    p.add_argument("--input", action="append", default=[], help="NAME=PATH, in load order (an archive or mod folder)")
    p.add_argument("--profile", type=Path, help="a me3 profile (its packages: inputs and, with --package, the mods)")
    p.add_argument("--compare", type=Path, help="a talk archive merged by another tool from the same mods")
    p.add_argument("--package", action="store_true", help="also build a package to check in game")
    args = p.parse_args()
    game = _common.game_dir(args.game)
    out = _common.output_dir(args.out, "esd-merge", game)
    _common.sandbox_launcher(out, game)

    from roundtable_souls import formats
    from roundtable_souls.game import archives
    from roundtable_souls.game import oodle as game_oodle
    from roundtable_souls.merging import merger
    from roundtable_souls.merging.rules import esd as esd_rule
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
        inputs.append((name, path / TALK if path.is_dir() else path))
    if not inputs:
        for r in rows:
            folder = Path(r["path"])
            if (folder / TALK).is_file():
                inputs.append((r["id"], folder / TALK))
    if len(inputs) < 2:
        sys.exit("two or more talk archives are needed: pass --input NAME=PATH, or --profile")
    for name, path in inputs:
        if not path.is_file():
            sys.exit(f"{name}: {path} is not a file")

    vanilla = archives.read(game, TALK)
    if vanilla is None:
        sys.exit(f"the game's archives have no {TALK}")
    layers = [(name, path.read_bytes()) for name, path in inputs]
    merger.ESD_MERGING = True  # as in the launcher (in case it has been switched off there)
    result = merger.merge(vanilla, layers, dec, comp)
    merged_body = formats.dcx.unpack(result.data, dec)[0]
    scripts = {e.name: e.data for e in formats.bnd4.read_bnd4(merged_body).entries if e.name}

    report = {
        "commit": _common.commit(),
        "inputs": [
            {"name": n, "path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for n, p in inputs
        ],
        "merged": result.merged,
        "changed": result.changed,
        "clashes": result.clashes,
        "notes": result.notes,
    }
    print(f"{TALK}: {'merged' if result.merged else 'not merged'}; {result.summary()}")
    for part, notes in result.notes.items():
        print(f"  {part.rsplit('/', 1)[-1]}:")
        for line in notes:
            print(f"    {line}")
    for part, who in result.clashes.items():
        print(f"  clash: {part.rsplit('/', 1)[-1]} ({' and '.join(who)}): the later one's copy is used")

    if args.compare:
        other = formats.bnd4.read_bnd4(formats.dcx.unpack(args.compare.read_bytes(), dec)[0])
        compared = {}
        for e in other.entries:
            mine = scripts.get(e.name)
            if mine is None or not e.name or not e.name.lower().endswith(".esd"):
                continue
            differ = compare(esd_rule, mine, e.data)
            if differ:
                compared[e.name.rsplit("\\", 1)[-1]] = differ
        report["compared_with"] = {"path": str(args.compare), "differences": compared}
        print(f"compared with {args.compare.name}: {'the same by meaning' if not compared else ''}")
        for name, differ in compared.items():
            print(f"  {name}: {len(differ)} states differ: {differ[:8]}")

    dest = out / "mods" / "esd-merge-test" / TALK
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(result.data)
    if args.package:
        if not rows:
            sys.exit("--package needs --profile (its packages are the mods to play with)")
        package(out, rows, inputs, result, added_entries(esd_rule, formats, vanilla, result.data, rows, dec))
    (out / "result.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\ndone in {time.time() - started:.0f}s: {out}")
    return 0


def compare(esd_rule, mine: bytes, theirs: bytes) -> list[str]:
    """States whose meaning differs, after the new states of each are matched by content."""
    a, b = esd_rule.read_esd(mine), esd_rule.read_esd(theirs)
    out = []
    for m in sorted(set(a.state_machines) | set(b.state_machines)):
        x, y = a.state_machines.get(m), b.state_machines.get(m)
        if x is None or y is None:
            out.append(f"machine {m} only in {'theirs' if x is None else 'ours'}")
            continue
        mapping = _match(esd_rule, x, y)
        for s, st in x.items():
            t = mapping.get(s, s)
            other = y.get(t)
            if other is None or esd_rule._normal(esd_rule._retarget(st, mapping)).key != esd_rule._normal(other).key:
                out.append(f"machine {m} state {s}" + (f" (theirs {t})" if t != s else ""))
        extra = set(y) - {mapping.get(s, s) for s in x}
        out += [f"machine {m} state {t} only in theirs" for t in sorted(extra)]
    return out


def _match(esd_rule, x: dict, y: dict) -> dict[int, int]:
    """Our state numbers that are another number in theirs: a state only we have, matched with one only they have
    that has the same commands (targets aside)."""
    ours = [s for s in x if s not in y or _commands(esd_rule, x[s]) != _commands(esd_rule, y[s])]
    theirs = [t for t in y if t not in x or _commands(esd_rule, x[t]) != _commands(esd_rule, y[t])]
    mapping = {}
    for s in ours:
        for t in theirs:
            if t not in mapping.values() and _commands(esd_rule, x[s]) == _commands(esd_rule, y[t]):
                mapping[s] = t
                break
    return {s: t for s, t in mapping.items() if s != t}


def _commands(esd_rule, state) -> tuple:
    return esd_rule._normal(state).key[:3]


def added_entries(esd_rule, formats, vanilla: bytes, merged: bytes, rows: list[dict], dec) -> list[str]:
    """The menu entries (AddTalkListData) the merged scripts add to the game's menus (the mods' own menus aside), with
    their text as the profile's packages give it (the later package's text)."""

    def entries(data: bytes) -> dict:
        found = {}
        for e in formats.bnd4.read_bnd4(formats.dcx.unpack(data, dec)[0]).entries:
            if not (e.name or "").lower().endswith(".esd"):
                continue
            name = e.name.replace("\\", "/").rsplit("/", 1)[-1]
            for m, states in esd_rule.read_esd(e.data).state_machines.items():
                for s, st in states.items():
                    for c in st.enter_commands:
                        form = esd_rule._command(c)
                        at = esd_rule._TALK_LIST.get(form[:2])
                        if at is not None and len(form[2]) > at + 1:
                            found[(name, m, s, form[2][at][1])] = form[2][at + 1][1]
        return found

    game, ours = entries(vanilla), entries(merged)
    texts: dict = {}
    for r in rows:
        for msg in sorted((Path(r["path"]) / "msg" / "engus").glob("menu*.msgbnd.dcx")):
            try:
                archive = formats.bnd4.read_bnd4(formats.dcx.unpack(msg.read_bytes(), dec)[0])
            except Exception:
                continue
            for e in archive.entries:
                if (e.name or "").endswith("EventTextForTalk.fmg"):
                    texts.update({k: v for k, v in formats.fmg.fmg_entries(e.data).items() if v})
    return [
        f"'{texts.get(text, f'text {text}')}' (option {option}; {name}, machine {m} state {s})"
        for (name, m, s, option), text in ours.items()
        if (name, m, s, option) not in game and (name, m) in {(k[0], k[1]) for k in game}
    ]


def package(out: Path, rows: list[dict], inputs, result, added: list[str]) -> None:
    lines = [
        "# Roundtable Souls in-game check: talk scripts merged by the launcher. Plays on a separate save; online off.",
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
        'id = "esd-merge-test"',
        "path = 'mods/esd-merge-test'",
        "load_after = [" + ", ".join(f'{{ id = "{r["id"]}", optional = true }}' for r in rows) + "]",
        "",
    ]
    profile = out / "profile.me3"
    profile.write_text("\n".join(lines), encoding="utf-8")
    me3 = _common.me3_exe()
    (out / "launch.cmd").write_text(f'@echo off\r\n"{me3 or "me3"}" launch -g eldenring -p "{profile}"\r\n')
    names = " and ".join(name for name, _ in inputs)
    every = [line for lines_ in result.notes.values() for line in lines_]
    machines = [line for line in every if line.startswith("machine ") and line.split()[2] == "added"]
    notes = "\n".join(f"   - {line}" for line in every if line not in machines)
    if machines:
        notes += f"\n   - {len(machines)} state machines added (the mods' own menus)"
    entries = "\n".join(f"   - {line}" for line in added) or "   - (none found)"
    (out / "CHECK.txt").write_text(
        f"In-game check: the grace menu merged by the launcher from {names}\n"
        f"Made {time.strftime('%Y-%m-%d %H:%M')} by scripts/verify/esd_merge.py ({_common.commit()})\n\n"
        "What the merge did (result.json has all of it):\n"
        f"{notes}\n\n"
        "Menu entries the mods add (each has to be offered, once, where the mod alone offers it):\n"
        f"{entries}\n\n"
        "1. Close the game and Roundtable Souls.\n"
        f"2. Double-click launch.cmd. The game uses a separate save, {SAVE}; your characters are not loaded. Online\n"
        "   play stays off, and DLL mods (Seamless Co-op, Revive's DLL, ...) are not loaded.\n"
        "3. Continue a character on this save, or start a throwaway one and walk to the first site of grace.\n"
        "4. Rest at the grace. The menu has to list the game's options and every option the mods add (each mod's\n"
        "   own entry, once). Open each mod's option and back out; open each of the game's options and back out.\n"
        "5. Leave the grace, rest again, and Pass time to another hour.\n"
        "6. Note anything different: a missing, extra or doubled option, an option opening another's menu, a menu that\n"
        "   does not close, a freeze or a crash. 'Everything as expected' is the result to note too.\n",
        encoding="utf-8",
    )
    print(f"  package: {out / 'launch.cmd'}\n  what to look for: {out / 'CHECK.txt'}")


if __name__ == "__main__":
    sys.exit(main())
