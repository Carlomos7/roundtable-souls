"""Build a package for an in-game check: does the game load what the launcher writes, in a given DCX layout?

Two small marker mods both change the menu text, the parameters and the player's animation archive (marker B adds
an unused clip to it; with --anim-swap, marker A also changes a clip). The launcher's own Combine merges them (the
same code a Rebuild runs), and the files it wrote are then stored in the chosen layout:

    6/6   Oodle level 6, header byte 6: what the launcher writes (left exactly as the launcher wrote it)
    4/4   Oodle level 4, header byte 4
    4/6   Oodle level 4, header byte 6
    dflt  zlib (DFLT) level 9 instead of Oodle, in the same header, byte 9

    uv run python scripts/verify/ingame_package.py --layout 6/6 [--game DIR] [--out DIR]

The output folder holds the mods, the combined package, a me3 profile that plays on a separate save file
(RoundtableTest.sl2, created by the game on first use; your own saves are not loaded), launch.cmd, CHECK.txt (what to
look for) and package.json (what was written). The 4/4, 4/6 and dflt layouts are experiments: the launcher itself
only writes 6/6.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time

import _common

LAYOUTS = {"6/6": (b"KRAK", 6, 6), "4/4": (b"KRAK", 4, 4), "4/6": (b"KRAK", 4, 6), "dflt": (b"DFLT", 9, 9)}
SAVE = "RoundtableTest.sl2"
TEXT = "msg/engus/menu_dlc02.msgbnd.dcx"  # English menu text; the DLC table is the one the game reads
MENU = "gr_menutext.fmg"
NEW_GAME = (401303, 406001)  # the title menu's NEW GAME (with and without a save)
SYSTEM = 401304
CHARA = "CharaInitParam.param"
VIGOR = 194  # byte offset of base Vigor (Mind follows) in a starting class's row (checked against the game's values)
# (class, its stats Vigor..Arcane, new Vigor and Mind). A class's level must match its stats' total (a change that
# broke that crashed the game at start), so Vigor gains what Mind loses.
CLASSES = {3000: ("Vagabond", bytes([15, 10, 11, 14, 13, 9, 9, 7]), (20, 5)), 3001: ("Warrior", bytes([11, 12, 11, 10, 16, 10, 8, 9]), (16, 7))}  # fmt: skip
ANIMS = "chr/c0000_a00_hi.anibnd.dcx"  # the player's animations: a large Oodle archive
UNUSED_CLIP = "a000_999990.hkx"  # marker B adds this copy of a clip; nothing plays it


def main() -> int:
    p = _common.parser((__doc__ or "").split("\n\n")[0])
    p.add_argument("--layout", required=True, choices=sorted(LAYOUTS))
    p.add_argument(
        "--anim-swap",
        metavar="CLIP=SOURCE",
        help="marker A also replaces animation CLIP (e.g. a000_000000) with SOURCE's data, for a visible animation "
        "check; without it both mods ship the game's own animations unchanged",
    )
    args = p.parse_args()
    game = _common.game_dir(args.game)
    label = args.layout
    out = _common.output_dir(args.out, "ingame-" + label.replace("/", "-"), game)
    _common.sandbox_launcher(out, game)

    from roundtable_souls.gamefiles import find_oodle
    from roundtable_souls.mods import formats, gamearchive, merge
    from roundtable_souls.mods import paramfile as pf
    from roundtable_souls.mods.backends import builtin
    from roundtable_souls.system import common

    # A Rebuild refuses while the game runs because it rewrites files the game may have open. Everything here is
    # written inside the output folder, which the game does not use, and the game's own files are only read, so that
    # check is switched off for this run only (the launcher itself is unchanged).
    common.game_running = lambda: False
    dec = find_oodle(game)
    comp = formats.oodle_compressor(game)
    if comp is None:
        sys.exit("the game's oo2core DLL could not be loaded (Windows only)")
    started = time.time()

    # ---------------------------------------------------------------- the marker mods
    text_raw = gamearchive.read(game, TEXT)
    anim_raw = gamearchive.read(game, ANIMS)
    if text_raw is None or anim_raw is None:
        sys.exit("the game's archives do not have the menu text or the animations")
    text_body, text_how = formats.unpack(text_raw, dec)
    anim_body, anim_how = formats.unpack(anim_raw, dec)
    reg_raw = (game / "regulation.bin").read_bytes()

    def text_with(changes: dict[int, str]) -> bytes:
        b = formats.read_bnd4(text_body)
        e = next(e for e in b.entries if (e.name or "").replace("\\", "/").rsplit("/", 1)[-1].lower() == MENU)
        f = formats.read_fmg(e.data)
        for k, v in changes.items():
            if f.entries.get(k) is None:
                sys.exit(f"the menu text has no entry {k}; the game version may differ from the one this was made for")
            f.entries[k] = v
        e.data = formats.write_fmg(f)
        return formats.pack(formats.write_bnd4(b), text_how, comp)

    def regulation_with(row_id: int) -> bytes:
        reg = pf.read_regulation(reg_raw, dec)
        bf = reg.bnd.get(CHARA)
        assert bf is not None
        param = pf.read_param(bf.data)
        name, stats, new = CLASSES[row_id]
        row = next(r for r in param.rows if r.id == row_id)
        if row.data[VIGOR : VIGOR + len(stats)] != stats:
            sys.exit(f"{name}'s starting stats are not where expected; the game version may differ")
        row.data = row.data[:VIGOR] + bytes(new) + row.data[VIGOR + 2 :]
        bf.data = pf.write_param(param)
        return pf.write_regulation(reg)

    def anims_with(swap: str | None = None, add_unused: bool = False) -> bytes:
        b = formats.read_bnd4(anim_body)
        by = {(e.name or "").replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".hkx"): e for e in b.entries}
        if swap:
            clip, source = (s.strip().lower().removesuffix(".hkx") for s in swap.split("=", 1))
            if clip not in by or source not in by:
                sys.exit(f"the animation archive has no {clip if clip not in by else source}")
            by[clip].data = by[source].data
        if add_unused:  # a copy of a clip under a new name nothing plays: the merged archive then differs from the
            # game's, so the launcher compresses it itself instead of passing the game's own bytes through
            model = next(e for e in b.entries if e.name and e.name.lower().endswith(".hkx"))
            assert model.name is not None
            name = model.name.replace("\\", "/").rsplit("/", 1)[-1]
            clip_id = lambda n: 1_000_000_000 + int(n[5:11])  # noqa: E731  (a000_010000.hkx has ID 1000010000)
            if model.id != clip_id(name) or any(e.id == clip_id(UNUSED_CLIP) for e in b.entries):
                sys.exit("the animation archive's IDs do not follow the clip numbers as expected")
            b.entries.append(
                formats.Entry(
                    model.name[: len(model.name) - len(name)] + UNUSED_CLIP,
                    clip_id(UNUSED_CLIP),
                    model.data,
                    model.flags,
                    model.uncompressed,
                )
            )
        return formats.pack(formats.write_bnd4(b), anim_how, comp)

    mods = out / "mods"
    markers = {
        "marker-a": {
            TEXT: text_with({k: f"NEW GAME [RS {label} A]" for k in NEW_GAME}),
            "regulation.bin": regulation_with(3000),
            ANIMS: anims_with(swap=args.anim_swap),
        },
        "marker-b": {
            TEXT: text_with({SYSTEM: f"SYSTEM [RS {label} B]"}),
            "regulation.bin": regulation_with(3001),
            ANIMS: anims_with(add_unused=True),
        },
    }
    for mod, files in markers.items():
        for rel, data in files.items():
            dest = mods / mod / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
    print(f"marker mods written ({time.time() - started:.0f}s)")

    profile = out / "profile.me3"
    profile.write_text(
        "# Roundtable Souls in-game check. Plays on a separate save file; online stays off.\n"
        'profileVersion = "v1"\n'
        f'savefile = "{SAVE}"\n'
        "start_online = false\n"
        "disable_arxan = true\n\n"  # as in a working Elden Ring profile (see the in-game checklist)
        '[[supports]]\ngame = "eldenring"\n\n'
        '[[packages]]\nid = "marker-a"\npath = "mods/marker-a"\n\n'
        '[[packages]]\nid = "marker-b"\npath = "mods/marker-b"\n',
        encoding="utf-8",
    )

    # ---------------------------------------------------------------- the launcher's own Combine
    t = time.time()
    merge.rebuild(profile, lambda s: print("  " + s), combine=True)
    combine_s = time.time() - t
    tool = builtin.find(profile, merge.layers(profile))
    if tool is None:
        sys.exit("the combine made no package")
    combined = tool.folder
    record = tool.record()
    merged = [f["rel"] for f in (record.get("files") or {}).values() if f.get("output")]
    if sorted(r.lower() for r in merged) != sorted([TEXT.lower(), ANIMS.lower()]):
        sys.exit(f"expected the launcher to merge the text and the animations; it merged {merged}")

    # ---------------------------------------------------------------- the layout under test
    kind, level, header_level = LAYOUTS[label]
    written = []
    for rel in merged:
        path = combined / rel
        raw = path.read_bytes()
        if raw[0x28:0x2C] != b"KRAK" or raw[0x30] != 6:
            sys.exit(f"{rel}: the launcher did not write the 6/6 layout (kind {raw[0x28:0x2C]!r}, byte {raw[0x30]})")
        if label != "6/6":
            t = time.time()
            body, how = formats.unpack(raw, dec)
            assert how is not None
            header = bytearray(how.header)
            header[0x28:0x2C] = kind
            header[0x30] = header_level
            if kind == b"KRAK":
                payload = formats._kraken(body, level, comp)
            else:
                import zlib

                payload = zlib.compress(body, level)
            import struct

            struct.pack_into(">II", header, 0x1C, len(body), len(payload))
            data = bytes(header) + payload
            raw = data + b"\0" * (-len(data) % 0x10)
            if formats.unpack(raw, dec)[0] != body:
                sys.exit(f"{rel}: the rewritten file does not read back to the same content")
            path.write_bytes(raw)
            print(f"  {rel}: stored as {label} ({time.time() - t:.0f}s)")
        written.append(
            {
                "file": rel,
                "kind": raw[0x28:0x2C].decode(),
                "payload_level": level,
                "header_byte_0x30": raw[0x30],
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    reg_out = combined / "regulation.bin"
    check = pf.read_regulation(reg_out.read_bytes(), dec)
    rows = {r.id: r.data for r in pf.read_param(check.bnd.get(CHARA).data).rows}  # type: ignore[union-attr]
    for row_id, (name, _stats, new) in CLASSES.items():
        if rows[row_id][VIGOR : VIGOR + 2] != bytes(new):
            sys.exit(f"the combined parameters do not give {name} Vigor {new[0]} and Mind {new[1]}")

    # ---------------------------------------------------------------- what to do with it
    me3 = _common.me3_exe()
    me3_version = ""
    if me3:
        try:
            me3_version = subprocess.run([str(me3), "--version"], capture_output=True, text=True).stdout.strip()
        except OSError:
            pass
    launch = out / "launch.cmd"
    launch.write_text(
        f'@echo off\r\n"{me3 or "me3"}" launch -g eldenring -p "{profile}"\r\n',
        encoding="utf-8",
    )
    anim_line = (
        f"   The animation {args.anim_swap.split('=')[0]} now plays {args.anim_swap.split('=')[1]}'s motion.\n"
        if args.anim_swap
        else "   (Their motions are the game's own, so a normal look is the result; this cannot show a change.)\n"
    )
    (out / "CHECK.txt").write_text(
        f"In-game check: files the launcher wrote, stored in the {label} layout\n"
        f"Made {time.strftime('%Y-%m-%d %H:%M')} by scripts/verify/ingame_package.py ({_common.commit()})\n\n"
        "1. Close the game and Roundtable Souls.\n"
        f"2. Double-click launch.cmd in this folder. The game uses a separate save, {SAVE}, which it creates in\n"
        "   your save folder; your characters are not loaded. Online play stays off.\n"
        f'3. Title screen: the menu reads "NEW GAME [RS {label} A]" and "SYSTEM [RS {label} B]".\n'
        "   Both texts: the merged text file loaded, with both mods' changes. Normal text: it did not load.\n"
        "4. New Game, class selection: Vagabond Vigor 20, Mind 5; Warrior Vigor 16, Mind 7 (usually 15/10, 11/12).\n"
        "   Both: the combined parameters loaded.\n"
        "5. Optional: create a throwaway character on this save, then walk, run, roll and attack.\n"
        f"{anim_line}"
        "6. Quit, and note the results (a crash, an error or normal text is a result too).\n\n"
        "The player's animation archive and the menu text are the files stored in this layout; the parameters are\n"
        "always written the same way (regulation.bin, ZSTD inside its encryption).\n",
        encoding="utf-8",
    )
    info = {
        "layout": label,
        "made": time.strftime("%Y-%m-%d %H:%M:%S"),
        "commit": _common.commit(),
        "game_regulation_version": pf.read_regulation(reg_raw, dec).version,
        "me3": me3_version,
        "save_file": SAVE,
        "combine_seconds": round(combine_s, 1),
        "files": written,
        "markers": {
            "text": {
                TEXT: {
                    "GR_MenuText": {str(k): f"NEW GAME [RS {label} A]" for k in NEW_GAME}
                    | {str(SYSTEM): f"SYSTEM [RS {label} B]"}
                }
            },
            "parameters": {
                CHARA: {str(k): {"class": v[0], "vigor": v[2][0], "mind": v[2][1]} for k, v in CLASSES.items()}
            },
            "animation_swap": args.anim_swap or None,
        },
    }
    (out / "package.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    print(f"\nready in {time.time() - started:.0f}s: {out}")
    print(f"  launch: {launch}\n  what to look for: {out / 'CHECK.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
