"""Merge every game file that two or more enabled packages of a profile ship, and report what the merger does.

For each such file (in me3's load order of the packages): how many parts each mod changed, where changes met (the
later mod wins), which parts a mod's copy leaves out (removed, the launcher's current rule), or why the file was not
merged. Nothing is written into the profile or the mods: merged results go to the output folder, with result.json.

    uv run python scripts/verify/clash_corpus.py [--profile ME3] [--game DIR] [--out DIR]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import _common


def main() -> int:
    p = _common.parser((__doc__ or "").split("\n\n")[0])
    p.add_argument("--profile", type=Path, help="a me3 profile (default: the launcher's Elden Ring setup)")
    args = p.parse_args()
    game = _common.game_dir(args.game)
    out = _common.output_dir(args.out, "clash-corpus", game)
    _common.sandbox_launcher(out, game)

    from roundtable_souls import formats
    from roundtable_souls.game import archives
    from roundtable_souls.game import oodle as game_oodle
    from roundtable_souls.merging import merger
    from roundtable_souls.mods import merge
    from roundtable_souls.mods import profile as profile_tools
    from roundtable_souls.mods.backends import builtin

    profile = args.profile or Path(_common.settings().get("profile") or "")
    if not profile.is_file():
        sys.exit("no profile: pass --profile or set profile in local.toml")
    started = time.time()
    ordered = profile_tools.me3_order(profile, profile.read_text(encoding="utf-8"))
    layers = merge.layers(profile)
    shared = builtin.shared_files(layers)
    dec = game_oodle.find_oodle(game)
    comp = game_oodle.oodle_compressor(game)
    rows = []
    for _low, owners in sorted(shared.items()):
        rel = owners[0]["rel"]
        row: dict = {"file": rel, "mods": [o["name"] for o in owners]}
        try:
            vanilla = archives.read(game, rel)
            if vanilla is None:
                row["result"] = "skipped: the game has no such file"
            else:
                layers_ = [(o["name"], (Path(o["folder"]) / o["rel"]).read_bytes()) for o in owners]
                r = merger.merge(vanilla, layers_, dec, comp)
                if not r.merged:
                    row["result"] = "not merged: not an archive or text table (the later mod's copy is used)"
                else:
                    dest = out / "merged" / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(r.data)
                    row |= {
                        "result": "merged",
                        "parts_changed": len(r.changed),
                        "clashes": {k: v for k, v in list(r.clashes.items())[:50]},
                        "clash_count": len(r.clashes),
                        "removed_count": len(r.removed),
                        "removed_by": sorted({m for v in r.removed.values() for m in v}),
                    }
        except (OSError, formats.FormatError, archives.ArchiveError) as e:
            row["result"] = f"could not be merged: {e}"
        rows.append(row)
    result = {
        "commit": _common.commit(),
        "profile": profile.name,
        "order_problem": ordered.problem,
        "packages_in_order": [r["id"] for r in ordered.rows],
        "shared_files": len(rows),
        "files": rows,
        "seconds": round(time.time() - started, 1),
    }
    (out / "result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    for row in rows:
        extra = ""
        if row.get("result") == "merged":
            extra = (
                f": {row['parts_changed']} parts changed, {row['clash_count']} clashes, {row['removed_count']} removed"
            )
            if row["removed_by"]:
                extra += f" (left out by {', '.join(row['removed_by'])})"
        print(f"{row['file']} [{' then '.join(row['mods'])}] {row['result']}{extra}")
    print(f"{len(rows)} files shipped by more than one package; result: {out / 'result.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
