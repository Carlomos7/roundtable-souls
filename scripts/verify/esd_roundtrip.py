"""Check that the launcher's ESD code (formats/esd) reads and writes talk scripts without losing anything.

For every ESD inside the talk archives checked (the game's own, found by name, plus any --file):
  1. it reads, is written back, and the written file reads again to the same structure: state machines and states in
     the same order, every condition in order with its target, nested conditions and pass commands, every enter, exit
     and ongoing command, and every condition test and command argument byte for byte (opaque EZL), the name and the
     four header values;
  2. with Soulstruct available (`uv run --with soulstruct ...`), Soulstruct reads the original to the same structure,
     as an independent reader of the same format.
  3. every condition leads to a state of its own machine (the reader refuses anything else), in the original and in
     the written file.
The writer lays files out as the game's own are, so the game's talk scripts should come back byte for byte; that is
reported per file ("identical"). A file another tool wrote may come back laid out differently with the same
structure; that is reported, not a failure.

    uv run python scripts/verify/esd_roundtrip.py [--game DIR] [--out DIR] [--file TALKESDBND ...]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import _common

from roundtable_souls import formats

# Talk archives of the base game and the DLC, tried by name; those the game does not have are skipped.
GAME_TALK = ["script/talk/m00_00_00_00.talkesdbnd.dcx"] + [
    f"script/talk/m{area}_00_00_00.talkesdbnd.dcx"
    for area in ("10", "11", "12", "13", "14", "15", "16", "18", "19", "20", "21", "22", "25", "28", "60", "61")
]


def shape(esd) -> dict:
    """The whole structure as plain values, in stored order, for comparing two readings."""

    def command(c) -> list:
        return [c.bank, c.index, [bytes(a).hex() for a in c.args]]

    def condition(c) -> list:
        return [
            c.next_state_id,
            bytes(c.test_ezl).hex(),
            [command(x) for x in c.pass_commands],
            [condition(x) for x in c.subconditions],
        ]

    return {
        "magic": list(esd.magic),
        "name": esd.esd_name,
        "machines": [
            [
                machine_id,
                [
                    [
                        s.state_id,
                        [condition(c) for c in s.conditions],
                        [command(c) for c in s.enter_commands],
                        [command(c) for c in s.exit_commands],
                        [command(c) for c in s.ongoing_commands],
                    ]
                    for s in states.values()
                ],
            ]
            for machine_id, states in esd.state_machines.items()
        ],
    }


def counts(esd) -> dict:
    def walk(c):
        yield c
        for s in c.subconditions:
            yield from walk(s)

    states = [s for m in esd.state_machines.values() for s in m.values()]
    conditions = [x for s in states for c in s.conditions for x in walk(c)]
    return {
        "machines": len(esd.state_machines),
        "states": len(states),
        "conditions": len(conditions),
        "nested": sum(1 for c in conditions for _ in c.subconditions),
        "commands": sum(len(s.enter_commands) + len(s.exit_commands) + len(s.ongoing_commands) for s in states)
        + sum(len(c.pass_commands) for c in conditions),
    }


def soulstruct_reader():
    """Soulstruct's own reader (Dark Souls III's settings are version 3 with long offsets, as Elden Ring's), or None."""
    try:
        from soulstruct.darksouls3.ezstate.esd import TalkESD  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001  (not installed, or a version without it)
        return None
    return lambda data: TalkESD.from_bytes(data)


def check(name: str, data: bytes, other) -> dict:
    from roundtable_souls.formats.esd import read_esd, write_esd

    row: dict = {"esd": name, "bytes": len(data)}
    try:
        esd = read_esd(data)
    except Exception as e:  # noqa: BLE001
        return row | {"result": f"not read: {e}"}
    written = write_esd(esd)
    again = read_esd(written)
    problems = []
    if shape(again) != shape(esd):
        problems.append("written file reads back to a different structure")
    row |= counts(esd) | {"written_bytes": len(written), "identical": written == data}
    if other is not None:
        try:
            theirs = other(data)
            if shape(theirs) != shape(esd):
                problems.append("Soulstruct reads the original to a different structure")
            row["soulstruct"] = "same"
        except Exception as e:  # noqa: BLE001
            row["soulstruct"] = f"could not read: {e}"
    row["result"] = "; ".join(problems) or "same structure"
    return row


def main() -> int:
    p = _common.parser((__doc__ or "").split("\n\n")[0])
    p.add_argument("--file", action="append", type=Path, help="a talk archive (.talkesdbnd.dcx) to check; repeatable")
    args = p.parse_args()
    game = _common.game_dir(args.game)
    out = _common.output_dir(args.out, "esd-roundtrip", game)
    _common.sandbox_launcher(out, game)

    from roundtable_souls.game import archives as gamearchive
    from roundtable_souls.game.oodle import find_oodle

    dec = find_oodle(game)
    other = soulstruct_reader()
    started = time.time()
    sources: list[tuple[str, bytes | None]] = [(f"game: {rel}", gamearchive.read(game, rel)) for rel in GAME_TALK]
    sources += [(f"file: {'/'.join(f.parts[-5:])}", f.read_bytes()) for f in args.file or []]
    archives, rows, missing = [], [], []
    for label, raw in sources:
        if raw is None:
            missing.append(label)
            continue
        body, _how = formats.dcx.unpack(raw, dec)
        esds = [e for e in formats.bnd4.read_bnd4(body).entries if (e.name or "").lower().endswith(".esd")]
        archives.append({"archive": label, "esds": len(esds)})
        for e in esds:
            rows.append({"archive": label} | check((e.name or "").replace("\\", "/").rsplit("/", 1)[-1], e.data, other))
    failed = [r for r in rows if r["result"] != "same structure"]
    identical = sum(1 for r in rows if r.get("identical"))
    result = {
        "commit": _common.commit(),
        "independent_reader": "soulstruct" if other else "not installed (run with: uv run --with soulstruct ...)",
        "archives": archives,
        "not_in_the_game": missing,
        "esds": len(rows),
        "failed": len(failed),
        "written_back_byte_for_byte": identical,
        "rows": rows,
        "seconds": round(time.time() - started, 1),
    }
    (out / "result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    for r in rows:
        print(
            f"{r['result']:<16} {r['archive'][-70:]:<70} {r['esd']:<16} machines {r.get('machines', '-'):>3} "
            f"states {r.get('states', '-'):>5} conditions {r.get('conditions', '-'):>5} "
            f"bytes {r['bytes']} -> {r.get('written_bytes', '-')}{' identical' if r.get('identical') else ''}"
            + (f" | soulstruct {r['soulstruct']}" if "soulstruct" in r else "")
        )
    print(
        f"{len(rows)} ESDs in {len(archives)} archives; not in the game: {len(missing)}; failed: {len(failed)}; "
        f"written back byte for byte: {identical}"
    )
    print(("PASS" if rows and not failed else "FAIL"), "-", out / "result.json")
    return 0 if rows and not failed else 1


if __name__ == "__main__":
    sys.exit(main())
