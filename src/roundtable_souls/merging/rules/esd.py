"""Talk scripts (ESD): merged state by state within a safe envelope; anything outside it is not merged.

What each mod changed is found against the game's own script. A mod's copy is usually the game's script decompiled
and compiled again by a community tool, which writes the same logic differently; those differences are not changes
(see `_simplify` and `_flat`):
    numbers stored another way (an integer in one byte or four, a float as single or double)
    the 'continue if false' and 'return if false' shortcuts (bytes A6 and B7)
    a value kept in a register written out in full where it is used again
    'f() == 1' written 'f()' (except for functions that give other numbers: the chosen menu option), and
    '1 == f()' written 'f() == 1'
    a nested condition whose outer test always passes, or nested conditions written as one 'and'
    conditions with the same target written as one 'or'
The comparison uses these normal forms; the result is built from the stored bytes (the game's states and the mods'
additions as they wrote them).

Merged:
    new state machines (the same machine ID from two mods must be the same machine)
    new states in the game's machines; a new state whose number another mod already uses for a different state gets
    the next free number, and the mod's own references to it follow
    conditions and commands added to a game state, among the game's own; additions by several mods at the same place
    come in load order, and the same addition from two mods is made once
    a game state one mod changed otherwise (that mod's state is used), or that several mods changed the same way
Not merged (the later mod's copy is used whole, with the reason recorded):
    a game state or machine a mod's copy leaves out
    a game state two mods changed differently, or that one changed and another added to
    added conditions or commands that use registers (values one test keeps for another)
    two mods adding the same menu option to one state: a talk list entry (AddTalkListData or its 'if' form) or a test
    of the chosen entry with the same number
    expression bytes the launcher cannot read
States no mod changed are the game's own.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from roundtable_souls import formats
from roundtable_souls.formats.esd import ESD, Command, Condition, State, read_esd, write_esd
from roundtable_souls.merging.changes import Result

SIGNATURE = b"fsSL"
TRUE = ("n", 1)
_COMPARE_OR_LOGIC = range(0x91, 0x9B)  # these give 0 or 1
_BINARY = set(range(0x8C, 0x9A)) - {0x8D, 0x97}  # 0x8D is negation; 0x97 is not known
_REGISTERS = range(0xA7, 0xB7)  # A7-AE keep a value, AF-B6 use it again
_TALK_LIST = {(1, 19): 0, (5, 19): 1}  # AddTalkListData(option, text, -1) and its 'if' form: the option's argument
_CHOSEN_ENTRY = ("n", 23)  # GetTalkListEntryResult(): the option the player chose
_NUMBERS = {_CHOSEN_ENTRY}  # functions giving numbers other than 0 and 1 that are compared with 1 ('== 1' matters)


class Unsupported(Exception):
    """Outside what this rule merges; the message says why."""


def is_esd(body: bytes) -> bool:
    return body[:4] == SIGNATURE


# ----------------------------------------------------------------------------- expressions
def _tokens(code: bytes):
    """(byte, value) for each step of an expression: values for numbers and strings, None for the rest."""
    i, n = 0, len(code)
    try:
        while i < n:
            c = code[i]
            if c <= 0x7F:
                yield c, c - 64
                i += 1
            elif c == 0x80:
                yield c, struct.unpack_from("<f", code, i + 1)[0]
                i += 5
            elif c == 0x81:
                yield c, struct.unpack_from("<d", code, i + 1)[0]
                i += 9
            elif c == 0x82:
                yield c, struct.unpack_from("<i", code, i + 1)[0]
                i += 5
            elif c == 0xA5:
                j = i + 1
                while code[j : j + 2] != b"\0\0":
                    if j + 2 > n:
                        raise Unsupported("an expression has a string without its end")
                    j += 2
                yield c, code[i + 1 : j].decode("utf-16-le")
                i = j + 2
            elif 0x84 <= c <= 0x8A or c == 0x8D or c in _BINARY or c == 0xA1 or 0xA6 <= c <= 0xBA:
                yield c, None
                i += 1
            else:
                raise Unsupported(f"an expression has the byte {c:#04x}, which the launcher cannot read")
    except struct.error as e:
        raise Unsupported(f"an expression ends inside a number ({e})") from e


def _uses_registers(code: bytes) -> bool:
    return any(c in _REGISTERS for c, _ in _tokens(code))


def _expression(code: bytes, registers: dict) -> tuple:
    """The normal form of an expression. `registers`: values kept by earlier tests of the same state, used again."""
    stack: list = []
    try:
        for c, value in _tokens(code):
            if c <= 0x82:
                stack.append(("n", value))
            elif c == 0xA5:
                stack.append(("s", value))
            elif 0x84 <= c <= 0x8A:
                count = c - 0x84
                args = tuple(stack[len(stack) - count :]) if count else ()
                del stack[len(stack) - count :]
                stack.append(("call", stack.pop(), args))
            elif c == 0x8D:
                stack.append(("neg", stack.pop()))
            elif c in _BINARY:
                right, left = stack.pop(), stack.pop()
                stack.append(("op", c, left, right))
            elif c in (0xA1, 0xA6, 0xB7):
                continue
            elif 0xA7 <= c <= 0xAE:
                registers[c - 0xA7] = stack[-1]
            elif 0xAF <= c <= 0xB6:
                stack.append(registers.get(c - 0xAF, ("register", c - 0xAF)))
            elif c == 0xB8:
                stack.append(("machine argument", stack.pop()))
            else:  # B9, BA: the called machine's state
                stack.append(("machine", c))
    except IndexError as e:
        raise Unsupported("an expression uses more values than it has") from e
    if len(stack) != 1:
        raise Unsupported("an expression leaves more than one value")
    return _simplify(stack[0])


def _simplify(e: tuple) -> tuple:
    if e[0] == "op":
        op, left, right = e[1], _simplify(e[2]), _simplify(e[3])
        if op in (0x95, 0x96) and left[0] == "n" and right[0] != "n":
            left, right = right, left
        if op == 0x95 and right == TRUE and (_test(left) or left[0] == "op" and left[1] in _COMPARE_OR_LOGIC):
            return left
        if op == 0x98 and right == TRUE:
            return left
        if op == 0x98 and left == TRUE:
            return right
        return ("op", op, left, right)
    if e[0] == "call":
        return ("call", e[1], tuple(_simplify(a) for a in e[2]))
    if e[0] in ("neg", "machine argument"):
        return (e[0], _simplify(e[1]))
    return e


def _test(e: tuple) -> bool:
    """A call of a function that answers yes or no: every function but those known to give other numbers."""
    return e[0] == "call" and e[1] not in _NUMBERS


def _ors(e: tuple) -> list[tuple]:
    if e[0] == "op" and e[1] == 0x99:
        return _ors(e[2]) + _ors(e[3])
    return [e]


# ----------------------------------------------------------------------------- normal forms of states
def _command(c: Command) -> tuple:
    return (c.bank, c.index, tuple(_expression(bytes(a), {}) for a in c.args))


def _flat(conditions: list[Condition], registers: dict, outer: tuple = TRUE) -> list[tuple[int, tuple]]:
    """(index of the stored condition, normal form) for each condition: nested ones whose outer condition only tests
    are expanded into 'and's, and 'or's are split into conditions of their own."""
    out = []
    for index, c in enumerate(conditions):
        test = _expression(c.test_ezl, registers)
        if outer != TRUE:
            test = outer if test == TRUE else ("op", 0x98, outer, test)
        if c.subconditions and c.next_state_id == -1 and not c.pass_commands:
            out += [(index, item) for _, item in _flat(c.subconditions, registers, test)]
            continue
        passing = tuple(_command(p) for p in c.pass_commands)
        nested = tuple(item for _, item in _flat(c.subconditions, registers)) if c.subconditions else ()
        out += [(index, (part, c.next_state_id, passing, nested)) for part in _ors(test)]
    return out


@dataclass
class _Normal:
    lists: tuple[list[tuple[int, tuple]], ...]  # enter, exit, ongoing commands and conditions: (stored index, form)

    @property
    def key(self) -> tuple:
        return tuple(tuple(form for _, form in items) for items in self.lists)


def _normal(state: State) -> _Normal:
    commands = [[(i, _command(c)) for i, c in enumerate(cs)] for cs in _lists(state)[:3]]
    return _Normal((*commands, _flat(state.conditions, {})))


def _lists(state: State) -> tuple[list, list, list, list]:
    return state.enter_commands, state.exit_commands, state.ongoing_commands, state.conditions


LIST_NAMES = (
    ("command run on entering", "commands run on entering"),
    ("command run on leaving", "commands run on leaving"),
    ("command run each frame", "commands run each frame"),
    ("condition", "conditions"),
)


def _added(base: list[tuple[int, tuple]], mod: list[tuple[int, tuple]], base_count: int):
    """When the mod's list is the base's with whole stored items added between the base's own: (where in the base's
    stored items, index of the mod's stored item) for each; otherwise None."""
    matched, extra = 0, []
    for i, (_, form) in enumerate(mod):
        if matched < len(base) and form == base[matched][1]:
            matched += 1
        else:
            extra.append((matched, i))
    if matched < len(base):
        return None
    by_item: dict[int, set[int]] = {}
    for at, i in extra:
        by_item.setdefault(mod[i][0], set()).add(at)
    out = []
    for stored, places in by_item.items():
        if sum(1 for s, _ in mod if s == stored) != sum(1 for _, i in extra if mod[i][0] == stored) or len(places) > 1:
            return None  # part of one of the mod's stored items matches the base: an edit, not an addition
        at = places.pop()
        if 0 < at < len(base) and base[at - 1][0] == base[at][0]:
            return None  # inside what the base stores as one item
        out.append((base[at][0] if at < len(base) else base_count, stored))
    return out


# ----------------------------------------------------------------------------- copies with other state numbers
def _retarget(state: State, renumber: dict[int, int], state_id: int | None = None) -> State:
    if not renumber and state_id is None:
        return state
    memo: dict[int, Condition] = {}

    def cond(c: Condition) -> Condition:
        if id(c) not in memo:
            memo[id(c)] = Condition(
                renumber.get(c.next_state_id, c.next_state_id),
                c.test_ezl,
                c.pass_commands,
                [cond(s) for s in c.subconditions],
            )
        return memo[id(c)]

    return State(
        state.state_id if state_id is None else state_id,
        [cond(c) for c in state.conditions],
        state.enter_commands,
        state.exit_commands,
        state.ongoing_commands,
    )


# ----------------------------------------------------------------------------- the plan
@dataclass
class _Plan:
    """What happens to one game state."""

    edit: State | None = None  # a mod's own version of it
    edit_key: tuple | None = None
    by: list[str] = field(default_factory=list)
    adds: list[dict[int, list[tuple[str, object, tuple]]]] = field(default_factory=lambda: [{}, {}, {}, {}])


def _item_form(item, is_condition: bool) -> tuple:
    if is_condition:
        return tuple(form for _, form in _flat([item], {}))
    return _command(item)


def _uses_registers_item(item, is_condition: bool) -> bool:
    if not is_condition:
        return any(_uses_registers(bytes(a)) for a in item.args)
    return (
        _uses_registers(item.test_ezl)
        or any(_uses_registers(bytes(a)) for p in item.pass_commands for a in p.args)
        or any(_uses_registers_item(s, True) for s in item.subconditions)
    )


def _options(form: tuple, is_condition: bool) -> set:
    """Menu option numbers an added item uses: a talk list entry's number, or a test of the chosen entry."""
    if not is_condition:
        at = _TALK_LIST.get(form[:2])
        if at is None:
            return set()
        args = form[2]
        return {args[at][1] if at < len(args) and args[at][0] == "n" else "?"}
    found: set = set()

    def walk(e):
        if isinstance(e, tuple) and e and e[0] == "op":
            if e[1] == 0x95 and e[2] == ("call", _CHOSEN_ENTRY, ()):
                found.add(e[3][1] if e[3][0] == "n" else "?")
            walk(e[2])
            walk(e[3])
        elif isinstance(e, tuple) and e and e[0] == "call":
            for a in e[2]:
                walk(a)

    for item in form:
        walk(item[0])
    return found


def merge(base: bytes, bodies: list[tuple[str, bytes]], where: str = "") -> Result:
    """Merge the mods' copies of one talk script (in load order) against the game's. Outside the envelope (see the
    module's description) the later mod's copy is used whole: merged=False, a clash, and the reason in notes."""
    path = where or "/"
    changed = [(label, body) for label, body in bodies if body != base]
    if not changed:
        return Result(base, merged=True)
    try:
        data, changed_by, notes = _merge(base, bodies)
    except (Unsupported, formats.FormatError) as e:
        out = Result(changed[-1][1], merged=False)
        out.changed[path] = [label for label, _ in changed]
        out.clashes[path] = [label for label, _ in changed]
        out.notes[path] = [f"not merged: {e}; {changed[-1][0]}'s copy is used whole"]
        return out
    out = Result(data)
    if changed_by:
        out.changed[path] = changed_by
    if notes:
        out.notes[path] = notes
    return out


def _merge(base: bytes, bodies: list[tuple[str, bytes]]) -> tuple[bytes, list[str], list[str]]:
    game = read_esd(base)
    norms = {(m, s): _normal(st) for m, states in game.state_machines.items() for s, st in states.items()}
    plans: dict[tuple[int, int], _Plan] = {}
    added: dict[int, dict[int, tuple[str, State, tuple]]] = {m: {} for m in game.state_machines}
    machines: dict[int, tuple[str, dict[int, State], dict]] = {}
    notes: list[str] = []
    changed_by: list[str] = []

    for label, body in bodies:
        mod = read_esd(body)
        did = False
        for m, states in game.state_machines.items():
            mine = mod.state_machines.get(m)
            if mine is None:
                raise Unsupported(f"{label}'s copy leaves out state machine {m}")
            gone = [s for s in states if s not in mine]
            if gone:
                raise Unsupported(f"{label}'s copy leaves out state {gone[0]} of state machine {m}")
            renumber = _renumber(m, states, mine, added[m])
            for old, new in renumber.items():
                notes.append(f"machine {m}: {label}'s new state {old} is numbered {new} ({old} was taken)")
            for s, st in states.items():
                theirs = _retarget(mine[s], renumber)
                did |= _apply(label, m, s, st, norms[(m, s)], theirs, plans, notes)
            for s, st in mine.items():
                if s in states:
                    continue
                final = renumber.get(s, s)
                if final in added[m]:
                    continue  # the same state another mod added
                copy = _retarget(st, renumber, final)
                added[m][final] = (label, copy, _normal(copy).key)
                notes.append(f"machine {m}: state {final} added by {label}")
                did = True
        for m, mine in mod.state_machines.items():
            if m in game.state_machines:
                continue
            key = {s: _normal(st).key for s, st in mine.items()}
            if m in machines:
                if machines[m][2] != key:
                    raise Unsupported(f"{machines[m][0]} and {label} both add state machine {m}, differently")
                continue
            machines[m] = (label, mine, key)
            notes.append(f"machine {m} added by {label}")
            did = True
        if did:
            changed_by.append(label)

    _check_options(plans)
    out = ESD(magic=list(game.magic), esd_name=game.esd_name, state_machines={})
    for m, states in game.state_machines.items():
        result: dict[int, State] = {}
        for s, st in states.items():
            plan = plans.get((m, s))
            if plan is None:
                result[s] = st
            elif plan.edit is not None:
                result[s] = plan.edit
            else:
                lists = [_with_added(items, plan.adds[k]) for k, items in enumerate(_lists(st))]
                result[s] = State(s, lists[3], lists[0], lists[1], lists[2])
        for s, (_, st, _) in added[m].items():
            result[s] = st
        out.state_machines[m] = result
    for m, (_, mine, _) in machines.items():
        out.state_machines[m] = mine
    if not changed_by:
        return base, [], []
    data = write_esd(out)
    read_esd(data)  # every condition leads to a state of its own machine
    return data, changed_by, notes


def _renumber(m: int, states: dict, mine: dict, taken: dict[int, tuple[str, State, tuple]]) -> dict[int, int]:
    """New numbers for the mod's new states whose numbers another mod already used for a different state."""
    new = [s for s in mine if s not in states]
    renumber: dict[int, int] = {}
    while True:
        clash = [
            s
            for s in new
            if s not in renumber and s in taken and _normal(_retarget(mine[s], renumber)).key != taken[s][2]
        ]
        if not clash:
            return renumber
        used = set(states) | set(taken) | set(mine) | set(renumber.values())
        for s in clash:
            free = max(used) + 1
            renumber[s] = free
            used.add(free)


def _apply(label: str, m: int, s: int, game_state: State, normal: _Normal, theirs: State, plans, notes) -> bool:
    """Record what the mod did to one game state. True when it changed it."""
    mine = _normal(theirs)
    if mine.key == normal.key:
        return False
    adds = [_added(normal.lists[k], mine.lists[k], len(_lists(game_state)[k])) for k in range(4)]
    plan = plans.setdefault((m, s), _Plan())
    if all(a is not None for a in adds):
        if plan.edit is not None:
            raise Unsupported(f"state {s} of machine {m}: {', '.join(plan.by)} changed it and {label} adds to it")
        counts = []
        for k, found in enumerate(adds):
            stored = _lists(theirs)[k]
            for at, i in found or []:
                item = stored[i]
                if _uses_registers_item(item, k == 3):
                    raise Unsupported(f"state {s} of machine {m}: {label} adds to it using registers")
                form = _item_form(item, k == 3)
                here = plan.adds[k].setdefault(at, [])
                if any(f == form for _, _, f in here):
                    continue  # the same addition from another mod
                here.append((label, item, form))
            if found:
                counts.append(f"{len(found)} {LIST_NAMES[k][len(found) != 1]}")
        plan.by.append(label)
        notes.append(f"machine {m} state {s}: {label} adds {', '.join(counts)}")
        return True
    if any(plan.adds):
        raise Unsupported(f"state {s} of machine {m}: {', '.join(plan.by)} added to it and {label} changes it")
    if plan.edit is not None:
        if plan.edit_key != mine.key:
            raise Unsupported(f"state {s} of machine {m}: {', '.join(plan.by)} and {label} change it differently")
        plan.by.append(label)
        return True
    plan.edit, plan.edit_key = theirs, mine.key
    plan.by.append(label)
    notes.append(f"machine {m} state {s}: {label}'s version is used (changed by it alone)")
    return True


def _check_options(plans: dict[tuple[int, int], _Plan]) -> None:
    for (m, s), plan in plans.items():
        for k, adds in enumerate(plan.adds):
            owners: dict = {}
            for items in adds.values():
                for label, _, form in items:
                    for option in _options(form, k == 3):
                        owners.setdefault(option, set()).add(label)
            for option, labels in owners.items():
                if len(labels) > 1 or option == "?" and len(plan.by) > 1:
                    what = "an option number worked out while playing" if option == "?" else f"menu option {option}"
                    raise Unsupported(f"state {s} of machine {m}: {' and '.join(sorted(labels))} both add {what}")


def _with_added(items: list, adds: dict[int, list[tuple[str, object, tuple]]]) -> list:
    out = []
    for at in range(len(items) + 1):
        out += [item for _, item, _ in adds.get(at, [])]
        if at < len(items):
            out.append(items[at])
    return out
