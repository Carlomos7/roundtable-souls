"""One writer for every change the launcher makes to a me3 profile, and the rules every change follows.

A ProfileWriter reads the profile once and remembers its exact bytes. Its edit methods change only the text it holds,
with the text surgery of mods.profile_edit (the changed lines, with the comments and formatting around them kept; a
profile is never regenerated from parsed TOML). plan() runs the rules over the proposed change and returns a Plan: the
new text, what changed, notes, and the refusals; nothing is written. commit() writes it: the history copy
(mods.history) and the .bak first, then the text in one atomic replace; or, inside an operation (mods.operations), as
one of the operation's journal steps, so it changes together with the rest.

The rules are plug-ins of one interface (ProfileRule), run in a fixed order on every plan:

    UnchangedSinceRead     the file on disk still holds the bytes that were read: checked when planning, again right
                           before the replace, and inside an operation by the journal before its file step; else
                           refused ("the profile changed outside the launcher; reload and try again")
    Safety                 the history copy and the .bak before every write
    StayLast               the mod that must stay last kept after everything else (mods.order.reconcile)
    SharedDependencyGuard  a shared dependency (a game's co-op DLL) is never removed or switched off as a side effect
                           of a change aimed at something else
    ValidForMe3            what me3 refuses to start with: a package id used twice, a load order loop, a required
                           dependency that is missing; and two switched-on DLLs with the same file name
    Requires               a mod's declared dependencies stay present and switched on (Requirements holds the data;
                           by default the overhaul configs' requires lists, for the entries each overhaul owns)
    Paths                  entries the launcher adds get paths relative to the profile, short enough for Windows

A rule refuses only what the change itself introduces: a problem the profile already had is noted (Plan.notes), not
a reason to refuse every later edit. A verbatim change (the whole text as the player saved it in the editor, an
earlier version put back) goes through Safety and UnchangedSinceRead only.

Entries are addressed by block index, as mods.profile_edit addresses them; removing one shifts the indexes after it,
so several removals go from the highest index down. A profile in the inline-array form is converted to blocks by the
first edit of an entry (that form has no comments to lose), as every such edit did before; a setting changed on its
own leaves the form as it is.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from roundtable_souls import overhauls
from roundtable_souls.formats import me3_profile
from roundtable_souls.game import catalog as games
from roundtable_souls.mods import checks, history, naming, profile_edit
from roundtable_souls.mods import order as mod_order
from roundtable_souls.mods.profile_edit import ModError
from roundtable_souls.platform import files

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations
    from roundtable_souls.merging.build import Operation

CHANGED_OUTSIDE = "the profile changed outside the launcher; reload and try again"
STANDALONE_LOCK_WAIT = 5.0  # seconds a write outside an operation waits for another window's operation to finish


# ----------------------------------------------------------------------------- what a plan holds
@dataclass(frozen=True)
class Refusal:
    rule: str
    message: str


@dataclass
class Change:
    """One edit made through the writer. action: add, remove, options, setting, block or text. path: the entry's
    path as the profile had it when the edit was made (what a rule matches entries by; indexes shift)."""

    action: str
    kind: str = ""
    index: int | None = None
    path: str = ""
    row: dict = field(default_factory=dict)  # add: the entry; options: the options set; setting: {key: value}
    before: dict = field(default_factory=dict)  # options: the entry's options before the edit
    deepest: int = 0  # add: the longest file path inside the entry's folder, in characters, when known


class Refused(ModError):
    """A plan a rule refused; nothing was written."""

    def __init__(self, refusals: Sequence[Refusal]):
        self.refusals = list(refusals)
        super().__init__("; ".join(r.message for r in self.refusals))


@dataclass
class Plan:
    """A proposed change: the text to write, what changed, and what the rules said. ok: no rule refused it."""

    profile: Path
    why: str
    read: bytes  # the bytes read; b"" when the profile did not exist
    existed: bool
    before: str  # the text as read (converted to blocks when it was in the inline-array form)
    text: str  # the text to write
    changes: list[Change]
    verbatim: bool = False
    data: bytes | None = None  # exact bytes to write instead of text (an earlier version put back)
    loc: Locations | None = None
    target: dict | None = None  # the mod that must stay last, as the profile was before the change
    refusals: list[Refusal] = field(default_factory=list)
    notes: dict[str, Any] = field(default_factory=dict)  # order_problem; problems the profile already had
    snapshot: Path | None = None  # after commit: the history copy taken first
    backup: Path | None = None  # after commit: the .bak
    written: bool = False
    _entries: dict[str, list[dict]] = field(default_factory=dict, repr=False)

    @property
    def ok(self) -> bool:
        return not self.refusals

    @property
    def bytes_to_write(self) -> bytes:
        return self.data if self.data is not None else self.text.encode("utf-8")

    def entries(self) -> list[dict]:
        """The entries the text to write holds (formats.me3_profile.entries)."""
        return self._cached("after", self.text)

    def entries_before(self) -> list[dict]:
        return self._cached("before", self.before)

    def _cached(self, key: str, text: str) -> list[dict]:
        if key not in self._entries:
            try:
                self._entries[key] = me3_profile.entries(text)
            except ValueError:  # a text that does not parse at all (a verbatim save): nothing to look at
                self._entries[key] = []
        return self._entries[key]


# ----------------------------------------------------------------------------- the rule interface
class ProfileRule:
    """One rule every write follows. adjust() may change the plan's text and add notes; check() returns the
    refusals it finds; before_write() runs at commit, right before the bytes go, and may refuse. A rule applies to a
    verbatim change only when it says so."""

    name = "rule"
    verbatim = False

    def adjust(self, plan: Plan) -> None:
        return None

    def check(self, plan: Plan) -> list[Refusal]:
        return []

    def before_write(self, plan: Plan) -> Refusal | None:
        return None


class Safety(ProfileRule):
    """The history copy (mods.history) and the .bak beside the profile, before every write of a profile that exists.
    The write itself is atomic (one replace), or one step of an operation's journal."""

    name = "safety"
    verbatim = True

    def before_write(self, plan: Plan) -> Refusal | None:
        if not plan.existed:
            return None
        plan.snapshot = history.snapshot(plan.profile, plan.why)
        bak = plan.profile.with_name(plan.profile.name + ".bak")
        shutil.copy2(plan.profile, bak)
        plan.backup = bak
        return None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class UnchangedSinceRead(ProfileRule):
    """The file still holds the bytes the writer read. An edit saved by a text editor or another tool since would be
    overwritten without a word otherwise. Windows has no compare-and-swap, so this is a check right before the
    replace (the window is the replace itself); inside an operation the journal checks again before its file step."""

    name = "unchanged-since-read"
    verbatim = True

    def check(self, plan: Plan) -> list[Refusal]:
        found = self._refusal(plan)
        return [found] if found else []

    def before_write(self, plan: Plan) -> Refusal | None:
        return self._refusal(plan)

    def _refusal(self, plan: Plan) -> Refusal | None:
        exists = plan.profile.is_file()
        if not plan.existed:
            return Refusal(self.name, f"{plan.profile.name} already exists") if exists else None
        if not exists:
            return Refusal(self.name, CHANGED_OUTSIDE)
        if plan.profile.read_bytes() != plan.read:
            return Refusal(self.name, CHANGED_OUTSIDE)
        return None


class StayLast(ProfileRule):
    """The mod that must stay last (mods.order) listed after everything else: its own load order lists are brought
    up to date in the text about to be written. When that would make the load order loop, the lists are left and the
    reason is noted (order_problem), as before. Needs the game's locations: without them nothing is touched."""

    name = "stay-last"

    def adjust(self, plan: Plan) -> None:
        if plan.target is None:
            return
        renamed = {}
        for c in plan.changes:
            if c.action == "options" and c.kind == "package":
                old, new = c.before.get("id"), c.row.get("id")
                if old and new and new != old:
                    renamed[str(old).lower()] = str(new)
        text, problem = mod_order.reconcile(plan.profile, plan.text, plan.target, renamed)
        plan.text = text
        if problem:
            plan.notes["order_problem"] = problem


def _native_name(entry: dict) -> str:
    return Path(entry.get("path") or "").name.lower()


def _norm(path: str) -> str:
    return str(path).replace("\\", "/").lower()


class SharedDependencyGuard(ProfileRule):
    """A shared dependency, a DLL other mods need (a game's co-op DLL: Seamless Co-op), is never removed or switched
    off as a side effect: only a change aimed at that entry itself may. shared: the DLL file names, lower-case."""

    name = "shared-dependency"

    def __init__(self, shared: Iterable[str] | None = None):
        self.shared = {s.lower() for s in shared} if shared is not None else None

    def names(self) -> set[str]:
        if self.shared is not None:
            return self.shared
        return {g.coop_dll.lower() for g in games.GAMES if g.coop_dll}

    def check(self, plan: Plan) -> list[Refusal]:
        shared = self.names()
        if not shared:
            return []
        on = lambda entries: {
            _norm(e["path"]): e for e in entries if e["kind"] == "native" and e["enabled"] and _native_name(e) in shared
        }
        before, after = on(plan.entries_before()), on(plan.entries())
        aimed = {_norm(c.path) for c in plan.changes if c.path}
        out = []
        for path, e in before.items():
            if path in after or path in aimed:
                continue
            out.append(
                Refusal(
                    self.name,
                    f"{e['name']} is a shared dependency and stays switched on; this change would "
                    f"{'remove it' if not any(_norm(x['path']) == path for x in plan.entries()) else 'switch it off'} "
                    "as a side effect",
                )
            )
        return out


_REFUSED_BY_ME3 = ("Id '", "Load order loops", "Must load ")


class ValidForMe3(ProfileRule):
    """What me3 refuses to start with (mods.checks.entry_problems): a package id used twice, a load order loop, a
    required dependency that is not there; and, since me3 refers to DLLs by file name, two switched-on DLLs with the
    same file name. Only problems the change introduces are refused; the ones the profile already had are noted."""

    name = "valid-for-me3"

    def check(self, plan: Plan) -> list[Refusal]:
        before = self._problems(plan.profile, plan.entries_before())
        after = self._problems(plan.profile, plan.entries())
        kept = sorted(after & before)
        if kept:
            plan.notes["problems"] = kept
        return [Refusal(self.name, p) for p in sorted(after - before)]

    @staticmethod
    def _problems(profile: Path, entries: list[dict]) -> set[str]:
        found: set[str] = set()
        for problems in checks.entry_problems(profile, entries).values():
            for p in problems:
                if p.startswith(_REFUSED_BY_ME3):
                    found.add(p if p.startswith(("Id '", "Must load ")) else p + "; me3 would not start")
        by_name: dict[str, list[dict]] = {}
        for e in entries:
            if e["kind"] == "native" and e["enabled"] and e.get("path"):
                by_name.setdefault(_native_name(e), []).append(e)
        for same in by_name.values():
            if len(same) > 1:
                paths = " and ".join(e["path"] for e in same)
                found.add(
                    f"Two switched-on DLLs are named {Path(same[0]['path']).name} ({paths}); me3 refers to DLLs by "
                    "file name, so only one can be on"
                )
        return found


@dataclass(frozen=True)
class Requirement:
    """What one mod needs in the profile: an entry of this kind (a native's DLL file name, a package's id), present
    and switched on."""

    kind: str
    name: str


class Requirements(Protocol):
    """Where the Requires rule reads a mod's declared dependencies from (an overhaul config, say)."""

    def of(self, entry: dict) -> list[Requirement]:
        """What this entry (formats.me3_profile.entries) requires; [] when nothing is known about it."""
        ...


class NoRequirements:
    def of(self, entry: dict) -> list[Requirement]:
        return []


class StaticRequirements:
    """Requirements by entry name (a package's id or a DLL's file name, case aside)."""

    def __init__(self, table: dict[str, Sequence[Requirement]]):
        self.table = {k.lower(): list(v) for k, v in table.items()}

    def of(self, entry: dict) -> list[Requirement]:
        return list(self.table.get(me3_profile.entry_ref(entry).lower(), ()))


class OverhaulRequirements:
    """Requirements from the overhaul configs (overhauls.load): an entry an overhaul owns (its package ids, its DLL
    file names) needs what that edition's requires list names. game: the configs of one game (all when None)."""

    def __init__(self, configs: Sequence[overhauls.OverhaulConfig] | None = None, game: str | None = None):
        self._configs = list(configs) if configs is not None else None
        self.game = game

    @property
    def configs(self) -> list[overhauls.OverhaulConfig]:
        if self._configs is None:
            self._configs = overhauls.load(self.game)
        return self._configs

    def of(self, entry: dict) -> list[Requirement]:
        return [
            Requirement(r.kind, r.name) for r in overhauls.requirements.needed_by(self.configs, entry["kind"], entry)
        ]


class Requires(ProfileRule):
    """A mod's declared dependencies (Requirements) stay present and switched on. Refused when the change removes or
    switches off something a mod that stays on needs, or adds a mod whose needs the profile does not meet."""

    name = "requires"

    def __init__(self, requirements: Requirements | None = None):
        self.requirements = requirements if requirements is not None else OverhaulRequirements()

    def check(self, plan: Plan) -> list[Refusal]:
        before, after = plan.entries_before(), plan.entries()
        unmet_before = self._unmet(before)
        out = []
        for by, need, state in sorted(self._unmet(after) - unmet_before):
            out.append(Refusal(self.name, f"{by} needs {need}, which this change would {state}"))
        return out

    def _unmet(self, entries: list[dict]) -> set[tuple[str, str, str]]:
        present = {(e["kind"], me3_profile.entry_ref(e).lower()): e for e in entries if e.get("path")}
        out = set()
        for e in entries:
            if not e["enabled"]:
                continue
            for req in self.requirements.of(e):
                have = present.get((req.kind, req.name.lower()))
                if have is None:
                    out.add((e["name"], req.name, "leave out of the profile"))
                elif not have["enabled"]:
                    out.add((e["name"], req.name, "leave switched off"))
        return out


class Paths(ProfileRule):
    """Entries the launcher adds point at their files with a path relative to the profile (the writer makes it so
    when it adds them; the player's own entries are left as written), and stay short enough for Windows: the deepest
    file path below the entry must fit in MAX_PATH characters, well under Windows' limit of 260. When the mod's
    files are not known yet, ROOM characters are assumed for them. Both limits are mods.naming's."""

    name = "paths"
    MAX_PATH = naming.MAX_PATH
    ROOM = naming.ROOM

    def check(self, plan: Plan) -> list[Refusal]:
        out = []
        for c in plan.changes:
            if c.action != "add" or not c.row.get("path"):
                continue
            problem = naming.path_problem(me3_profile.resolve(plan.profile, c.row["path"]), c.deepest)
            if problem is not None:
                out.append(Refusal(self.name, problem))
        return out


def default_rules(requirements: Requirements | None = None) -> list[ProfileRule]:
    """The rules in the order they run."""
    return [
        UnchangedSinceRead(),
        Safety(),
        StayLast(),
        SharedDependencyGuard(),
        ValidForMe3(),
        Requires(requirements),
        Paths(),
    ]


# ----------------------------------------------------------------------------- the writer
class ProfileWriter:
    """Every change to one profile: read once, edited in memory, planned under the rules, written once.

        writer = ProfileWriter(profile, loc)
        writer.add_package("grass", folder)
        plan = writer.plan("before installing grass")   # the rules run; nothing is written
        writer.commit(plan)                              # or writer.commit(plan, operation=op)

    loc: the game's locations, for the mod that must stay last (without them that rule does nothing). requirements:
    where the Requires rule reads declared dependencies. rules: the rules to use instead of default_rules()."""

    def __init__(
        self,
        profile: Path,
        loc: Locations | None = None,
        *,
        requirements: Requirements | None = None,
        rules: Sequence[ProfileRule] | None = None,
        missing_ok: bool = False,
    ):
        self.profile = Path(profile)
        self.loc = loc
        self.rules = list(rules) if rules is not None else default_rules(requirements)
        self.existed = self.profile.is_file()
        if not self.existed and not missing_ok:
            raise ModError(f"{self.profile.name} is not there")
        self.read = self.profile.read_bytes() if self.existed else b""
        self.original = self.read.decode("utf-8", errors="replace")
        self.text = self.original
        self.before = self.text
        self.changes: list[Change] = []
        self.verbatim = False
        self.data: bytes | None = None
        self.target = mod_order.target(self.profile, loc) if loc is not None and self.existed else None

    @classmethod
    def create(cls, profile: Path, text: str, **kw) -> ProfileWriter:
        """A writer for a profile that does not exist yet, holding its first text."""
        w = cls(profile, missing_ok=True, **kw)
        if w.existed:
            raise ModError(f"{w.profile.name} already exists")
        w.replace_text(text)
        return w

    # ---------------------------------------------------------------- reading the text as it stands
    def entries(self) -> list[dict]:
        """The entries as the edits so far leave them (formats.me3_profile.entries): 'index' addresses them."""
        return me3_profile.entries(self.as_blocks())

    def find(self, kind: str, name: str) -> int | None:
        """The index of the entry of this kind called name (its id, else its file or folder name), case aside."""
        low = name.lower()
        return next((e["index"] for e in self.entries() if e["kind"] == kind and e["name"].lower() == low), None)

    def options(self, index: int) -> dict:
        return me3_profile.block_options(self.as_blocks(), index)

    # ---------------------------------------------------------------- edits (the text in memory only)
    def add_entry(
        self,
        kind: str,
        row: dict,
        *,
        before: int | None = None,
        after_last: bool = False,
        deepest: int = 0,
    ) -> dict:
        """Add an entry: {id, path, enabled, load_after, ...}, its path a Path (made relative to the profile) or the
        string the profile should hold. It goes above block `before` when given; else above the mod that must stay
        last (a package above its package, a DLL above its first DLL), so the file reads in load order; else at the
        end. after_last keeps it after that mod on purpose: last, naming the mod in its own load_after. deepest: the
        longest file path inside its folder, in characters, for the Paths rule. Returns the entry as added."""
        self.as_blocks()
        row = {**row, "kind": kind, "path": self._relative(row["path"])}
        where = before
        if after_last and self.target is not None:
            owner = self._owner(kind)
            if owner is not None:
                row["load_after"] = [{"id": me3_profile.entry_ref(owner), "optional": True}]
            where = None
        elif where is None:
            where = self._last_place(kind)
        if where is None:
            self.text = profile_edit.append_entry(self.text, kind, row)
        else:
            self.text = profile_edit.insert_entry(self.text, kind, row, where)
        self.changes.append(Change("add", kind, path=row["path"], row=row, deepest=deepest))
        return row

    def add_package(
        self, ident: str, path: Path | str, *, before: int | None = None, after_last=False, deepest=0, **opts
    ) -> dict:
        row = {"id": ident, "path": path, **opts}
        return self.add_entry("package", row, before=before, after_last=after_last, deepest=deepest)

    def add_native(
        self, path: Path | str, *, before: int | None = None, after_last: bool = False, deepest=0, **opts
    ) -> dict:
        return self.add_entry("native", {"path": path, **opts}, before=before, after_last=after_last, deepest=deepest)

    def remove_entry(self, index: int) -> tuple[str, dict]:
        """Take block `index` out with its own comments (profile_edit.remove_entry). Returns (the text taken out,
        where it was), what restore_entry needs to put it back."""
        o = self.options(index)
        self.text, chunk, where = profile_edit.remove_entry(self.as_blocks(), index)
        self.changes.append(Change("remove", o["kind"], index, o["path"], before=o))
        return chunk, where

    def restore_entry(self, chunk: str, where: dict) -> None:
        """Put an entry taken out by remove_entry back where it was (profile_edit.restore_entry)."""
        self.text = profile_edit.restore_entry(self.as_blocks(), chunk, where)
        self.changes.append(Change("add", row={}))

    def set_options(self, index: int, opts: dict) -> None:
        """Rewrite the option keys of one block (profile_edit.set_block_options); keys absent from opts stay."""
        o = self.options(index)
        self.text = profile_edit.set_block_options(self.as_blocks(), index, opts)
        self.changes.append(Change("options", o["kind"], index, o["path"], row=dict(opts), before=o))

    def replace_block(self, index: int, lines: list[str]) -> None:
        """One block's lines replaced as given (an edit profile_edit has no function for)."""
        o = self.options(index)
        b = me3_profile.blocks(self.as_blocks())[index]
        all_lines = self.text.splitlines(keepends=True)
        all_lines[b["start"] : b["end"]] = lines
        self.text = "".join(all_lines)
        self.changes.append(Change("block", o["kind"], index, o["path"], before=o))

    def set_setting(self, key: str, value) -> None:
        """Set, replace or (None) remove one top-level me3 setting (mods.profile.set_setting)."""
        from roundtable_souls.mods import profile as profile_tools

        self.text = profile_tools.set_setting(self.text, key, value)
        self.changes.append(Change("setting", row={key: value}))

    def replace_text(self, text: str) -> None:
        """The whole text, as given (verbatim: the player's own text, or one the caller worked out). Only Safety and
        UnchangedSinceRead apply."""
        self.text = text
        self.data = None
        self.verbatim = True
        self.changes.append(Change("text"))

    def restore_bytes(self, data: bytes) -> None:
        """Exact bytes, as given (verbatim: an earlier version put back)."""
        self.data = data
        self.text = data.decode("utf-8", errors="replace")
        self.verbatim = True
        self.changes.append(Change("text"))

    # ---------------------------------------------------------------- planning and writing
    def plan(self, why: str) -> Plan:
        """Run the rules over the edits so far. Nothing is written; the Plan says what would be, and why not."""
        plan = Plan(
            profile=self.profile,
            why=why,
            read=self.read,
            existed=self.existed,
            before=self.before,
            text=self.text,
            changes=list(self.changes),
            verbatim=self.verbatim,
            data=self.data,
            loc=self.loc,
            target=self.target,
        )
        rules = self._applying(plan)
        for rule in rules:
            rule.adjust(plan)
        for rule in rules:
            plan.refusals.extend(rule.check(plan))
        return plan

    def commit(self, plan: Plan, operation: Operation | None = None) -> Path | None:
        """Write the plan: standalone, as one atomic replace after the history copy and the .bak; or, with
        operation, as a step of its journal (applied when the operation commits, checked again then). Nothing is
        written when the plan was refused (Refused is raised) or when there is nothing to change. Returns the .bak
        (None when nothing was written, or the profile is new)."""
        if plan.refusals:
            raise Refused(plan.refusals)
        data = plan.bytes_to_write
        if not plan.changes and data == plan.read:
            return None
        if operation is not None:  # the operation already holds the folder's lock
            self._before_write(plan)
            operation.write_file(plan.profile, data, expect=_sha256(plan.read) if plan.existed else "missing")
        else:
            from roundtable_souls.merging import build

            # The same lock operations hold, for the last check and the replace: another launcher window can't write
            # this profile in between (a write already inside an operation on this thread just enters).
            with build.ops_lock(plan.profile.parent, timeout=STANDALONE_LOCK_WAIT):
                self._before_write(plan)
                files.atomic_write(plan.profile, data)
        plan.written = True
        return plan.backup

    def _before_write(self, plan: Plan) -> None:
        for rule in self._applying(plan):
            found = rule.before_write(plan)
            if found is not None:
                raise Refused([found])

    def write(self, why: str, operation: Operation | None = None) -> Plan:
        """plan() and commit() in one: the committed plan (raises Refused when a rule refused it)."""
        plan = self.plan(why)
        self.commit(plan, operation)
        return plan

    # ---------------------------------------------------------------- helpers
    def _applying(self, plan: Plan) -> list[ProfileRule]:
        return [r for r in self.rules if r.verbatim or not plan.verbatim]

    def as_blocks(self) -> str:
        """The text as [[packages]] / [[natives]] blocks, converting an inline-array profile once."""
        if me3_profile.is_array_form(self.text):
            self.text = me3_profile.to_blocks(self.text)
        return self.text

    def _relative(self, path: Path | str) -> str:
        if isinstance(path, Path) or Path(path).is_absolute():
            return profile_edit.rel(self.profile, Path(path))
        return str(path).replace("\\", "/")

    def _roles(self) -> tuple[dict | None, list[dict], list[dict]]:
        assert self.target is not None
        items = mod_order._items(self.profile, self.as_blocks())
        return mod_order._roles(self.profile, items, self.target)

    def _last_place(self, kind: str) -> int | None:
        """The block new entries of this kind go above: the package that must stay last, or the first of its DLLs.
        None without one."""
        if self.target is None:
            return None
        pkg, _last, mine = self._roles()
        if kind == "package":
            return pkg["index"] if pkg else None
        return mine[0]["index"] if mine else None

    def _owner(self, kind: str) -> dict | None:
        """The entry of the mod that must stay last that an entry kept after it on purpose names: its package, or
        the first of its DLLs that must load last."""
        pkg, last, _mine = self._roles()
        return pkg if kind == "package" else (last[0] if last else None)
