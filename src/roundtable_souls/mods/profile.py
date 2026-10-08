"""me3 profile helpers beyond enable/disable: the top-level profile settings me3 v1 defines, and a
read-only conflict scan across enabled packages (which file wins when two packages ship the same path).

Load order rule (me3): packages later in the effective order override earlier ones. The effective
order is the file order, then every package with load_after is moved behind the packages it names.
"""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

from roundtable_souls.formats import me3_profile
from roundtable_souls.formats.me3_profile import resolve
from roundtable_souls.game import catalog as games
from roundtable_souls.game import config as game_config
from roundtable_souls.mods.checks import ACCEPTABLE_FOLDERS, NOT_GAME_FOLDERS

REGULATION = games.ELDEN_RING.regulation  # the parameter file a package may ship

SETTING_KEYS = ("savefile", "start_online", "disable_arxan", "mem_patch", "mem_patch_heap_size")
SETTING_TEXT = {
    "savefile": (
        "Save file",
        "A different save file name for this profile, in the game's save folder. When it does not exist yet, me3 "
        "starts it as a copy of the normal save.",
    ),
    "start_online": (
        "Online matchmaking",
        "me3 blocks the official servers by default. Only private-server mods need this on; Seamless Co-op does "
        "not. On with mods risks a ban.",
    ),
    "disable_arxan": ("Neutralise Arxan", "Disables the game's tamper protection; helps some mods stay stable."),
    "mem_patch": ("Memory patch", "Lifts the game's memory limits for heavy mods (me3 default: on for Elden Ring)."),
    "mem_patch_heap_size": (
        "Heap size (MB)",
        "Override how much memory the game allocates with the memory patch. 0 = me3 default.",
    ),
}
IGNORED_NAMES = {"me3.toml", ".nexus_metadata.json", "thumbs.db", "desktop.ini", ".ds_store", ".gitignore"}
IGNORED_SUFFIXES = {".bak", ".tmp", ".old"}
ROOT_DOC_SUFFIXES = {
    ".txt",
    ".md",
    ".url",
    ".html",
    ".pdf",
    ".png",
    ".jpg",
}  # notes at a package root are not game paths
_KEY_LINE = re.compile(r"^[ \t]*([A-Za-z_][A-Za-z0-9_]*)[ \t]*=", re.M)
_SECTION = re.compile(r"^[ \t]*\[")


# ----------------------------------------------------------------------------- settings
def read_settings(text: str) -> dict:
    """Top-level profile settings me3 understands, or {} when the file does not parse."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}
    return {k: data.get(k) for k in SETTING_KEYS if k in data}


def _format(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _top_region_end(lines: list[str]) -> int:
    """Index of the first line that starts a table ([[packages]], [x]) or an inline array (packages = [)."""
    for i, line in enumerate(lines):
        body = line.rstrip("\r\n")
        if _SECTION.match(body):
            return i
        m = _KEY_LINE.match(body)
        if m and m.group(1) in ("packages", "natives", "supports"):
            return i
    return len(lines)


def set_setting(text: str, key: str, value) -> str:
    """Set, replace or (value None) remove one top-level setting. Comments, order and line endings stay.
    A commented-out line for the key is left alone; the live line goes right after profileVersion."""
    if key not in SETTING_KEYS:
        raise KeyError(key)
    if key == "savefile" and value not in (None, "") and ("/" in str(value) or "\\" in str(value)):
        raise ValueError("savefile is a file name in the game's save folder, not a path")
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith(("\n", "\r\n")):
        lines[-1] += nl  # a file without a final newline must not glue lines together
    end = _top_region_end(lines)
    hits = [i for i in range(end) if (m := _KEY_LINE.match(lines[i].rstrip("\r\n"))) and m.group(1) == key]
    for i in reversed(hits[1:]):  # a duplicated key would make the TOML invalid: keep one line
        del lines[i]
    hit = hits[0] if hits else None
    if value is None or value == "" or (key == "mem_patch_heap_size" and value == 0):
        if hit is not None:
            del lines[hit]
        return "".join(lines)
    new_line = f"{key} = {_format(value)}{nl}"
    if hit is not None:
        lines[hit] = new_line
        return "".join(lines)
    after = 0
    for i in range(end):
        m = _KEY_LINE.match(lines[i].rstrip("\r\n"))
        if m and m.group(1) == "profileVersion":
            after = i + 1
            break
    lines.insert(after, new_line)
    return "".join(lines)


# ----------------------------------------------------------------------------- packages in load order
def _dependents(raw) -> list:
    """load_after / load_before as me3 reads them: {id, optional}. An entry without optional, or a bare name, is
    taken as required (me3 itself does not read such a profile)."""
    from roundtable_souls.mods.order import Dependent

    out = []
    for d in raw or []:
        if isinstance(d, dict) and d.get("id"):
            out.append(Dependent(str(d["id"]), d.get("optional") is True))
        elif isinstance(d, str):
            out.append(Dependent(d, False))
    return out


def package_rows(text: str, include_disabled: bool = False) -> list[dict]:
    """Packages with id, path, load_after / load_before ids, in file order. Both me3 shapes. index is the entry's
    block number (as mods.profile_edit numbers them); id is the name the launcher uses (the id, else the folder name);
    me3_id is the id me3 uses (None: me3 uses the path); after and before keep each dependency's optional flag.
    include_disabled: switched-off packages too (me3 orders them, then leaves them out). Empty when the file is not
    valid TOML (me3 does not read it)."""
    if not me3_profile.parses(text):
        return []
    out = []
    for e in me3_profile.entries(text):
        row = e["row"]
        if e["kind"] != "package" or row is None:
            continue
        if not e["enabled"] and not include_disabled:
            continue
        path = e["path"]
        if not path:
            continue
        after = _dependents(row.get("load_after"))
        before = _dependents(row.get("load_before"))
        out.append(
            {
                "index": e["index"],
                "id": str(row.get("id") or Path(path).name),
                "me3_id": str(row["id"]) if row.get("id") else None,
                "path": path,
                "enabled": e["enabled"],
                "load_after": [d.id for d in after],
                "load_before": [d.id for d in before],
                "after": after,
                "before": before,
            }
        )
    return out


def me3_order(profile: Path | None, text: str):
    """The enabled packages in the order me3 loads them (mods.order.Ordered: rows, problem, dropped). With the
    profile's path, packages whose folder is missing are left out first, as me3 does."""
    from roundtable_souls.mods import order

    rows = package_rows(text, include_disabled=True)
    if profile is None:
        return order.order_rows(rows)
    profile = Path(profile)
    return order.order_rows(rows, profile.parent, lambda r: resolve(profile, r["path"]).exists())


# ----------------------------------------------------------------------------- conflict scan (read-only)
def category_of(rel: str) -> str:
    """What the game file at rel is, for the conflict list: the plain name the game's file-category map gives it
    ("characters", "text"); for a path the map does not know, the regulation file's name, the top folder, or "other"
    for a file at the top."""
    known = game_config.load().category_of(rel)
    if known is not None:
        return known
    parts = rel.replace("\\", "/").split("/")
    if parts[0].startswith(REGULATION):
        return REGULATION
    return parts[0] if len(parts) > 1 else "other"


def scan_conflicts(profile: Path, text: str | None = None, max_files: int = 400000) -> dict:
    """Walk every enabled package and report paths two or more provide. Only the game folders at a package's top
    level (parts, chr, ...) are walked: me3 serves a package's files at their path below it, so anything else (a
    folder of other mods, backups, notes) is never asked for by the game and cannot conflict.

    Returns {packages: [{id, path, files, wins, loses, missing}], conflicts: [{path, category, winner, losers}],
             files: total, by_category: {cat: n}, truncated: bool}."""
    profile = Path(profile)
    if text is None:
        text = profile.read_text(encoding="utf-8", errors="replace")
    ordered = me3_order(profile, text)
    order = ordered.rows + [r for r in ordered.dropped if r.get("enabled", True)]  # missing folders: shown, empty
    seen: dict[str, list[tuple[int, str, int, float]]] = {}
    packages = []
    total = 0
    truncated = False
    for rank, row in enumerate(order):
        root = resolve(profile, row["path"])
        info = {"id": row["id"], "path": str(root), "files": 0, "wins": 0, "loses": 0, "missing": not root.is_dir()}
        packages.append(info)
        if info["missing"]:
            continue
        game_folders = ACCEPTABLE_FOLDERS - NOT_GAME_FOLDERS
        for dirpath, dirnames, filenames in os.walk(root):
            if Path(dirpath) == root:
                dirnames[:] = [d for d in dirnames if d.lower() in game_folders]
            else:
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                low = fn.lower()
                if low in IGNORED_NAMES or Path(low).suffix in IGNORED_SUFFIXES:
                    continue
                full = Path(dirpath) / fn
                rel = str(full.relative_to(root)).replace("\\", "/")
                if "/" not in rel and Path(low).suffix in ROOT_DOC_SUFFIXES:
                    continue
                try:
                    st = full.stat()
                except OSError:
                    continue
                seen.setdefault(rel.lower(), []).append((rank, rel, st.st_size, st.st_mtime))
                info["files"] += 1
                total += 1
                if total >= max_files:
                    truncated = True
                    break
            if truncated:
                break
        if truncated:
            break
    conflicts = []
    by_cat: dict[str, int] = {}
    for _key, hits in seen.items():
        if len(hits) < 2:
            continue
        hits.sort()
        win = hits[-1]
        winner = packages[win[0]]
        winner["wins"] += 1
        losers = []
        for rank, _rel, size, _mtime in hits[:-1]:
            packages[rank]["loses"] += 1
            losers.append({"id": packages[rank]["id"], "size": size})
        cat = category_of(win[1])
        by_cat[cat] = by_cat.get(cat, 0) + 1
        conflicts.append(
            {"path": win[1], "category": cat, "winner": winner["id"], "winner_size": win[2], "losers": losers}
        )
    conflicts.sort(key=lambda c: (c["category"], c["path"].lower()))
    return {
        "packages": packages,
        "conflicts": conflicts,
        "files": total,
        "by_category": by_cat,
        "truncated": truncated,
        "order_problem": ordered.problem,  # me3 would not start with this profile (the order shown is the file's)
    }
