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

import os
import re
import shutil
import subprocess
import tempfile
import time
import tomllib
import zipfile
from pathlib import Path

ARCHIVE_EXTENSIONS = (
    ".zip",
    ".7z",
    ".rar",
)  # .7z via py7zr (bundled), .rar via an extractor on the PC

ACCEPTABLE_FOLDERS = {
    "_backup",
    "_unknown",
    "action",
    "asset",
    "chr",
    "cutscene",
    "event",
    "font",
    "map",
    "material",
    "menu",
    "movie",
    "msg",
    "other",
    "param",
    "parts",
    "script",
    "sd",
    "sfx",
    "shader",
    "sound",
    "expression",
    "facegen",
    "obj",
    "mtd",
    "model",
    "sfxbnd",
}
IGNORED_DLLS = {
    "dinput8.dll",
    "modengine2.dll",
    "mod_loader.dll",
    "lua.dll",
    "zlib1.dll",
    "me3-mod-host.dll",
    "me3_mod_host.dll",
}
# Loose game files at an archive root (a common Nexus layout: one .partsbnd.dcx and a readme) and the folder
# the game serves them from. First match wins.
LOOSE_RULES = (
    (re.compile(r"\.partsbnd(\.dcx)?$", re.I), "parts"),
    (re.compile(r"\.(chrbnd|anibnd|texbnd|behbnd)(\.dcx)?$", re.I), "chr"),
    (re.compile(r"^c\d{4}_[hl]\.bnd(\.dcx)?$", re.I), "chr"),
    (re.compile(r"\.msgbnd(\.dcx)?$", re.I), "msg"),
    (re.compile(r"\.ffxbnd(\.dcx)?$", re.I), "sfx"),
    (re.compile(r"\.emevd(\.dcx)?$", re.I), "event"),
    (re.compile(r"\.(matbinbnd|mtdbnd)(\.dcx)?$", re.I), "material"),
    (re.compile(r"\.(fsb|bnk|fev)$", re.I), "sound"),
    (re.compile(r"\.(gfx|sblytbnd)(\.dcx)?$", re.I), "menu"),
    (re.compile(r"\.(luabnd|talkesdbnd)(\.dcx)?$", re.I), "script"),
    (re.compile(r"\.(mapbnd|msb|nva|hkxbhd|hkxbdt|btl|btab|flver)(\.dcx)?$", re.I), "map"),
    (re.compile(r"\.(objbnd|geombnd|geomhkxbnd)(\.dcx)?$", re.I), "asset"),
    (re.compile(r"^regulation\.bin$", re.I), ""),
)


def loose_files(folder: Path) -> list[tuple[Path, str]]:
    """(file, game folder) for loose game files sitting directly in folder."""
    out = []
    for c in _children(Path(folder)):
        if not c.is_file():
            continue
        for rx, sub in LOOSE_RULES:
            if rx.search(c.name):
                out.append((c, sub))
                break
    return out


NATIVE_OPTION_KEYS = ("enabled", "optional", "load_early", "initializer", "finalizer", "load_after", "load_before")
PACKAGE_OPTION_KEYS = ("enabled", "id", "load_after", "load_before")
_BLOCK = re.compile(r"^[ \t]*\[\[(packages|natives)\]\][ \t]*$", re.I)
_ANY_TABLE = re.compile(r"^[ \t]*\[")
_KEY = re.compile(r"^[ \t]*([A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*(.*)$")
_ARRAY_KEY = re.compile(r"^[ \t]*(packages|natives|supports)[ \t]*=", re.I)


class ModError(Exception):
    pass


# ----------------------------------------------------------------------------- detection
def _children(folder: Path) -> list[Path]:
    try:
        return [
            c
            for c in folder.iterdir()
            if not c.name.startswith(".") and c.name.lower() not in ("__macosx", "thumbs.db", "desktop.ini")
        ]
    except OSError:
        return []


def detect_kind(folder: Path) -> str:
    """'me3' | 'native' | 'package' | 'unknown' for one folder."""
    folder = Path(folder)
    kids = _children(folder)
    dlls = [c for c in kids if c.is_file() and c.suffix.lower() == ".dll" and c.name.lower() not in IGNORED_DLLS]
    assets = (
        any(c.is_dir() and c.name.lower() in ACCEPTABLE_FOLDERS for c in kids) or (folder / "regulation.bin").is_file()
    )
    if dlls and not assets:
        return "native"
    if assets:
        return "package"
    if any(p.name.lower() not in IGNORED_DLLS for p in folder.rglob("*.dll")):
        return "native"
    if loose_files(folder):
        return "package"
    if any(folder.rglob("*.me3")):
        return "me3"  # only a profile, no mod files of its own
    return "unknown"


JUNK_FOLDERS = {"__macosx", "screenshots", "images", "docs", "documentation", "readme", "optional files"}


def _is_mod_root(d: Path) -> bool:
    """A folder that is a mod itself: game folders / regulation.bin / loose game files (a package), DLLs (a native)
    or a .me3 (a whole profile) directly inside it."""
    kids = _children(d)
    return (
        any(c.is_dir() and c.name.lower() in ACCEPTABLE_FOLDERS - {"_backup", "_unknown"} for c in kids)
        or (d / "regulation.bin").is_file()
        or bool(loose_files(d))
        or any(c.is_file() and c.suffix.lower() == ".dll" and c.name.lower() not in IGNORED_DLLS for c in kids)
    )


DOC_SUFFIXES = {
    ".txt",
    ".md",
    ".pdf",
    ".url",
    ".html",
    ".htm",
    ".rtf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
}
SETTINGS_SUFFIXES = {".ini", ".toml", ".json", ".cfg", ".conf", ".yaml", ".yml", ".xml"}


LOADER_DLLS = {"dinput8.dll", "modengine2.dll", "mod_loader.dll", "me3-mod-host.dll"}  # me3 loads mods itself


def contents(root: Path, kind: str) -> list[dict]:
    """What sits at the top of a mod, grouped, with whether it installs by default:
    game (game folders and files), regulation (regulation.bin), dll, settings (a DLL mod's own files), doc
    (readmes, licences, images), profile (a .me3 shipped as an example), loader (another mod loader's DLL, which me3
    replaces) and other (not recognised: kept as shipped, since a mod may need a file this launcher does not know)."""
    root = Path(root)
    loose = {Path(f).name for f, _ in loose_files(root)}
    out = []
    for c in sorted(_children(root), key=lambda x: (x.is_file(), x.name.lower())):
        low, suf = c.name.lower(), c.suffix.lower()
        if c.is_dir():
            if low in ACCEPTABLE_FOLDERS - {"_backup", "_unknown"}:
                group = "game"
            elif kind == "native":
                group = "files"  # a DLL mod's own folder (its data, locale, a helper DLL)
            else:
                group = "other"
        elif low == "regulation.bin":
            group = "regulation"
        elif c.name in loose:
            group = "game"
        elif suf == ".dll":
            group = "dll" if low not in IGNORED_DLLS else "loader" if low in LOADER_DLLS else "other"
        elif suf == ".me3":
            group = "profile"
        elif kind == "native" and (
            suf in SETTINGS_SUFFIXES
            or (suf == ".txt" and not re.match(r"(?i)^(readme|license|licence|changelog|credits)", low))
        ):
            group = "settings"
        elif suf in DOC_SUFFIXES or re.match(r"(?i)^(readme|license|licence|changelog|credits|notice)", low):
            group = "doc"
        else:
            group = "other"
        try:
            size = c.stat().st_size if c.is_file() else sum(x.stat().st_size for x in c.rglob("*") if x.is_file())
        except OSError:
            size = 0
        out.append(
            {
                "name": c.name,
                "group": group,
                "size": size,
                "on": group not in ("doc", "profile", "loader"),
            }
        )
    return out


def extras(top: Path, root: Path) -> list[dict]:
    """Files the archive has beside the mod folder rather than in it (a readme or an example .me3 next to mod/). Not
    part of the mod, so left out unless ticked; a ticked one is copied into the mod's folder. 'extra' is its path
    from the top of the unpacked archive."""
    top, root = Path(top), Path(root)
    out, seen = [], {c.name.lower() for c in _children(root)}
    here = root.parent
    while here == top or top in here.parents:
        for c in sorted(_children(here), key=lambda x: x.name.lower()):
            if not c.is_file() or c.name.lower() in seen:
                continue
            seen.add(c.name.lower())
            suf, low = c.suffix.lower(), c.name.lower()
            doc = suf in DOC_SUFFIXES or re.match(r"(?i)^(readme|license|licence|changelog|credits|notice)", low)
            group = "profile" if suf == ".me3" else "doc" if doc else "other"
            size = c.stat().st_size
            out.append(
                {"name": c.name, "group": group, "size": size, "on": False, "extra": c.relative_to(top).as_posix()}
            )
        if here == top:
            break
        here = here.parent
    return out


def find_roots(folder: Path, max_depth: int = 4) -> list[Path]:
    """Every mod inside an unpacked archive or folder, however it is wrapped: a folder named after the mod, a mod/
    folder next to a readme, or several variants side by side (English/mod and Italian/mod). A mod folder is not
    looked inside further."""
    found: list[Path] = []

    def walk(d: Path, depth: int):
        if _is_mod_root(d):
            if _only_regulation(d) and depth < max_depth:  # a leftover regulation.bin beside the real mod folder
                inner: list[Path] = []
                for c in sorted(_children(d), key=lambda x: x.name.lower()):
                    if c.is_dir() and c.name.lower() not in JUNK_FOLDERS:
                        inner += [r for r in find_roots(c, max_depth - depth - 1) if not _only_regulation(r)]
                if inner:
                    found.extend(inner)
                    return
            found.append(d)
            return
        if depth >= max_depth:
            return
        for c in sorted(_children(d), key=lambda x: x.name.lower()):
            if c.is_dir() and c.name.lower() not in JUNK_FOLDERS:
                walk(c, depth + 1)

    walk(Path(folder), 0)
    return found


def _only_regulation(d: Path) -> bool:
    """A mod folder whose only game file is regulation.bin (no game folders, DLLs or other loose game files)."""
    kids = _children(d)
    return (
        (d / "regulation.bin").is_file()
        and not any(c.is_dir() and c.name.lower() in ACCEPTABLE_FOLDERS - {"_backup", "_unknown"} for c in kids)
        and not any(c.is_file() and c.suffix.lower() == ".dll" and c.name.lower() not in IGNORED_DLLS for c in kids)
        and all(Path(f).name.lower() == "regulation.bin" for f, _ in loose_files(d))
    )


def find_root(folder: Path) -> Path:
    """The one mod inside (see find_roots); the folder itself when there is none."""
    roots_found = find_roots(folder)
    return roots_found[0] if roots_found else Path(folder)


def detect(source: Path, root: Path | None = None) -> dict:
    """What a folder (already extracted) contains: root, kind, asset folders, DLLs, the .me3 if any. root picks one
    of several mods inside (find_roots); otherwise the first."""
    root = Path(root) if root is not None else find_root(Path(source))
    kind = detect_kind(root)
    kids = _children(root)
    assets = sorted(c.name for c in kids if c.is_dir() and c.name.lower() in ACCEPTABLE_FOLDERS)
    if (root / "regulation.bin").is_file():
        assets.append("regulation.bin")
    dlls = sorted(p for p in root.rglob("*.dll") if p.name.lower() not in IGNORED_DLLS)
    me3 = next(iter(root.rglob("*.me3")), None)
    has_dirs = any(c.is_dir() and c.name.lower() in ACCEPTABLE_FOLDERS for c in kids)
    loose = loose_files(root) if kind == "package" and not has_dirs else []
    for _f, sub in loose:
        label = sub or "regulation.bin"
        if label not in assets:
            assets.append(label)
    msg = root / "msg"
    languages = sorted(c.name for c in _children(msg) if c.is_dir()) if kind == "package" and msg.is_dir() else []
    return {
        "root": root,
        "kind": kind,
        "assets": assets,
        "dlls": dlls,
        "me3": me3,
        "loose": loose,
        "languages": languages,
        "size": sum(p.stat().st_size for p in root.rglob("*") if p.is_file()),
    }


# ----------------------------------------------------------------------------- archives
def _unsafe(name: str) -> bool:
    name = name.replace("\\", "/")
    return name.startswith("/") or ".." in name.split("/") or (len(name) > 1 and name[1] == ":")


def extract_zip(archive: Path, dest: Path) -> Path:
    """Extract a .zip into dest, refusing entries that would escape it."""
    archive = Path(archive)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if _unsafe(info.filename):
                raise ModError(f"archive entry escapes the folder: {info.filename}")
        z.extractall(dest)
    return dest


def extract_7z(archive: Path, dest: Path) -> Path:
    """.7z through py7zr (bundled in the exe); entries that would escape the folder are refused."""
    try:
        import py7zr
    except ImportError as e:
        raise ModError("7z support is missing from this build") from e
    archive = Path(archive)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with py7zr.SevenZipFile(archive, "r") as z:
            for name in z.getnames():
                if _unsafe(name):
                    raise ModError(f"archive entry escapes the folder: {name}")
            z.extractall(path=dest)
    except ModError:
        raise
    except Exception as e:
        raise ModError(f"could not read the 7z archive: {e}") from e
    return dest


def _no_window():
    try:
        from roundtable_souls.system import common

        return common.NO_WINDOW
    except Exception:
        return 0


def rar_tools() -> list[list[str]]:
    """Command lines that can unpack .rar on this PC, best first: Windows' own bsdtar (libarchive reads RAR and RAR5),
    then 7-Zip, then WinRAR's UnRAR. Each takes the archive and the destination appended by extract_rar."""
    tools = []
    win = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
    if win.is_file():
        tools.append([str(win), "-xf"])
    for pf in filter(None, (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"))):
        for exe in (Path(pf) / "7-Zip" / "7z.exe", Path(pf) / "WinRAR" / "UnRAR.exe"):
            if exe.is_file():
                tools.append([str(exe), "x", "-y"])
    return tools


def extract_rar(archive: Path, dest: Path) -> Path:
    """.rar through whichever extractor the PC has. bsdtar refuses absolute and .. paths on its own; the others
    are followed by a check that nothing landed outside dest."""
    archive = Path(archive)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    tools = rar_tools()
    if not tools:
        raise ModError(
            "no .rar extractor found: Windows' tar.exe, 7-Zip or WinRAR is needed, or unpack it first and install the folder"
        )
    errors = []
    for tool in tools:
        if tool[1] == "-xf":
            cmd = tool + [str(archive), "-C", str(dest)]
        else:
            cmd = tool + [str(archive), f"-o{dest}"]
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                creationflags=_no_window(),
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            errors.append(f"{Path(tool[0]).name}: {e}")
            continue
        if r.returncode == 0 and any(dest.iterdir()):
            root = dest.resolve()
            for p in dest.rglob("*"):
                if root not in p.resolve().parents and p.resolve() != root:
                    shutil.rmtree(dest, ignore_errors=True)
                    raise ModError("archive tried to write outside the folder; refused")
            return dest
        errors.append(
            f"{Path(tool[0]).name}: {(r.stderr or r.stdout or '').strip()[:200] or 'exit ' + str(r.returncode)}"
        )
        for p in dest.iterdir():
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    raise ModError("could not unpack the .rar: " + "; ".join(errors))


def extract_archive(archive: Path, dest: Path) -> Path:
    ext = Path(archive).suffix.lower()
    if ext == ".zip":
        return extract_zip(archive, dest)
    if ext == ".7z":
        return extract_7z(archive, dest)
    if ext == ".rar":
        return extract_rar(archive, dest)
    raise ModError(f"{ext or 'that file'} is not a supported archive (zip, 7z, rar)")


def stage(source: Path, staging_root: Path) -> tuple[Path, bool]:
    """(folder to detect from, is_temporary). Archives are extracted, and a lone .dll copied, into a temp folder under
    staging_root."""
    source = Path(source)
    if source.is_dir():
        return source, False
    if source.suffix.lower() in ARCHIVE_EXTENSIONS:
        tmp = Path(tempfile.mkdtemp(prefix="install-", dir=str(staging_root)))
        try:
            extract_archive(source, tmp)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return tmp, True
    if source.suffix.lower() == ".dll" and source.is_file():  # a DLL mod on its own
        tmp = Path(tempfile.mkdtemp(prefix="install-", dir=str(staging_root)))
        (tmp / source.stem).mkdir()
        shutil.copy2(source, tmp / source.stem / source.name)
        return tmp, True
    raise ModError("pick a .zip, .7z or .rar archive, a .dll, or a folder")


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


def plan_install(
    profile: Path, source: Path, name: str | None = None, pkg_id: str | None = None, variant: str | None = None
) -> dict:
    """Unpack (archives, into the launcher's temp folder) and describe what install() would do. The unpacked copy is
    kept in the plan ('unpacked'), so replan() can change the folder name, id or variant without unpacking again."""
    profile = Path(profile)
    from roundtable_souls import folders

    folders.adopt_legacy_profile_folders(profile.parent)
    staging_root = folders.temp("installing")
    for old in staging_root.iterdir():  # a crash mid-install can leave a temp folder behind
        try:
            if old.is_dir() and time.time() - old.stat().st_mtime > 3600:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass
    folder, temp = stage(source, staging_root)
    source = Path(source)
    default = source.stem if source.suffix.lower() in (*ARCHIVE_EXTENSIONS, ".dll") else source.name
    return _plan(profile, folder, temp, default, name, pkg_id, variant)


def replan(
    profile: Path, plan: dict, name: str | None = None, pkg_id: str | None = None, variant: str | None = None
) -> dict:
    """The same unpacked source with another folder name, id or variant."""
    return _plan(
        Path(profile), Path(plan["unpacked"]), bool(plan.get("staging")), plan["default_name"], name, pkg_id, variant
    )


def _plan(profile: Path, folder: Path, temp: bool, default_name: str, name, pkg_id, variant) -> dict:
    candidates = find_roots(folder)
    labels = []
    for c in candidates:
        try:
            labels.append(c.relative_to(folder).as_posix() or folder.name)
        except ValueError:
            labels.append(c.name)
    pick = labels.index(variant) if variant in labels else 0
    d = detect(folder, candidates[pick] if candidates else folder)
    text = read_text(profile)
    pk_root, nt_root = roots(profile, text)
    base = slug(name) if name else slug(default_name).lower()  # typed names are kept as typed
    if not name and not temp and same_folder(Path(d["root"]).parent, pk_root if d["kind"] == "package" else nt_root):
        base = Path(d["root"]).name  # already in place: keep the folder's own name
    plan = {
        **d,
        "name": base,
        "default_name": default_name,
        "unpacked": folder,
        "staging": folder if temp else None,
        "array_form": is_array_form(text),
        "variants": labels if len(labels) > 1 else [],
        "variant": labels[pick] if labels else "",
    }
    if d["kind"] == "me3":
        plan["error"] = (
            "This is a whole me3 profile, not a mod. Copy its .me3 next to yours and pick it as a setup instead."
        )
    elif d["kind"] == "unknown":
        plan["error"] = (
            "No game folders (parts, chr, msg, ...), no regulation.bin, no known game file and no DLL found in here."
        )
    elif d["kind"] == "package":
        plan["dest"] = pk_root / base
        ident = slug(pkg_id) if pkg_id else base
        plan["id"] = ident
        plan["entries"] = [{"kind": "package", "id": ident, "path": rel(profile, plan["dest"])}]
        taken = {(e.get("id") or "").lower() for e in entries(profile) if e["kind"] == "package"}
        plan["id_taken"] = ident.lower() in taken
    else:
        plan["dest"] = nt_root / base
        plan["entries"] = [
            {"kind": "native", "path": rel(profile, plan["dest"] / p.relative_to(d["root"]))} for p in d["dlls"]
        ]
    if plan.get("dest") and Path(plan["dest"]).exists():
        plan["exists"] = True
        try:
            plan["in_place"] = Path(plan["dest"]).resolve() == Path(d["root"]).resolve()
        except OSError:
            plan["in_place"] = False
    existing = {resolve(profile, e["path"]).resolve() for e in entries(profile) if e.get("path")}
    plan["already_listed"] = [
        e["path"] for e in plan.get("entries") or [] if resolve(profile, e["path"]).resolve() in existing
    ]
    if plan.get("already_listed") and plan.get("id_taken"):
        plan["id_taken"] = False  # reinstalling over itself keeps its own id
    if d["kind"] in ("package", "native"):
        plan["contents"] = contents(d["root"], d["kind"]) + extras(folder, d["root"])
        plan["profiles_inside"] = [str(m.relative_to(folder)) for m in folder.rglob("*.me3")]
    if d["kind"] == "package" and (d["root"] / "regulation.bin").is_file():
        plan.update(regulation_order(profile, skip=plan.get("dest")))
        from roundtable_souls.mods import merge

        plan.update(merge.offer(profile, d["root"], plan["regulation_packages"]))
    return plan


def regulation_order(profile: Path, skip: Path | None = None) -> dict:
    """The enabled packages that ship a regulation.bin, in me3's effective load order. me3 serves one regulation.bin:
    the last of these. {regulation_packages: [{index, name}], regulation_winner: name or None}. skip leaves out the
    package in that folder (the mod being reinstalled)."""
    from roundtable_souls.mods import profile as profile_tools

    profile = Path(profile)
    text = read_text(profile)
    items = {e["index"]: e for e in entries(profile)}
    order = profile_tools.effective_order(profile_tools.package_rows(text))
    by_id = {
        (e.get("id") or Path(e.get("path") or "").name).lower(): e for e in items.values() if e["kind"] == "package"
    }
    ships = []
    for row in order:
        e = by_id.get(str(row["id"]).lower())
        folder = resolve(profile, e["path"]) if e else None
        if skip is not None and folder is not None and same_folder(folder, Path(skip)):
            continue
        if e and folder is not None and e.get("enabled", True) and (folder / "regulation.bin").is_file():
            ships.append({"index": e["index"], "name": e["name"]})
    return {"regulation_packages": ships, "regulation_winner": ships[-1]["name"] if ships else None}


def install(profile: Path, plan: dict, overwrite: bool = False) -> dict:
    """Copy the mod into place and append its profile entries. Returns {dest, entries, backup}."""
    profile = Path(profile)
    if plan.get("error"):
        raise ModError(plan["error"])
    dest = Path(plan["dest"])
    in_place = bool(plan.get("in_place"))
    if dest.exists() and not in_place:
        if not overwrite:
            raise ModError(f"{dest.name} already exists in {dest.parent}")
        shutil.rmtree(dest)
    loose = {Path(f).name: sub for f, sub in (plan.get("loose") or [])}
    skip = {n.lower() for n in plan.get("exclude") or []}
    root = Path(plan["root"])

    def left_out(folder, names):
        junk = {"__MACOSX", "Thumbs.db", ".DS_Store"}
        top = Path(folder) == root
        return [n for n in names if n in junk or (top and n.lower() in skip)]

    if in_place:
        pass  # the files are already where they belong: only the profile changes
    elif loose:
        # loose game files go into the folder the game serves them from; everything else copies as it is
        dest.mkdir(parents=True, exist_ok=True)
        for c in _children(root):
            if c.name.lower() in skip:
                continue
            sub = loose.get(c.name)
            if c.is_file() and sub is not None:
                target = (dest / sub) if sub else dest
                target.mkdir(parents=True, exist_ok=True)
                shutil.copy2(c, target / c.name)
            elif c.is_dir():
                shutil.copytree(c, dest / c.name, ignore=left_out)
            else:
                shutil.copy2(c, dest / c.name)
    else:
        shutil.copytree(root, dest, ignore=left_out)
    if not in_place:  # ticked files from beside the mod folder
        for c in plan.get("contents") or []:
            if c.get("extra") and c["name"].lower() not in skip:
                shutil.copy2(Path(plan["unpacked"]) / c["extra"], dest / c["name"])
    text = read_text(profile)
    if is_array_form(text):
        text = to_blocks(text)
    listed = set(plan.get("already_listed") or [])
    added = [
        e
        for e in plan["entries"]
        if e["path"] not in listed
        and not (e["kind"] == "native" and Path(e["path"]).relative_to(rel(profile, dest)).parts[0].lower() in skip)
    ]
    before = plan.get("insert_before")  # a package's name: where it is now, not where it was when the plan was made
    if isinstance(before, str):
        before = next(
            (x["index"] for x in entries(profile) if x["kind"] == "package" and x["name"].lower() == before.lower()),
            None,
        )
    for e in added:
        text = append_entry(text, e["kind"], e) if before is None else insert_entry(text, e["kind"], e, before)
    bak = _write(profile, text, f"before installing {plan['name']}") if added or text != read_text(profile) else None
    if plan.get("staging"):
        shutil.rmtree(plan["staging"], ignore_errors=True)
    return {"dest": dest, "entries": added, "backup": bak, "in_place": in_place}


def uninstall(profile: Path, index: int, delete_folder: bool = True, to_trash: bool = True) -> dict:
    """Remove one block, with its own comments (see remove_entry). With delete_folder, the mod's folder goes too when
    it lies beside the profile and no other entry still points into it (a natives folder shared by several DLLs is
    kept): to the Recycle Bin (to_trash), so it can come back, else deleted. Returns what was removed and where, so
    it can be put back (see mods.undo)."""
    profile = Path(profile)
    text = read_text(profile)
    if is_array_form(text):
        text = to_blocks(text)
    o = block_options(text, index)
    target = resolve(profile, o["path"]) if o["path"] else None
    folder = None
    if target is not None:
        folder = target if o["kind"] == "package" else target.parent
    name = o["id"] or Path(o["path"]).name or f"entry {index + 1}"
    new_text, chunk, where = remove_entry(text, index)
    removed_folder = False
    trashed = None
    if delete_folder and folder is not None and folder.is_dir():
        inside = profile.parent.resolve() in folder.resolve().parents
        still = [block_options(new_text, b["index"])["path"] for b in blocks(new_text)]
        shared = any(
            p
            and (
                folder.resolve() == resolve(profile, p).resolve()
                or folder.resolve() in resolve(profile, p).resolve().parents
            )
            for p in still
        )
        if inside and not shared and folder.resolve() != profile.parent.resolve():
            from roundtable_souls.system import trash as trash_bin

            if to_trash and trash_bin.available():
                try:
                    trashed = trash_bin.send(folder)
                    removed_folder = True
                except trash_bin.TrashError:
                    trashed = None  # cancelled at Windows' warning, or no bin: the folder stays
            else:
                shutil.rmtree(folder)
                removed_folder = True
    bak = _write(profile, new_text, f"before removing {name}")
    return {
        "kind": o["kind"],
        "path": o["path"],
        "name": name,
        "folder": folder,
        "removed_folder": removed_folder,
        "backup": bak,
        "entry_text": chunk,
        "where": where,
        "trash": trashed,  # where the folder went in the Recycle Bin (system.trash), when it went there
    }


def set_options(profile: Path, index: int, opts: dict) -> Path:
    profile = Path(profile)
    text = read_text(profile)
    if is_array_form(text):
        text = to_blocks(text)
    name = block_options(text, index)["id"] or Path(block_options(text, index)["path"]).name
    what = (
        f"before turning {name} {'on' if opts['enabled'] else 'off'}"
        if set(opts) == {"enabled"}
        else f"before changing {name}'s options"
    )
    return _write(profile, set_block_options(text, index, opts), what)


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
NOT_GAME_FOLDERS = {"_backup", "_unknown"}  # accepted when installing, but me3 serves nothing from them


def has_game_files(folder: Path) -> bool:
    """Whether a package folder holds game files at its own top level (game folders, regulation.bin, loose files):
    what me3 actually serves from it. A folder of other mods' folders has none."""
    folder = Path(folder)
    kids = _children(folder)
    return (
        any(c.is_dir() and c.name.lower() in ACCEPTABLE_FOLDERS - NOT_GAME_FOLDERS for c in kids)
        or (folder / "regulation.bin").is_file()
        or bool(loose_files(folder))
    )


def _canon(p: Path) -> Path:
    """A path for comparing: resolved, and on Windows lower-cased with one kind of slash."""
    try:
        p = Path(p).resolve()
    except OSError:
        p = Path(os.path.abspath(p))
    return Path(os.path.normcase(str(p)))


def same_folder(a: Path, b: Path) -> bool:
    """Two paths name the same place (case and slash direction ignored on Windows)."""
    return _canon(a) == _canon(b)


def _within(inner: Path, outer: Path) -> bool:
    """inner lies below outer (both _canon'd)."""
    return inner != outer and outer in inner.parents


def _unlisted_packages(folder: Path, listed: set[Path], max_depth: int = 3) -> list[Path]:
    """Package folders (game files at their top level) below folder that no entry points at. A folder that holds
    listed packages deeper down is looked past; folders starting with _ (backups) are skipped."""
    found: list[Path] = []

    def walk(d: Path, depth: int):
        for c in sorted(_children(d), key=lambda x: x.name.lower()):
            key = _canon(c)
            if not c.is_dir() or c.name.startswith("_") or key in listed:
                continue
            if any(_within(g, key) for g in listed):
                walk(c, depth + 1)
            elif has_game_files(c):
                found.append(c)
            elif depth < max_depth:
                walk(c, depth + 1)

    if Path(folder).is_dir():
        walk(Path(folder), 1)
    return found


def package_tree(profile: Path, items: list[dict], max_depth: int = 3) -> dict[int, dict]:
    """How the profile's package folders sit inside each other, by entry index:

    folder: the resolved folder. own_files: it serves game files itself (see has_game_files). children: indexes of
    listed packages inside it. parent: the closest listed package it sits inside, or None. holder: it serves nothing
    itself and only holds other mods (listed or not), so it is a folder, not a mod. unlisted: package folders inside
    a holder that no entry points at, so me3 never loads them."""
    profile = Path(profile)
    folders = {e["index"]: resolve(profile, e["path"]) for e in items if e.get("kind") == "package" and e.get("path")}
    keys = {i: _canon(f) for i, f in folders.items()}
    listed = set(keys.values())
    out = {}
    for i, f in folders.items():
        out[i] = {
            "folder": f,
            "own_files": f.is_dir() and has_game_files(f),
            "children": [j for j, g in keys.items() if _within(g, keys[i])],
            "parent": None,
            "unlisted": [],
            "holder": False,
        }
    for i in folders:
        around = [j for j, g in keys.items() if _within(keys[i], g)]
        if around:
            out[i]["parent"] = max(around, key=lambda j: len(keys[j].parts))
    for info in out.values():
        if info["folder"].is_dir() and not info["own_files"]:
            info["unlisted"] = _unlisted_packages(info["folder"], listed, max_depth)
            info["holder"] = bool(info["children"] or info["unlisted"])
    return out


# Libraries other programs load (upscalers, compilers, C runtimes): never a me3 native on their own.
RUNTIME_DLL = re.compile(
    r"^(nvngx|sl\.|amd_fidelityfx|ffx_|libxess|d3dcompiler|dxcompiler|dxil|msvcp|vcruntime|ucrtbase|concrt|api-ms-)",
    re.I,
)


def _unlisted_natives(root: Path, listed: set[Path]) -> list[Path]:
    """DLLs in the natives folder that no entry loads. Every DLL directly in it counts (one file per mod is the
    usual layout); in a subfolder that already has a listed DLL the others are taken as that mod's helpers. Runtime
    libraries and folders of ReShade add-ons (*.addon, *.addon64) are not me3 mods and are left out."""
    root = Path(root)
    if not root.is_dir():
        return []
    helper_dirs = {p.parent for p in listed}
    found = []
    for dll in sorted(root.rglob("*.dll"), key=lambda x: str(x).lower()):
        key = _canon(dll)
        if key in listed or dll.name.lower() in IGNORED_DLLS or RUNTIME_DLL.match(dll.name):
            continue
        if len(dll.relative_to(root).parts) > 3:
            continue
        if dll.parent != root and (key.parent in helper_dirs or any(dll.parent.glob("*.addon*"))):
            continue
        found.append(dll)
    return found


def folder_overview(profile: Path, items: list[dict], tree: dict[int, dict] | None = None) -> dict:
    """The profile's mod folders as folders, beside the entries:

    packages: {root, holders, unlisted, listed}: the packages folder new mods go into (mod/ by default); entries
      that point at a folder of mods instead of a mod (they load nothing themselves, so the page shows them here,
      not as mods); package folders no entry loads; how many listed packages sit in the root. root is None when the
      folder is missing or is itself a package with game files (one package for everything, as in me3's guide).
    natives: {root, unlisted, listed} for the natives folder, None when it is missing."""
    profile = Path(profile)
    tree = tree if tree is not None else package_tree(profile, items)
    try:
        pk_root, nt_root = roots(profile, read_text(profile))
    except OSError:
        return {"packages": None, "natives": None}
    listed = {_canon(n["folder"]) for n in tree.values()}
    root_key = _canon(pk_root)
    holders = [i for i, n in tree.items() if n["holder"]]
    root_is_mod = any(_canon(n["folder"]) == root_key and n["own_files"] for n in tree.values())
    unlisted: list[Path] = []
    seen: set[Path] = set()
    root = pk_root if pk_root.is_dir() and not root_is_mod else None
    for u in (_unlisted_packages(root, listed) if root else []) + [u for i in holders for u in tree[i]["unlisted"]]:
        if _canon(u) not in seen:
            seen.add(_canon(u))
            unlisted.append(u)
    packages = None
    if root or holders:
        packages = {
            "root": root,
            "holders": holders,
            "unlisted": unlisted,
            "listed": sum(
                1 for i, n in tree.items() if i not in holders and root and _within(_canon(n["folder"]), root_key)
            ),
        }
    natives = None
    if nt_root.is_dir():
        dlls = {_canon(resolve(profile, e["path"])) for e in items if e.get("kind") == "native" and e.get("path")}
        natives = {
            "root": nt_root,
            "unlisted": _unlisted_natives(nt_root, dlls),
            "listed": sum(1 for d in dlls if _within(d, _canon(nt_root))),
        }
    return {"packages": packages, "natives": natives}


def entry_ref(entry: dict) -> str:
    """The name other entries use in load_after / load_before: a package's id (its folder name when it has none),
    a native's DLL file name."""
    if entry.get("kind") == "package" and entry.get("id"):
        return entry["id"]
    return Path(entry.get("path") or "").name


def _find_loop(after: dict[int, set[int]]) -> list[int] | None:
    """One cycle in 'i loads after each of after[i]', as the path around it, or None."""
    state: dict[int, int] = {}  # 1 on the current path, 2 done

    def visit(i: int, trail: list[int]) -> list[int] | None:
        state[i] = 1
        for j in sorted(after.get(i, ())):
            if state.get(j) == 1:
                return trail[trail.index(j) :] + [j]
            if not state.get(j):
                found = visit(j, trail + [j])
                if found:
                    return found
        state[i] = 2
        return None

    for i in sorted(after):
        if not state.get(i):
            found = visit(i, [i])
            if found:
                return found
    return None


def entry_problems(profile: Path, items: list[dict]) -> dict[int, list[str]]:
    """What would make me3 refuse or skip an entry, by index. Load order only links entries of the same kind, and a
    dependency that is not optional must be present and enabled, or me3 stops."""
    profile = Path(profile)
    out: dict[int, list[str]] = {e["index"]: [] for e in items}
    for kind in ("package", "native"):
        group = [e for e in items if e["kind"] == kind]
        refs: dict[str, list[dict]] = {}
        for e in group:
            refs.setdefault(entry_ref(e).lower(), []).append(e)
        for e in group:
            say = out[e["index"]]
            target = resolve(profile, e["path"]) if e.get("path") else None
            if target is None:
                say.append("No path")
            elif kind == "package" and not target.is_dir():
                say.append("Folder missing" if not target.exists() else "Path is a file, not a folder")
            elif kind == "native" and not target.is_file():
                say.append("DLL missing")
            elif kind == "native" and target.suffix.lower() != ".dll":
                say.append("Not a .dll")
            same = [o for o in refs.get(entry_ref(e).lower(), []) if o is not e]
            if kind == "package" and e.get("id") and same:
                say.append(f"Id '{e['id']}' is used twice; me3 needs each id once")
            for key, word in (("load_after", "after"), ("load_before", "before")):
                for d in e.get(key) or []:
                    if d.get("optional"):
                        continue
                    hits = refs.get(str(d["id"]).lower()) or []
                    if not hits:
                        say.append(f"Must load {word} '{d['id']}', which is not in this profile: me3 stops")
                    elif not any(h.get("enabled", True) for h in hits):
                        say.append(f"Must load {word} '{d['id']}', which is off: me3 stops")
        # a loop in the order (a after b, b after a) cannot be satisfied
        after: dict[int, set[int]] = {e["index"]: set() for e in group}
        for e in group:
            for d in e.get("load_after") or []:
                for h in refs.get(str(d["id"]).lower()) or []:
                    after[e["index"]].add(h["index"])
            for d in e.get("load_before") or []:
                for h in refs.get(str(d["id"]).lower()) or []:
                    after[h["index"]].add(e["index"])
        names = {e["index"]: entry_ref(e) for e in group}
        loop = _find_loop(after)
        if loop:
            text = "Load order loops: " + " → ".join(names[i] for i in loop)
            for i in set(loop):
                out[i].append(text)
    return out


def add_existing(profile: Path, folders: list[Path], kind: str = "package") -> dict:
    """List files that already sit in place as entries, last in the load order. Nothing is copied. Packages are
    folders and get an id from the path below the packages folder ('improved-textures/architecture' ->
    improved-textures-architecture); natives are DLL files, named by their file."""
    profile = Path(profile)
    text = read_text(profile)
    if is_array_form(text):
        text = to_blocks(text)
    pk_root, _nt = roots(profile, text)
    have = {(block_options(text, b["index"]).get("id") or "").lower() for b in blocks(text) if b["kind"] == "package"}
    added = []
    for f in folders:
        f = Path(f)
        if kind == "native":
            row = {"kind": "native", "path": rel(profile, f)}
            text = append_entry(text, "native", row)
            added.append(row)
            continue
        try:
            below = f.resolve().relative_to(pk_root.resolve())
        except OSError, ValueError:
            below = Path(f.name)
        ident = slug("-".join(below.parts)) or slug(f.name)
        base, n = ident, 2
        while ident.lower() in have:
            ident, n = f"{base}-{n}", n + 1
        have.add(ident.lower())
        row = {"kind": "package", "id": ident, "path": rel(profile, f)}
        text = append_entry(text, "package", row)
        added.append(row)
    bak = _write(profile, text) if added else None
    return {"entries": added, "backup": bak}


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
