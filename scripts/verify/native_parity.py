"""The launcher's own build of an overhaul (mods.engine, nothing of the mod's run) compared with the mod's own build
from the same inputs: the parity check of Phase 6 (S3c).

The profile's overhaul (found by its config, data/overhauls) is built by the launcher into the output folder, from a
copy of the profile that points the overhaul's package there; the profile, the packages, the download and the mod's
installed build are only read. The installed build is the reference: it must be the mod's installer's output (no
`builtBy` in its manifest) and made from the same inputs (the sources its manifest lists, unchanged since). Then every
file of both is compared:

    archives (DCX/BND4)     part by part: bytes, else by meaning for talk scripts (ESD, state by state as
                            esd_merge.py --compare), animation events (TAE, animation by animation, exactly) and
                            text (FMG, entry by entry)
    regulation.bin          table by table, row by row (IDs, order, bytes)
    anything else           by sha256 (the scripts, the copied DLLs, audio and UI)

Every difference is listed in report.md and result.json, to be explained or fixed before the build is accepted.

    uv run python scripts/verify/native_parity.py [--profile ME3] [--setup DIR]
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import _common
import esd_merge
import tae_merge

SKIP = {"merge-report.txt", "revivePrototype.log", "installation.json"}  # reports and logs; the manifest is separate


def main() -> int:
    p = _common.parser((__doc__ or "").split("\n\n")[0])
    p.add_argument("--profile", type=Path, help="the me3 profile with the overhaul (default: local.toml 'profile')")
    p.add_argument("--setup", type=Path, help="the overhaul's download (default: where its manifest says)")
    args = p.parse_args()
    game = _common.game_dir(args.game)
    out = _common.output_dir(args.out, "native-parity", game)
    _common.sandbox_launcher(out, game)

    from roundtable_souls import overhauls
    from roundtable_souls.game import oodle as game_oodle
    from roundtable_souls.mods import engine, profile_edit
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

    problems = reference_problems(recorded, profile)
    for line in problems:
        print(f"reference: {line}")

    copy = write_profile(out / "input" / "profile.me3", profile, rows, row, out / "native" / reference.name / "mod")
    log: list[str] = []
    print(f"building {recipe['label']} {version} with the launcher into {out / 'native'}")
    engine.build(copy, out / "native" / reference.name / "mod", setup, recipe, version, log.append, game_dir=game)
    native = out / "native" / reference.name

    dec = game_oodle.find_oodle(game)
    files = compare_trees(native, reference, dec)
    native_report = (native / recipe["output"].get("report", "merge-report.txt")).read_text(encoding="utf-8")
    differ = {k: v for k, v in files.items() if v["result"] != "same"}
    result = {
        "commit": _common.commit(),
        "profile": str(profile),
        "setup": str(setup),
        "reference": str(reference),
        "recipe": recipe["id"],
        "version": version,
        "reference_problems": problems,
        "files": files,
        "native_report": native_report,
        "seconds": round(time.time() - started),
    }
    (out / "result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    (out / "report.md").write_text(report_text(result, differ), encoding="utf-8")
    print(f"{len(files)} files compared: {len(files) - len(differ)} the same, {len(differ)} differ")
    for rel, f in differ.items():
        details = f.get("details") or []
        more = f" and {len(details) - 4} more" if len(details) > 4 else ""
        print(f"  {rel}: {f['result']}" + (f" ({'; '.join(details[:4])}{more})" if details else ""))
    print(f"\ndone in {result['seconds']}s: {out / 'report.md'}")
    return 0 if not differ and not problems else 1


def reference_problems(recorded: dict, profile: Path) -> list[str]:
    """Why the installed build may not be the mod's own build from today's inputs (empty: it is)."""
    out = []
    if recorded.get("builtBy"):
        out.append(f"built by {recorded['builtBy']}, not by the mod's installer: not a reference")
    for row in recorded.get("sources") or []:
        path = Path(str(row.get("path") or ""))
        if path.name.lower().endswith(".me3"):
            continue  # the profile's text, not a merge input
        if not path.is_file():
            out.append(f"an input of the installed build is gone: {path}")
        elif _sha(path) != row.get("sha256"):
            out.append(f"an input changed since the installed build was made: {path}")
    return out


def write_profile(dest: Path, profile: Path, rows: list[dict], overhaul: dict, target: Path) -> Path:
    """A copy of the profile with absolute paths, the overhaul's package pointing at `target`."""
    from roundtable_souls.mods import profile_edit

    def q(text: str) -> str:
        return json.dumps(text)

    def deps(r: dict, key: str) -> str:
        items = [
            f"{{ id = {q(d['id'])}, optional = {str(bool(d.get('optional'))).lower()} }}" for d in r.get(key) or []
        ]
        return f"{key} = [{', '.join(items)}]" if items else ""

    lines = ['profileVersion = "v1"', "", "[[supports]]", 'game = "eldenring"', ""]
    for r in rows:
        if not r.get("path"):
            continue
        path = target if r is overhaul else profile_edit.resolve(profile, r["path"])
        lines.append("[[packages]]" if r["kind"] == "package" else "[[natives]]")
        if r["kind"] == "package":
            lines.append(f"id = {q(r.get('id') or Path(r['path']).name)}")
        lines.append(f"path = {q(Path(path).as_posix())}")
        if not r.get("enabled", True):
            lines.append("enabled = false")
        lines += [x for x in (deps(r, "load_after"), deps(r, "load_before")) if x]
        lines.append("")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def compare_trees(native: Path, reference: Path, dec) -> dict[str, dict]:
    def listing(root: Path) -> dict[str, Path]:
        return {
            p.relative_to(root).as_posix(): p
            for p in root.rglob("*")
            if p.is_file() and ".roundtable-build" not in p.parts and p.name.lower() not in {s.lower() for s in SKIP}
        }

    ours, theirs = listing(native), listing(reference)
    out: dict[str, dict] = {}
    for rel in sorted(set(ours) | set(theirs), key=str.lower):
        if rel not in theirs:
            out[rel] = {"result": "only in the launcher's build"}
        elif rel not in ours:
            out[rel] = {"result": "only in the mod's build"}
        else:
            out[rel] = compare_file(rel, ours[rel].read_bytes(), theirs[rel].read_bytes(), dec)
    return out


def compare_file(rel: str, a: bytes, b: bytes, dec) -> dict:
    from roundtable_souls import formats

    if a == b:
        return {"result": "same", "how": "bytes"}
    name = rel.rsplit("/", 1)[-1].lower()
    try:
        if name == "regulation.bin":
            details = compare_regulation(a, b, dec)
            return {"result": "same" if not details else "differs", "how": "rows", "details": details}
        if a[:4] == b"DCX\0" or formats.bnd4.is_bnd4(a):
            details = compare_archive(a, b, dec)
            return {"result": "same" if not details else "differs", "how": "parts", "details": details}
    except Exception as e:  # a reader's verdict is a finding too
        return {"result": "differs", "how": "unreadable", "details": [f"{type(e).__name__}: {e}"]}
    return {"result": "differs", "how": "sha256", "details": [f"ours {_hash(a)[:16]}, theirs {_hash(b)[:16]}"]}


def compare_regulation(a: bytes, b: bytes, dec) -> list[str]:
    from roundtable_souls import formats

    ra, rb = formats.regulation.read_regulation(a, dec), formats.regulation.read_regulation(b, dec)
    ta = {e.name: e.data for e in ra.bnd.entries if e.name}
    tb = {e.name: e.data for e in rb.bnd.entries if e.name}
    out = [f"{n.rsplit(chr(92), 1)[-1]} only in ours" for n in ta if n not in tb]
    out += [f"{n.rsplit(chr(92), 1)[-1]} only in theirs" for n in tb if n not in ta]
    if ra.version != rb.version:
        out.append(f"regulation version: ours {ra.version}, theirs {rb.version}")
    for n in ta:
        if n not in tb or ta[n] == tb[n]:
            continue
        pa, pb = formats.param.read_param(ta[n]), formats.param.read_param(tb[n])
        rows_a, rows_b = [(r.id, r.data) for r in pa.rows], [(r.id, r.data) for r in pb.rows]
        if rows_a != rows_b:
            ids_a, ids_b = [i for i, _ in rows_a], [i for i, _ in rows_b]
            what = "row IDs or order" if ids_a != ids_b else f"{sum(x != y for x, y in zip(rows_a, rows_b))} rows"
            out.append(f"{n.rsplit(chr(92), 1)[-1]}: {what} differ")
        elif pa.header != pb.header or pa.tail != pb.tail:
            out.append(f"{n.rsplit(chr(92), 1)[-1]}: same rows; header or names differ")
    return out


def compare_archive(a: bytes, b: bytes, dec) -> list[str]:
    from roundtable_souls import formats
    from roundtable_souls.merging.rules import esd as esd_rule

    ba = formats.dcx.unpack(a, dec)[0] if a[:4] == b"DCX\0" else a
    bb = formats.dcx.unpack(b, dec)[0] if b[:4] == b"DCX\0" else b
    if ba == bb:
        return []  # the same content, compressed differently
    pa = {e.name: e.data for e in formats.bnd4.read_bnd4(ba).entries if e.name}
    pb = {e.name: e.data for e in formats.bnd4.read_bnd4(bb).entries if e.name}
    out = [f"{n} only in ours" for n in pa if n not in pb]
    out += [f"{n} only in theirs" for n in pb if n not in pa]
    for n, x in pa.items():
        y = pb.get(n)
        if y is None or x == y:
            continue
        short = n.replace("\\", "/").rsplit("/", 1)[-1]
        if esd_rule.is_esd(x) and esd_rule.is_esd(y):
            differ = esd_merge.compare(esd_rule, x, y)
            out += [f"{short}: {d}" for d in differ]
        elif formats.tae.is_tae(x) and formats.tae.is_tae(y):
            out += [f"{short}: {d}" for d in tae_merge.compare(formats.tae, x, y)]
        elif formats.fmg.is_fmg(x) and formats.fmg.is_fmg(y):
            ea, eb = formats.fmg.fmg_entries(x), formats.fmg.fmg_entries(y)
            keys = sorted(k for k in set(ea) | set(eb) if ea.get(k) != eb.get(k))
            out += [f"{short}: {len(keys)} entries differ ({', '.join(map(str, keys[:6]))})"] if keys else []
        else:
            out.append(f"{short}: bytes differ")
    if not out:
        same = [n for n in pa if pa[n] == pb.get(n)]
        if len(same) == len(pa) == len(pb):
            out.append("the same parts in another order or another archive header")
    return out


def report_text(result: dict, differ: dict) -> str:
    lines = [
        f"# Native build parity: {result['recipe']} {result['version']}",
        "",
        f"Made {time.strftime('%Y-%m-%d %H:%M')} by scripts/verify/native_parity.py ({result['commit']}).",
        f"Reference: the mod's own build in {result['reference']}. Download: {result['setup']}.",
        "",
        "## Reference",
        "",
        *([f"- {p}" for p in result["reference_problems"]] or ["- the mod's installer's output, from today's inputs"]),
        "",
        f"## Files: {len(result['files'])} compared, {len(differ)} differ",
        "",
    ]
    for rel, f in differ.items():
        lines.append(f"- `{rel}`: {f['result']}" + (f" ({f['how']})" if f.get("how") else ""))
        lines += [f"  - {d}" for d in f.get("details") or []]
    if not differ:
        lines.append("Every file is the same (by bytes, by meaning or row by row, as listed in result.json).")
    lines += ["", "## The launcher's build report", "", "```", result["native_report"].strip(), "```", ""]
    return "\n".join(lines)


def _sha(p: Path) -> str:
    return _hash(p.read_bytes())


def _hash(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


if __name__ == "__main__":
    sys.exit(main())
