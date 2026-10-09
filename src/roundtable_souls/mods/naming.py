"""What the launcher calls the folders it makes, in one place: mod ids, the names Windows refuses, the launcher's own
reserved names, ids made unique against the ones taken, and how long a path may get.

    mod_id        a mod's name as the launcher's folder name: lowercase kebab-case ASCII, version tokens and Nexus's
                  numeric suffix removed ("Elden Ring Reforged v1.4.6" -> "elden-ring-reforged")
    unsafe        why Windows would refuse a name (a device name such as CON or COM1, a trailing dot or space, a
                  character it does not allow), or None
    unique        an id not yet taken: the id, else the id with -2, -3, ...
    path_problem  why a folder is too deep for Windows once its files are inside (one limit for every check)

These are the names of the launcher's own layout (mods.library). Today's installs still name their folders with
mods.profile_edit.slug, which keeps the name's case; a mod's own files and folders are never renamed.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path

# "Hair 13-561-1-1-1648994275": the Nexus mod id, its version and the upload time, added to the download's name
NEXUS_SUFFIX = re.compile(r"-\d+-[\d-]+-\d{10}$")

# Version tokens in a mod's name: v2, v1.4.6, ver 2.1, version 3, 0.1.33-rc3, 1.2b, 2.0 beta 4.
_VERSION = re.compile(
    r"(?<![a-z0-9])(?:v|ver|version)[ ._-]?\d+(?:[._]\d+)*[a-z]?(?:[ ._-]?(?:alpha|beta|rc|pre|hotfix|fix|patch)[ ._-]?\d*)?"
    r"(?![a-z0-9])"
    r"|(?<![a-z0-9])\d+(?:\.\d+)+[a-z]?(?:[ ._-]?(?:alpha|beta|rc|pre|hotfix|fix|patch)[ ._-]?\d*)?(?![a-z0-9])",
    re.IGNORECASE,
)

ID_LENGTH = 48  # the longest id the launcher makes, suffixes included
FALLBACK = "mod"  # a name with nothing usable in it

# Names Windows gives to devices, with or without an extension (con.txt is the console too); superscript digits count.
_DEVICES = {"con", "prn", "aux", "nul", "conin$", "conout$"} | {
    f"{p}{d}" for p in ("com", "lpt") for d in "123456789¹²³"
}
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Names the launcher uses for its own folders: no mod id may take them.
RESERVED = frozenset({"combined-parameters", "profiles", "packages", "natives", "overhauls", "sources", "builds"})

# How long a path may get. Windows refuses most paths of 260 characters or more; the launcher keeps the deepest file
# below what it adds under MAX_PATH, and assumes ROOM characters for a mod's files while they are not known yet.
MAX_PATH = 220
ROOM = 40


def mod_id(name: str) -> str:
    """The launcher's id for a mod called `name`: lowercase kebab-case ASCII without version tokens or Nexus's suffix,
    at most ID_LENGTH characters, never a Windows device name ("mod" when nothing is left)."""
    base = NEXUS_SUFFIX.sub("", name.strip())
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    base = _VERSION.sub(" ", base).replace("'", "")  # Clever's -> clevers
    out = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    out = out[:ID_LENGTH].rstrip("-") or FALLBACK
    return f"{out}-mod" if out in _DEVICES else out


def unsafe(name: str) -> str | None:
    """Why Windows would refuse `name` as a file or folder name, or None when it is fine."""
    if not name or name in (".", ".."):
        return "a name can't be empty or only dots"
    bad = _ILLEGAL.search(name)
    if bad is not None:
        shown = repr(bad.group()) if bad.group() < " " else bad.group()
        return f"Windows doesn't allow {shown} in a name"
    if name[-1] in ". ":
        return "Windows doesn't allow a name to end with a dot or a space"
    if name.split(".")[0].rstrip(" ").lower() in _DEVICES:
        return f"{name.split('.')[0]} is a name Windows keeps for a device"
    return None


def unique(ident: str, taken: Iterable[str]) -> str:
    """`ident`, or `ident`-2, -3, ... when it is taken (case aside) or is one of the launcher's reserved names; the
    result stays within ID_LENGTH characters."""
    used = {t.lower() for t in taken} | RESERVED
    if ident.lower() not in used:
        return ident
    n = 2
    while True:
        tail = f"-{n}"
        cand = ident[: ID_LENGTH - len(tail)].rstrip("-") + tail
        if cand.lower() not in used:
            return cand
        n += 1


def deepest(folder: str | Path, inside: int | None = None) -> int:
    """How long the deepest file path below `folder` is: the folder, a separator and the longest path inside it (ROOM
    when that is not known)."""
    return len(str(folder)) + 1 + (inside or ROOM)


def path_problem(folder: str | Path, inside: int | None = None) -> str | None:
    """Why `folder` is too deep a place for its files (the deepest path over MAX_PATH), in plain words, or None."""
    n = deepest(folder, inside)
    if n <= MAX_PATH:
        return None
    return (
        f"{folder} is too long a path for Windows ({n} characters with the files inside; {MAX_PATH} are safe). Use a "
        "shorter folder name, or a profile folder closer to the drive's root."
    )
