"""An in-game check of the launcher's own build of an overhaul (Phase 6, S3c): the launcher builds the overhaul into
this script's output folder, the way a Rebuild with "Build Nightreign Revive in the launcher" would, and a copy of the
profile plays that build instead of the installed one. The profile, the mod's installed build and its download are
only read; nothing in the profile folder changes.

The output folder holds the build (native/), profile.me3 (a copy of the profile with absolute paths, the overhaul's
package pointing at the build, the same top-level settings, a separate me3 save file name), launch.cmd (backs the
whole save folder up into save-backup/<time>/ first, then starts the game through me3 with that profile), CHECK.txt
(what to look at) and info.json. Seamless Co-op keeps its own save whatever the profile says, which is why
launch.cmd backs the save folder up every time.

    uv run python scripts/verify/ingame_overhaul.py [--profile ME3] [--setup DIR] [--game DIR] [--out DIR]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import _common
import native_parity

SAVE = "RoundtableTest.sl2"
CHECKS = (
    "the save loads (a character of this save, or a new one, reaches the game)",
    "your character's animations look right (walk, run, roll, attacks)",
    "effects, including rain",
    "co-op: the downed state when a player dies, and the revive animation",
    "the grace menu: every option is there and opens",
    "Revive's own settings menu opens and its values are yours",
    "map markers",
)


def main() -> int:
    p = _common.parser((__doc__ or "").split("\n\n")[0])
    p.add_argument("--profile", type=Path, help="the me3 profile with the overhaul (default: local.toml 'profile')")
    p.add_argument("--setup", type=Path, help="the overhaul's download (default: where its manifest says)")
    args = p.parse_args()
    game = _common.game_dir(args.game)
    out = _common.output_dir(args.out, "ingame-overhaul", game)
    loc = _common.sandbox_launcher(out, game)

    from roundtable_souls import overhauls
    from roundtable_souls.mods import engine, profile_edit
    from roundtable_souls.mods import profile as profile_tools
    from roundtable_souls.mods.backends import manifest_refresh

    started = time.time()
    profile = args.profile or (Path(_common.settings()["profile"]) if "profile" in _common.settings() else None)
    if profile is None or not profile.is_file():
        sys.exit("pass --profile (the me3 profile with the overhaul) or set profile in local.toml")
    rows = profile_edit.entries(profile)
    ids = {(r.get("id") or "").lower(): r for r in rows if r["kind"] == "package"}
    found = [(o, ids[i]) for o in overhauls.load("eldenring") for i in o.recognise.mod_ids if i in ids]
    if not found:
        sys.exit(f"{profile.name} loads no overhaul the launcher has a config for")
    config, row = found[0]
    target = profile_edit.resolve(profile, row["path"])
    reference = target.parent
    manifest = reference / config.recognise.manifest
    try:
        recorded = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit(f"the installed build has no readable {manifest.name}: {e}")
    setup = args.setup or manifest_refresh._find_setup(profile, recorded)
    if setup is None:
        sys.exit("the overhaul's download (setup folder) was not found: pass --setup")
    recipe, version, why = engine.match(setup)
    if recipe is None:
        sys.exit(f"no build in the config fits {setup}: {why or 'another edition or layout'}")

    # the profile copy: absolute paths, the overhaul's package at the build, the same settings, its own save file
    native_mod = out / "native" / reference.name / "mod"
    copy = native_parity.write_profile(out / "profile.me3", profile, rows, row, native_mod)
    text = copy.read_text(encoding="utf-8")
    settings = profile_tools.read_settings(profile_edit.read_text(profile))
    settings["savefile"] = SAVE
    for key, value in settings.items():
        text = profile_tools.set_setting(text, key, value)
    copy.write_text(
        "# Roundtable Souls in-game check of the launcher's own build (scripts/verify/ingame_overhaul.py).\n"
        "# A copy of your profile: the overhaul's package points at the build in this folder.\n" + text,
        encoding="utf-8",
    )

    log: list[str] = []
    print(f"building {recipe['label']} {version} with the launcher into {native_mod.parent}")
    t = time.time()
    result = engine.build(copy, native_mod, setup, recipe, version, log.append, game_dir=game, loc=loc)
    build_s = time.time() - t
    print(f"built in {build_s:.0f}s")

    me3 = _common.me3_exe()
    launch = out / "launch.cmd"
    backup = out / "save-backup"
    launch.write_text(
        "@echo off\r\n"
        "setlocal\r\n"
        'set "STAMP=%date:~-4%%date:~-7,2%%date:~-10,2%-%time:~0,2%%time:~3,2%%time:~6,2%"\r\n'
        'set "STAMP=%STAMP: =0%"\r\n'
        f'set "BK={backup}\\%STAMP%"\r\n'
        'robocopy "%APPDATA%\\EldenRing" "%BK%" /E /NFL /NDL /NJH /NJS /NP >nul\r\n'
        "if %ERRORLEVEL% GEQ 8 (\r\n"
        "  echo Could not back the save folder up; the game was not started.\r\n"
        "  pause\r\n"
        "  exit /b 1\r\n"
        ")\r\n"
        "echo Saves backed up to %BK%\r\n"
        f'"{me3 or "me3"}" launch -g eldenring -p "{copy}"\r\n',
        encoding="utf-8",
    )
    lines = "\n".join(f"   {n + 1}. {c}" for n, c in enumerate(CHECKS))
    (out / "CHECK.txt").write_text(
        f"In-game check: {recipe['label']} {version} built by the launcher itself (nothing of the mod's own tools ran)\n"
        f"Made {time.strftime('%Y-%m-%d %H:%M')} by scripts/verify/ingame_overhaul.py ({_common.commit()})\n\n"
        "1. Close the game and Roundtable Souls.\n"
        "2. Double-click launch.cmd in this folder. It first copies your whole save folder into save-backup\\<time>\\\n"
        "   (so it can be put back by copying it over), then starts the game through me3 with profile.me3: your\n"
        "   mods as they are, the overhaul from the build in this folder. Seamless Co-op uses its own save as usual.\n"
        "3. Go through these and note pass or fail for each (a crash or an error is a result too):\n"
        f"{lines}\n"
        "4. Quit the game. Send the list to the coordinator; it goes into the evidence ledger (S3c).\n\n"
        "If anything is wrong: close the game, and copy the newest save-backup\\<time>\\ folder back over\n"
        "%APPDATA%\\EldenRing. Your real profile was not changed by any of this.\n",
        encoding="utf-8",
    )
    info = {
        "made": time.strftime("%Y-%m-%d %H:%M:%S"),
        "commit": _common.commit(),
        "profile": str(profile),
        "setup": str(setup),
        "recipe": recipe["id"],
        "version": version,
        "build": str(native_mod),
        "build_seconds": round(build_s, 1),
        "sources": result.get("sources"),
        "save_file": SAVE,
        "me3": str(me3) if me3 else None,
        "log": log,
    }
    (out / "info.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    print(f"\nready in {time.time() - started:.0f}s: {out}")
    print(f"  launch: {launch}\n  what to look for: {out / 'CHECK.txt'}")
    if me3 is None:
        print("  me3 was not found on this PC: edit launch.cmd to point at me3.exe before using it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
