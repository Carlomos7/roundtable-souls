"""The install plan's shape: what plan_mod_install found in a source and what install_mod would do with it, validated before the window sees it."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ModEntry(BaseModel):
    """One [[packages]] or [[natives]] block a plan would add."""

    kind: Literal["package", "native"]
    path: str
    id: str | None = None


class ModPlan(BaseModel):
    """What `plan_mod_install` found in a source and what `install_mod` would do with it."""

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    kind: Literal["package", "native", "profile", "unknown"]
    name: str
    root: Path
    staging: Path | None = None
    array_form: bool
    dest: Path | None = None
    entries: list[ModEntry] = Field(default_factory=list)
    exists: bool = False
    in_place: bool = False
    already_listed: list[str] = Field(default_factory=list)
    error: str | None = None
