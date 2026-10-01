"""Elden Ring ESD (EzState) files, read and written structurally.

Adapted from the ESD reader and writer of Soulstruct by Scott Mooney (Grimrukh), https://github.com/Grimrukh/soulstruct,
at commit 12b69189a2ccebbc623a1b6565be89a18d6c9958 (version 2.6.0), GPL-3.0-or-later. Only reading and writing were
taken; each file states its source and what was changed. Binary plumbing is constrata (MIT), by the same author. Not
yet used by the launcher's merging.
"""

from .command import Command
from .condition import Condition
from .core import ESD, read_esd, write_esd
from .state import State

__all__ = ["ESD", "Command", "Condition", "State", "read_esd", "write_esd"]
