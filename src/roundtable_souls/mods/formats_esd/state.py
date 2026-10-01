# Adapted from Soulstruct (https://github.com/Grimrukh/soulstruct), src/soulstruct/base/ezstate/esd/state.py at
# commit 12b69189a2ccebbc623a1b6565be89a18d6c9958 (version 2.6.0, 2026-09-27). Copyright (c) Scott Mooney (Grimrukh).
# Licensed under the GNU General Public License v3.0 or later, as is Roundtable Souls.
#
# Modified for Roundtable Souls, 2026-10-01:
#   - imports constrata directly instead of soulstruct.utilities.binary (a re-export of it);
#   - removed the ESP script and HTML output (to_esp, to_html, html_title_bar) and the EZL register helper they used;
#   - removed the ESD_TYPE class variable (talk/chr only selected function names for that output).

"""One state of an ESD state machine: its ID, its conditions in order, and its enter, exit and ongoing commands."""

from __future__ import annotations

__all__ = ["State"]

import copy
import typing as tp
from dataclasses import dataclass, field

from constrata import BinaryReader, BinaryStruct, BinaryWriter, varint

from .command import Command
from .condition import Condition


class StateStruct(BinaryStruct):
    state_id: varint
    condition_pointers_offset: varint
    condition_pointers_count: varint
    enter_commands_offset: varint
    enter_commands_count: varint
    exit_commands_offset: varint
    exit_commands_count: varint
    ongoing_commands_offset: varint
    ongoing_commands_count: varint


@dataclass(slots=True)
class State:
    """A single state that the EzState machine (ESD file) can occupy at a moment in time.

    Lists of enter, ongoing (per frame), and exit `Command`s may be executed.

    A list of `Condition`s is checked each frame to see if the state machine should change to a new state.
    """

    state_id: int
    conditions: list[Condition] = field(default_factory=list)
    enter_commands: list[Command] = field(default_factory=list)
    exit_commands: list[Command] = field(default_factory=list)
    ongoing_commands: list[Command] = field(default_factory=list)

    @classmethod
    def from_esd_reader(cls, reader: BinaryReader) -> tp.Self:
        """Unpack a `State` from ESD file binary."""

        header = StateStruct.from_bytes(reader)
        next_state_offset = reader.position  # reset at end of this call

        conditions = []
        if header.condition_pointers_offset != -1:  # otherwise, state has no conditions
            reader.seek(header.condition_pointers_offset)
            condition_offsets = reader.unpack(f"{header.condition_pointers_count}v")
            for offset in condition_offsets:
                reader.seek(offset)
                conditions.append(Condition.from_esd_reader(reader))

        if header.enter_commands_offset != -1:
            reader.seek(header.enter_commands_offset)
            enter_commands = [Command.from_esd_reader(reader) for _ in range(header.enter_commands_count)]
        else:
            enter_commands = []

        if header.exit_commands_offset != -1:
            reader.seek(header.exit_commands_offset)
            exit_commands = [Command.from_esd_reader(reader) for _ in range(header.exit_commands_count)]
        else:
            exit_commands = []

        if header.ongoing_commands_offset != -1:
            reader.seek(header.ongoing_commands_offset)
            ongoing_commands = [Command.from_esd_reader(reader) for _ in range(header.ongoing_commands_count)]
        else:
            ongoing_commands = []

        reader.seek(next_state_offset)
        return cls(header.state_id, conditions, enter_commands, exit_commands, ongoing_commands)

    def copy(self) -> tp.Self:
        """Create a deep copy of this `State`. (Needed for writing dummy duplicates of first state.)"""
        return copy.deepcopy(self)

    def to_esd_writer(self, writer: BinaryWriter):
        StateStruct.object_to_writer(
            self,
            writer,
            condition_pointers_count=len(self.conditions),
            enter_commands_count=len(self.enter_commands),
            exit_commands_count=len(self.exit_commands),
            ongoing_commands_count=len(self.ongoing_commands),
        )

    def pack_conditions(
        self, writer: BinaryWriter, state_id_offsets: dict[int, int], all_condition_offsets: dict[Condition, int]
    ) -> list[Condition]:
        """Pack all conditions and (recursively) subconditions in this State.

        Identical conditions are shared file-wide: two `State`s that use the exact same `Condition` share one packed
        condition. Returns the conditions this State packed first, every subcondition included; only these have their
        arguments and data packed later.
        """
        new_conditions = []  # subconditions only recursively packed for new conditions
        for condition in self.conditions:
            if condition not in all_condition_offsets:  # `Condition` and `Command` have hash/eq methods to enable this
                all_condition_offsets[condition] = writer.position
                condition.to_esd_writer(writer, state_id_offsets)
                new_conditions.append(condition)
        new_subconditions = []
        for condition in new_conditions:
            new_subconditions += condition.pack_subconditions(writer, state_id_offsets, all_condition_offsets)
        return new_conditions + new_subconditions

    def pack_commands(self, writer: BinaryWriter, conditions_to_pack: list[Condition]) -> int:
        """Returns the total number of `Command`s found in this `State`."""
        # Condition pass commands first. `conditions_to_pack` already includes every subcondition at every depth, so
        # one pass over it packs every condition's own pass commands exactly once.
        count = 0
        for condition in conditions_to_pack:
            count += condition.pack_pass_commands(writer)

        if self.enter_commands:
            writer.fill_with_position("enter_commands_offset", obj=self)
            for command in self.enter_commands:
                command.to_esd_writer(writer)
        else:
            writer.fill("enter_commands_offset", -1, obj=self)

        if self.exit_commands:
            writer.fill_with_position("exit_commands_offset", obj=self)
            for command in self.exit_commands:
                command.to_esd_writer(writer)
        else:
            writer.fill("exit_commands_offset", -1, obj=self)

        if self.ongoing_commands:
            writer.fill_with_position("ongoing_commands_offset", obj=self)
            for command in self.ongoing_commands:
                command.to_esd_writer(writer)
        else:
            writer.fill("ongoing_commands_offset", -1, obj=self)

        count += len(self.enter_commands) + len(self.exit_commands) + len(self.ongoing_commands)
        return count

    def pack_command_args(self, writer: BinaryWriter, conditions_to_pack: list[Condition]) -> int:
        """Returns the total number of `Command` arguments found in this `State`."""
        count = 0
        for condition in conditions_to_pack:
            count += condition.pack_pass_command_args(writer)
        for command in self.enter_commands:
            count += command.pack_args_offsets(writer)
        for command in self.exit_commands:
            count += command.pack_args_offsets(writer)
        for command in self.ongoing_commands:
            count += command.pack_args_offsets(writer)
        return count

    def pack_condition_test_data(self, writer: BinaryWriter, conditions_to_pack: list[Condition]):
        for condition in conditions_to_pack:
            condition.pack_test_data(writer)

    def pack_command_arg_data(self, writer: BinaryWriter, conditions_to_pack: list[Condition]):
        for condition in conditions_to_pack:
            condition.pack_pass_command_arg_data(writer)
        for command in self.enter_commands:
            command.pack_args_data(writer)
        for command in self.exit_commands:
            command.pack_args_data(writer)
        for command in self.ongoing_commands:
            command.pack_args_data(writer)

    def pack_condition_pointers(
        self,
        writer: BinaryWriter,
        all_condition_offsets: dict[Condition, int],
        recurred_conditions: set[Condition],
    ) -> int:
        """Returns total number of `Condition` pointers used in this `State`.

        Every `Condition` in this State gets a pointer, though several may point at one shared condition; each shared
        condition has its own subcondition pointers packed once (tracked in `recurred_conditions`).
        """
        if not self.conditions:
            writer.fill("condition_pointers_offset", -1, obj=self)
            return 0

        writer.fill_with_position("condition_pointers_offset", obj=self)
        count = 0
        for condition in self.conditions:
            try:
                condition_offset = all_condition_offsets[condition]
            except KeyError:
                raise ValueError(
                    f"Could not find condition of state {self.state_id} in packed conditions dictionary."
                ) from None
            writer.pack("v", condition_offset)
            count += 1
        for condition in self.conditions:
            if condition not in recurred_conditions:
                count += condition.pack_subconditions_pointers(writer, all_condition_offsets, recurred_conditions)
                recurred_conditions.add(condition)
        return count

    def __repr__(self) -> str:
        s = f"State[{self.state_id}](<{len(self.conditions)} conditions>"
        if self.enter_commands:
            s += f", <{len(self.enter_commands)} enter commands>"
        if self.ongoing_commands:
            s += f", <{len(self.ongoing_commands)} ongoing commands>"
        if self.exit_commands:
            s += f", <{len(self.exit_commands)} exit commands>"
        s += ")"
        return s
