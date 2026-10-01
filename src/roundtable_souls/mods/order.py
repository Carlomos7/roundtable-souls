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
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
