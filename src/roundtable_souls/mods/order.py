# me3's load order, ported from me3 (https://github.com/garyttierney/me3) at commit
# 9b1e080bcf691608021e7bd8a4447198a2dcb94c: `sort_dependencies` in crates/mod-protocol/src/dependency.rs, and how
# crates/cli/src/db/profile.rs (`compile`) applies it to a profile's packages and natives. The ordering code is the
# same in me3 releases 0.11.0, 0.12.0, 0.12.1 and 0.13.0. me3 is dual-licensed MIT OR Apache-2.0; this port is used
# under the MIT license (see THIRD_PARTY_NOTICES.md). Copyright (c) the me3 contributors.
#
# Ported for Roundtable Souls, 2026-10-01: the same steps in the same order, including the details that decide ties
# (insertion order of the dependency graph, the first ready entry, how dependency runs are kept in Rust's
# BinaryHeap and spliced back between the other entries, and the heap's own order for the runs left at the end).
# Checked against me3's own code with a Rust harness on generated profiles; the expected results are kept in
# tests/unit/order_cases.json.

"""The order me3 loads a profile's packages (and natives) in: the later one wins a file both ship.

me3 keeps the profile's order, except that an entry with dependencies (load_after, load_before) is moved as part of
a "run" of linked entries, placed after the entries listed before the first entry of the run that has no
dependencies of its own. Disabled entries take part in ordering and are dropped afterwards; entries whose folder
does not exist are dropped first. A missing dependency that is not optional, or a cycle, makes me3 refuse to start.

The mod that must stay last (the second part of this module, formerly mods.stay_last):

Keeping the mod that must stay last (mods.merge.overlay: a package whose rebuild tool folds the others into it)
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

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from roundtable_souls.mods import checks
from roundtable_souls.mods import profile_edit as mod_manage
from roundtable_souls.mods.profile_settings import Unreadable  # noqa: F401  (keep_after raises it)

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations

ME3_ORDER_VERSIONS = ("0.11.0", "0.12.0", "0.12.1", "0.13.0")  # releases whose ordering code was compared
ME3_ORDER_SINCE = (0, 11, 0)


@dataclass(frozen=True)
class Dependent:
    """One load_after / load_before entry: the id it names, and whether me3 may go on without it."""

    id: str
    optional: bool


@dataclass
class Item:
    id: str
    loads_after: list[Dependent] = field(default_factory=list)
    loads_before: list[Dependent] = field(default_factory=list)
    value: Any = None  # what the caller ordered (a profile row)


class OrderError(ValueError):
    """me3 would refuse this profile."""


class MissingDependency(OrderError):
    def __init__(self, ident: str):
        self.id = ident
        super().__init__(f"Required dependency is unavailable: {ident}")


class Cyclic(OrderError):
    def __init__(self, ids: list[str]):
        self.ids = ids
        super().__init__(f"Dependencies resulted in cycles, remaining dependencies: {_rust_debug(ids)}")


def _rust_debug(ids: list[str]) -> str:
    """A list of strings as Rust's Debug prints it (me3's error text)."""
    quoted = (s.replace("\\", "\\\\").replace('"', '\\"') for s in ids)
    return "[" + ", ".join(f'"{s}"' for s in quoted) + "]"


# ----------------------------------------------------------------------------- the dependency graph
@dataclass
class _Node:
    num_prec: int = 0
    succ: set[str] = field(default_factory=set)


def _add_dependency(sorter: dict[str, _Node], prec: str, succ: str) -> None:
    node = sorter.get(prec)
    if node is None:
        sorter[prec] = _Node(0, {succ})
    else:
        if succ in node.succ:
            return  # already registered
        node.succ.add(succ)
    target = sorter.get(succ)
    if target is None:
        sorter[succ] = _Node(1, set())
    else:
        target.num_prec += 1


def _pop_dependency(sorter: dict[str, _Node]) -> tuple[str, bool] | None:
    key = next((k for k, v in sorter.items() if v.num_prec == 0), None)
    if key is None:
        return None
    node = sorter.pop(key)  # dict deletion keeps the others' order, as IndexMap::shift_remove
    for s in node.succ:
        if s in sorter:
            sorter[s].num_prec -= 1
    return key, bool(node.succ)


# ----------------------------------------------------------------------------- dependency runs in a Rust BinaryHeap
@dataclass
class _Run:
    max_index: int = 0
    dependencies: list[Item] = field(default_factory=list)


def _le(a: _Run, b: _Run) -> bool:
    """a <= b under DependencyRun's Ord, which is reversed (other.max_index.cmp(self.max_index)): a min-heap."""
    return b.max_index <= a.max_index


class _RustHeap:
    """std::collections::BinaryHeap: the same sift steps, so equal runs come out (and stay) where Rust puts them."""

    def __init__(self) -> None:
        self.data: list[_Run] = []

    def push(self, item: _Run) -> None:
        old_len = len(self.data)
        self.data.append(item)
        self._sift_up(0, old_len)

    def peek(self) -> _Run | None:
        return self.data[0] if self.data else None

    def pop(self) -> _Run | None:
        if not self.data:
            return None
        item = self.data.pop()
        if self.data:
            item, self.data[0] = self.data[0], item
            self._sift_down_to_bottom(0)
        return item

    def _sift_up(self, start: int, pos: int) -> int:
        data = self.data
        element = data[pos]
        while pos > start:
            parent = (pos - 1) // 2
            if _le(element, data[parent]):
                break
            data[pos] = data[parent]
            pos = parent
        data[pos] = element
        return pos

    def _sift_down_to_bottom(self, pos: int) -> None:
        data = self.data
        end = len(data)
        start = pos
        element = data[pos]
        child = 2 * pos + 1
        while child <= max(end - 2, 0):
            if _le(data[child], data[child + 1]):
                child += 1
            data[pos] = data[child]
            pos = child
            child = 2 * pos + 1
        if child == end - 1:
            data[pos] = data[child]
            pos = child
        data[pos] = element
        self._sift_up(start, pos)


# ----------------------------------------------------------------------------- sort_dependencies
def sort_dependencies(items: list[Item]) -> list[Item]:
    """me3's sort_dependencies. Raises MissingDependency or Cyclic where me3 returns its errors."""
    every: dict[str, tuple[Item, int]] = {}
    for index, item in enumerate(items):
        every[item.id] = (item, index)  # a repeated id keeps the first position and the last entry, as IndexMap

    sorter: dict[str, _Node] = {}
    for ident, (item, _index) in every.items():
        links = [(d, "after") for d in item.loads_after] + [(d, "before") for d in item.loads_before]
        for dep, order in links:
            if dep.id not in every:
                if not dep.optional:
                    raise MissingDependency(dep.id)
                continue
            prec, succ = (ident, dep.id) if order == "before" else (dep.id, ident)
            _add_dependency(sorter, prec, succ)

    runs = _RustHeap()
    current = _Run()
    max_index: int | None = None
    while (popped := _pop_dependency(sorter)) is not None:
        key, has_succ = popped
        item, index = every.pop(key)
        if max_index is None and not item.loads_after and not item.loads_before:
            max_index = index
        current.dependencies.append(item)
        if not has_succ:
            current.max_index = max_index if max_index is not None else index
            max_index = None
            runs.push(current)
            current = _Run()

    if sorter:
        raise Cyclic(list(every))

    out: list[Item] = []
    for item, index in every.values():
        top = runs.peek()
        if top is not None and top.max_index < index:
            run = runs.pop()
            assert run is not None
            out.extend(run.dependencies)
        out.append(item)
    for run in runs.data:  # what is left, in the heap's own order (Rust's into_iter)
        out.extend(run.dependencies)
    return out


# ----------------------------------------------------------------------------- a profile's packages
def me3_path_id(base: Path | None, path: str) -> str:
    """The id me3 gives a package without one: its path made absolute against the profile's folder, as Rust's
    PathBuf::join writes it (the separators in the profile are kept)."""
    if base is None or Path(path).is_absolute():
        return path
    text = str(base)
    return text + ("" if text.endswith(("\\", "/")) else os.sep) + path


@dataclass
class Ordered:
    rows: list[dict]  # the enabled entries, in me3's order (or in file order when me3 would refuse)
    problem: str | None = None  # why me3 would refuse to start with this profile
    dropped: list[dict] = field(default_factory=list)  # entries me3 skips: folder not found


def order_rows(rows: Iterable[dict], base: Path | None = None, exists: Callable[[dict], bool] | None = None) -> Ordered:
    """Order profile rows as me3 does. A row: {id: me3 id or None, path, enabled, after: [Dependent],
    before: [Dependent], ...}; it is returned as it was given. exists: whether a row's folder is there (me3 drops
    the others before ordering); by default every row is kept."""
    rows = list(rows)
    kept, dropped = [], []
    for row in rows:
        (kept if exists is None or exists(row) else dropped).append(row)
    items = [
        Item(row.get("me3_id") or me3_path_id(base, row["path"]), row.get("after", []), row.get("before", []), row)
        for row in kept
    ]
    try:
        ordered = [item.value for item in sort_dependencies(items)]
    except OrderError as e:
        return Ordered([r for r in kept if r.get("enabled", True)], str(e), dropped)
    return Ordered([r for r in ordered if r.get("enabled", True)], None, dropped)


def supported(version: str | None) -> bool | None:
    """Whether this port is known to match a me3 version's ordering: True for 0.11.0 and later (the code compared is
    the same there); None otherwise (an earlier version, whose ordering was not compared, or an unknown one)."""
    if not version:
        return None
    digits = []
    for part in version.strip().lstrip("v").split("-")[0].split("+")[0].split(".")[:3]:
        if not part.isdigit():
            return None
        digits.append(int(part))
    while len(digits) < 3:
        digits.append(0)
    return True if tuple(digits) >= ME3_ORDER_SINCE else None


# ----------------------------------------------------------------------------- the mod that must stay last (formerly mods.stay_last)
def target(profile: Path, loc: Locations) -> dict | None:
    """The mod that must stay last, as the profile on disk has it: {folder, own, name}, own being the folders its
    DLLs live in (its rebuild tool's own folders, or the folder holding its package when no tool was found). None
    when the profile has none (then nothing is ever touched). loc: the game's locations."""
    from roundtable_souls.mods import rebuild as merge

    profile = Path(profile)
    try:
        if not profile.is_file() or not merge.is_elden_ring(profile):
            return None
        layer, tool, _by_hand = merge.overlay(profile, loc=loc)
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
    if tgt is None:
        if loc is None:
            raise TypeError("reconcile() needs tgt or loc")
        tgt = target(profile, loc)
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
    ordered = order_rows(rows, Path(profile).parent, lambda r: mod_manage.resolve(profile, r["path"]).exists())
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
