"""Installing a mod: what a download or folder contains (package, DLL or profile; its game folders, settings files and documents), the plan the install dialog shows, copying it into the profile's folders and adding its entries, and adding mods already on disk."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations

import re
import shutil
import time
from pathlib import Path

from roundtable_souls.game import catalog as games
from roundtable_souls.mods.checks import (
    ACCEPTABLE_FOLDERS,
    IGNORED_DLLS,
    _children,
    loose_files,
    same_folder,
)
from roundtable_souls.mods.extract import ARCHIVE_EXTENSIONS, stage
from roundtable_souls.mods.profile_edit import (
    ModError,
    _last_place,
    _ordered,
    _stage_write,
    _write_ordered,
    append_entry,
    block_options,
    blocks,
    entries,
    entry_ref,
    insert_entry,
    is_array_form,
    read_text,
    rel,
    resolve,
    roots,
    slug,
    to_blocks,
)

REGULATION = games.ELDEN_RING.regulation  # the parameter file a package may ship


def detect_kind(folder: Path) -> str:
    """'me3' | 'native' | 'package' | 'unknown' for one folder."""
    folder = Path(folder)
    kids = _children(folder)
    dlls = [c for c in kids if c.is_file() and c.suffix.lower() == ".dll" and c.name.lower() not in IGNORED_DLLS]
    assets = any(c.is_dir() and c.name.lower() in ACCEPTABLE_FOLDERS for c in kids) or (folder / REGULATION).is_file()
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
        or (d / REGULATION).is_file()
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
        elif low == REGULATION:
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
        (d / REGULATION).is_file()
        and not any(c.is_dir() and c.name.lower() in ACCEPTABLE_FOLDERS - {"_backup", "_unknown"} for c in kids)
        and not any(c.is_file() and c.suffix.lower() == ".dll" and c.name.lower() not in IGNORED_DLLS for c in kids)
        and all(Path(f).name.lower() == REGULATION for f, _ in loose_files(d))
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
    if (root / REGULATION).is_file():
        assets.append(REGULATION)
    dlls = sorted(p for p in root.rglob("*.dll") if p.name.lower() not in IGNORED_DLLS)
    me3 = next(iter(root.rglob("*.me3")), None)
    has_dirs = any(c.is_dir() and c.name.lower() in ACCEPTABLE_FOLDERS for c in kids)
    loose = loose_files(root) if kind == "package" and not has_dirs else []
    for _f, sub in loose:
        label = sub or REGULATION
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


def plan_install(
    profile: Path,
    source: Path,
    name: str | None = None,
    pkg_id: str | None = None,
    variant: str | None = None,
    *,
    loc: Locations,
) -> dict:
    """Unpack (archives, into the launcher's temp folder) and describe what install() would do. The unpacked copy is
    kept in the plan ('unpacked'), so replan() can change the folder name, id or variant without unpacking again."""
    profile = Path(profile)
    from roundtable_souls.platform import data_folder

    data_folder.adopt_legacy_profile_folders(profile.parent)
    staging_root = data_folder.temp("installing")
    for old in staging_root.iterdir():  # a crash mid-install can leave a temp folder behind
        try:
            if old.is_dir() and time.time() - old.stat().st_mtime > 3600:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass
    folder, temp = stage(source, staging_root)
    source = Path(source)
    default = source.stem if source.suffix.lower() in (*ARCHIVE_EXTENSIONS, ".dll") else source.name
    return _plan(profile, folder, temp, default, name, pkg_id, variant, loc)


def replan(
    profile: Path,
    plan: dict,
    name: str | None = None,
    pkg_id: str | None = None,
    variant: str | None = None,
    *,
    loc: Locations,
) -> dict:
    """The same unpacked source with another folder name, id or variant."""
    return _plan(
        Path(profile),
        Path(plan["unpacked"]),
        bool(plan.get("staging")),
        plan["default_name"],
        name,
        pkg_id,
        variant,
        loc,
    )


def _plan(profile: Path, folder: Path, temp: bool, default_name: str, name, pkg_id, variant, loc: Locations) -> dict:
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
    if d["kind"] in ("package", "native") and not plan.get("already_listed"):
        from roundtable_souls.mods import order as mod_order

        tgt = mod_order.target(profile, loc)
        if tgt is not None and not same_folder(Path(plan["dest"]), tgt["folder"]):
            plan["stay_last"] = tgt["name"]  # new entries go before it; the dialog offers to keep this one after
    if d["kind"] in ("package", "native"):
        plan["contents"] = contents(d["root"], d["kind"]) + extras(folder, d["root"])
        plan["profiles_inside"] = [str(m.relative_to(folder)) for m in folder.rglob("*.me3")]
    if d["kind"] == "package" and (d["root"] / REGULATION).is_file():
        plan.update(regulation_order(profile, skip=plan.get("dest")))
        from roundtable_souls.mods import rebuild as merge

        plan.update(merge.offer(profile, d["root"], plan["regulation_packages"], loc=loc))
    return plan


def regulation_order(profile: Path, skip: Path | None = None) -> dict:
    """The enabled packages that ship a regulation.bin, in me3's effective load order. me3 serves one regulation.bin:
    the last of these. {regulation_packages: [{index, name}], regulation_winner: name or None}. skip leaves out the
    package in that folder (the mod being reinstalled)."""
    from roundtable_souls.mods import profile as profile_tools

    profile = Path(profile)
    text = read_text(profile)
    items = {e["index"]: e for e in entries(profile)}
    order = profile_tools.me3_order(profile, text).rows
    by_id = {
        (e.get("id") or Path(e.get("path") or "").name).lower(): e for e in items.values() if e["kind"] == "package"
    }
    ships = []
    for row in order:
        e = by_id.get(str(row["id"]).lower())
        folder = resolve(profile, e["path"]) if e else None
        if skip is not None and folder is not None and same_folder(folder, Path(skip)):
            continue
        if e and folder is not None and e.get("enabled", True) and (folder / REGULATION).is_file():
            ships.append({"index": e["index"], "name": e["name"]})
    return {"regulation_packages": ships, "regulation_winner": ships[-1]["name"] if ships else None}


def _copy_into(plan: dict, into: Path) -> None:
    """The mod's files, as the plan picked them, into a new folder `into`."""
    loose = {Path(f).name: sub for f, sub in (plan.get("loose") or [])}
    skip = {n.lower() for n in plan.get("exclude") or []}
    root = Path(plan["root"])

    def left_out(folder, names):
        junk = {"__MACOSX", "Thumbs.db", ".DS_Store"}
        top = Path(folder) == root
        return [n for n in names if n in junk or (top and n.lower() in skip)]

    if loose:
        # loose game files go into the folder the game serves them from; everything else copies as it is
        into.mkdir(parents=True, exist_ok=True)
        for c in _children(root):
            if c.name.lower() in skip:
                continue
            sub = loose.get(c.name)
            if c.is_file() and sub is not None:
                target = (into / sub) if sub else into
                target.mkdir(parents=True, exist_ok=True)
                shutil.copy2(c, target / c.name)
            elif c.is_dir():
                shutil.copytree(c, into / c.name, ignore=left_out)
            else:
                shutil.copy2(c, into / c.name)
    else:
        shutil.copytree(root, into, ignore=left_out)
    for c in plan.get("contents") or []:  # ticked files from beside the mod folder
        if c.get("extra") and c["name"].lower() not in skip:
            shutil.copy2(Path(plan["unpacked"]) / c["extra"], into / c["name"])


def install(profile: Path, plan: dict, overwrite: bool = False, then=None, *, loc: Locations) -> dict:
    """Install the mod as one recoverable operation (see mods.operations): its files are copied into a staging
    folder beside their place and the new profile text is worked out, nothing live changing; then the folder takes
    its place (an existing one, on an update, is kept aside for a rollback) and the profile is written under one
    journal. then(): work that needs the new state (a rebuild); when it fails, the whole install is undone. Returns
    {dest, entries, backup, in_place, order_problem, operation, update, kept}."""
    from roundtable_souls.mods import operations

    profile = Path(profile)
    if plan.get("error"):
        raise ModError(plan["error"])
    dest = Path(plan["dest"])
    in_place = bool(plan.get("in_place"))
    update = dest.exists() and not in_place
    if update and not overwrite:
        raise ModError(f"{dest.name} already exists in {dest.parent}")
    with operations.lock(profile):
        operations.recover(profile)
        op = operations.start(profile, f"{'update' if update else 'install'} of {plan['name']}")
        try:
            out = _prepare(profile, plan, dest, in_place, update, op, loc)
        except BaseException:
            op.discard()
            raise
        operations.commit(op, then)
    if plan.get("staging"):
        shutil.rmtree(plan["staging"], ignore_errors=True)
    return out


def _prepare(profile: Path, plan: dict, dest: Path, in_place: bool, update: bool, op, loc: Locations) -> dict:
    """Stage install()'s files and profile text in op. Nothing live changes."""
    from roundtable_souls.mods import operations

    skip = {n.lower() for n in plan.get("exclude") or []}
    kept: list[str] = []
    if not in_place:
        staged = dest.with_name(f".{dest.name}.staging-{op.id}")
        _copy_into(plan, staged)
        if update:
            kept = operations.keep_user_edits(profile, dest, staged)
        op.replace_folder(dest, staged)
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
    from roundtable_souls.mods import order as mod_order

    tgt = mod_order.target(profile, loc)
    after_it = bool(plan.get("after_overlay")) and tgt is not None
    before = plan.get("insert_before")  # a package's name: where it is now, not where it was when the plan was made
    if isinstance(before, str):
        before = next(
            (x["index"] for x in entries(profile) if x["kind"] == "package" and x["name"].lower() == before.lower()),
            None,
        )
    for e in added:
        where = before
        if after_it:  # kept after the mod that must stay last on purpose: last, and saying so in its own entry
            items = mod_order._items(profile, text)
            pkg, last, _mine = mod_order._roles(profile, items, tgt)
            owner = pkg if e["kind"] == "package" else (last[0] if last else None)
            if owner is not None:
                e = {**e, "load_after": [{"id": entry_ref(owner), "optional": True}]}
            where = None
        elif where is None or e["kind"] == "native":
            where = _last_place(profile, text, e["kind"], tgt)
        text = append_entry(text, e["kind"], e) if where is None else insert_entry(text, e["kind"], e, where)
    problem = None
    bak = None
    if added or text != read_text(profile):
        text, problem = _ordered(profile, text, tgt)
        bak = _stage_write(op, profile, text, f"before installing {plan['name']}")
    out = {
        "dest": dest,
        "entries": added,
        "backup": bak,
        "in_place": in_place,
        "order_problem": problem,
        "operation": str(op.dir),
        "update": update,
        "kept": kept,
    }
    operations.describe(op, profile, plan, dest, in_place, update, added, kept)
    return out


def add_existing(profile: Path, folders: list[Path], kind: str = "package", *, loc: Locations) -> dict:
    """List files that already sit in place as entries, last in the load order. Nothing is copied. Packages are
    folders and get an id from the path below the packages folder ('improved-textures/architecture' ->
    improved-textures-architecture); natives are DLL files, named by their file."""
    profile = Path(profile)
    text = read_text(profile)
    if is_array_form(text):
        text = to_blocks(text)
    from roundtable_souls.mods import order as mod_order

    tgt = mod_order.target(profile, loc)
    pk_root, _nt = roots(profile, text)
    have = {(block_options(text, b["index"]).get("id") or "").lower() for b in blocks(text) if b["kind"] == "package"}
    added = []

    def put(text, row):
        where = _last_place(profile, text, row["kind"], tgt)
        return append_entry(text, row["kind"], row) if where is None else insert_entry(text, row["kind"], row, where)

    for f in folders:
        f = Path(f)
        if kind == "native":
            row = {"kind": "native", "path": rel(profile, f)}
            text = put(text, row)
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
        text = put(text, row)
        added.append(row)
    bak, problem = _write_ordered(profile, text, "before adding existing mods", tgt) if added else (None, None)
    return {"entries": added, "backup": bak, "order_problem": problem}
