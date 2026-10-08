"""me3 profiles and the mods they list.

profile (reading a profile), profile_edit (editing its text), profile_writer (the one writer every change goes
through, with its rules), order (me3's load order, and keeping the mod that must stay last after the others),
install, extract, remove and checks (installing, unpacking, removing, and what is wrong with a profile's entries),
conflicts (which file wins), rebuild (merged parameters and files), history and undo, configs (a DLL's settings
files), profile_settings, models (the install plan's shape). engine and backends are the setup engines Phase 6
replaces."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from roundtable_souls.mods import (
        backends,
        checks,
        configs,
        conflicts,
        engine,
        extract,
        history,
        install,
        models,
        order,
        profile,
        profile_edit,
        profile_settings,
        profile_writer,
        rebuild,
        remove,
        undo,
    )

__all__ = [
    "checks",
    "configs",
    "conflicts",
    "engine",
    "extract",
    "history",
    "install",
    "models",
    "order",
    "profile",
    "profile_edit",
    "profile_settings",
    "profile_writer",
    "rebuild",
    "remove",
    "undo",
    "backends",
]
