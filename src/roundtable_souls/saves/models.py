"""Shapes of the save data that crosses layer boundaries: findings and save info (the install plan is mods/models.py).

The producers build plain dicts (the window and the tests read them as dicts) and validate them against
these models before handing them over, so a missing key or a wrong type fails at the source, not in a widget.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Level = Literal["ok", "info", "warn", "error"]


class Finding(BaseModel):
    """One line of the save health report."""

    model_config = ConfigDict(extra="allow")

    level: Level
    code: str
    title: str
    detail: str = ""


class CharacterStats(BaseModel):
    vig: int
    mind: int
    end: int
    str: int
    dex: int
    int: int
    fai: int
    arc: int


class Character(BaseModel):
    """An active slot as the Play and Saves pages show it."""

    model_config = ConfigDict(extra="allow")

    slot: int = Field(ge=1, le=10)
    name: str
    level: int
    body: str
    hp: int
    runes: int
    ok: bool
    where: str
    torrent: str
    stats: CharacterStats


class UnreadableSlot(BaseModel):
    slot: int = Field(ge=1, le=10)
    name: str
    level: int
    ver: int
    error: str


class ChecksumPlan(BaseModel):
    slots: list[int]
    ud10: bool


class SaveInfo(BaseModel):
    """Everything `core.save_info` reports about one save file. Read-only plans say what each repair would do."""

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    path: Path
    name: str
    kind: Literal["Seamless Co-op", "Standard"]
    modified: str
    block: str
    error: str | None
    needs_repair: bool
    convert_ok: bool
    findings: list[Finding]
    characters: list[Character]
    unreadable: list[UnreadableSlot] = Field(default_factory=list)
    checksum_fixes: ChecksumPlan
    vanilla_plan: list[Any]
    loading_plan: list[Any]
    tarnished_flag: bool | None = None
    dlc_owned: bool | None = None
