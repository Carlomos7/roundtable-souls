"""merging.rules.esd: talk scripts merged state by state against the game's, within the envelope; anything else is
the later mod's copy, whole, with the reason. Built scripts only (the real grace menus: scripts/verify/esd_merge.py)."""

import struct

import pytest
from fakegame import bnd, dcx, files_of

from roundtable_souls.formats.esd import ESD, Command, Condition, State, read_esd, write_esd
from roundtable_souls.merging import merger
from roundtable_souls.merging.rules import esd as rule

END = b"\xa1"
TRUE = b"\x41" + END
GAME_TEXT = ["Leave", "Pass time"]


def num(n: int) -> bytes:
    return bytes([n + 64]) if -64 <= n < 64 else b"\x82" + struct.pack("<i", n)


def wide(n: int) -> bytes:  # how a recompiling tool writes the same number
    return b"\x82" + struct.pack("<i", n)


def chosen(n: int, spell=num) -> bytes:  # GetTalkListEntryResult() == n
    return b"\x57\x84" + spell(n) + b"\x95" + END


def entry(n: int, text: int, spell=num) -> Command:  # AddTalkListData(n, text, -1)
    return Command(1, 19, [bytearray(spell(n) + END), bytearray(wide(text) + END), bytearray(num(-1) + END)])


def call(index: int) -> Command:
    return Command(1, index, [])


def game_script(spell=num, nested: bool = True) -> ESD:
    if nested:  # a test then an always-true nested condition, as the game stores it
        back = Condition(-1, b"\x50\x84\xa6\x41\x95" + END, subconditions=[Condition(0, TRUE)])
    else:  # how a recompiling tool writes the same
        back = Condition(0, b"\x50\x84" + END)
    menu = {
        0: State(0, [Condition(1, TRUE)], [entry(1, 100, spell), entry(2, 200, spell)]),
        1: State(1, [Condition(2, chosen(1, spell)), Condition(3, chosen(2, spell))]),
        2: State(2, [back]),
        3: State(3, [Condition(0, TRUE)], [call(110)]),
    }
    return ESD(magic=[1, 2, 3, 4], esd_name="t000001000", state_machines={1: menu, 9: {0: State(0, [])}})


def with_option(esd: ESD, option: int, text: int, new_state: int, action: int, spell=num) -> ESD:
    menu = esd.state_machines[1]
    menu[0].enter_commands.append(entry(option, text, spell))
    menu[1].conditions.append(Condition(new_state, chosen(option, spell)))
    menu[new_state] = State(new_state, [Condition(0, TRUE)], [call(action)])
    return esd


GAME = write_esd(game_script())


def merged(*layers):
    return rule.merge(GAME, list(layers), "t000001000.esd")


def options(data: bytes) -> list[tuple[int, int]]:
    """(option, the state its choice leads to), as the merged menu offers them."""
    menu = read_esd(data).state_machines[1]
    shown = [rule._command(c)[2][0][1] for c in menu[0].enter_commands if (c.bank, c.index) == (1, 19)]
    leads = {}
    for c in menu[1].conditions:
        form = rule._expression(c.test_ezl, {})
        leads[form[3][1]] = c.next_state_id
    return [(o, leads.get(o)) for o in shown]


def test_options_two_mods_add_are_both_offered_and_a_taken_state_number_moves():
    a = write_esd(with_option(game_script(), 10, 1000, 4, 120))
    b = write_esd(with_option(game_script(), 20, 2000, 4, 130))
    r = merged(("a", a), ("b", b))
    assert r.merged and not r.clashes and r.changed == {"t000001000.esd": ["a", "b"]}
    assert options(r.data) == [(1, 2), (2, 3), (10, 4), (20, 5)]  # b's state 4 is now 5
    menu = read_esd(r.data).state_machines[1]
    assert menu[4].enter_commands == [call(120)] and menu[5].enter_commands == [call(130)]
    notes = r.notes["t000001000.esd"]
    assert "machine 1: b's new state 4 is numbered 5 (4 was taken)" in notes
    assert "machine 1 state 0: a adds 1 command run on entering" in notes


def test_a_recompiled_copy_is_compared_by_meaning_and_the_games_own_states_are_kept():
    a = write_esd(with_option(game_script(), 10, 1000, 4, 120))
    tool = write_esd(with_option(game_script(spell=wide, nested=False), 20, 2000, 4, 130, spell=wide))
    r = merged(("a", a), ("tool", tool))
    assert r.merged and not r.clashes
    assert options(r.data) == [(1, 2), (2, 3), (10, 4), (20, 5)]
    menu, game = read_esd(r.data).state_machines[1], game_script().state_machines[1]
    assert menu[2] == game[2] and menu[3] == game[3]  # only number spelling and nesting differed: the game's
    assert menu[1].conditions[:2] == game[1].conditions


def test_a_mod_built_on_another_mods_copy_adds_only_its_own_part():
    a = with_option(game_script(), 10, 1000, 4, 120)
    b = with_option(with_option(game_script(), 10, 1000, 4, 120), 20, 2000, 5, 130)
    r = merged(("a", write_esd(a)), ("b", write_esd(b)))
    assert r.merged and not r.clashes
    assert options(r.data) == [(1, 2), (2, 3), (10, 4), (20, 5)]  # a's option once
    assert read_esd(r.data).state_machines == b.state_machines


def test_new_machines_are_added_and_the_same_one_twice_is_one():
    a, b = game_script(), game_script()
    for esd in (a, b):
        esd.state_machines[50] = {0: State(0, [Condition(1, TRUE)]), 1: State(1, [], [call(7)])}
    b.state_machines[60] = {0: State(0, [])}
    r = merged(("a", write_esd(a)), ("b", write_esd(b)))
    assert r.merged and set(read_esd(r.data).state_machines) == {1, 9, 50, 60}


def _without_state_3(esd: ESD) -> ESD:
    menu = esd.state_machines[1]
    del menu[3]
    menu[1].conditions.pop()
    return esd


@pytest.mark.parametrize(
    ("a", "b", "why"),
    [
        (lambda e: with_option(e, 10, 1000, 4, 120), lambda e: with_option(e, 10, 3000, 4, 130), "menu option 10"),
        (
            lambda e: e.state_machines[1][3].enter_commands.append(call(111)) or e,
            lambda e: e.state_machines[1][3].enter_commands.insert(0, call(112)) or e,
            None,  # both add to the same place's neighbourhood: fine; see the next cases for clashes
        ),
        (
            lambda e: setattr(e.state_machines[1][3], "enter_commands", [call(111)]) or e,
            lambda e: setattr(e.state_machines[1][3], "enter_commands", [call(112)]) or e,
            "state 3 of machine 1: a and b change it differently",
        ),
        (
            lambda e: setattr(e.state_machines[1][3], "enter_commands", [call(111)]) or e,
            lambda e: e.state_machines[1][3].enter_commands.append(call(112)) or e,
            "state 3 of machine 1: a changed it and b adds to it",
        ),
        (lambda e: e, lambda e: _without_state_3(e), "b's copy leaves out state 3 of state machine 1"),
        (lambda e: e, lambda e: e.state_machines.pop(9) and e, "b's copy leaves out state machine 9"),
        (
            lambda e: e,
            lambda e: e.state_machines[1][1].conditions.insert(0, Condition(3, b"\x57\x84\xa7\x45\x95" + END)) or e,
            "b adds to it using registers",
        ),
        (
            lambda e: e,
            lambda e: e.state_machines[1][1].conditions.insert(0, Condition(3, b"\x57\x84\x83" + END)) or e,
            "the byte 0x83",
        ),
        (
            lambda e: e.state_machines.__setitem__(50, {0: State(0, [], [call(1)])}) or e,
            lambda e: e.state_machines.__setitem__(50, {0: State(0, [], [call(2)])}) or e,
            "a and b both add state machine 50, differently",
        ),
    ],
)
def test_what_is_outside_the_envelope_is_the_later_mods_copy_whole_with_the_reason(a, b, why):
    first, second = write_esd(a(game_script())), write_esd(b(game_script()))
    r = merged(("a", first), ("b", second))
    if why is None:
        assert r.merged and not r.clashes
        assert read_esd(r.data).state_machines[1][3].enter_commands == [call(112), call(110), call(111)]
        return
    changers = [name for name, data in (("a", first), ("b", second)) if data != GAME]
    assert not r.merged and r.data == second and r.clashes == {"t000001000.esd": changers}
    assert why in r.notes["t000001000.esd"][0] and "b's copy is used whole" in r.notes["t000001000.esd"][0]


def test_a_copy_no_mod_changed_is_the_games():
    r = merged(("a", GAME), ("b", write_esd(game_script(spell=wide, nested=False))))
    assert r.merged and r.data == GAME and not r.changed


def test_in_an_archive_scripts_are_merged_and_switched_off_the_later_mods_is_used(monkeypatch):
    a = write_esd(with_option(game_script(), 10, 1000, 4, 120))
    b = write_esd(with_option(game_script(), 20, 2000, 4, 130))
    game = dcx(bnd({"t000001000.esd": GAME, "other.esd": GAME}))
    layers = [(name, dcx(bnd({"t000001000.esd": x, "other.esd": GAME}))) for name, x in (("a", a), ("b", b))]
    on = merger.merge(game, layers)
    monkeypatch.setattr(merger, "ESD_MERGING", False)
    off = merger.merge(game, layers)
    assert off.clashes and files_of(off.data)["t000001000.esd"] == b  # as before ESD merging: the later mod's script
    assert not on.clashes and options(files_of(on.data)["t000001000.esd"]) == [(1, 2), (2, 3), (10, 4), (20, 5)]
    assert files_of(on.data)["other.esd"] == GAME
