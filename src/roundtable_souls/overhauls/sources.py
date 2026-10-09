"""An overhaul's download in the launcher's layout: which of its files its builds read, by role, and which it runs
with, from two tables in its config (docs/Overhaul configs.md):

    [builds.sources]   download path pattern -> "<role>/<path>": the files its builds read, by what they do with them
                       (mods.library.ROLES): merge (at game paths, merged on top of the profile's packages), text
                       (strings per language), hooks (script fragments), base (fallbacks used only when no package
                       has the file)
    [builds.runtime]   download path pattern -> path in its own folder: its DLLs, settings, assets

A pattern is a path with / where * stands for any part of one folder or file name and ** for any number of folders;
the target repeats the same wildcards in the same order and is filled with what they matched. When several
patterns of one table match a file, the one with the most fixed characters wins (a file named in full beats a
folder's **); a target of "" leaves the file out. Files neither table takes are not the overhaul's to keep.

Everything here is pure: translate() works on the download's file list, fingerprint_of() on file hashes; only
fingerprint() reads files. The fingerprint identifies a download (a config's verified versions are listed by it):
a sha256 over exactly the files the config takes, at their download paths, before translation, the same whatever
order the files are listed in.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from roundtable_souls.overhauls.config import Build

ROLES = ("merge", "text", "hooks", "base")  # mods.library's sources/<id>/ folders
_WILD = re.compile(r"\*\*|\*")


class TranslateError(ValueError):
    """A download the config's tables can't place: two patterns equally good for one file, or two files for one
    place."""


@dataclass(frozen=True)
class Pattern:
    """One row of a table: a download path pattern and where its files go ("" = left out)."""

    pattern: str
    target: str

    @property
    def fixed(self) -> int:
        """How specific it is: its characters other than wildcards."""
        return len(_WILD.sub("", self.pattern))

    def regex(self) -> re.Pattern[str]:
        parts = self.pattern.split("/")
        out = ""
        for i, part in enumerate(parts):
            last = i == len(parts) - 1
            if part == "**":
                out += "(.*)" if last else "(?:(.*)/)?"
                continue
            out += "".join("([^/]*)" if p == "*" else re.escape(p) for p in re.split(r"(\*)", part) if p)
            out += "" if last else "/"
        return re.compile(out, re.IGNORECASE)

    def place(self, path: str) -> str | None:
        """Where `path` goes under this row (its target filled in), "" when left out, None when it doesn't match."""
        m = self.regex().fullmatch(path)
        if m is None:
            return None
        if not self.target:
            return ""
        got = iter(m.groups())
        filled = _WILD.sub(lambda _w: next(got) or "", self.target)
        return re.sub("/{2,}", "/", filled).strip("/")


def problems(table: Mapping[str, str], *, roles: bool) -> list[str]:
    """What is wrong with a table's rows (empty when nothing): patterns and targets are relative paths without .. or
    backslashes, ** stands alone as a folder, the target repeats the pattern's wildcards in order, and with roles
    each target starts with a role."""
    out = []
    for pattern, target in table.items():
        for what, text in (("pattern", pattern), ("target", target)):
            if "\\" in text or text.startswith("/") or ":" in text or ".." in text.split("/"):
                out.append(f"{pattern}: the {what} must be a relative path with /, without ..")
            if any("**" in seg and seg != "**" for seg in text.split("/")):
                out.append(f"{pattern}: ** must be a whole folder name in the {what}")
        if not pattern:
            out.append("a pattern can't be empty")
        if target and _WILD.findall(target) != _WILD.findall(pattern):
            out.append(f"{pattern}: the target {target!r} must repeat the pattern's wildcards in the same order")
        if target and roles and target.split("/")[0] not in ROLES:
            out.append(f"{pattern}: the target {target!r} must start with one of {', '.join(ROLES)}")
    return out


def _place(table: Mapping[str, str], path: str) -> tuple[str, str] | None:
    """(pattern, where) of the most specific row matching path, or None. Two equally specific rows: refused."""
    hits = [(p, w) for p, w in ((Pattern(k, v), Pattern(k, v).place(path)) for k, v in table.items()) if w is not None]
    if not hits:
        return None
    best = max(p.fixed for p, _w in hits)
    top = [(p, w) for p, w in hits if p.fixed == best]
    if len({w for _p, w in top}) > 1:
        names = " and ".join(p.pattern for p, _w in top)
        raise TranslateError(f"{path} matches {names} equally; name the file in full to say where it goes")
    return top[0][0].pattern, top[0][1]


@dataclass(frozen=True)
class Translation:
    """A download in the launcher's layout. Each mapping is place -> the download path it comes from (its origin)."""

    sources: dict[str, str] = field(default_factory=dict)  # "<role>/<path>" -> download path
    runtime: dict[str, str] = field(default_factory=dict)  # path in overhauls/<id>/ -> download path
    dropped: list[str] = field(default_factory=list)  # left out on purpose (a target of "")
    untaken: list[str] = field(default_factory=list)  # matched by no row

    def taken(self) -> list[str]:
        """The download paths the config takes, each once, sorted: what the fingerprint covers."""
        return sorted({*self.sources.values(), *self.runtime.values()}, key=lambda p: (p.lower(), p))

    def role(self, name: str) -> dict[str, str]:
        """One role's files: path inside the role folder -> download path."""
        return {k.split("/", 1)[1]: v for k, v in self.sources.items() if k.split("/", 1)[0] == name and "/" in k}


def translate(download_files: Iterable[str], build: Build) -> Translation:
    """Where each of a download's files (paths relative to it, / or \\) goes under the build's [builds.sources] and
    [builds.runtime]. Raises TranslateError when two rows are equally good for a file or two files would land in one
    place."""
    out = Translation()
    for raw in sorted({str(f).replace("\\", "/").strip("/") for f in download_files}, key=lambda p: (p.lower(), p)):
        taken = False
        for table, into in ((build.sources, out.sources), (build.runtime, out.runtime)):
            hit = _place(table, raw)
            if hit is None:
                continue
            pattern, where = hit
            if not where:
                continue
            taken = True
            key = where.lower()
            clash = next((k for k in into if k.lower() == key), None)
            if clash is not None:
                raise TranslateError(f"{into[clash]} and {raw} would both become {where} ({pattern})")
            into[where] = raw
        if not taken:
            hit_any = any(_place(t, raw) is not None for t in (build.sources, build.runtime))
            (out.dropped if hit_any else out.untaken).append(raw)
    return out


def fingerprint_of(hashes: Mapping[str, str]) -> str:
    """The fingerprint of these files (download path -> sha256): order and slash direction don't change it."""
    rows = sorted((p.replace("\\", "/").strip("/").lower(), h.lower()) for p, h in hashes.items())
    return hashlib.sha256("".join(f"{p}\0{h}\n" for p, h in rows).encode()).hexdigest()


def download_files(download: Path) -> list[str]:
    """Every file in a download folder, relative, with /."""
    root = Path(download)
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def fingerprint(download: Path, build: Build) -> str:
    """The download's fingerprint for this build: over exactly the files its tables take, at download paths."""
    root = Path(download)
    hashes = {}
    for rel in translate(download_files(root), build).taken():
        h = hashlib.sha256()
        with (root / rel).open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        hashes[rel] = h.hexdigest()
    return fingerprint_of(hashes)
