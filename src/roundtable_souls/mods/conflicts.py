"""What a profile loads, in one scan: merge health, every file two enabled packages both ship with what actually
happens to it, the combine's overlapping rows, and the entries me3 would refuse.

me3's rule for a file two packages ship is that the later one's copy is used. That is the whole story for most
files, but not for the ones a rebuild tool or the launcher's combine folds together: there the earlier copies are
inside the result, as long as it is up to date. Each earlier copy therefore gets one outcome:

    replaced   the later package's copy is used and this one is not (me3's rule; the only real loss)
    combined   the package that must stay last (or the combined-parameters package) was built from this copy, as it
               is now (its checksum is in the tool's list of sources, or the combine's record)
    stale      it is combined, but the copy used was different from this one today, or it was not used at all
               although it should be (rebuild to bring it in)
    unreached  the rebuild tool takes the file from the last package before it only, and another package's copy
               sits in between (for regulation.bin, the combine brings every pack's in)

Nothing is claimed combined without a checksum to back it.
"""

from __future__ import annotations

import os
from pathlib import Path

from roundtable_souls.mods import checks
from roundtable_souls.mods import profile as profile_tools
from roundtable_souls.mods import profile_edit as mod_manage
from roundtable_souls.mods import rebuild as merge
from roundtable_souls.mods.backends import builtin, local_path

OUTCOMES = ("replaced", "combined", "stale", "unreached")
OUTCOME_TEXT = {
    "replaced": "replaced",
    "combined": "combined",
    "stale": "combined, out of date",
    "unreached": "does not reach the rebuild",
}


def _key(p: Path) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def classify(profile: Path, scan: dict, game_dir=None) -> dict:
    """Outcomes for every overlap in scan (profile.scan_conflicts). Returns {conflicts: [{path, category, winner,
    losers: [{id, outcome}]}], counts: {outcome: n}, packages: {id: {outcome: n, wins: n}}}."""
    profile = Path(profile)
    folders = {p["id"]: Path(p["path"]) for p in scan.get("packages") or []}
    tool = combine = None
    tool_files: set[str] = set()
    tool_sources: dict[str, str] = {}
    combined: dict[str, str] = {}
    merged_files: set[str] = set()
    if merge.is_elden_ring(profile):
        layers = merge.layers(profile)
        _target, tool, _by_hand = merge.overlay(profile, layers)
        combine = builtin.find(profile, layers)
        if tool is not None:
            tool_files = {f.lower() for f in tool.merges()} | merge.covered(tool)
            for s in tool.sources() or []:
                tool_sources[_key(local_path(s["path"], profile, game_dir))] = s["sha256"]
        if combine is not None:
            rec = combine.record()
            for p in rec.get("packs") or []:
                if isinstance(p, dict) and p.get("path"):
                    combined[_key(Path(p["path"]))] = str(p.get("sha256") or "")
            for f in (rec.get("files") or {}).values():
                if f.get("output"):
                    merged_files.add(str(f.get("rel") or "").lower())
                    for s in f.get("sources") or []:
                        combined[_key(Path(s["path"]))] = str(s.get("sha256") or "")
    tool_dir = _key(tool.package["folder"]) if tool is not None else None
    comb_dir = _key(combine.folder) if combine is not None else None

    def used_by(sources: dict[str, str], copy: Path) -> str:
        want = sources.get(_key(copy))
        if want is None:
            return "stale"
        return "combined" if merge.sha256(copy) == want else "stale"

    out, counts = [], dict.fromkeys(OUTCOMES, 0)
    per: dict[str, dict] = {pid: {**dict.fromkeys(OUTCOMES, 0), "wins": 0} for pid in folders}
    for c in scan.get("conflicts") or []:
        rel = c["path"]
        low = rel.replace("\\", "/").lower()
        winner_dir = _key(folders.get(c["winner"], Path()))
        losers = c.get("losers") or []
        judged = []
        for i, loser in enumerate(losers):
            copy = folders.get(loser["id"], Path()) / rel
            outcome = "replaced"
            nearest = i == len(losers) - 1
            if tool_dir is not None and winner_dir == tool_dir and low in tool_files:
                if nearest:
                    outcome = used_by(tool_sources, copy)
                elif low == builtin.REGULATION and comb_dir is not None:
                    outcome = used_by(combined, copy)  # inside the combined file the tool takes
                else:
                    outcome = "unreached"
            elif comb_dir is not None and winner_dir == comb_dir and (low == builtin.REGULATION or low in merged_files):
                outcome = used_by(combined, copy)
            judged.append({"id": loser["id"], "outcome": outcome})
            counts[outcome] += 1
            if loser["id"] in per:
                per[loser["id"]][outcome] += 1
        if c["winner"] in per:
            per[c["winner"]]["wins"] += 1
        out.append({"path": rel, "category": c.get("category", ""), "winner": c["winner"], "losers": judged})
    return {"conflicts": out, "counts": counts, "packages": per}


def merged_from(profile: Path, package_id: str, ov: dict | None = None) -> list[str]:
    """The files of one package that a combined result was built from (combined, or combined but out of date):
    what stays in the game after the package is removed, until a rebuild. ov: an overview() of this profile to
    reuse, else one is worked out."""
    ov = ov if ov is not None else overview(Path(profile))
    out = []
    for c in (ov.get("overlaps") or {}).get("conflicts") or []:
        if any(l["id"] == package_id and l["outcome"] in ("combined", "stale") for l in c["losers"]):
            out.append(c["path"])
    return sorted(set(out), key=str.lower)


def row_conflicts(profile: Path) -> list[str]:
    """The combine's report lines about rows two packs both changed (empty without a combine)."""
    profile = Path(profile)
    if not merge.is_elden_ring(profile):
        return []
    combine = builtin.find(profile, merge.layers(profile))
    if combine is None:
        return []
    lines = combine.record().get("report") or []
    at = next((i for i, line in enumerate(lines) if "changed by more than one pack" in str(line)), None)
    return [str(x) for x in lines[at:]] if at is not None else []


def problems(profile: Path) -> list[dict]:
    """Entries me3 would refuse or skip: [{name, kind, problems}]."""
    items = mod_manage.entries(Path(profile))
    found = checks.entry_problems(Path(profile), items)
    by_index = {e["index"]: e for e in items}
    return [
        {"name": by_index[i]["name"], "kind": by_index[i]["kind"], "problems": list(p)}
        for i, p in found.items()
        if p and i in by_index
    ]


def overview(profile: Path) -> dict:
    """Everything the Mods page's Load order card and its pill show, from one pass (run it off the UI thread)."""
    from roundtable_souls.mods import locations

    profile = Path(profile)
    out: dict = {"profile": str(profile)}
    try:
        out["health"] = merge.health(profile)
    except Exception as e:  # a broken profile or unreadable record: say nothing rather than guess
        out["health"] = {"state": None, "error": str(e)}
    try:
        scan = profile_tools.scan_conflicts(profile)
        out["scan"] = scan
        out["overlaps"] = classify(profile, scan, locations.get().game_dir())
    except Exception as e:
        out["scan"] = {"error": str(e)}
        out["overlaps"] = {"conflicts": [], "counts": dict.fromkeys(OUTCOMES, 0), "packages": {}}
    try:
        out["rows"] = row_conflicts(profile)
    except Exception:
        out["rows"] = []
    try:
        out["problems"] = problems(profile)
    except Exception:
        out["problems"] = []
    try:
        from roundtable_souls.mods import stay_last

        out["stay_last"] = stay_last.status(profile)
    except Exception:
        out["stay_last"] = None
    try:
        out["tool_backups"] = merge.tool_backups(profile) if merge.is_elden_ring(profile) else []
    except Exception:
        out["tool_backups"] = []
    return out
