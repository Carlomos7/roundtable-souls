# Adapted from Soulstruct (https://github.com/Grimrukh/soulstruct), src/soulstruct/base/ezstate/esd/condition.py at
# commit 12b69189a2ccebbc623a1b6565be89a18d6c9958 (version 2.6.0, 2026-09-27). Copyright (c) Scott Mooney (Grimrukh).
# Licensed under the GNU General Public License v3.0 or later, as is Roundtable Souls.
#
# Modified for Roundtable Souls, 2026-10-01:
#   - imports constrata directly instead of soulstruct.utilities.binary (a re-export of it);
#   - removed the ESP script and HTML output (to_esp, to_html) and the EZL decompiler they used;
#   - removed four pack_subconditions_* helpers the writer no longer calls (pack_subconditions_pass_commands,
#     pack_subconditions_pass_command_args, pack_subconditions_test_data, pack_subconditions_pass_command_arg_data);
#   - removed the unused _indent field (HTML output only);
#   - __eq__ returns NotImplemented for anything that is not a Condition;
#   - the next state's ID is converted to int where it is read.

"""A condition an ESD state tests each frame: its test (opaque EZL bytes), the state it leads to, the commands it runs
when it passes, and nested conditions, all in their stored order."""

from __future__ import annotations

__all__ = ["Condition"]

import typing as tp
from dataclasses import dataclass, field

from constrata import RESERVED, BinaryReader, BinaryStruct, BinaryWriter, varint

from .command import Command


class ConditionStruct(BinaryStruct):
    next_state_offset: varint  # offset to the actual `State` header (where `state_id` is conveniently first)
    pass_commands_offset: varint
    pass_commands_count: varint
    subcondition_pointers_offset: varint
    subcondition_pointers_count: varint
    test_ezl_offset: varint
    test_ezl_size: varint


@dataclass(slots=True)
class Condition:
    """A single condition belonging to one `State` that will send the machine to another `State` if it passes."""

    next_state_id: int
    test_ezl: bytes
    pass_commands: list[Command] = field(default_factory=list)
    subconditions: list[Condition] = field(default_factory=list)

    @classmethod
    def from_esd_reader(cls, reader: BinaryReader) -> tp.Self:
        header = ConditionStruct.from_bytes(reader)

        if header.pass_commands_offset > 0:
            reader.seek(header.pass_commands_offset)
            pass_commands = [Command.from_esd_reader(reader) for _ in range(header.pass_commands_count)]
        else:
            pass_commands = []

        subconditions = []
        if header.subcondition_pointers_offset > 0:
            reader.seek(header.subcondition_pointers_offset)
            subcondition_offsets = reader.unpack(f"{header.subcondition_pointers_count}v")
            for offset in subcondition_offsets:
                reader.seek(offset)
                subconditions.append(Condition.from_esd_reader(reader))  # safe recursion

        reader.seek(header.test_ezl_offset)
        test_ezl = reader.unpack_bytes(length=header.test_ezl_size)

        if header.next_state_offset > 0:
            reader.seek(header.next_state_offset)
            next_state_id = int(reader["v"])
        else:
            next_state_id = -1

        return cls(next_state_id, test_ezl, pass_commands, subconditions)

    def to_esd_writer(self, writer: BinaryWriter, state_id_offsets: dict[int, int]):
        if self.next_state_id != -1:
            try:
                next_state_offset = state_id_offsets[self.next_state_id]
            except KeyError:
                raise ValueError(f"Condition has non-existent next state ID: {self.next_state_id}.") from None
        else:
            next_state_offset = -1
        ConditionStruct.object_to_writer(
            self,
            writer,
            next_state_offset=next_state_offset,
            pass_commands_count=len(self.pass_commands),
            subcondition_pointers_offset=RESERVED,
            subcondition_pointers_count=len(self.subconditions),
            test_ezl_size=len(self.test_ezl),
        )

    def pack_subconditions(
        self, writer: BinaryWriter, state_id_offsets: dict[int, int], all_condition_offsets: dict[Condition, int]
    ) -> list[Condition]:
        """Pack these subconditions first, then recur on them."""
        new_conditions = []
        for subcondition in self.subconditions:
            if subcondition not in all_condition_offsets:
                all_condition_offsets[subcondition] = writer.position
                subcondition.to_esd_writer(writer, state_id_offsets)
                new_conditions.append(subcondition)
        new_subconditions = []
        for subcondition in new_conditions:
            new_subconditions += subcondition.pack_subconditions(writer, state_id_offsets, all_condition_offsets)
        return new_conditions + new_subconditions

    def pack_pass_commands(self, writer: BinaryWriter) -> int:
        """Returns the number of pass commands."""
        if not self.pass_commands:
            writer.fill("pass_commands_offset", -1, obj=self)
            return 0  # no pass commands to pack

        writer.fill_with_position("pass_commands_offset", obj=self)
        for pass_command in self.pass_commands:
            pass_command.to_esd_writer(writer)
        return len(self.pass_commands)

    def pack_pass_command_args(self, writer: BinaryWriter) -> int:
        """Returns total number of pass command args."""
        count = 0
        for pass_command in self.pass_commands:
            count += pass_command.pack_args_offsets(writer)
        return count

    def pack_test_data(self, writer: BinaryWriter):
        writer.fill_with_position("test_ezl_offset", obj=self)
        writer.append(self.test_ezl)

    def pack_pass_command_arg_data(self, writer: BinaryWriter):
        for pass_command in self.pass_commands:
            pass_command.pack_args_data(writer)

    def pack_subconditions_pointers(
        self,
        writer: BinaryWriter,
        all_condition_offsets: dict[Condition, int],
        recurred_conditions: set[Condition],
    ) -> int:
        """Returns total number of pointers found."""
        if not self.subconditions:
            writer.fill("subcondition_pointers_offset", -1, obj=self)
            return 0

        writer.fill_with_position("subcondition_pointers_offset", obj=self)
        count = 0
        for subcondition in self.subconditions:
            try:
                subcondition_offset = all_condition_offsets[subcondition]
            except KeyError:
                raise ValueError("Could not find subcondition in packed conditions dictionary.") from None
            writer.pack("v", subcondition_offset)
            count += 1
        for subcondition in self.subconditions:
            if subcondition not in recurred_conditions:
                count += subcondition.pack_subconditions_pointers(writer, all_condition_offsets, recurred_conditions)
                recurred_conditions.add(subcondition)
        return count

    def __hash__(self):
        """Allows `Condition` instances to be used as dict keys, so we can track redundant instances during pack."""
        return hash((self.next_state_id, self.test_ezl, tuple(self.pass_commands), tuple(self.subconditions)))

    def __eq__(self, other_condition: object):
        """Required for checking if the `Condition` already exists as a dictionary key."""
        if not isinstance(other_condition, Condition):
            return NotImplemented
        return (
            self.next_state_id == other_condition.next_state_id
            and self.test_ezl == other_condition.test_ezl
            and self.pass_commands == other_condition.pass_commands
            and self.subconditions == other_condition.subconditions
        )
