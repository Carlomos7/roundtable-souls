"""Check that the shared BND4 code reproduces the game's binders byte for byte and that the regulation keeps every row.

1. Archives: each listed game archive (default below), unwrapped from its DCX, read and written back by the shared
   code, gives the game's own bytes.
2. The regulation binder: the game's regulation.bin, decrypted and decompressed, read and written back gives the
   same bytes. The encrypted file differs on every write (random IV), so it is not compared.
3. Every table, against an independent reader (gamefiles.bnd4_files) and the stored entry headers: the same names,
   IDs, flags and contents in the same order. Each table's rows (ID, which occurrence of that ID, row bytes, name),
   read independently of the parameter code for IDs, and its metadata (header, type name, names area) survive
   reading and writing.
4. --compare A B: two regulation.bin files (for example made from the same inputs before and after a change) have
   byte-identical binders, or where they differ, table by table and row by row.

  uv run python scripts/verify/bnd4_roundtrip.py [--game DIR] [--out DIR] [--file REL ...] [--compare A B]
"""

from __future__ import annotations

import json
import struct
import sys
import time
from collections import Counter
from pathlib import Path

import _common

ARCHIVES = (
    "msg/engus/menu_dlc02.msgbnd.dcx",
    "msg/engus/item_dlc02.msgbnd.dcx",
    "msg/jpnjp/menu_dlc02.msgbnd.dcx",
    "menu/hi/01_common.sblytbnd.dcx",
    "chr/c0000_a00_lo.anibnd.dcx",
    "chr/c0000_a00_hi.anibnd.dcx",
    "chr/c0000.anibnd.dcx",
    "chr/c0000.behbnd.dcx",
    "sfx/sfxbnd_commoneffects.ffxbnd.dcx",
    "script/talk/m00_00_00_00.talkesdbnd.dcx",
)


def short(name: str | None) -> str:
    return (name or "").replace("\\", "/").rsplit("/", 1)[-1]


def first_difference(a: bytes, b: bytes) -> int | None:
    if a == b:
        return None
    return next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))


def binder_of(raw: bytes, dec) -> bytes:
    from roundtable_souls.gamefiles import dcx_decompress, decrypt_regulation

    return dcx_decompress(decrypt_regulation(raw), dec)


def rows_of(data: bytes) -> list[tuple[int, int, bytes, str]]:
    """(ID, occurrence of that ID, row bytes, name), in stored order."""
    from roundtable_souls.mods import paramfile as pf

    seen: Counter = Counter()
    out = []
    for r in pf.read_param(data).rows:
        out.append((r.id, seen[r.id], r.data, r.name))
        seen[r.id] += 1
    return out


def check_archives(game: Path, dec, files) -> list[dict]:
    from roundtable_souls.mods import formats, gamearchive

    results = []
    for rel in files:
        raw = gamearchive.read(game, rel)
        if raw is None:
            results.append({"file": rel, "result": "not in the game's archives"})
            continue
        body, _how = formats.unpack(raw, dec)
        if not formats.is_bnd4(body):
            results.append({"file": rel, "result": "not a BND4 archive"})
            continue
        b = formats.read_bnd4(body)
        at = first_difference(formats.write_bnd4(b), body)
        results.append(
            {
                "file": rel,
                "entries": len(b.entries),
                "bytes": len(body),
                "result": "identical" if at is None else f"differs at {at:#x}",
            }
        )
    return results


def check_regulation(body: bytes) -> dict:
    from roundtable_souls.gamefiles import bnd4_files, param_row_ids
    from roundtable_souls.mods import formats, param_merge
    from roundtable_souls.mods import paramfile as pf

    problems: list[str] = []
    b = pf.read_binder(body)
    written = pf.binder_bytes(b)
    at = first_difference(written, body)
    if at is not None:
        problems.append(f"binder written back differs at {at:#x}")
    if formats.write_bnd4(b) != body:
        problems.append("the general writer alone does not reproduce the binder")

    independent = bnd4_files(body)
    size = struct.unpack_from("<q", body, 0x20)[0]
    stored = [
        (body[0x40 + i * size], struct.unpack_from("<i", body, 0x40 + i * size + 28)[0]) for i in range(len(b.entries))
    ]
    if [(short(e.name), e.data) for e in b.entries] != independent:
        problems.append("table names or contents differ from the independent reader")
    if [(e.flags, e.id) for e in b.entries] != stored:
        problems.append("table flags or IDs differ from the stored entry headers")

    back = pf.read_binder(written)
    rows_total = dup_tables = dup_ids = 0
    for e, e2 in zip(b.entries, back.entries, strict=True):
        name = short(e.name)
        p = pf.read_param(e.data)
        rows = rows_of(e.data)
        rows_total += len(rows)
        if [r[0] for r in rows] != param_row_ids(e.data):
            problems.append(f"{name}: row IDs or their order differ from the independent reader")
        if pf.write_param(p) != e.data:
            problems.append(f"{name}: the table written back differs (rows, names or metadata)")
        if rows_of(e2.data) != rows or e2.data != e.data or (e2.id, e2.flags, e2.name) != (e.id, e.flags, e.name):
            problems.append(f"{name}: changed by writing the binder")
        if len(param_merge._keyed(p.rows)) != len(rows):
            problems.append(f"{name}: the merger's row keys do not cover every row once")
        dups = {i: n for i, n in Counter(r[0] for r in rows).items() if n > 1}
        if dups:
            dup_tables += 1
            dup_ids += len(dups)
    return {
        "tables": len(b.entries),
        "rows": rows_total,
        "tables_with_duplicate_ids": dup_tables,
        "duplicate_ids": dup_ids,
        "binder_bytes": len(body),
        "problems": problems,
    }


def compare(a: bytes, b: bytes) -> dict:
    from roundtable_souls.mods import paramfile as pf

    at = first_difference(a, b)
    if at is None:
        return {"binders": "identical", "bytes": len(a)}
    ba, bb = pf.read_binder(a), pf.read_binder(b)
    out: dict = {"binders": f"differ at {at:#x}", "tables": []}
    if [short(e.name) for e in ba.entries] != [short(e.name) for e in bb.entries]:
        out["table_order"] = "differs"
    other = {short(e.name).lower(): e for e in bb.entries}
    for e in ba.entries:
        f = other.get(short(e.name).lower())
        if f is None:
            out["tables"].append({"table": short(e.name), "only_in": "A"})
        elif f.data != e.data or (f.id, f.flags) != (e.id, e.flags):
            ra, rb = rows_of(e.data), rows_of(f.data)
            changed = sum(1 for x, y in zip(ra, rb) if x != y) + abs(len(ra) - len(rb))
            out["tables"].append({"table": short(e.name), "rows_differ": changed, "rows": [len(ra), len(rb)]})
    return out


def main() -> int:
    p = _common.parser((__doc__ or "").split("\n\n")[0])
    p.add_argument(
        "--file", action="append", help="a game archive to round-trip (repeatable; default: the ten below in this file)"
    )
    p.add_argument("--compare", nargs=2, type=Path, metavar=("A", "B"), help="two regulation.bin files to compare")
    args = p.parse_args()
    game = _common.game_dir(args.game)
    out = _common.output_dir(args.out, "bnd4-roundtrip", game)
    _common.sandbox_launcher(out, game)

    from roundtable_souls.gamefiles import find_oodle

    dec = find_oodle(game)
    started = time.time()
    result: dict = {"commit": _common.commit(), "game_regulation_bytes": (game / "regulation.bin").stat().st_size}
    ok = True
    if args.compare:
        a, b = (binder_of(path.read_bytes(), dec) for path in args.compare)
        result["compare"] = {"a": args.compare[0].name, "b": args.compare[1].name} | compare(a, b)
        ok = result["compare"]["binders"] == "identical"
    else:
        result["archives"] = check_archives(game, dec, args.file or ARCHIVES)
        result["regulation"] = check_regulation(binder_of((game / "regulation.bin").read_bytes(), dec))
        ok = all(r["result"] == "identical" for r in result["archives"]) and not result["regulation"]["problems"]
    result["seconds"] = round(time.time() - started, 1)
    (out / "result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))
    print(("PASS" if ok else "FAIL"), "-", out / "result.json")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
