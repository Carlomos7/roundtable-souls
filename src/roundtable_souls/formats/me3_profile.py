"""me3 profiles (.me3): reading the [[packages]] / [[natives]] entries out of the text, in both shapes me3 accepts.

Hand-written profiles use [[packages]] / [[natives]] blocks; Nightreign Revive's installer writes packages = [ { ... } ]
and natives = [ { ... } ] instead. Text surgery on a profile (adding, removing, rewriting entries) is mods.profile_edit's;
this module reads, and renders one entry as a block (entry_lines, to_blocks).
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


def quote(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _path_lit(p: str) -> str:
    p = str(p).replace("\\", "/")
    return "'" + p + "'" if "'" not in p else quote(p)


def dep_list(deps, nl: str = "", tall: bool = False) -> str:
    """A load order list; with nl, written one entry per line when tall or longer than two entries."""
    items = []
    for d in deps or []:
        if isinstance(d, str):
            d = {"id": d, "optional": True}
        items.append(
            "{ id = " + quote(d["id"]) + ", optional = " + ("true" if d.get("optional", True) else "false") + " }"
        )
    if nl and items and (tall or len(items) > 2):
        return "[" + nl + "".join(f"  {i},{nl}" for i in items) + "]"
    return "[" + ", ".join(items) + "]"


def entry_lines(kind: str, row: dict, nl: str) -> list[str]:
    out = [f"[[{'packages' if kind == 'package' else 'natives'}]]{nl}"]
    if kind == "package" and row.get("id"):
        out.append(f"id = {quote(row['id'])}{nl}")
    out.append(f"path = {_path_lit(row['path'])}{nl}")
    if row.get("enabled") is False:
        out.append(f"enabled = false{nl}")
    if kind == "native":
        if row.get("optional"):
            out.append(f"optional = true{nl}")
        if row.get("load_early"):
            out.append(f"load_early = true{nl}")
        init = row.get("initializer")
        if isinstance(init, dict):
            if init.get("function"):
                out.append(f"initializer = {{ function = {quote(init['function'])} }}{nl}")
            elif isinstance(init.get("delay"), dict) and init["delay"].get("ms") is not None:
                out.append(f"initializer = {{ delay = {{ ms = {int(init['delay']['ms'])} }} }}{nl}")
        if row.get("finalizer"):
            out.append(f"finalizer = {quote(row['finalizer'])}{nl}")
    if row.get("load_after"):
        out.append(f"load_after = {dep_list(row['load_after'])}{nl}")
    if row.get("load_before"):
        out.append(f"load_before = {dep_list(row['load_before'])}{nl}")
    return out


def to_blocks(text: str) -> str:
    """Rewrite an inline-array profile (Revive's shape) as [[packages]] / [[natives]] blocks."""
    data = tomllib.loads(text)
    nl = "\r\n" if "\r\n" in text else "\n"
    out = []
    for key in ("profileVersion", "savefile", "start_online", "disable_arxan", "mem_patch", "mem_patch_heap_size"):
        if key in data:
            v = data[key]
            lit = "true" if v is True else "false" if v is False else str(v) if isinstance(v, int) else quote(v)
            out.append(f"{key} = {lit}{nl}")
    for sup in data.get("supports") or []:
        if isinstance(sup, dict) and sup.get("game"):
            out.append(f"{nl}[[supports]]{nl}game = {quote(sup['game'])}{nl}")
    for key, kind in (("natives", "native"), ("packages", "package")):
        rows = data.get(key) or []
        if isinstance(rows, dict):
            rows = [rows]
        for row in rows:
            if isinstance(row, dict) and _path_of(row):
                out.append(nl)
                out.extend(entry_lines(kind, {**row, "path": _path_of(row)}, nl))
    return "".join(out)


def _block_row(b: dict) -> dict | None:
    """One block's own table, parsed on its own (a broken block does not hide the others); None when it does not
    parse."""
    try:
        data = tomllib.loads("".join(b["lines"]))
    except tomllib.TOMLDecodeError:
        return None
    rows = data.get("packages") or data.get("natives") or [{}]
    row = rows[0] if isinstance(rows, list) else rows
    return row if isinstance(row, dict) else {}


def block_options(text: str, index: int) -> dict:
    """Parsed options of one block (via tomllib on that block alone)."""
    b = blocks(text)[index]
    row = _block_row(b)
    return _options(b["kind"], row)


def _options(kind: str, row: dict | None) -> dict:
    if row is None:
        return {"kind": kind, "path": "", "id": "", "enabled": True}
    deps = lambda v: [
        {"id": d["id"], "optional": bool(d.get("optional", False))}
        if isinstance(d, dict)
        else {"id": str(d), "optional": True}
        for d in (v or [])
    ]
    return {
        "kind": kind,
        "path": _path_of(row),
        "id": str(row.get("id") or ""),
        "enabled": row.get("enabled", True) is not False,
        "optional": bool(row.get("optional", False)),
        "load_early": bool(row.get("load_early", False)),
        "initializer": row.get("initializer") if isinstance(row.get("initializer"), dict) else None,
        "finalizer": str(row.get("finalizer") or ""),
        "load_after": deps(row.get("load_after")),
        "load_before": deps(row.get("load_before")),
    }


def _path_of(row: dict) -> str:
    """An entry's path; me3 also takes it under the older name source."""
    return str(row.get("path") or row.get("source") or "")


def parses(text: str) -> bool:
    """Whether the whole file is valid TOML: me3 refuses a profile that is not, however readable its entries are."""
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return False
    return True


def entries(text: str) -> list[dict]:
    """Every [[packages]] / [[natives]] entry, enabled or not, in file order: its options (block_options), 'index'
    (the block number the edits in mods.profile_edit address), 'name' (its id, else its file or folder name) and
    'row' (its own table as written; None when that block does not parse). enabled defaults to true. A commented-out
    entry is a comment, not an entry. An inline-array profile is read as to_blocks writes it, so its indexes are the
    ones an edit sees after converting it; it raises tomllib.TOMLDecodeError when it does not parse."""
    if is_array_form(text):
        text = to_blocks(text)
    out = []
    for b in blocks(text):
        row = _block_row(b)
        o = _options(b["kind"], row)
        o["index"] = b["index"]
        o["name"] = o["id"] or Path(o["path"]).name or f"entry {b['index'] + 1}"
        o["row"] = row
        out.append(o)
    return out


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
