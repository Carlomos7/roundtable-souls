"""The ESD (EzState) code in formats/esd, on small ESDs built here. Real talk scripts are a real-data check
(scripts/verify/esd_roundtrip.py)."""

import struct

import pytest

from roundtable_souls.formats import FormatError
from roundtable_souls.formats.esd import ESD, Command, Condition, State, read_esd, write_esd

TRUE = b"\x41\xa1"  # EZL for "true"; condition tests and command arguments are kept as opaque bytes
EXTERNAL = 0x6C  # the external header's size: internal offsets start after it


def cmd(bank: int, index: int, *args: bytes) -> Command:
    return Command(bank, index, [bytearray(a) for a in args])


def sample() -> ESD:
    """Two machines; conditions with targets, pass commands and a nested condition; all three command lists."""
    nested = Condition(-1, b"\x42\xa1", [cmd(1, 7, b"\x40")], [Condition(3, TRUE)])
    machine = {
        1: State(1, [Condition(2, b"\x41\x42\x8c\xa1", [cmd(1, 3, b"\x41\xa1", b"\x82\x00\x00\x00\xa1")]), nested],
                 enter_commands=[cmd(1, 1)], exit_commands=[cmd(1, 2, b"\x3f")]),
        2: State(2, [Condition(1, TRUE)], ongoing_commands=[cmd(5, 9, b"\x40\xa1")]),
        3: State(3, [Condition(1, TRUE)]),  # equal to state 2's condition, but its own: stored separately
    }  # fmt: skip
    called = {0: State(0, [Condition(-1, TRUE)])}  # a machine another one calls
    return ESD(magic=[1, 2, 3, 4], esd_name="t000001000", state_machines={1: machine, 0x7FFFFFFF: called})


def test_an_esd_reads_back_to_the_same_structure():
    esd = sample()
    back = read_esd(write_esd(esd))
    assert back.state_machines == esd.state_machines
    assert [(m, list(s)) for m, s in back.state_machines.items()] == [(1, [1, 2, 3]), (0x7FFFFFFF, [0])]
    assert (back.magic, back.esd_name) == ([1, 2, 3, 4], "t000001000")
    first = back.state_machines[1][1]
    assert [c.next_state_id for c in first.conditions] == [2, -1]
    assert first.conditions[1].subconditions[0].next_state_id == 3
    assert first.conditions[0].pass_commands[0].args == [bytearray(b"\x41\xa1"), bytearray(b"\x82\x00\x00\x00\xa1")]
    assert write_esd(back) == write_esd(esd)  # the layout is settled after one write


def conditions_stored(data: bytes) -> int:
    return struct.unpack_from("<i", data, 0x38)[0]


def machine_table(data: bytes) -> list[tuple[int, int, int]]:
    """(machine ID, offset of its states, how many) from a written file."""
    count = struct.unpack_from("<q", data, EXTERNAL + 32)[0]
    return [struct.unpack_from("<3q", data, EXTERNAL + 72 + 32 * i) for i in range(count)]


def test_each_condition_object_is_stored_once_and_equal_ones_separately():
    shared = Condition(1, TRUE)
    esd = ESD(state_machines={1: {1: State(1, [Condition(2, TRUE)]), 2: State(2, [shared]), 3: State(3, [shared])}})
    assert conditions_stored(write_esd(esd)) == 2  # the shared object once
    back = read_esd(write_esd(esd))
    assert back.state_machines[1][2].conditions[0] is back.state_machines[1][3].conditions[0]  # still shared
    assert conditions_stored(write_esd(sample())) == 6  # sample(): equal conditions of states 2 and 3 kept apart


def test_conditions_lead_to_states_of_their_own_machine():
    # Both machines number their states 0 and 1, so a target found by state ID alone could be either machine's.
    def machine():
        return {0: State(0, [Condition(1, TRUE)]), 1: State(1, [Condition(0, TRUE)])}

    data = write_esd(ESD(state_machines={10: machine(), 20: machine()}))
    for _machine_id, states_at, count in machine_table(data):
        own = range(states_at, states_at + 72 * count, 72)
        for k in range(count):
            pointers_at = struct.unpack_from("<q", data, EXTERNAL + states_at + 72 * k + 8)[0]
            condition_at = struct.unpack_from("<q", data, EXTERNAL + pointers_at)[0]
            assert struct.unpack_from("<q", data, EXTERNAL + condition_at)[0] in own


def test_a_condition_leading_into_another_machine_is_refused():
    def machine():
        return {0: State(0, [Condition(1, TRUE)]), 1: State(1, [Condition(0, TRUE)])}

    data = bytearray(write_esd(ESD(state_machines={10: machine(), 20: machine()})))
    (_a, first_states, _n), (_b, other_states, _m) = machine_table(bytes(data))
    pointers_at = struct.unpack_from("<q", data, EXTERNAL + first_states + 8)[0]
    condition_at = struct.unpack_from("<q", data, EXTERNAL + pointers_at)[0]
    struct.pack_into("<q", data, EXTERNAL + condition_at, other_states + 72)  # the other machine's state 1
    with pytest.raises(FormatError, match="not a state of its machine"):
        read_esd(bytes(data))


def test_the_last_state_of_a_machine_is_a_copy_of_the_first_ones_header():
    data = write_esd(sample())
    (_id, states_at, count), _called = machine_table(data)
    first = EXTERNAL + states_at
    last = first + 72 * count
    assert data[last : last + 72] == data[first : first + 72]


def test_an_esd_without_state_machines_round_trips():
    esd = ESD(magic=[5, 6, 7, 8], esd_name="t334011000")
    data = write_esd(esd)
    assert struct.unpack_from("<q", data, EXTERNAL + 24)[0] == -1  # no machine table
    back = read_esd(data)
    assert back.state_machines == {} and back.esd_name == "t334011000" and write_esd(back) == data


def test_commands_with_different_argument_counts_are_different():
    assert cmd(1, 1, b"\x40") != cmd(1, 1, b"\x40", b"\x41")
    assert Condition(1, TRUE, [cmd(1, 1, b"\x40")]) != Condition(1, TRUE, [cmd(1, 1, b"\x40", b"\x41")])


def test_a_condition_to_a_missing_state_is_not_written():
    esd = ESD(state_machines={1: {1: State(1, [Condition(99, TRUE)])}})
    with pytest.raises(ValueError, match="99"):
        write_esd(esd)


def test_a_state_id_used_twice_in_a_machine_is_refused():
    one_machine = ESD(state_machines={1: {1: State(1, [Condition(2, TRUE)]), 2: State(2, [Condition(1, TRUE)])}})
    data = bytearray(write_esd(one_machine))
    second_state = EXTERNAL + 72 + 32 + 72  # internal header, one machine header, the first state
    struct.pack_into("<q", data, second_state, 1)
    with pytest.raises(FormatError, match="appears twice"):
        read_esd(bytes(data))


def test_a_state_count_that_does_not_match_its_machines_is_refused():
    data = bytearray(write_esd(sample()))
    struct.pack_into("<i", data, 0x30, struct.unpack_from("<i", data, 0x30)[0] + 1)
    with pytest.raises(FormatError, match="states stored"):
        read_esd(bytes(data))


@pytest.mark.parametrize("patch", [(0, b"fSSL"), (8, struct.pack("<2i", 1, 1))], ids=["32-bit", "version-1"])
def test_another_games_layout_is_refused(patch):
    at, value = patch
    data = bytearray(write_esd(sample()))
    data[at : at + len(value)] = value
    with pytest.raises(FormatError):
        read_esd(bytes(data))
