"""Build a package for an in-game check: does the game run talk scripts (ESD) the launcher wrote?

Every talk script in a grace and menu archive (script/talk/m00_00_00_00.talkesdbnd.dcx) is read and written back by
the launcher's ESD code with nothing changed, checked to read back to the same structure, and the archive is stored as
the launcher stores files (Oodle 6/6).

    uv run python scripts/verify/ingame_esd_package.py --mod DIR [--game DIR] [--out DIR]
    uv run python scripts/verify/ingame_esd_package.py [--game DIR] [--out DIR]

With --mod, the archive is that mod's own (for example a map mod's grace menu, written by another tool), and the
package holds a copy of the mod's other files beside it, so the mod works as usual. The writer lays the scripts out
as the game's own files are, which differs from how the other tool laid them out: the game has to behave exactly as
with the mod's own file. Without --mod, the archive is the game's own; its scripts are written back byte for byte, so
that package shows only that the archive the launcher stores loads.

The output folder holds the package, a me3 profile that plays on a separate save file (RoundtableTest.sl2; your own
saves are not loaded), launch.cmd, CHECK.txt (what to look for) and package.json (what was written).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import _common
from esd_roundtrip import counts, shape

TALK = "script/talk/m00_00_00_00.talkesdbnd.dcx"
SAVE = "RoundtableTest.sl2"


def main() -> int:
    p = _common.parser((__doc__ or "").split("\n\n")[0])
    p.add_argument("--mod", type=Path, help="a mod folder whose talk archive to rewrite (its files are only read)")
    args = p.parse_args()
    game = _common.game_dir(args.game)
    out = _common.output_dir(args.out, "ingame-esd", game)
    _common.sandbox_launcher(out, game)

    from roundtable_souls.gamefiles import find_oodle
    from roundtable_souls.mods import formats, gamearchive
    from roundtable_souls.mods.formats_esd import read_esd, write_esd

    started = time.time()
    dec = find_oodle(game)
    comp = formats.oodle_compressor(game)
    if args.mod:
        mod = Path(args.mod)
        source = mod / TALK
        if not source.is_file():
            sys.exit(f"{mod} has no {TALK}")
        raw = source.read_bytes()
        package = f"{mod.name}-esd-rewritten"
        origin = f"the mod {mod.name}"
    else:
        found = gamearchive.read(game, TALK)
        if found is None:
            sys.exit(f"the game's archives have no {TALK}")
        raw = found
        package = "game-esd-rewritten"
        origin = "the game"
    body, how = formats.unpack(raw, dec)
    if how is None:
        sys.exit(f"{TALK} of {origin} is not a DCX file")
    archive = formats.read_bnd4(body)
    rewritten = []
    for e in archive.entries:
        name = (e.name or "").replace("\\", "/").rsplit("/", 1)[-1]
        if not name.lower().endswith(".esd"):
            continue
        esd = read_esd(e.data)
        data = write_esd(esd)
        if shape(read_esd(data)) != shape(esd):
            sys.exit(f"{name}: the rewritten script does not read back to the same structure")
        rewritten.append({"esd": name, "bytes": [len(e.data), len(data)], "identical": data == e.data} | counts(esd))
        e.data = data
    stored = formats.pack(formats.write_bnd4(archive), how, comp)
    back = formats.read_bnd4(formats.unpack(stored, dec)[0])
    if [x.data for x in back.entries] != [x.data for x in archive.entries]:
        sys.exit("the stored archive does not read back")

    folder = out / "mods" / package
    if args.mod:
        shutil.copytree(args.mod, folder)  # the mod's other files, as they are
    dest = folder / TALK
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(stored)

    profile = out / "profile.me3"
    profile.write_text(
        "# Roundtable Souls in-game check. Plays on a separate save file; online stays off.\n"
        'profileVersion = "v1"\n'
        f'savefile = "{SAVE}"\n'
        "start_online = false\n"
        "disable_arxan = true\n\n"
        '[[supports]]\ngame = "eldenring"\n\n'
        f'[[packages]]\nid = "{package}"\npath = "mods/{package}"\n',
        encoding="utf-8",
    )
    me3 = _common.me3_exe()
    me3_version = ""
    if me3:
        try:
            me3_version = subprocess.run([str(me3), "--version"], capture_output=True, text=True).stdout.strip()
        except OSError:
            pass
    launch = out / "launch.cmd"
    launch.write_text(f'@echo off\r\n"{me3 or "me3"}" launch -g eldenring -p "{profile}"\r\n', encoding="utf-8")
    usual = (
        f"exactly as with {origin}'s own grace menu (with its own options, if the mod adds any)"
        if args.mod
        else "exactly as usual"
    )
    (out / "CHECK.txt").write_text(
        f"In-game check: the grace menu and other talk scripts of {origin}, written by the launcher, nothing changed\n"
        f"Made {time.strftime('%Y-%m-%d %H:%M')} by scripts/verify/ingame_esd_package.py ({_common.commit()})\n\n"
        f"Loading alone is not the result: the menus have to behave {usual}.\n\n"
        "1. Close the game and Roundtable Souls.\n"
        f"2. Double-click launch.cmd in this folder. The game uses a separate save, {SAVE}; your characters are\n"
        "   not loaded. Online play stays off.\n"
        "3. Continue a character on this save, or start a throwaway one and walk to the first site of grace.\n"
        "4. Rest at the grace. The menu lists its usual options. Open each one, back out, and choose Leave.\n"
        "   Rest again and Pass time to another hour.\n"
        "5. If the character can already level up at a grace, open Level Up and back out without spending.\n"
        "6. Note anything different from usual: a missing or extra option, an option doing something else,\n"
        "   a menu that does not close, a freeze or a crash. 'Everything as usual' is the result to note too.\n",
        encoding="utf-8",
    )
    info = {
        "made": time.strftime("%Y-%m-%d %H:%M:%S"),
        "commit": _common.commit(),
        "me3": me3_version,
        "save_file": SAVE,
        "archive": TALK,
        "from": origin,
        "layout": f"{how.kind.decode()} (stored as the launcher stores it)",
        "sha256": hashlib.sha256(stored).hexdigest(),
        "scripts": rewritten,
    }
    (out / "package.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    for r in rewritten:
        same = "written back byte for byte" if r["identical"] else "laid out anew, same structure"
        print(f"  {r['esd']}: {r['states']} states, {r['bytes'][0]} -> {r['bytes'][1]} bytes, {same}")
    print(f"\nready in {time.time() - started:.0f}s: {out}")
    print(f"  launch: {launch}\n  what to look for: {out / 'CHECK.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
