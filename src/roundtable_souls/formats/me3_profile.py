"""me3 profiles (.me3): reading the [[packages]] / [[natives]] entries out of the text, in both shapes me3 accepts.

Hand-written profiles use [[packages]] / [[natives]] blocks; Nightreign Revive's installer writes packages = [ { ... } ]
and natives = [ { ... } ] instead. Text surgery on a profile (adding, removing, rewriting entries) is mods.profile_edit's;
this module only reads.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_BLOCK = re.compile(r"^[ \t]*\[\[(packages|natives)\]\][ \t]*$", re.I)
_ANY_TABLE = re.compile(r"^[ \t]*\[")
_ARRAY_KEY = re.compile(r"^[ \t]*(packages|natives|supports)[ \t]*=", re.I)


def blocks(text: str) -> list[dict]:
    """[[packages]] / [[natives]] blocks with line spans: {index, kind, start, end, lines, keys}. Comments are not blocks."""
    lines = text.splitlines(keepends=True)
    heads = [
        (i, "package" if m.group(1).lower() == "packages" else "native")
        for i, l in enumerate(lines)
        if (m := _BLOCK.match(l.rstrip("\r\n")))
    ]
    out = []
    for n, (i, kind) in enumerate(heads):
        j = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        # a following non-mod table ([supports] etc.) ends the block too
        for k in range(i + 1, j):
            if _ANY_TABLE.match(lines[k].rstrip("\r\n")) and not _BLOCK.match(lines[k].rstrip("\r\n")):
                j = k
                break
        out.append({"index": n, "kind": kind, "start": i, "end": j, "lines": lines[i:j]})
    return out


def is_array_form(text: str) -> bool:
    return not any(_BLOCK.match(l) for l in text.splitlines()) and any(_ARRAY_KEY.match(l) for l in text.splitlines())


def block_options(text: str, index: int) -> dict:
    """Parsed options of one block (via tomllib on that block alone)."""
    b = blocks(text)[index]
    body = "".join(b["lines"])
    try:
        data = tomllib.loads(body)
    except tomllib.TOMLDecodeError:
        return {"kind": b["kind"], "path": "", "id": "", "enabled": True}
    rows = data.get("packages") or data.get("natives") or [{}]
    row = rows[0] if isinstance(rows, list) else rows
    deps = lambda v: [
        {"id": d["id"], "optional": bool(d.get("optional", False))}
        if isinstance(d, dict)
        else {"id": str(d), "optional": True}
        for d in (v or [])
    ]
    return {
        "kind": b["kind"],
        "path": str(row.get("path") or ""),
        "id": str(row.get("id") or ""),
        "enabled": row.get("enabled", True) is not False,
        "optional": bool(row.get("optional", False)),
        "load_early": bool(row.get("load_early", False)),
        "initializer": row.get("initializer") if isinstance(row.get("initializer"), dict) else None,
        "finalizer": str(row.get("finalizer") or ""),
        "load_after": deps(row.get("load_after")),
        "load_before": deps(row.get("load_before")),
    }


def read_text(path: Path) -> str:
    """Profile text with its line endings intact (read_text would turn CRLF into LF)."""
    return Path(path).read_bytes().decode("utf-8", errors="replace")


def entry_ref(entry: dict) -> str:
    """The name other entries use in load_after / load_before: a package's id (its folder name when it has none),
    a native's DLL file name."""
    if entry.get("kind") == "package" and entry.get("id"):
        return entry["id"]
    return Path(entry.get("path") or "").name


def resolve(profile: Path, path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (Path(profile).parent / p)
