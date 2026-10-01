"""Combine the parameter changes of several packs into one regulation.bin, against the game's own.

For every table, each pack is compared with the game's copy and only what it changed is applied, in load order:

- a changed row is applied field-agnostically, four bytes at a time: two packs that change different parts of the
  same row both apply; where they change the same bytes, the later pack wins (reported as a conflict)
- a row a pack adds is added (a later pack adding the same row wins, reported)
- a row a pack lacks is kept: packs made from older game data often lack newer rows, and dropping them would undo
  the game's own additions
- a table whose rows have another size than the game's is skipped for that pack (made for another game version)
- a table the game does not have is taken from the last pack that has it

Rows are matched by ID and, for the few tables that repeat an ID, by which occurrence it is.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field

from roundtable_souls.mods import formats
from roundtable_souls.mods import paramfile as pf

WORD = 4


@dataclass
class PackReport:
    name: str
    version: str
    tables: int = 0
    changed: int = 0
    added: int = 0
    skipped: list[str] = field(default_factory=list)  # "Table: why"


@dataclass
class Report:
    base_version: str
    packs: list[PackReport]
    conflicts: list[tuple[str, int, list[str]]] = field(default_factory=list)  # (table, row id, packs, in order)
    tables: int = 0

    def lines(self, limit: int = 12) -> list[str]:
        out = []
        for p in self.packs:
            what = f"{p.name}: {p.changed} changed and {p.added} new rows in {p.tables} tables"
            if p.version != self.base_version:
                what += f" (made for regulation {p.version}; the game has {self.base_version})"
            out.append(what)
            out += [f"  skipped {s}" for s in p.skipped]
        if self.conflicts:
            out.append(
                f"{len(self.conflicts)} rows changed by more than one pack; the later pack won where they overlap:"
            )
            out += [f"  {t} {rid}: {' then '.join(who)}" for t, rid, who in self.conflicts[:limit]]
            if len(self.conflicts) > limit:
                out.append(f"  and {len(self.conflicts) - limit} more")
        return out


def _short(name: str) -> str:
    return name.replace("\\", "/").rsplit("/", 1)[-1]


def _keyed(rows: list[pf.Row]) -> dict[tuple[int, int], pf.Row]:
    seen: dict[int, int] = {}
    out = {}
    for r in rows:
        k = seen.get(r.id, 0)
        seen[r.id] = k + 1
        out[(r.id, k)] = r
    return out


def _apply_words(result: bytearray, pack: bytes, base: bytes) -> bool:
    """Apply the bytes pack changed from base onto result. True when some of them had been changed differently by an
    earlier pack (the same field edited twice)."""
    clash = False
    for i in range(0, len(base), WORD):
        pw, bw = pack[i : i + WORD], base[i : i + WORD]
        if pw == bw:
            continue
        cur = result[i : i + WORD]
        if cur != bw and cur != pw:
            clash = True
        result[i : i + WORD] = pw
    return clash


def combine(base_raw: bytes, packs: list[tuple[str, bytes]], oodle=None) -> tuple[bytes, Report]:
    """(encrypted regulation.bin, report) combining packs (name, regulation bytes), in load order, onto base_raw (the
    game's own regulation.bin)."""
    base = pf.read_regulation(base_raw, oodle)
    regs = [(name, pf.read_regulation(raw, oodle)) for name, raw in packs]
    report = Report(base.version, [PackReport(name, r.version) for name, r in regs])
    names = [e.name or "" for e in base.bnd.entries]
    extra: dict[str, formats.Entry] = {}
    for _name, r in regs:
        for f in r.bnd.entries:
            if base.bnd.get(_short(f.name or "")) is None:
                extra[_short(f.name or "").lower()] = f  # a table the game does not have: the last pack's
    for full in names:
        short = _short(full)
        vfile = base.bnd.get(short)
        assert vfile is not None
        touched = [(i, r.bnd.get(short)) for i, (_n, r) in enumerate(regs)]
        touched = [(i, f) for i, f in touched if f is not None and f.data != vfile.data]
        if not touched:
            continue
        v = pf.read_param(vfile.data)
        vkeyed = _keyed(v.rows)
        out_rows = [pf.Row(r.id, bytes(r.data), r.name) for r in v.rows]
        at = {k: i for i, k in enumerate(vkeyed)}  # key -> position in out_rows
        changers: dict[tuple[int, int], list[str]] = {}
        clashed: set[tuple[int, int]] = set()
        table_changed = False
        for i, f in touched:
            pname = regs[i][0]
            rep = report.packs[i]
            try:
                p = pf.read_param(f.data)
            except pf.FormatError as e:
                rep.skipped.append(f"{short}: {e}")
                continue
            if p.stride != v.stride:
                rep.skipped.append(
                    f"{short}: rows are {p.stride} bytes, the game's are {v.stride} (another game version)"
                )
                continue
            did = False
            for key, row in _keyed(p.rows).items():
                if key in vkeyed:
                    vrow = vkeyed[key]
                    if row.data == vrow.data and (not row.name or row.name == out_rows[at[key]].name):
                        continue
                    cur = out_rows[at[key]]
                    data = bytearray(cur.data)
                    if row.data != vrow.data:
                        if _apply_words(data, row.data, vrow.data):
                            clashed.add(key)
                        rep.changed += 1
                        changers.setdefault(key, []).append(pname)
                    out_rows[at[key]] = pf.Row(cur.id, bytes(data), row.name or cur.name)
                    did = True
                elif key in at:  # added by an earlier pack too
                    clashed.add(key)
                    changers.setdefault(key, []).append(pname)
                    out_rows[at[key]] = pf.Row(row.id, bytes(row.data), row.name)
                    rep.added += 1
                    did = True
                else:
                    ids = [r.id for r in out_rows]
                    pos = bisect.bisect_right(ids, row.id) if ids == sorted(ids) else len(out_rows)
                    out_rows.insert(pos, pf.Row(row.id, bytes(row.data), row.name))
                    at = {k: (j + 1 if j >= pos else j) for k, j in at.items()}
                    at[key] = pos
                    changers[key] = [pname]
                    rep.added += 1
                    did = True
            if did:
                rep.tables += 1
                table_changed = True
        for key in sorted(clashed):
            if len(changers.get(key, [])) > 1:
                report.conflicts.append((short.rsplit(".", 1)[0], key[0], changers[key]))
        if table_changed:
            v.rows = out_rows
            vfile.data = pf.write_param(v)
            report.tables += 1
    for f in extra.values():
        new_id = max((x.id for x in base.bnd.entries), default=-1) + 1
        base.bnd.entries.append(formats.Entry(f.name, new_id, f.data, f.flags))
        report.tables += 1
    return pf.write_regulation(base), report
