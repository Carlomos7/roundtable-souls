"""Install, remove and configure mods in a me3 profile, and create or delete profiles.

A folder is a *package* when it holds game asset folders (parts, chr,
msg, ...) or regulation.bin, a *native* when it holds DLLs and no assets, a whole *me3 profile* when it
contains a .me3 file. Single-folder wrappers (the usual zip layout) are unwrapped first.

Profile edits are text-level so comments and order survive: new [[packages]] / [[natives]] blocks go
at the end (later loads later, so a new mod overrides what is above it), and per-mod options rewrite
only the keys inside one block. Profiles in the inline-array form Revive's installer writes are
converted to blocks first (that form has no comments to lose).
"""

from __future__ import annotations

import re
import shutil
import time
import tomllib
from pathlib import Path

NATIVE_OPTION_KEYS = ("enabled", "optional", "load_early", "initializer", "finalizer", "load_after", "load_before")
PACKAGE_OPTION_KEYS = ("enabled", "id", "load_after", "load_before")
_BLOCK = re.compile(r"^[ \t]*\[\[(packages|natives)\]\][ \t]*$", re.I)
_ANY_TABLE = re.compile(r"^[ \t]*\[")
_KEY = re.compile(r"^[ \t]*([A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*(.*)$")
_ARRAY_KEY = re.compile(r"^[ \t]*(packages|natives|supports)[ \t]*=", re.I)


class ModError(Exception):
    pass


# ----------------------------------------------------------------------------- detection


# ----------------------------------------------------------------------------- archives


# ----------------------------------------------------------------------------- profile text
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


def _q(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _path_lit(p: str) -> str:
    p = str(p).replace("\\", "/")
    return "'" + p + "'" if "'" not in p else _q(p)


def _dep_list(deps, nl: str = "", tall: bool = False) -> str:
    """A load order list; with nl, written one entry per line when tall or longer than two entries."""
    items = []
    for d in deps or []:
        if isinstance(d, str):
            d = {"id": d, "optional": True}
        items.append(
            "{ id = " + _q(d["id"]) + ", optional = " + ("true" if d.get("optional", True) else "false") + " }"
        )
    if nl and items and (tall or len(items) > 2):
        return "[" + nl + "".join(f"  {i},{nl}" for i in items) + "]"
    return "[" + ", ".join(items) + "]"


def _entry_lines(kind: str, row: dict, nl: str) -> list[str]:
    out = [f"[[{'packages' if kind == 'package' else 'natives'}]]{nl}"]
    if kind == "package" and row.get("id"):
        out.append(f"id = {_q(row['id'])}{nl}")
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
                out.append(f"initializer = {{ function = {_q(init['function'])} }}{nl}")
            elif isinstance(init.get("delay"), dict) and init["delay"].get("ms") is not None:
                out.append(f"initializer = {{ delay = {{ ms = {int(init['delay']['ms'])} }} }}{nl}")
        if row.get("finalizer"):
            out.append(f"finalizer = {_q(row['finalizer'])}{nl}")
    if row.get("load_after"):
        out.append(f"load_after = {_dep_list(row['load_after'])}{nl}")
    if row.get("load_before"):
        out.append(f"load_before = {_dep_list(row['load_before'])}{nl}")
    return out


def to_blocks(text: str) -> str:
    """Rewrite an inline-array profile (Revive's shape) as [[packages]] / [[natives]] blocks."""
    data = tomllib.loads(text)
    nl = "\r\n" if "\r\n" in text else "\n"
    out = []
    for key in ("profileVersion", "savefile", "start_online", "disable_arxan", "mem_patch", "mem_patch_heap_size"):
        if key in data:
            v = data[key]
            lit = "true" if v is True else "false" if v is False else str(v) if isinstance(v, int) else _q(v)
            out.append(f"{key} = {lit}{nl}")
    for sup in data.get("supports") or []:
        if isinstance(sup, dict) and sup.get("game"):
            out.append(f"{nl}[[supports]]{nl}game = {_q(sup['game'])}{nl}")
    for key, kind in (("natives", "native"), ("packages", "package")):
        rows = data.get(key) or []
        if isinstance(rows, dict):
            rows = [rows]
        for row in rows:
            if isinstance(row, dict) and row.get("path"):
                out.append(nl)
                out.extend(_entry_lines(kind, row, nl))
    return "".join(out)


def _strip_key(lines: list[str], key: str) -> list[str]:
    """Remove a key from a block's lines, including a multi-line [ ... ] value."""
    out = []
    skipping = False
    depth = 0
    for l in lines:
        body = l.rstrip("\r\n")
        if skipping:
            depth += body.count("[") - body.count("]")
            if depth <= 0:
                skipping = False
            continue
        m = _KEY.match(body)
        if m and m.group(1) == key:
            val = m.group(2)
            depth = val.count("[") - val.count("]")
            if depth > 0:
                skipping = True
            continue
        out.append(l)
    return out


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


def set_block_options(text: str, index: int, opts: dict) -> str:
    """Rewrite the option keys of one block; path and comments stay. Keys absent from opts are left alone;
    keys given as None / False / empty are removed (me3's defaults)."""
    bl = blocks(text)
    b = bl[index]
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = list(b["lines"])
    keys = NATIVE_OPTION_KEYS if b["kind"] == "native" else PACKAGE_OPTION_KEYS
    new = []
    for key in keys:
        if key not in opts:
            continue
        v = opts[key]
        was = next((i for i, l in enumerate(lines) if (m := _KEY.match(l.rstrip("\r\n"))) and m.group(1) == key), None)
        lines_was = lines[was] if was is not None else ""
        lines = _strip_key(lines, key)
        before = len(new)  # a key that was there is rewritten where it was
        if key == "enabled":
            if v is False:
                new.append(f"enabled = false{nl}")
        elif key in ("optional", "load_early"):
            if v:
                new.append(f"{key} = true{nl}")
        elif key == "id":
            if not v:  # blank: keep whatever the block had
                cur = block_options(text, index).get("id")
                if cur:
                    new.append(f"id = {_q(cur)}{nl}")
            else:
                new.append(f"id = {_q(v)}{nl}")
        elif key == "finalizer":
            if v:
                new.append(f"finalizer = {_q(v)}{nl}")
        elif key == "initializer":
            if isinstance(v, dict) and v.get("function"):
                new.append(f"initializer = {{ function = {_q(v['function'])} }}{nl}")
            elif isinstance(v, dict) and isinstance(v.get("delay"), dict) and v["delay"].get("ms") is not None:
                new.append(f"initializer = {{ delay = {{ ms = {int(v['delay']['ms'])} }} }}{nl}")
        elif key in ("load_after", "load_before"):
            if v:
                tall = was is not None and lines_was.rstrip().endswith("[")  # keep a one-per-line list that way
                new.append(f"{key} = {_dep_list(v, nl, tall)}{nl}")
        if was is not None:
            lines[was:was] = new[before:]
            del new[before:]
    # insert new keys right after the path line (or the header)
    at = 1
    for i, l in enumerate(lines):
        m = _KEY.match(l.rstrip("\r\n"))
        if m and m.group(1) == "path":
            at = i + 1
            break
    if at < len(lines) and not lines[at - 1].endswith(("\n", "\r\n")):
        lines[at - 1] += nl
    lines[at:at] = new
    all_lines = text.splitlines(keepends=True)
    all_lines[b["start"] : b["end"]] = lines
    return "".join(all_lines)


_COMMENTED_TOML = re.compile(r"^\s*#+\s*(?:\[|\]|\{|[A-Za-z_][\w.-]*\s*=)")


def _commented_entry(line: str) -> bool:
    """A comment line that is a commented-out entry or key (# [[packages]], # id = "x", # ]), not a note: a note may
    mention a setting (full_search = 0) but does not start with one."""
    return bool(_COMMENTED_TOML.match(line))


def entry_span(text: str, index: int) -> tuple[int, int]:
    """The lines [start, end) block `index` owns: the comment lines directly above its header (up to a blank line or
    a commented-out entry) and its body up to its last key line, comments inside it included. The blank lines after
    it, and comments that describe the next entry, belong to what follows."""
    b = blocks(text)[index]
    lines = text.splitlines(keepends=True)
    start = b["start"]
    while start > 0:
        prev = lines[start - 1]
        if not prev.strip().startswith("#") or _commented_entry(prev):
            break
        start -= 1
    end = b["start"] + 1
    for k in range(b["start"] + 1, b["end"]):
        body = lines[k].strip()
        if body and not body.startswith("#"):
            end = k + 1
    return start, end


CONTEXT = 3  # lines of context remembered on each side of a removed entry


def remove_entry(text: str, index: int) -> tuple[str, str, dict]:
    """Take block `index` out with its own comments (entry_span), leaving the entries around it and their comments
    as they were. Returns (new text, the text taken out, where it was: {prev, next, next_ref})."""
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    start, end = entry_span(text, index)
    chunk = "".join(lines[start:end])
    if not chunk.endswith(("\n", "\r\n")):
        chunk += nl
    after = end
    while after < len(lines) and not lines[after].strip():
        after += 1
    blank_above = start == 0 or not lines[start - 1].strip()
    joiner = [] if blank_above or after >= len(lines) else [nl]
    new_lines = lines[:start] + joiner + lines[after:]
    if after >= len(lines):  # it was the last thing in the file: no trailing blank lines left behind
        while new_lines and not new_lines[-1].strip():
            new_lines.pop()
    prev = next((lines[k].strip() for k in range(start - 1, -1, -1) if lines[k].strip()), "")
    nxt = lines[after].strip() if after < len(lines) else ""
    following = [x for x in blocks(text) if x["index"] > index]
    next_ref = None
    if following:
        o = block_options(text, following[0]["index"])
        next_ref = {"kind": o["kind"], "ref": entry_ref({**o, "kind": o["kind"]}), "path": o["path"]}
    new_text = "".join(new_lines)
    if new_text and not new_text.endswith(("\n", "\r\n")) and text.endswith(("\n", "\r\n")):
        new_text += nl
    gap_above = 0
    k = start - 1
    while k >= 0 and not lines[k].strip():
        gap_above, k = gap_above + 1, k - 1
    above = [lines[k].strip() for k in range(start - 1, -1, -1) if lines[k].strip()][:CONTEXT]
    below = [lines[k].strip() for k in range(after, len(lines)) if lines[k].strip()][:CONTEXT]
    where = {
        "prev": prev,
        "next": nxt,
        "above": above,  # nearest first
        "below": below,
        "next_ref": next_ref,
        "gap_above": gap_above,
        "gap_below": after - end,
    }
    return new_text, chunk, where


def remove_block(text: str, index: int) -> str:
    """The text without block `index` and its own comments (see remove_entry)."""
    return remove_entry(text, index)[0]


def restore_entry(text: str, chunk: str, where: dict) -> str:
    """Put an entry taken out by remove_entry back: between the same two lines when they still sit together, else
    just above the entry that followed it (and that entry's comments), else after the line that preceded it, else at
    the end."""
    nl = "\r\n" if "\r\n" in text else "\n"
    chunk = chunk.replace("\r\n", "\n").replace("\n", nl)
    lines = text.splitlines(keepends=True)
    prev, nxt = where.get("prev") or "", where.get("next") or ""

    gap_above = int(where.get("gap_above", 1))
    gap_below = int(where.get("gap_below", 1))

    def put(at: int) -> str:
        """Insert at line `at`, with the blank lines the entry had above and below it (as far as they are not
        already there)."""
        before = list(lines[:at])
        after = list(lines[at:])
        if before and not before[-1].endswith(("\n", "\r\n")):
            before[-1] += nl
        have_above = 0
        while have_above < len(before) and not before[len(before) - 1 - have_above].strip():
            have_above += 1
        lead = [nl] * max(0, gap_above - have_above) if before else []
        tail = [nl] * gap_below if after else []
        return "".join(before + lead + [chunk] + tail + after)

    above, below = where.get("above") or ([prev] if prev else []), where.get("below") or ([nxt] if nxt else [])
    if above or below:
        # The best place is where the lines around it are the ones it had: every nearby line that matches scores,
        # the nearest ones most, so a line repeated all over the file (enabled = false) cannot win on its own.
        nonblank = [i for i, line in enumerate(lines) if line.strip()]
        best, best_score = None, 0.0
        for pos in range(len(nonblank) + 1):
            at = nonblank[pos] if pos < len(nonblank) else len(lines)
            score = 0.0
            for n, want in enumerate(above):
                k = pos - 1 - n
                if k < 0 or lines[nonblank[k]].strip() != want:
                    break
                score += 1.0 / (n + 1)
            for n, want in enumerate(below):
                k = pos + n
                if k >= len(nonblank) or lines[nonblank[k]].strip() != want:
                    break
                score += 1.0 / (n + 1)
            if score > best_score:
                best, best_score = at, score
        full = sum(1.0 / (n + 1) for n in range(len(above))) + sum(1.0 / (n + 1) for n in range(len(below)))
        if best is not None and best_score >= 0.6 * full:
            return put(best)
    ref = where.get("next_ref") or {}
    if ref:
        for b in blocks(text):
            o = block_options(text, b["index"])
            if o["kind"] == ref.get("kind") and (
                entry_ref({**o, "kind": o["kind"]}) == ref.get("ref") or (o["path"] and o["path"] == ref.get("path"))
            ):
                return put(entry_span(text, b["index"])[0])
    if prev:
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() == prev:
                return put(i + 1)
    return put(len(lines))


def insert_entry(text: str, kind: str, row: dict, before: int) -> str:
    """Add an entry just above block number `before` (and above the comment lines that describe that block)."""
    b = next((x for x in blocks(text) if x["index"] == before), None)
    if b is None:
        return append_entry(text, kind, row)
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    at = b["start"]
    while at > 0:
        prev = lines[at - 1].strip()
        if not prev.startswith("#") or _commented_entry(prev):
            break  # a blank line, a real line, or a commented-out entry: the note above ends here
        at -= 1
    new = "".join(_entry_lines(kind, row, nl)) + nl
    return "".join(lines[:at]) + new + "".join(lines[at:])


def append_entry(text: str, kind: str, row: dict) -> str:
    nl = "\r\n" if "\r\n" in text else "\n"
    if text and not text.endswith(("\n", "\r\n")):
        text += nl
    return text + nl + "".join(_entry_lines(kind, row, nl))


def read_text(path: Path) -> str:
    """Profile text with its line endings intact (read_text would turn CRLF into LF)."""
    return Path(path).read_bytes().decode("utf-8", errors="replace")


# ----------------------------------------------------------------------------- where things live
def entry_ref(entry: dict) -> str:
    """The name other entries use in load_after / load_before: a package's id (its folder name when it has none),
    a native's DLL file name."""
    if entry.get("kind") == "package" and entry.get("id"):
        return entry["id"]
    return Path(entry.get("path") or "").name


def resolve(profile: Path, path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (Path(profile).parent / p)


def roots(profile: Path, text: str) -> tuple[Path, Path]:
    """(packages root, natives root). New packages go into the mods container existing packages share (a folder
    named mod / mods / packages beside the profile), else mod/; natives likewise into natives/. A package that lives
    inside another mod's own folder (Revive's NightreignRevive/mod) is never used as the container."""
    profile = Path(profile)
    if is_array_form(text):
        text = to_blocks(text)
    counts: dict[tuple[str, Path], int] = {}
    for b in blocks(text):
        o = block_options(text, b["index"])
        if not o["path"]:
            continue
        parent = resolve(profile, o["path"]).parent
        counts[(b["kind"], parent)] = counts.get((b["kind"], parent), 0) + 1

    def pick(kind, names, default):
        best = None
        for (k, parent), _n in sorted(counts.items(), key=lambda kv: -kv[1]):
            if k == kind and parent.name.lower() in names and parent.parent == profile.parent:
                best = parent
                break
        return best or profile.parent / default

    return pick("package", ("mod", "mods", "packages"), "mod"), pick("native", ("natives", "dll", "dlls"), "natives")


_NEXUS_SUFFIX = re.compile(r"-\d+-[\d-]+-\d{10}$")  # "Hair 13-561-1-1-1648994275": mod id, version, upload time


def slug(name: str) -> str:
    """A folder / id friendly name: Nexus's numeric suffix dropped, odd characters collapsed to one dash."""
    base = _NEXUS_SUFFIX.sub("", name.strip())
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", base)
    s = re.sub(r"-{2,}", "-", s).strip("-.")
    return s[:60] or "mod"


def rel(profile: Path, target: Path) -> str:
    try:
        return str(Path(target).relative_to(Path(profile).parent)).replace("\\", "/")
    except ValueError:
        return str(target).replace("\\", "/")


# ----------------------------------------------------------------------------- operations
def _write(profile: Path, new_text: str, why: str = "change") -> Path:
    """Write the profile atomically: a copy in its history first (see mods.history), and one .bak beside it."""
    from roundtable_souls.mods import history

    profile = Path(profile)
    history.snapshot(profile, why)
    bak = profile.with_name(profile.name + ".bak")
    shutil.copy2(profile, bak)
    tmp = profile.with_name(profile.name + ".tmp")
    tmp.write_text(new_text, encoding="utf-8", newline="")
    tmp.replace(profile)
    return bak


def _write_ordered(
    profile: Path, new_text: str, why: str, tgt: dict | None, renamed: dict[str, str] | None = None
) -> tuple[Path, str | None]:
    """_write, with the mod that must stay last kept after everything else (see mods.stay_last). tgt is what
    stay_last.target() said before the change. Returns (backup, why it could not be kept last, or None)."""
    from roundtable_souls.mods import stay_last

    problem = None
    if tgt:
        new_text, problem = stay_last.reconcile(profile, new_text, tgt, renamed)
    return _write(profile, new_text, why), problem


def _last_place(profile: Path, text: str, kind: str, tgt: dict | None) -> int | None:
    """The block new entries of this kind go above, so the file reads in load order: the package that must stay
    last, or the first of its DLLs. None without one."""
    from roundtable_souls.mods import stay_last

    if not tgt:
        return None
    items = stay_last._items(profile, text)
    pkg, _last, mine = stay_last._roles(profile, items, tgt)
    if kind == "package":
        return pkg["index"] if pkg else None
    return mine[0]["index"] if mine else None


def set_options(profile: Path, index: int, opts: dict) -> Path:
    profile = Path(profile)
    text = read_text(profile)
    if is_array_form(text):
        text = to_blocks(text)
    name = block_options(text, index)["id"] or Path(block_options(text, index)["path"]).name
    if set(opts) == {"enabled"}:  # switching a mod on or off: the load order lists already name every entry
        what = f"before turning {name} {'on' if opts['enabled'] else 'off'}"
        return _write(profile, set_block_options(text, index, opts), what)
    from roundtable_souls.mods import stay_last

    old = block_options(text, index)
    renamed = {}
    if old["kind"] == "package" and opts.get("id") and old["id"] and opts["id"] != old["id"]:
        renamed = {old["id"].lower(): opts["id"]}
    new = set_block_options(text, index, opts)
    bak, _problem = _write_ordered(
        profile, new, f"before changing {name}'s options", stay_last.target(profile), renamed
    )
    return bak  # a loop the change would make shows on the Load order card


def entries(profile: Path) -> list[dict]:
    """Every block, enabled or not, with its options; 'index' addresses it for the other operations."""
    text = read_text(Path(profile))
    if is_array_form(text):
        text = to_blocks(text)
    out = []
    for b in blocks(text):
        o = block_options(text, b["index"])
        o["index"] = b["index"]
        o["name"] = o["id"] or Path(o["path"]).name or f"entry {b['index'] + 1}"
        out.append(o)
    return out


# ----------------------------------------------------------------------------- package folders in a profile


# ----------------------------------------------------------------------------- profiles
def create_profile(folder: Path, name: str, game: str = "eldenring", copy_from: Path | None = None) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stem = slug(name)
    if stem.lower().endswith(".me3"):
        stem = stem[:-4]
    path = folder / f"{stem}.me3"
    if path.exists():
        raise ModError(f"{path.name} already exists")
    if copy_from and Path(copy_from).is_file():
        text = read_text(Path(copy_from))
    else:
        text = f'profileVersion = "v1"\n\n[[supports]]\ngame = {_q(game)}\n'
    path.write_text(text, encoding="utf-8", newline="")
    (folder / "mod").mkdir(exist_ok=True)
    (folder / "natives").mkdir(exist_ok=True)
    return path


def delete_profile(path: Path) -> Path:
    """Move the .me3 into the launcher's deleted profiles (folders.deleted_profiles), with a note of where it
    lived. Mod folders are never touched; its .bak goes along, its offline copy is regenerated when needed."""
    import json

    from roundtable_souls import folders

    path = Path(path)
    if not path.is_file():
        raise ModError(f"{path} is not a file")
    trash = folders.deleted_profiles(path.parent)
    trash.mkdir(parents=True, exist_ok=True)
    dest = trash / f"{path.stem}.{time.strftime('%Y%m%d-%H%M%S')}.me3"
    shutil.move(str(path), str(dest))
    Path(str(dest) + ".json").write_text(
        json.dumps({"from": str(path), "when": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=1), encoding="utf-8"
    )
    for extra in (path.with_name(path.name + ".bak"), path.with_name(path.stem + ".offline.me3")):
        if extra.exists():
            try:
                extra.unlink()
            except OSError:
                pass
    return dest
