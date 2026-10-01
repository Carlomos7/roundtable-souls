# Adapted from Soulstruct (https://github.com/Grimrukh/soulstruct), src/soulstruct/base/ezstate/esd/core.py at
# commit 12b69189a2ccebbc623a1b6565be89a18d6c9958 (version 2.6.0, 2026-09-27), with the version-3 settings of
# src/soulstruct/darksouls3/ezstate/esd/core.py. Copyright (c) Scott Mooney (Grimrukh).
# Licensed under the GNU General Public License v3.0 or later, as is Roundtable Souls.
#
# Modified for Roundtable Souls, 2026-10-01:
#   - imports constrata directly instead of soulstruct.utilities.binary (a re-export of it);
#   - ESD is a plain dataclass instead of a soulstruct GameFile, read with from_bytes and written with to_bytes;
#   - one configuration only, Elden Ring's: version 3 with 64-bit offsets ("fsSL"). The 32-bit internal header and
#     the per-game subclasses were removed; any other layout is refused rather than read;
#   - removed reading and writing of ESP scripts (from_esp_directory, from_esp_file, read_esp_header, to_esp,
#     write_esp_file, write_esp_directory, from_auto_detect_source_type), HTML output (to_html, write_html),
#     get_next_states and the ESD type (talk/chr), and with them the ESP compiler and EZL parser modules;
#   - a state ID that appears twice in one machine is refused (it was logged and the later copy dropped), and so is a
#     file whose state count is not its machines' states plus the copy of the first state each machine of more than
#     one state carries at its end (that copy is not read; the writer makes it again);
#   - reading errors are raised as FormatError;
#   - an ESD without state machines is read and written: its machine table offset is -1 (the game has such files,
#     e.g. t334011000.esd; the original asserted 72 and refused them).

# pyright: reportArgumentType=false
# (constrata's binary(), binary_array() and binary_string() declare their optional arguments without None; every
# struct field definition below would otherwise be reported.)

"""Elden Ring ESD files (EzState state machines: the grace menu, NPC dialogue), read and written structurally.

Everything a state machine does is kept: machines and their states by ID, each state's conditions in order with
their next-state targets, nested conditions and pass commands, and enter, exit and ongoing commands. Condition tests
and command arguments are EZL bytecode, kept as opaque bytes. Writing lays the file out afresh: offsets, and the
sharing of identical conditions, may differ from the file read, while the structure is the same.
"""

from __future__ import annotations

__all__ = ["ESD", "read_esd", "write_esd"]

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

from .condition import Condition
from .state import State

VERSION = 3  # Elden Ring's (also Dark Souls III's and Sekiro's)


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
            for _ in range(machine_header.state_count):
                # The copy of the first state at the end of a machine is not counted here, so it is not read.
                state = State.from_esd_reader(reader)
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
        return bytes(self._writer())

    def _writer(self) -> BinaryWriter:
        """Packs tables and computes new byte offsets for them."""
        # Encoded name length is number of UTF-16 characters, including terminator, IF name exists.
        esd_name_length = len(self.esd_name) + 1 if self.esd_name else 0

        # External header is constructed last, as all offsets are relative to the end of it.
        external_header_writer = ESDExternalHeaderStruct.object_to_writer(
            self,
            byte_order=ByteOrder.LittleEndian,
            long_varints=True,
            esd_name_length=esd_name_length,  # number of UTF-16 characters, NOT size of encoded bytes
            state_machine_count=len(self.state_machines),  # also appears in internal header
            # Asserted fields (signature, version, sizes, footer) are filled by constrata; the rest are reserved.
        )

        # Pack internal header. This is the writer we use throughout, except when filling external header offsets.
        writer = ESDInternalHeaderStruct.object_to_writer(
            self,
            byte_order=ByteOrder.LittleEndian,
            long_varints=True,
            state_machine_count=len(self.state_machines),  # also appears in external header
            state_machine_headers_offset=72 if self.state_machines else -1,
            esd_name_offset=RESERVED,  # only reserved field in internal header
            esd_name_length=esd_name_length,  # number of UTF-16 characters, NOT size of encoded bytes
        )

        for state_machine_index, states in self.state_machines.items():
            StateMachineHeaderStruct.object_to_writer(
                states,
                writer,
                index=state_machine_index,
                states_offset=RESERVED,
                state_count=len(states),  # does NOT include dummy state, confusingly
                states_offset_2=RESERVED,  # duplicate of `states_offset`
            )

        # For `next_state_offset` of Conditions.
        state_id_offsets: dict[int, int] = {}
        all_states: list[State] = []  # for ease below (includes dummy state)

        for states in self.state_machines.values():
            writer.fill_with_position("states_offset", obj=states)
            writer.fill_with_position("states_offset_2", obj=states)
            for state in states.values():
                state_id_offsets[state.state_id] = writer.position
                state.to_esd_writer(writer)
                all_states.append(state)
            if len(states) > 1:
                # A duplicate of the first state, with its own condition pointers and arg data.
                dummy_state = list(states.values())[0].copy()
                dummy_state.to_esd_writer(writer)
                all_states.append(dummy_state)
                # NOT added to `state_id_offsets`: a Condition pointing to the first state uses the real one.

        # Total state count in header includes dummy states.
        external_header_writer.fill("state_count", len(all_states), obj=self)

        # Offsets of written Conditions, re-used across States where they are identical. States reach conditions
        # through 'condition pointers' packed near the end of the file (one per condition of every state).
        all_condition_offsets: dict[Condition, int] = {}

        state_fresh_conditions = []
        for state in all_states:
            fresh_conditions = state.pack_conditions(writer, state_id_offsets, all_condition_offsets)
            state_fresh_conditions.append(fresh_conditions)
        external_header_writer.fill("condition_count", len(all_condition_offsets), obj=self)

        command_count = 0
        for state, fresh_conditions in zip(all_states, state_fresh_conditions, strict=True):
            command_count += state.pack_commands(writer, fresh_conditions)
        external_header_writer.fill("command_count", command_count, obj=self)

        command_arg_count = 0
        for state, fresh_conditions in zip(all_states, state_fresh_conditions, strict=True):
            command_arg_count += state.pack_command_args(writer, fresh_conditions)
        external_header_writer.fill("command_arg_count", command_arg_count, obj=self)

        condition_pointers_count = 0
        recurred_conditions: set[Condition] = set()
        external_header_writer.fill("condition_pointers_offset", writer.position, obj=self)
        for state in all_states:
            condition_pointers_count += state.pack_condition_pointers(
                writer, all_condition_offsets, recurred_conditions
            )
        external_header_writer.fill("condition_pointers_count", condition_pointers_count, obj=self)

        for state, fresh_conditions in zip(all_states, state_fresh_conditions, strict=True):
            state.pack_condition_test_data(writer, fresh_conditions)

        for state, fresh_conditions in zip(all_states, state_fresh_conditions, strict=True):
            state.pack_command_arg_data(writer, fresh_conditions)

        external_header_writer.fill("tail_offset", writer.position, obj=self)

        if self.esd_name:
            writer.fill_with_position("esd_name_offset", obj=self)
            writer.append(self.esd_name.encode("utf-16-le") + b"\0\0")
        else:
            writer.fill("esd_name_offset", -1, obj=self)

        external_header_writer.fill("unk_offset_1", writer.position, obj=self)
        external_header_writer.fill("unk_offset_2", writer.position, obj=self)
        external_header_writer.fill("internal_data_size", writer.position, obj=self)

        external_header_writer.append(bytes(writer))
        return external_header_writer


def read_esd(data: bytes) -> ESD:
    return ESD.from_bytes(data)


def write_esd(esd: ESD) -> bytes:
    return esd.to_bytes()
