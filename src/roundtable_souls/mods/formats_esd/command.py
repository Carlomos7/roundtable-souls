# Adapted from Soulstruct (https://github.com/Grimrukh/soulstruct), src/soulstruct/base/ezstate/esd/command.py at
# commit 12b69189a2ccebbc623a1b6565be89a18d6c9958 (version 2.6.0, 2026-09-27). Copyright (c) Scott Mooney
# (Grimrukh). Licensed under the GNU General Public License v3.0 or later, as is Roundtable Souls.
#
# Modified for Roundtable Souls, 2026-10-01:
#   - imports constrata directly instead of soulstruct.utilities.binary (a re-export of it);
#   - removed the ESP script and HTML output (to_esp, to_html) and with them the command name tables
#     (functions.py) and the EZL decompiler (ezl_parser.py), and the _indent field;
#   - __eq__ also compares the number of arguments: before, zip() let two commands whose arguments differed only in
#     count compare equal.

"""A command an ESD state runs: a bank and index (which function) and its arguments, each kept as opaque EZL bytes."""

from __future__ import annotations

__all__ = ["Command"]

import typing as tp
from dataclasses import dataclass, field

from constrata import BinaryReader, BinaryStruct, BinaryWriter, varint


class CommandStruct(BinaryStruct):
    bank: int
    index: int
    args_offset: varint
    args_count: varint


class CommandArgsStruct(BinaryStruct):
    arg_ezl_offset: varint
    arg_ezl_size: varint


@dataclass(slots=True)
class Command:
    bank: int
    index: int
    args: list[bytearray] = field(default_factory=list)

    @classmethod
    def from_esd_reader(cls, reader: BinaryReader) -> tp.Self:
        header = CommandStruct.from_bytes(reader)

        args = []
        if header.args_offset > 0:
            with reader.temp_offset(header.args_offset):
                for _ in range(header.args_count):
                    arg_struct = CommandArgsStruct.from_bytes(reader)
                    args_bytes = reader.unpack_bytes(length=arg_struct.arg_ezl_size, offset=arg_struct.arg_ezl_offset)
                    args.append(bytearray(args_bytes))

        return cls(header.bank, header.index, args)

    def to_esd_writer(self, writer: BinaryWriter):
        CommandStruct.object_to_writer(self, writer, args_count=len(self.args))

    def pack_args_offsets(self, writer: BinaryWriter) -> int:
        """Pack offsets to packed EZL arg data. Returns number of args."""
        if not self.args:
            writer.fill("args_offset", -1, obj=self)
            return 0

        writer.fill_with_position("args_offset", obj=self)
        for arg_bytearray in self.args:
            # Offsets are reserved using the bytes object IDs, so we don't use `CommandArgsStruct`.
            writer.reserve("arg_ezl_offset", "v", obj=arg_bytearray)
            writer.pack("v", len(arg_bytearray))
        return len(self.args)

    def pack_args_data(self, writer: BinaryWriter):
        """Pack EZL bytes."""
        for arg_bytearray in self.args:
            writer.fill_with_position("arg_ezl_offset", obj=arg_bytearray)
            writer.append(arg_bytearray)

    def __hash__(self):
        return hash((self.bank, self.index, tuple(bytes(a) for a in self.args)))

    def __eq__(self, other_command: object):
        if not isinstance(other_command, Command):
            return NotImplemented
        return (
            self.bank == other_command.bank
            and self.index == other_command.index
            and len(self.args) == len(other_command.args)
            and all(bytes(a) == bytes(b) for a, b in zip(self.args, other_command.args, strict=True))
        )
