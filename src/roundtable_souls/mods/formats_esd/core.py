# Adapted from Soulstruct (https://github.com/Grimrukh/soulstruct), src/soulstruct/base/ezstate/esd/core.py at
# commit 12b69189a2ccebbc623a1b6565be89a18d6c9958 (version 2.6.0, 2026-09-27),
# with the version-3 settings of src/soulstruct/darksouls3/ezstate/esd/core.py. Copyright (c) Scott Mooney
# (Grimrukh). Licensed under the GNU General Public License v3.0 or later, as is Roundtable Souls.
#
# Modified for Roundtable Souls, 2026-10-01:
#   - imports constrata directly instead of soulstruct.utilities.binary (a re-export of it);
#   - ESD is a plain dataclass instead of a soulstruct GameFile, read with from_bytes and written with to_bytes;
#   - one configuration only, Elden Ring's: version 3 with 64-bit offsets ("fsSL"); the 32-bit internal header and
#     the per-game subclasses were removed, and any other layout is refused;
#   - removed ESP script reading and writing, HTML output, get_next_states and the ESD type (talk/chr), and with
#     them the ESP compiler and EZL parser modules;
#   - reading: a repeated state ID in a machine, a state count that does not match the machines, and a condition
#     leading outside its machine are refused (the first was logged and dropped); an ESD without state machines
#     (machine table offset -1; the game has one) is read; errors are raised as FormatError;
#   - writing was rewritten to the game's own layout, found by comparing with the game's files: state offsets per
#     machine (the original kept one table keyed by state ID, which repeats across machines, so conditions led
#     into other machines; the game crashed on such a file in an in-game test, 2026-10-01); each condition object
#     written once per machine instead of equal conditions shared file-wide; the copy of each machine's first state
#     at its end is a copy of that state's header, with an (unread) pointer list of its own; tables in the game's
#     order (all direct conditions, then nested ones; states' commands, then pass commands; state pointer lists,
#     then nested lists; direct tests, then per state its nested tests and command arguments, then pass command
#     arguments); the name aligned to 2 bytes. Every one of the game's 282 talk scripts checked is written back
#     byte for byte.

# pyright: reportArgumentType=false
# (constrata's binary(), binary_array() and binary_string() declare their optional arguments without None; every
# struct field definition below would otherwise be reported.)

"""Elden Ring ESD files (EzState state machines: the grace menu, NPC dialogue), read and written structurally.

Everything a state machine does is kept: machines and their states by ID, each state's conditions in order with
their next-state targets, nested conditions and pass commands, and enter, exit and ongoing commands. Condition tests
and command arguments are EZL bytecode, kept as opaque bytes. Writing lays the file out as the game's own files are:
the game's talk scripts are written back byte for byte. A file another tool wrote may come out laid out differently,
with the same structure.
"""

from __future__ import annotations

__all__ = ["ESD", "read_esd", "write_esd"]

import copy
import typing as tp
from dataclasses import dataclass, field

from constrata import (
    RESERVED,
    BinaryReader,
    BinaryStruct,
    BinaryWriter,
    ByteOrder,
    binary,
    binary_array,
    binary_pad,
    binary_string,
    long,
    varint,
)

from roundtable_souls.gamefiles import FormatError

from .command import Command
from .condition import Condition
from .state import State

VERSION = 3  # Elden Ring's (also Dark Souls III's and Sekiro's)
STATE_SIZE = 72
EXTERNAL_HEADER_SIZE = 0x6C  # internal offsets count from its end


class ESDExternalHeaderStruct(BinaryStruct):
    """All offsets are relative to the END of this struct. Always 32-bit ints, even for its offset fields."""

    signature: bytes = binary_string(4, asserted=b"fsSL")
    _one: int = binary(asserted=1)
    game_version: list[int] = binary_array(2, asserted=[VERSION, VERSION])
    _table_size_offset: int = binary(asserted=84)
    internal_data_size: int  # excludes this header (i.e. EOF minus this header size)
    unk: int = binary(asserted=6)
    internal_header_size: int = binary(asserted=72)
    internal_header_count: int = binary(asserted=1)
    state_machine_header_size: int = binary(asserted=32)
    state_machine_count: int
    state_size: int = binary(asserted=72)
    state_count: int
    condition_size: int = binary(asserted=56)
    condition_count: int
    command_size: int = binary(asserted=24)
    command_count: int
    command_arg_size: int = binary(asserted=16)
    command_arg_count: int
    condition_pointers_offset: int
    condition_pointers_count: int
    tail_offset: int  # points to just before actual name
    esd_name_length: int
    unk_offset_1: int
    unk_size_1: int = binary(asserted=0)
    unk_offset_2: int
    unk_size_2: int = binary(asserted=0)


class ESDInternalHeaderStruct(BinaryStruct):
    _one: int = binary(asserted=1)
    magic: list[int] = binary_array(4)
    _pad1: bytes = binary_pad(4)
    state_machine_headers_offset: long = binary(asserted=[72, -1])  # -1: no state machines
    state_machine_count: long  # same as external header
    esd_name_offset: long  # accurate, unlike external header
    esd_name_length: long  # same as value in external header
    footer: list[long] = binary_array(2, asserted=[-1, -1])


class StateMachineHeaderStruct(BinaryStruct):
    index: varint
    states_offset: varint
    state_count: varint
    states_offset_2: varint  # duplicate


@dataclass
class ESD:
    """An EzState file: state machines by ID, each a dict of states by ID, in their stored order."""

    magic: list[int] = field(default_factory=lambda: [0] * 4)
    esd_name: str = ""
    state_machines: dict[int, dict[int, State]] = field(default_factory=dict)

    @classmethod
    def from_bytes(cls, data: bytes) -> tp.Self:
        try:
            return cls._read(data)
        except FormatError:
            raise
        except Exception as e:  # constrata's assertion and range errors, struct errors
            raise FormatError(f"not an Elden Ring ESD file this reader supports: {e}") from e

    @classmethod
    def _read(cls, data: bytes) -> tp.Self:
        reader = BinaryReader(data, byte_order=ByteOrder.LittleEndian, long_varints=True)
        header = ESDExternalHeaderStruct.from_bytes(reader)

        # Internal offsets start here, so we reset the reader to make these offsets naturally correct.
        reader = BinaryReader(reader.read(), byte_order=ByteOrder.LittleEndian, long_varints=True)
        internal_header = ESDInternalHeaderStruct.from_bytes(reader)
        if (internal_header.state_machine_headers_offset == -1) != (header.state_machine_count == 0):
            raise FormatError("the state machine table and its count disagree")

        machine_headers = [StateMachineHeaderStruct.from_bytes(reader) for _ in range(header.state_machine_count)]

        state_machines: dict[int, dict[int, State]] = {}
        for machine_header in machine_headers:
            if machine_header.index in state_machines:
                raise FormatError(f"state machine {machine_header.index} appears more than once")
            reader.seek(machine_header.states_offset)
            states: dict[int, State] = {}
            # Where this machine's states are: the only places its conditions may lead to.
            targets = range(
                machine_header.states_offset,
                machine_header.states_offset + STATE_SIZE * machine_header.state_count,
                STATE_SIZE,
            )
            read: dict = {}  # this machine's conditions by offset: what the file shares stays shared
            for _ in range(machine_header.state_count):
                # The copy of the first state at the end of a machine is not counted here, so it is not read.
                state = State.from_esd_reader(reader, targets, read)
                if state.state_id in states:
                    raise FormatError(f"state {state.state_id} appears twice in state machine {machine_header.index}")
                states[state.state_id] = state
            state_machines[machine_header.index] = states

        stored = sum(len(s) + (1 if len(s) > 1 else 0) for s in state_machines.values())
        if header.state_count != stored:
            raise FormatError(f"{header.state_count} states stored, {stored} expected from the state machines")

        if internal_header.esd_name_length > 0:
            # The length counts UTF-16 characters (the terminator included); the bytes are twice that.
            reader.seek(internal_header.esd_name_offset)
            esd_name = reader.unpack_string(length=2 * internal_header.esd_name_length, encoding="utf-16-le")
        else:
            esd_name = ""

        return cls(magic=list(internal_header.magic), esd_name=esd_name, state_machines=state_machines)

    def to_bytes(self) -> bytes:
        writer, copies = self._writer()
        data = bytearray(bytes(writer))
        for first, last in copies:  # each machine's last state: a copy of its first state's header
            a, b = EXTERNAL_HEADER_SIZE + first, EXTERNAL_HEADER_SIZE + last
            data[b : b + STATE_SIZE] = data[a : a + STATE_SIZE]
        return bytes(data)

    def _writer(self) -> tuple[BinaryWriter, list[tuple[int, int]]]:
        """Packs tables and computes new byte offsets for them. Also returns, per machine of more than one state, the
        offsets of its first state and of the copy of it to be made at its end."""
        # Each machine gets its own objects: a condition object shared between machines would need two targets.
        machines = {index: copy.deepcopy(states) for index, states in self.state_machines.items()}
        esd_name_length = len(self.esd_name) + 1 if self.esd_name else 0  # UTF-16 characters, terminator included

        # External header is constructed last, as all offsets are relative to the end of it.
        external_header_writer = ESDExternalHeaderStruct.object_to_writer(
            self,
            byte_order=ByteOrder.LittleEndian,
            long_varints=True,
            esd_name_length=esd_name_length,
            state_machine_count=len(machines),
            # Asserted fields (signature, version, sizes, footer) are filled by constrata; the rest are reserved.
        )
        writer = ESDInternalHeaderStruct.object_to_writer(
            self,
            byte_order=ByteOrder.LittleEndian,
            long_varints=True,
            state_machine_count=len(machines),
            state_machine_headers_offset=72 if machines else -1,
            esd_name_offset=RESERVED,
            esd_name_length=esd_name_length,
        )
        for state_machine_index, states in machines.items():
            StateMachineHeaderStruct.object_to_writer(
                states,
                writer,
                index=state_machine_index,
                states_offset=RESERVED,
                state_count=len(states),  # does NOT include the copy of the first state
                states_offset_2=RESERVED,
            )

        # States, machine by machine; a condition's target is a state of its own machine.
        state_offsets: dict[int, dict[int, int]] = {}
        copies: list[tuple[int, int]] = []
        for index, states in machines.items():
            writer.fill_with_position("states_offset", obj=states)
            writer.fill_with_position("states_offset_2", obj=states)
            state_offsets[index] = {}
            first = writer.position
            for state in states.values():
                state_offsets[index][state.state_id] = writer.position
                state.to_esd_writer(writer)
            if len(states) > 1:
                copies.append((first, writer.position))
                writer.append(bytes(STATE_SIZE))  # filled in by to_bytes
        state_total = sum(len(m) + (1 if len(m) > 1 else 0) for m in machines.values())
        external_header_writer.fill("state_count", state_total, obj=self)

        # Conditions: each object once, per machine (offsets by id()).
        condition_offsets: dict[int, dict[int, int]] = {index: {} for index in machines}
        written: list[tuple[int, Condition]] = []

        def write_condition(index: int, condition: Condition) -> bool:
            if id(condition) in condition_offsets[index]:
                return False
            condition_offsets[index][id(condition)] = writer.position
            condition.to_esd_writer(writer, state_offsets[index])
            written.append((index, condition))
            return True

        def nested_after(start: int) -> None:
            at = start
            while at < len(written):
                index, condition = written[at]
                for sub in condition.subconditions:
                    write_condition(index, sub)
                at += 1

        # Every state's own conditions first (all machines), then nested conditions, level by level.
        for index, states in machines.items():
            for state in states.values():
                for condition in state.conditions:
                    write_condition(index, condition)
        nested_after(0)
        external_header_writer.fill("condition_count", len(written), obj=self)

        # Commands: the states' (enter, exit, ongoing), then the conditions' pass commands.
        commands: list[Command] = []

        def state_commands(states):
            for state in states:
                commands.extend(state.pack_own_commands(writer))

        def pass_commands(conditions):
            for _index, condition in conditions:
                commands.extend(condition.pass_commands)
                condition.pack_pass_commands(writer)

        state_commands(state for states in machines.values() for state in states.values())
        pass_commands(written)
        external_header_writer.fill("command_count", len(commands), obj=self)
        external_header_writer.fill(
            "command_arg_count", sum(command.pack_args_offsets(writer) for command in commands), obj=self
        )

        # Condition pointers: each state's list, and per machine a list for the copy of its first state (the game's
        # own files have it; the copy's header points at the first state's list, so nothing reads it). Then the
        # lists of nested conditions, in the order the conditions were written.
        pointers = 0
        external_header_writer.fill("condition_pointers_offset", writer.position, obj=self)

        def nested_lists(conditions):
            nonlocal pointers
            for index, condition in conditions:
                pointers += condition.pack_subcondition_pointers(writer, condition_offsets[index])

        for index, states in machines.items():
            for state in states.values():
                pointers += state.pack_condition_pointers(writer, condition_offsets[index])
            if len(states) > 1:
                for condition in next(iter(states.values())).conditions:
                    writer.pack("v", condition_offsets[index][id(condition)])
                    pointers += 1
        nested_lists(written)
        external_header_writer.fill("condition_pointers_count", pointers, obj=self)

        # EZL data, in the game's own order: the tests of every state's own conditions; then, state by state, the
        # tests of its nested conditions and the arguments of its enter, exit and ongoing commands; then the
        # arguments of every pass command.
        order = {id(condition): at for at, (_index, condition) in enumerate(written)}
        direct = {id(c) for states in machines.values() for state in states.values() for c in state.conditions}
        tested: set[int] = set()
        for _index, condition in written:
            if id(condition) in direct:
                condition.pack_test_data(writer)
                tested.add(id(condition))
        for states in machines.values():
            for state in states.values():
                nested: list[Condition] = []
                pending = list(state.conditions)
                while pending:
                    condition = pending.pop()
                    for sub in condition.subconditions:
                        if id(sub) not in tested:
                            tested.add(id(sub))
                            nested.append(sub)
                            pending.append(sub)
                for condition in sorted(nested, key=lambda c: order[id(c)]):
                    condition.pack_test_data(writer)
                for command in (*state.enter_commands, *state.exit_commands, *state.ongoing_commands):
                    command.pack_args_data(writer)
        for _index, condition in written:
            for command in condition.pass_commands:
                command.pack_args_data(writer)

        external_header_writer.fill("tail_offset", writer.position, obj=self)
        if self.esd_name:
            writer.pad_align(2)
            writer.fill_with_position("esd_name_offset", obj=self)
            writer.append(self.esd_name.encode("utf-16-le") + b"\0\0")
        else:
            writer.fill("esd_name_offset", -1, obj=self)

        external_header_writer.fill("unk_offset_1", writer.position, obj=self)
        external_header_writer.fill("unk_offset_2", writer.position, obj=self)
        external_header_writer.fill("internal_data_size", writer.position, obj=self)

        if external_header_writer.position != EXTERNAL_HEADER_SIZE:
            raise ValueError("unexpected ESD header size")
        external_header_writer.append(bytes(writer))
        return external_header_writer, copies


def read_esd(data: bytes) -> ESD:
    return ESD.from_bytes(data)


def write_esd(esd: ESD) -> bytes:
    return esd.to_bytes()
