# Adapted from Soulstruct (https://github.com/Grimrukh/soulstruct), src/soulstruct/base/ezstate/esd/state.py at
# commit 12b69189a2ccebbc623a1b6565be89a18d6c9958 (version 2.6.0, 2026-09-27). Copyright (c) Scott Mooney
# (Grimrukh). Licensed under the GNU General Public License v3.0 or later, as is Roundtable Souls.
#
# Modified for Roundtable Souls, 2026-10-01:
#   - imports constrata directly instead of soulstruct.utilities.binary (a re-export of it);
#   - removed the ESP script and HTML output (to_esp, to_html, html_title_bar), the EZL register helper they
#     used, and the ESD_TYPE class variable (talk/chr only selected function names for that output);
#   - reading takes the offsets of the machine's states and the conditions of the machine read so far (see
#     condition.py);
#   - writing: the file's table order is now set by core.py, so the pack_* methods that set it (pack_conditions,
#     pack_commands, pack_command_args, pack_condition_test_data, pack_command_arg_data) and copy() were removed;
#     pack_own_commands packs the state's enter, exit and ongoing commands; pack_condition_pointers packs the
#     state's own list only, with conditions found by object.

"""One state of an ESD state machine: its ID, its conditions in order, and its enter, exit and ongoing commands."""

from __future__ import annotations

__all__ = ["State"]

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
    def from_esd_reader(
        cls, reader: BinaryReader, states: tp.Container[int], read: dict[int, Condition] | None = None
    ) -> tp.Self:
        """Unpack a `State` from ESD file binary. `states`: the offsets of its machine's states; `read`: the
        conditions of its machine read so far, by offset (see Condition.from_esd_reader)."""
        read = {} if read is None else read

        header = StateStruct.from_bytes(reader)
        next_state_offset = reader.position  # reset at end of this call

        conditions = []
        if header.condition_pointers_offset != -1:  # otherwise, state has no conditions
            reader.seek(header.condition_pointers_offset)
            condition_offsets = reader.unpack(f"{header.condition_pointers_count}v")
            for offset in condition_offsets:
                reader.seek(offset)
                conditions.append(Condition.from_esd_reader(reader, states, read))

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

    def to_esd_writer(self, writer: BinaryWriter):
        StateStruct.object_to_writer(
            self,
            writer,
            condition_pointers_count=len(self.conditions),
            enter_commands_count=len(self.enter_commands),
            exit_commands_count=len(self.exit_commands),
            ongoing_commands_count=len(self.ongoing_commands),
        )

    def pack_own_commands(self, writer: BinaryWriter) -> list[Command]:
        """Pack this state's enter, exit and ongoing commands, in that order. Returns them."""
        for name, commands in (
            ("enter_commands_offset", self.enter_commands),
            ("exit_commands_offset", self.exit_commands),
            ("ongoing_commands_offset", self.ongoing_commands),
        ):
            if commands:
                writer.fill_with_position(name, obj=self)
                for command in commands:
                    command.to_esd_writer(writer)
            else:
                writer.fill(name, -1, obj=self)
        return [*self.enter_commands, *self.exit_commands, *self.ongoing_commands]

    def pack_condition_pointers(
        self,
        writer: BinaryWriter,
        all_condition_offsets: dict[int, int],
    ) -> int:
        """Pack this state's list of condition pointers. Returns how many pointers."""
        if not self.conditions:
            writer.fill("condition_pointers_offset", -1, obj=self)
            return 0

        writer.fill_with_position("condition_pointers_offset", obj=self)
        count = 0
        for condition in self.conditions:
            try:
                condition_offset = all_condition_offsets[id(condition)]
            except KeyError:
                raise ValueError(
                    f"Could not find condition of state {self.state_id} in packed conditions dictionary."
                ) from None
            writer.pack("v", condition_offset)
            count += 1
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
