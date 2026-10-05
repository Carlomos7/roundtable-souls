"""What a profile's mod folders hold and what is wrong with its entries: the folders a game mod may have, DLLs that are not mods, the package tree, folders and DLLs no entry loads, entry references, load-order loops and the problems me3 would refuse."""

from __future__ import annotations

import os
import re
from pathlib import Path

from roundtable_souls.mods.profile_edit import (
    entry_ref,
    read_text,
    resolve,
    roots,
)

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


def _children(folder: Path) -> list[Path]:
    try:
        return [
            c
            for c in folder.iterdir()
            if not c.name.startswith(".") and c.name.lower() not in ("__macosx", "thumbs.db", "desktop.ini")
        ]
    except OSError:
        return []


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


def _present(profile: Path, e: dict) -> bool:
    """me3 leaves out an entry whose path does not exist before it orders the rest."""
    return bool(e.get("path")) and resolve(profile, e["path"]).exists()


def entry_problems(profile: Path, items: list[dict]) -> dict[int, list[str]]:
    """What would make me3 refuse or skip an entry, by index. Load order only links entries of the same kind, and a
    dependency that is not optional must be in the profile with its folder (or DLL) there, under exactly that id, or
    me3 stops (see mods.order). A dependency that is switched off is fine: me3 orders switched-off entries too."""
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
                    exact = [h for h in hits if entry_ref(h) == str(d["id"])]
                    if not hits:
                        say.append(f"Must load {word} '{d['id']}', which is not in this profile: me3 stops")
                    elif not exact:
                        say.append(
                            f"Must load {word} '{d['id']}', but the profile calls it '{entry_ref(hits[0])}' and me3 "
                            "matches ids exactly: me3 stops"
                        )
                    elif not any(_present(profile, h) for h in exact):
                        say.append(
                            f"Must load {word} '{d['id']}', whose {'folder' if kind == 'package' else 'DLL'} "
                            "is missing: me3 stops"
                        )
        # a loop in the order (a after b, b after a) cannot be satisfied: as me3 sees it (mods.order), between
        # entries that are there, linked by their exact ids
        present = [e for e in group if _present(profile, e)]
        by_id: dict[str, list[dict]] = {}
        for e in present:
            by_id.setdefault(entry_ref(e), []).append(e)
        after: dict[int, set[int]] = {e["index"]: set() for e in present}
        for e in present:
            for d in e.get("load_after") or []:
                for h in by_id.get(str(d["id"])) or []:
                    after[e["index"]].add(h["index"])
            for d in e.get("load_before") or []:
                for h in by_id.get(str(d["id"])) or []:
                    after[h["index"]].add(e["index"])
        names = {e["index"]: entry_ref(e) for e in group}
        loop = _find_loop(after)
        if loop:
            text = "Load order loops: " + " → ".join(names[i] for i in loop)
            for i in set(loop):
                out[i].append(text)
    return out
