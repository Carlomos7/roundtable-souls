"""Overhaul mods: their configs (data/overhauls/*.toml), read as OverhaulConfig. One description of each overhaul,
used to recognise it (Play-page detection, the offline launch's strip), to build it (mods.engine) and to place its
download in the launcher's layout (sources)."""

from roundtable_souls.overhauls import requirements, sources
from roundtable_souls.overhauls.config import (
    RECIPE_VERSION,
    Build,
    OverhaulConfig,
    Recognise,
    Requirement,
    load,
    local_dir,
    problems,
    read,
    recipe_sha256,
    schema,
    schema_path,
    write_schema,
)

__all__ = [
    "RECIPE_VERSION",
    "Build",
    "OverhaulConfig",
    "Recognise",
    "Requirement",
    "load",
    "local_dir",
    "problems",
    "read",
    "recipe_sha256",
    "requirements",
    "schema",
    "schema_path",
    "sources",
    "write_schema",
]
