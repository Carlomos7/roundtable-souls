"""Check that the launcher's parameter code keeps every row: duplicate IDs in their order, names and table metadata.

Reads a regulation.bin (the game's own by default; only read) and checks, for every table:
  1. reading and writing it back gives the same bytes (rows, order, names, header);
  2. the merger's row keys (ID plus which occurrence of that ID) cover every row once;
  3. combining the file with an unchanged copy of itself gives the same rows, in the same order;
  4. where rows share an ID, a pack changing only the second of them changes that row alone, and nothing moves.

    uv run python scripts/verify/param_rows.py [--game DIR] [--regulation FILE] [--out DIR]
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

import _common

from roundtable_souls import formats


def main() -> int:
    p = _common.parser((__doc__ or "").split("\n\n")[0])
    p.add_argument("--regulation", type=Path, help="a regulation.bin to check (default: the game's own)")
    args = p.parse_args()
    game = _common.game_dir(args.game)
    out = _common.output_dir(args.out, "param-rows", game)
    _common.sandbox_launcher(out, game)

    from roundtable_souls.game.oodle import find_oodle
    from roundtable_souls.mods import param_merge

    dec = find_oodle(game)
    source = args.regulation or game / "regulation.bin"
    raw = source.read_bytes()
    reg = formats.regulation.read_regulation(raw, dec)
    combined, _report = param_merge.combine(raw, [("unchanged copy", raw)], dec)
    after = formats.regulation.read_regulation(combined, dec)

    tables, problems = [], []
    for f in reg.bnd.entries:
        short = (f.name or "").replace("\\", "/").rsplit("/", 1)[-1]
        param = formats.param.read_param(f.data)
        ids = Counter(r.id for r in param.rows)
        dups = {i: n for i, n in ids.items() if n > 1}
        same_bytes = formats.param.write_param(param) == f.data
        keyed = param_merge._keyed(param.rows)
        keys_ok = len(keyed) == len(param.rows) and list(keyed.values()) == param.rows
        g = after.bnd.get(short)
        combined_rows = formats.param.read_param(g.data).rows if g is not None else []
        combine_ok = [(r.id, r.data, r.name) for r in combined_rows] == [(r.id, r.data, r.name) for r in param.rows]
        tables.append(
            {
                "table": short,
                "rows": len(param.rows),
                "duplicate_ids": len(dups),
                "rows_sharing_an_id": sum(dups.values()),
                "write_back_same_bytes": same_bytes,
                "merge_keys_cover_every_row": keys_ok,
                "combine_with_itself_same_rows": combine_ok,
            }
        )
        for what, ok in (("write-back", same_bytes), ("merge keys", keys_ok), ("combine", combine_ok)):
            if not ok:
                problems.append(f"{short}: {what}")

    # 4. a pack that changes only the second row sharing an ID: only that row changes, nothing moves
    for f in reg.bnd.entries:
        short = (f.name or "").replace("\\", "/").rsplit("/", 1)[-1]
        param = formats.param.read_param(f.data)
        seen: Counter = Counter()
        target = None
        for i, r in enumerate(param.rows):
            seen[r.id] += 1
            if seen[r.id] == 2:
                target = i
                break
        if target is None:
            continue
        edited = formats.regulation.read_regulation(raw, dec)
        ef = edited.bnd.get(short)
        assert ef is not None
        ep = formats.param.read_param(ef.data)
        row = ep.rows[target]
        row.data = bytes([row.data[0] ^ 0xFF]) + row.data[1:]
        ef.data = formats.param.write_param(ep)
        got = formats.param.read_param(formats.regulation.read_regulation(param_merge.combine(raw, [("edit", formats.regulation.write_regulation(edited))], dec)[0], dec).bnd.get(short).data).rows  # type: ignore[union-attr]  # fmt: skip
        changed = [i for i, (a, b) in enumerate(zip(param.rows, got, strict=False)) if (a.id, a.data) != (b.id, b.data)]
        ok = [r.id for r in got] == [r.id for r in param.rows] and changed == [target]
        entry = next(t for t in tables if t["table"] == short)
        entry["edit_second_duplicate_changes_only_it"] = ok
        print(f"{short}: editing row {target} (second row with ID {param.rows[target].id}) changed rows {changed}")
        if not ok:
            problems.append(f"{short}: a change to the second row sharing an ID did not land on that row alone")

    with_dups = [t for t in tables if t["duplicate_ids"]]
    print(
        f"{source.name}: regulation version {reg.version}, {len(tables)} tables, {sum(t['rows'] for t in tables)} rows"
    )
    print(f"tables with duplicate row IDs: {len(with_dups)}")
    for t in sorted(with_dups, key=lambda t: -t["rows_sharing_an_id"])[:10]:
        print(f"  {t['table']}: {t['duplicate_ids']} IDs used more than once ({t['rows_sharing_an_id']} rows)")
    print(f"problems: {len(problems)}")
    for line in problems:
        print("  - " + line)
    report = {
        "made": time.strftime("%Y-%m-%d %H:%M:%S"),
        "commit": _common.commit(),
        "regulation": source.name,
        "regulation_version": reg.version,
        "tables": tables,
        "problems": problems,
    }
    (out / "param-rows.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"report: {out / 'param-rows.json'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
