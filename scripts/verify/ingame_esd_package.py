"""Build a package for an in-game check: does the game run talk scripts (ESD) the launcher wrote?

Every talk script in the game's own grace and menu archive (script/talk/m00_00_00_00.talkesdbnd.dcx) is read and
written back by the launcher's ESD code with nothing changed. Each is checked to read back to the same structure, and
the archive is stored as the launcher stores files (Oodle 6/6). The written scripts are laid out afresh (identical
conditions stored once), which is what this check is for: the game has to behave exactly as with its own files.

    uv run python scripts/verify/ingame_esd_package.py [--game DIR] [--out DIR]

The output folder holds the package, a me3 profile that plays on a separate save file (RoundtableTest.sl2; your own
saves are not loaded), launch.cmd, CHECK.txt (what to look for) and package.json (what was written).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time

import _common
from esd_roundtrip import counts, shape

TALK = "script/talk/m00_00_00_00.talkesdbnd.dcx"
SAVE = "RoundtableTest.sl2"
PACKAGE = "esd-rewritten"


def main() -> int:
    p = _common.parser((__doc__ or "").split("\n\n")[0])
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
    raw = gamearchive.read(game, TALK)
    if raw is None:
        sys.exit(f"the game's archives have no {TALK}")
    body, how = formats.unpack(raw, dec)
    if how is None or how.kind != b"KRAK":
        sys.exit(f"{TALK} is not Oodle-compressed as expected")
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
        rewritten.append({"esd": name, "bytes": [len(e.data), len(data)]} | counts(esd))
        e.data = data
    packed = formats.pack(formats.write_bnd4(archive), how, comp)
    if formats.read_bnd4(formats.unpack(packed, dec)[0]).entries[0].data != archive.entries[0].data:
        sys.exit("the stored archive does not read back")
    dest = out / "mods" / PACKAGE / TALK
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(packed)

    profile = out / "profile.me3"
    profile.write_text(
        "# Roundtable Souls in-game check. Plays on a separate save file; online stays off.\n"
        'profileVersion = "v1"\n'
        f'savefile = "{SAVE}"\n'
        "start_online = false\n"
        "disable_arxan = true\n\n"
        '[[supports]]\ngame = "eldenring"\n\n'
        f'[[packages]]\nid = "{PACKAGE}"\npath = "mods/{PACKAGE}"\n',
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
    (out / "CHECK.txt").write_text(
        "In-game check: the grace menu and other talk scripts, written by the launcher with nothing changed\n"
        f"Made {time.strftime('%Y-%m-%d %H:%M')} by scripts/verify/ingame_esd_package.py ({_common.commit()})\n\n"
        "Loading alone is not the result: the game has to behave exactly as with its own files.\n\n"
        "1. Close the game and Roundtable Souls.\n"
        f"2. Double-click launch.cmd in this folder. The game uses a separate save, {SAVE}; your characters are\n"
        "   not loaded. Online play stays off. Every text and option should look exactly as usual.\n"
        "3. Continue a character on this save, or start a throwaway one and walk to the first site of grace.\n"
        "4. Rest at the grace. The menu lists its usual options (on a new character: Pass time, Flasks,\n"
        "   Memorize spell and the others it normally has at that point). Open each one, back out, and choose\n"
        "   Leave. Rest again and Pass time to another hour.\n"
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
        "layout": "KRAK 6/6",
        "sha256": hashlib.sha256(packed).hexdigest(),
        "scripts": rewritten,
    }
    (out / "package.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    for r in rewritten:
        print(f"  {r['esd']}: {r['states']} states, {r['bytes'][0]} -> {r['bytes'][1]} bytes, same structure")
    print(f"\nready in {time.time() - started:.0f}s: {out}")
    print(f"  launch: {launch}\n  what to look for: {out / 'CHECK.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
