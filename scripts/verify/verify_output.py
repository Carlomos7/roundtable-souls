"""Check a combined package the launcher wrote against a result worked out here from its inputs.

The package's record (combined-parameters.json) lists every merged file's sources in load order. For each merged
file this reads the game's own copy and each source with an independent reader when one is installed (Soulstruct;
else the launcher's own, and the report says so), works out the intended result, and compares it with the file on
disk: inner file names, IDs, flags and contents, and text entry by entry where several mods changed one text table.

The intended result follows the merge rules as documented: a part a mod changed or added is taken from the last mod
that changed it; a part missing from a mod's copy counts as removed. That last rule is an unvalidated assumption (a
mod made for an older game version also lacks parts it never meant to remove), so every removal is listed on its own.

Parameters (regulation.bin) are checked byte by byte against the packs with the launcher's own reader (the
decryption and table layout are the launcher's; Soulstruct's parameter reader merges rows that share an ID). The
merger works in 4-byte chunks, so two packs changing different bytes of one chunk is reported as that known
limitation, not as a failure.

    uv run --with soulstruct python scripts/verify/verify_output.py --package DIR [--game DIR] [--out DIR]

Real files are only read. Results: verify-output.json in the output folder.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import _common
import _readers
from calibrate import calibrate

from roundtable_souls import formats

REMOVED = None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def intended_parts(van: _readers.Parts, layers: list[tuple[str, _readers.Parts]], fmg) -> tuple[dict, dict, list]:
    """(intended parts, text tables merged entry by entry {key: texts}, removals [(part, by)])."""
    changes: dict[str, list] = {}
    for label, parts in layers:
        for key, v in parts.items():
            if key not in van or van[key][2] != v[2]:
                changes.setdefault(key, []).append((label, v))
        for key in van:
            if key not in parts:
                changes.setdefault(key, []).append((label, REMOVED))
    out = dict(van)
    texts: dict[str, dict[int, str]] = {}
    removals = []
    for key, ch in changes.items():
        kept = [v for _, v in ch if v is not REMOVED]
        distinct = {v[2] if v is not REMOVED else None for _, v in ch}
        last = ch[-1][1]
        if len(distinct) > 1 and len(ch) > 1 and key in van and len(kept) == len(ch) and key.endswith(".fmg"):
            if fmg is None:
                raise _readers.CannotRead(
                    f"{key}: several mods changed this text table and no text reader is available"
                )
            base = fmg(van[key][2])
            merged = dict(base)
            for _label, v in ch:
                t = fmg(v[2])
                for tid, s in t.items():
                    if base.get(tid) != s:
                        merged[tid] = s
                for tid in base:
                    if tid not in t:
                        merged.pop(tid, None)
            texts[key] = merged
            out[key] = kept[-1]
        elif last is REMOVED:
            out.pop(key, None)
            removals.append((key, ch[-1][0]))
        else:
            out[key] = last
    return out, texts, removals


def check_file(entry: dict, pkg: Path, game: Path, dec, read, fmg, failures: list, notes: list) -> dict:
    from roundtable_souls.game import archives as gamearchive

    rel = entry["rel"]
    raw = (pkg / rel).read_bytes()
    game_raw = gamearchive.read(game, rel)
    depth = len(Path(rel).parts)
    mod = lambda s: Path(s["path"]).parents[depth - 1].name  # noqa: E731  (the package folder the copy is in)
    res: dict = {"file": rel, "sources": [mod(s) for s in entry["sources"]]}
    if game_raw is None:
        notes.append(f"{rel}: the game has no such file")
        return res
    for s in entry["sources"]:
        if _sha(Path(s["path"])) != s["sha256"]:
            failures.append(f"{rel}: {s['path']} changed after the package was built; rebuild first")
            return res
    # the header: everything but the sizes, the compression kind and the level byte must be the game's own
    mask = lambda h: bytes(h[:0x1C]) + bytes(h[0x24:0x28]) + bytes(h[0x2C:0x30]) + bytes(h[0x31:0x4C])  # noqa: E731
    layout = f"{raw[0x28:0x2C].decode(errors='replace')} byte {raw[0x30]}"
    game_layout = f"{game_raw[0x28:0x2C].decode(errors='replace')} byte {game_raw[0x30]}"
    res["layout"] = layout
    if mask(raw) != mask(game_raw):
        failures.append(f"{rel}: the DCX header differs from the game's own beyond sizes, kind and level")
    if layout != game_layout:
        notes.append(f"{rel}: stored as {layout}; the game's own is {game_layout}")
    try:
        van = read(game_raw)
    except _readers.CannotRead as e:
        notes.append(f"{rel}: the reader cannot open the game's own copy ({e}), so it says nothing about ours")
        return res
    try:
        got = read(raw)
    except _readers.CannotRead as e:
        if layout != game_layout:  # calibrated on the game's layout only: a refusal here is about the reader
            notes.append(f"{rel}: the reader cannot open the {layout} layout ({e}); contents not checked")
        else:
            failures.append(f"{rel}: the reader opens the game's copy but not ours: {e}")
        return res
    layers = [(mod(s), read(Path(s["path"]).read_bytes())) for s in entry["sources"]]
    try:
        want, texts, removals = intended_parts(van, layers, fmg)
    except _readers.CannotRead as e:
        notes.append(f"{rel}: {e}")
        return res
    names_ok = set(got) == set(want)
    diff = []
    for key in sorted(set(got) & set(want)):
        g, w = got[key], want[key]
        if key in texts:
            if fmg(g[2]) != texts[key]:
                diff.append(f"{key}: text differs")
        elif g[2] != w[2]:
            diff.append(f"{key}: contents differ")
        if (g[0], g[1]) != (w[0], w[1]):
            diff.append(f"{key}: ID/flags {g[0]}/{g[1]} instead of {w[0]}/{w[1]}")
    res |= {
        "parts": len(got),
        "names_as_intended": names_ok,
        "parts_differing": diff[:20],
        "text_tables_merged_by_entry": sorted(texts),
        "removed_because_a_copy_lacks_them": len(removals),
    }
    if not names_ok:
        failures.append(
            f"{rel}: inner files differ: missing {sorted(set(want) - set(got))[:5]}, extra {sorted(set(got) - set(want))[:5]}"
        )
    if diff:
        failures.append(f"{rel}: {len(diff)} parts differ from the intended result, e.g. {diff[0]}")
    if removals:
        by: dict[str, int] = {}
        for _key, who in removals:
            by[who] = by.get(who, 0) + 1
        notes.append(
            f"{rel}: {len(removals)} of the game's parts are left out because a mod's copy lacks them "
            f"({', '.join(f'{n} by {w}' for w, n in by.items())}); whether the mod meant that is not known"
        )
    return res


def check_regulation(record: dict, pkg: Path, dec, failures: list, notes: list) -> dict:
    from roundtable_souls.mods import param_merge

    base, packs = Path(record["base"]), record.get("packs") or []
    for src in [{"path": record["base"], "sha256": record["base_sha256"]}, *packs]:
        if _sha(Path(src["path"])) != src["sha256"]:
            failures.append(f"regulation: {src['path']} changed after the package was built; rebuild first")
            return {}
    breg = formats.regulation.read_regulation(base.read_bytes(), dec)
    oreg = formats.regulation.read_regulation((pkg / "regulation.bin").read_bytes(), dec)
    pregs = [
        (Path(p["path"]).parent.name, formats.regulation.read_regulation(Path(p["path"]).read_bytes(), dec))
        for p in packs
    ]
    short = lambda n: n.replace("\\", "/").rsplit("/", 1)[-1]  # noqa: E731
    counts = {"tables": 0, "rows": 0, "rows_changed_by_packs": 0, "chunk_limitation": 0, "size_mismatch_skipped": 0}
    for f in breg.bnd.entries:
        name = short(f.name or "")
        counts["tables"] += 1
        vp = formats.param.read_param(f.data)
        vrows = param_merge._keyed(vp.rows)
        of = oreg.bnd.get(name)
        if of is None:
            failures.append(f"regulation: the output has no {name}")
            continue
        orows = param_merge._keyed(formats.param.read_param(of.data).rows)
        want = {k: bytearray(r.data) for k, r in vrows.items()}
        writers: dict[tuple, dict[int, str]] = {}
        for label, reg in pregs:
            pfile = reg.bnd.get(name)
            if pfile is None or pfile.data == f.data:
                continue
            prows = param_merge._keyed(formats.param.read_param(pfile.data).rows)
            for k, r in prows.items():
                if k not in vrows:
                    want[k] = bytearray(r.data)  # a new row: the last pack's
                    continue
                if len(r.data) != len(vrows[k].data):
                    counts["size_mismatch_skipped"] += 1
                    continue
                for i, (a, b) in enumerate(zip(r.data, vrows[k].data, strict=True)):
                    if a != b:
                        want[k][i] = a
                        writers.setdefault(k, {})[i] = label
        counts["rows"] += len(orows)
        for k, w in want.items():
            o = orows.get(k)
            if o is None:
                failures.append(f"regulation: {name} row {k[0]} (occurrence {k[1] + 1}) is missing")
                continue
            if k not in vrows or bytes(w) != bytes(vrows[k].data):
                counts["rows_changed_by_packs"] += 1
            if bytes(o.data) == bytes(w):
                continue
            bad = [i for i in range(len(w)) if o.data[i] != w[i]]
            chunks = writers.get(k, {})
            if all(any(j in chunks for j in range(i - i % 4, i - i % 4 + 4)) for i in bad):
                counts["chunk_limitation"] += 1
                notes.append(
                    f"regulation: {name} row {k[0]}: two packs changed different bytes of one 4-byte chunk "
                    "(the merger's known limitation)"
                )
            else:
                failures.append(f"regulation: {name} row {k[0]} (occurrence {k[1] + 1}) differs at bytes {bad[:6]}")
        extra = set(orows) - set(want)
        if extra:
            failures.append(f"regulation: {name} has rows no input has: {sorted(extra)[:5]}")
        if [k for k in orows if k in vrows] != list(vrows):
            failures.append(f"regulation: {name}: the game's rows are not in their original order")
    return counts


def main() -> int:
    p = _common.parser((__doc__ or "").split("\n\n")[0])
    p.add_argument("--package", type=Path, required=True, help="the combined package folder (combined-parameters)")
    args = p.parse_args()
    pkg = args.package.resolve()
    record = json.loads((pkg / "combined-parameters.json").read_text(encoding="utf-8"))
    game = _common.game_dir(args.game)
    out = _common.output_dir(args.out, "verify-output", game)
    _common.sandbox_launcher(out, game)
    from roundtable_souls.game.oodle import find_oodle

    dec = find_oodle(game)
    ss = _readers.soulstruct()
    read = ss or _readers.ours(dec)
    fmg = _readers.fmg_soulstruct() if ss else _readers.fmg_ours
    independent = ss is not None
    failures: list[str] = []
    notes: list[str] = []
    if not independent:
        notes.append("Soulstruct is not installed: the launcher's own reader was used, so this is not independent")
    merged = [e for e in (record.get("files") or {}).values() if e.get("output")]
    cal = calibrate(game, dec, [e["rel"] for e in merged])
    files = [check_file(e, pkg, game, dec, read, fmg, failures, notes) for e in merged]
    regulation = check_regulation(record, pkg, dec, failures, notes) if record.get("base") else {}

    print(
        f"reader: {'Soulstruct ' + str(_readers.soulstruct_version()) if independent else 'the launcher (not independent)'}"
    )
    for f in files:
        print(f"{f['file']}: {json.dumps({k: v for k, v in f.items() if k != 'file'})}")
    if regulation:
        print(f"regulation.bin: {json.dumps(regulation)}")
    print(f"\nvalidation failures: {len(failures)}")
    for line in failures:
        print("  - " + line)
    print(f"notes (not failures): {len(notes)}")
    for line in notes:
        print("  - " + line)
    report = {
        "made": time.strftime("%Y-%m-%d %H:%M:%S"),
        "commit": _common.commit(),
        "package_made_by": record.get("made_by"),
        "reader": "soulstruct " + str(_readers.soulstruct_version()) if independent else "launcher (not independent)",
        "calibration": cal,
        "files": files,
        "regulation": regulation,
        "failures": failures,
        "notes": notes,
    }
    (out / "verify-output.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"report: {out / 'verify-output.json'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
