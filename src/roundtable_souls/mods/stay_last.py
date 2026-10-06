"""Keeping the mod that must stay last (mods.merge.overlay: a package whose rebuild tool folds the others into it)
after every other mod, however mods are added.

The launcher changes only that mod's own entries: its package's load_after lists every other package, and each of
its DLLs (other than load_early ones) lists every other DLL. Every entry is listed, switched off or not, and each as
optional, so switching a mod on or off never rewrites the file. Entries of the profile's other mods are never
touched. A load_early DLL is not added (it loads in another phase), but one already listed stays.

Kept after it on purpose (an exception): an entry whose own load_after names that mod (or that it names in its
load_before), and the names in after_overlay in roundtable.json (see mods.profile_settings, "Keep it after").

reconcile() works on the text about to be written and is called where the launcher changes a profile: install,
remove, add existing, saved options. If the result would make the load order loop, nothing of it is used and the
reason is returned. status() says what loads after it without being kept there on purpose, for the Load order card
and its [Fix order]; fix() writes the reconciled profile.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from roundtable_souls.mods import checks
from roundtable_souls.mods import profile_edit as mod_manage
from roundtable_souls.mods.profile_settings import Unreadable  # noqa: F401  (keep_after raises it)

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations


def target(profile: Path, loc: Locations | None = None) -> dict | None:
    """The mod that must stay last, as the profile on disk has it: {folder, own, name}, own being the folders its
    DLLs live in (its rebuild tool's own folders, or the folder holding its package when no tool was found). None
    when the profile has none (then nothing is ever touched). loc: the game's locations (None:
    rebuild.elden_ring_locations())."""
    from roundtable_souls.mods import rebuild as merge

    profile = Path(profile)
    try:
        if not profile.is_file() or not merge.is_elden_ring(profile):
            return None
        layer, tool, _by_hand = merge.overlay(profile, loc=loc or merge.elden_ring_locations())
    except OSError, ValueError:
        return None
    if layer is None:
        return None
    folder = Path(layer["folder"])
    own = list(tool.own_folders()) if tool is not None else []
    if not own:
        text = mod_manage.read_text(profile)
        if mod_manage.is_array_form(text):
            text = mod_manage.to_blocks(text)
        pk_root, nt_root = mod_manage.roots(profile, text)
        parent = folder.parent
        common = (profile.parent, pk_root, nt_root)
        if not any(checks.same_folder(parent, c) for c in common):
            own = [parent]  # NightreignRevive/mod: its DLLs sit in NightreignRevive
    return {"folder": folder, "own": own, "name": layer["name"]}


def exceptions(profile: Path) -> set[str]:
    """Names (lower-case) kept after the mod that must stay last with Keep it after (roundtable.json)."""
    from roundtable_souls.mods import profile_settings

    return {str(x).lower() for x in profile_settings.load(profile).get("after_overlay") or []}


def keep_after(profile: Path, names: list[str], keep: bool = True) -> None:
    """Add names to (or with keep=False, take them out of) the entries kept after it on purpose."""
    from roundtable_souls.mods import profile_settings

    have = [str(x) for x in profile_settings.load(profile).get("after_overlay") or []]
    low = {n.lower() for n in names}
    if keep:
        new = have + [n for n in names if n.lower() not in {h.lower() for h in have}]
    else:
        new = [h for h in have if h.lower() not in low]
    profile_settings.update(profile, after_overlay=new or None)


# ----------------------------------------------------------------------------- reading the text
def _items(profile: Path, text: str) -> list[dict]:
    out = []
    for b in mod_manage.blocks(text):
        o = mod_manage.block_options(text, b["index"])
        o["index"] = b["index"]
        o["name"] = o["id"] or Path(o["path"]).name or f"entry {b['index'] + 1}"
        out.append(o)
    return out


def _roles(profile: Path, items: list[dict], tgt: dict) -> tuple[dict | None, list[dict], list[dict]]:
    """(its package entry, its DLL entries that must load last, every DLL entry of its own) in this text."""
    pkg = next(
        (
            e
            for e in items
            if e["kind"] == "package"
            and e["path"]
            and checks.same_folder(mod_manage.resolve(profile, e["path"]), tgt["folder"])
        ),
        None,
    )
    mine = [
        e
        for e in items
        if e["kind"] == "native"
        and e["path"]
        and any(checks._within(mod_manage.resolve(profile, e["path"]), o) for o in tgt["own"])
    ]
    return pkg, [e for e in mine if not e.get("load_early")], mine


def _kept_after(owner: dict, others: list[dict], skip: set[str]) -> set[str]:
    """Names of the entries kept after owner on purpose: in after_overlay, naming owner in their load_after, or
    named in owner's load_before."""
    ref = mod_manage.entry_ref(owner).lower()
    out = set(skip)
    for o in others:
        if any(str(d["id"]).lower() == ref for d in o.get("load_after") or []):
            out.add(mod_manage.entry_ref(o).lower())
    out |= {str(d["id"]).lower() for d in owner.get("load_before") or []}
    return out


def _wanted(owner: dict, others: list[dict], skip: set[str], renamed: dict[str, str]) -> list[dict]:
    """owner's load_after as it should be: what it lists now (renamed ids followed) that is still in the profile and
    not kept after it, then every other entry not listed yet, in file order, each optional."""
    present = {mod_manage.entry_ref(o).lower(): mod_manage.entry_ref(o) for o in others}
    after = _kept_after(owner, others, skip)
    keep, seen = [], set()
    for d in owner.get("load_after") or []:
        ident = renamed.get(str(d["id"]).lower(), str(d["id"]))
        low = ident.lower()
        if low in present and low not in after and low not in seen:
            keep.append({"id": ident, "optional": bool(d.get("optional", False))})
            seen.add(low)
    for o in others:
        low = mod_manage.entry_ref(o).lower()
        if low in seen or low in after:
            continue
        if o["kind"] == "native" and o.get("load_early"):
            continue
        keep.append({"id": present[low], "optional": True})
        seen.add(low)
    return keep


def _same_list(a: list[dict], b: list[dict]) -> bool:
    return [(str(d["id"]), bool(d.get("optional", False))) for d in a] == [
        (str(d["id"]), bool(d.get("optional", False))) for d in b
    ]


def _loops(profile: Path, text: str) -> set[str]:
    items = _items(profile, text)
    found = checks.entry_problems(profile, items)
    return {p for ps in found.values() for p in ps if p.startswith("Load order loops")}


def reconcile(
    profile: Path,
    text: str,
    tgt: dict | None = None,
    renamed: dict[str, str] | None = None,
    loc: Locations | None = None,
) -> tuple[str, str | None]:
    """The text with the mod that must stay last listed after everything else (see the module notes), and None; or
    the text unchanged and why, when the result would loop. tgt: target() of the profile before this change (found
    again, with loc, when not given). renamed: {old name (lower-case): new name} for an id just changed."""
    profile = Path(profile)
    tgt = target(profile, loc) if tgt is None else tgt
    if not tgt:
        return text, None
    base = mod_manage.to_blocks(text) if mod_manage.is_array_form(text) else text
    items = _items(profile, base)
    pkg, last_natives, mine = _roles(profile, items, tgt)
    if pkg is None:
        return text, None  # it is not in this profile any more (being removed)
    skip = exceptions(profile)
    renamed = {k.lower(): v for k, v in (renamed or {}).items()}
    out = base
    mine_idx = {e["index"] for e in mine}
    for owner in [pkg, *last_natives]:
        others = [
            e
            for e in items
            if e["kind"] == owner["kind"] and e["index"] != owner["index"] and e["index"] not in mine_idx and e["path"]
        ]
        want = _wanted(owner, others, skip, renamed)
        if not _same_list(want, owner.get("load_after") or []):
            out = mod_manage.set_block_options(out, owner["index"], {"load_after": want})
    if out == base:
        return text, None
    new_loops = _loops(profile, out) - _loops(profile, base)
    if new_loops:
        return text, (
            f"{tgt['name']} was not put last: {sorted(new_loops)[0].replace('Load order loops', 'the load order would loop')}. "
            "Check the Load after and Load before lists in Options."
        )
    return out, None


# ----------------------------------------------------------------------------- what the Load order card shows
def _order(profile: Path, rows: list[dict]) -> list[str]:
    """The enabled entries' names (lower-case) in the order me3 loads them (mods.order)."""
    from roundtable_souls.mods import order

    ordered = order.order_rows(rows, Path(profile).parent, lambda r: mod_manage.resolve(profile, r["path"]).exists())
    return [r["id"].lower() for r in ordered.rows]


def _rows(items: list[dict], kind: str) -> list[dict]:
    """Every entry of one kind (switched-off ones too: me3 orders them, then leaves them out), with the id me3 uses:
    a package's id (its path when it has none), a native's DLL file name."""
    from roundtable_souls.mods.profile import _dependents

    out = []
    for e in items:
        if e["kind"] != kind or not e["path"]:
            continue
        me3_id = (e.get("id") or None) if kind == "package" else Path(e["path"]).name
        out.append(
            {
                "index": e["index"],
                "id": mod_manage.entry_ref(e),
                "me3_id": me3_id,
                "path": e["path"],
                "enabled": e.get("enabled", True) is not False,
                "after": _dependents(e.get("load_after")),
                "before": _dependents(e.get("load_before")),
            }
        )
    return out


def status(profile: Path, *, loc: Locations) -> dict | None:
    """{name, late, kept, kept_setting, can_fix, problem} for the Load order card, or None when there is no mod
    that must stay last. late: enabled entries that load after it without being kept there on purpose (they replace
    its files); kept: the ones kept after it on purpose, kept_setting those of them kept by Keep it after
    (roundtable.json); can_fix: fix() would change the file; problem: why it cannot."""
    profile = Path(profile)
    tgt = target(profile, loc)
    if not tgt:
        return None
    text = mod_manage.read_text(profile)
    base = mod_manage.to_blocks(text) if mod_manage.is_array_form(text) else text
    items = _items(profile, base)
    pkg, last_natives, mine = _roles(profile, items, tgt)
    if pkg is None:
        return None
    skip = exceptions(profile)
    mine_idx = {e["index"] for e in mine}
    late, kept = [], []
    for owner in [pkg, *last_natives]:
        others = [
            e
            for e in items
            if e["kind"] == owner["kind"] and e["index"] not in mine_idx and e["index"] != owner["index"]
        ]
        after = _kept_after(owner, others, skip)
        order = _order(profile, _rows(items, owner["kind"]))
        ref = mod_manage.entry_ref(owner).lower()
        if ref not in order:
            continue  # switched off
        at = order.index(ref)
        names = {mod_manage.entry_ref(o).lower(): o for o in others}
        for low in order[at + 1 :]:
            o = names.get(low)
            if o is None or o.get("load_early"):
                continue  # a load_early DLL loads in an earlier phase, wherever it is listed
            (kept if low in after else late).append(o["name"])
        kept += [o["name"] for o in others if mod_manage.entry_ref(o).lower() in after and o["name"] not in kept]
    fixed, problem = reconcile(profile, text, tgt)
    kept_setting = list(
        dict.fromkeys(mod_manage.entry_ref(e) for e in items if mod_manage.entry_ref(e).lower() in skip)
    )
    return {
        "name": tgt["name"],
        "late": list(dict.fromkeys(late)),
        "kept": list(dict.fromkeys(kept)),
        "kept_setting": kept_setting,
        "can_fix": fixed != text,
        "problem": problem,
    }


def fix(profile: Path, *, loc: Locations) -> str | None:
    """Write the profile with the mod that must stay last put after everything else. Returns why it could not, or
    None (also when there was nothing to change)."""
    profile = Path(profile)
    text = mod_manage.read_text(profile)
    new, problem = reconcile(profile, text, loc=loc)
    if problem:
        return problem
    if new != text:
        mod_manage._write(profile, new, "before fixing the load order")
    return None
