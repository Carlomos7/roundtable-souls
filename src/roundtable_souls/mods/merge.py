"""Merge health: which package's regulation.bin me3 uses, whether the profile declares a rebuild tool that folds earlier
packages into it, and whether that merge still matches today's packages.

me3 serves one regulation.bin: the last enabled package in effective load order that has one. A pack placed before
that package keeps its file on disk but applies only if a rebuild tool rebuilds the combined file from it; a pack placed
last replaces the other one's. The merging itself is done by a backend: the launcher's own Combine (see
mods.backends.builtin and merging), or a rebuild tool found next to the package that must stay last (see
mods.backends). This module picks the backend, runs it on request, and checks the list of sources (path + sha256) the rebuild tool
leaves: for every file the rebuild tool took from the layers, the source must be the last enabled package before it that
ships that file (or the game's own file when none does), with the same bytes as today.

States:
    single    0-1 enabled packages have regulation.bin, and no rebuild tool
    stacked   2+ have it and there is no rebuild tool (only the last one's applies)
    current   a rebuild tool's last run matches today's packages
    stale     packages, their files, order or enablement changed since the rebuild tool's last run (or it left no list)
    failed    the launcher's last run of the rebuild tool did not finish or did not verify
Elden Ring profiles only.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from roundtable_souls import games
from roundtable_souls.mods import backends
from roundtable_souls.mods import manage as mod_manage

REGULATION = "regulation.bin"
TALK = "script/talk/m00_00_00_00.talkesdbnd.dcx"
STATE_TEXT = {
    "single": "One package ships parameters",
    "stacked": "Several packages ship parameters; only the last one's apply",
    "current": "Combined parameters are up to date",
    "stale": "Combined parameters are out of date",
    "failed": "Rebuilding combined parameters failed",
}


# ----------------------------------------------------------------------------- hashes
_HASHES: dict[str, tuple[int, int, str]] = {}
_HASHES_LOADED = False


def _hash_file() -> Path:
    from roundtable_souls import folders

    return folders.data_root() / "cache" / "hashes.json"


def sha256(path: Path) -> str | None:
    """sha256 of a file, remembered by path, size and modification time (merged archives are large)."""
    global _HASHES_LOADED
    path = Path(path)
    try:
        st = path.stat()
    except OSError:
        return None
    if not _HASHES_LOADED:
        _HASHES_LOADED = True
        try:
            _HASHES.update({k: tuple(v) for k, v in json.loads(_hash_file().read_text(encoding="utf-8")).items()})
        except OSError, ValueError:
            pass
    key = os.path.normcase(str(path.resolve()))
    hit = _HASHES.get(key)
    if hit and hit[0] == st.st_size and hit[1] == st.st_mtime_ns:
        return hit[2]
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    _HASHES[key] = (st.st_size, st.st_mtime_ns, h.hexdigest())
    try:
        out = _hash_file()
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(_HASHES), encoding="utf-8")
        tmp.replace(out)
    except OSError:
        pass
    return _HASHES[key][2]


# ----------------------------------------------------------------------------- layers
def is_elden_ring(profile: Path) -> bool:
    from roundtable_souls.platform import common

    named = common.profile_games(Path(profile))
    return games.ELDEN_RING.key in named if named else True  # a profile that names no game counts as Elden Ring's


def layers(profile: Path) -> list[dict]:
    """Enabled packages in me3's effective load order: [{index, name, id, folder}]."""
    from roundtable_souls.mods import profile as profile_tools

    profile = Path(profile)
    text = mod_manage.read_text(profile)
    if mod_manage.is_array_form(text):
        text = mod_manage.to_blocks(text)
    by_id = {}
    for e in mod_manage.entries(profile):
        if e["kind"] == "package" and e.get("enabled", True) and e.get("path"):
            by_id[(e.get("id") or Path(e["path"]).name).lower()] = e
    out = []
    for row in profile_tools.me3_order(profile, text).rows:
        e = by_id.get(str(row["id"]).lower())
        if e:
            out.append(
                {
                    "index": e["index"],
                    "name": e["name"],
                    "id": e.get("id") or "",
                    "folder": mod_manage.resolve(profile, e["path"]),
                }
            )
    return out


def _within(inner: Path, outer: Path) -> bool:
    a, b = mod_manage._canon(inner), mod_manage._canon(outer)
    return a == b or b in a.parents


def _rel_in(path: Path, folder: Path) -> str | None:
    try:
        return mod_manage._canon(path).relative_to(mod_manage._canon(folder)).as_posix()
    except ValueError:
        return None


def _winner_files(folder: Path) -> list[str]:
    out = []
    for dirpath, _dirs, files in os.walk(folder):
        for f in files:
            out.append(os.path.normcase(os.path.relpath(os.path.join(dirpath, f), folder)).replace("\\", "/"))
    return out


# ----------------------------------------------------------------------------- the overlay
def _key(profile: Path) -> str:
    return os.path.normcase(str(Path(profile).resolve()))


def _legacy_mark(profile: Path):
    """What launchers before 3.10 kept in their own settings (per PC), or None."""
    from roundtable_souls.settings import load_settings

    return (load_settings().get("parameter_overlays") or {}).get(_key(profile))  # read fresh: Options just set it


def _set_legacy_mark(profile: Path, value) -> None:
    from roundtable_souls.settings import get_settings, load_settings, save_settings

    marks = dict(load_settings().get("parameter_overlays") or {})
    if value is None:
        marks.pop(_key(profile), None)
    else:
        marks[_key(profile)] = value
    save_settings(parameter_overlays=marks)
    get_settings.cache_clear()


def overlay_mark(profile: Path) -> dict | None:
    """What Options set for this profile: {package: folder, rebuild: a rebuild.json or None}, or None (the overlay
    is found from its files). Kept in roundtable.json beside the profile (see mods.profile_settings); a mark in the
    launcher's own settings, where launchers before 3.10 kept it, is moved there the first time it is read."""
    from roundtable_souls.mods import profile_settings as ps

    profile = Path(profile)
    mine = ps.load(profile)
    if "overlay" in mine:
        got = mine["overlay"]
        if isinstance(got, dict) and got.get("package"):
            return {
                "package": ps.from_stored(profile, got["package"]),
                "rebuild": ps.from_stored(profile, got.get("rebuild")),
            }
        return None  # turned off in roundtable.json: found from its files
    got = _legacy_mark(profile)
    mark = None
    if isinstance(got, str) and got:  # before rebuild.json could be picked
        mark = {"package": Path(got), "rebuild": None}
    elif isinstance(got, dict) and got.get("package"):
        mark = {"package": Path(got["package"]), "rebuild": Path(got["rebuild"]) if got.get("rebuild") else None}
    if mark is not None:
        try:
            ps.update(profile, overlay=_stored_mark(profile, mark["package"], mark["rebuild"]))
        except ps.Unreadable, OSError:
            pass  # the folder is read-only or its file unreadable: the launcher's own setting still works
    return mark


def _stored_mark(profile: Path, folder: Path, rebuild_file: Path | None) -> dict:
    from roundtable_souls.mods import profile_settings as ps

    return {"package": ps.to_stored(profile, folder), "rebuild": ps.to_stored(profile, rebuild_file)}


def overlay_override(profile: Path) -> Path | None:
    """The package folder set as this profile's parameter overlay in Options, or None."""
    mark = overlay_mark(profile)
    return mark["package"] if mark else None


def set_overlay_override(profile: Path, folder: Path | None, rebuild_file: Path | None = None) -> str | None:
    """Set (or, with None, clear) the package that must stay last, in roundtable.json beside the profile. When that
    file cannot be written, it goes into the launcher's own settings instead, and the reason is returned."""
    from roundtable_souls.mods import profile_settings as ps

    profile = Path(profile)
    value = None if folder is None else _stored_mark(profile, Path(folder), rebuild_file)
    try:
        ps.update(profile, overlay=value)
    except (ps.Unreadable, OSError) as e:
        legacy = (
            None
            if folder is None
            else {"package": str(Path(folder)), "rebuild": str(rebuild_file) if rebuild_file else None}
        )
        _set_legacy_mark(profile, legacy)
        return f"kept in the launcher's own settings on this PC instead: {e}"
    if _legacy_mark(profile) is not None:
        _set_legacy_mark(profile, None)  # roundtable.json has it now; an old copy must not come back
    return None


def approved(tool) -> bool:
    """Whether the user allowed this rebuild tool (this version of it) to run. The launcher's own combine needs no
    permission."""
    from roundtable_souls.settings import load_settings

    if getattr(tool, "builtin", False):
        return True
    return tool.approval_key() in (load_settings().get("rebuild_approved") or [])


def approve(tool) -> None:
    from roundtable_souls.settings import get_settings, load_settings, save_settings

    keys = list(load_settings().get("rebuild_approved") or [])
    if tool.approval_key() not in keys:
        save_settings(rebuild_approved=[*keys, tool.approval_key()][-50:])
        get_settings.cache_clear()


def overlay(profile: Path, all_layers: list[dict] | None = None) -> tuple[dict | None, object, bool]:
    """(the package that must stay last, its rebuild tool or None, set by hand). Set by hand in Options wins when
    that package is loaded; otherwise it is the package whose rebuild tool is found next to it."""
    profile = Path(profile)
    all_layers = layers(profile) if all_layers is None else all_layers
    mark = overlay_mark(profile)
    if mark is not None:
        layer = next((l for l in all_layers if mod_manage.same_folder(l["folder"], mark["package"])), None)
        if layer is not None:
            return layer, backends.detect_for(profile, layer, mark["rebuild"]), True
    packs = [l for l in all_layers if (l["folder"] / REGULATION).is_file()]
    backend = backends.detect(profile, packs) if packs else None
    if backend is None and packs:
        return _declared_last(profile, all_layers, packs), None, False
    return (backend.package if backend else None), backend, False


def _declared_last(profile: Path, all_layers: list[dict], packs: list[dict]) -> dict | None:
    """A package that ships parameters and whose own entry says it loads after most others (at least two, and at
    least half of the other packages): one that must stay last, whose rebuild tool was not found (its setup files
    are missing). None when there is no such package."""
    by_index = {e["index"]: e for e in mod_manage.entries(profile)}
    refs = {mod_manage.entry_ref(by_index[l["index"]]).lower() for l in all_layers if l["index"] in by_index}
    for layer in reversed(packs):
        e = by_index.get(layer["index"])
        if e is None:
            continue
        others = refs - {mod_manage.entry_ref(e).lower()}
        named = {str(d["id"]).lower() for d in e.get("load_after") or []} & others
        if len(named) >= 2 and len(named) * 2 >= len(others):
            return layer
    return None


def setup_problem(profile: Path, all_layers: list[dict] | None = None, found: tuple | None = None) -> str | None:
    """Why the package that must stay last cannot be rebuilt on this PC (its setup files are missing, or it cannot
    run), or None. A rebuild stops before changing anything when there is one."""
    from roundtable_souls.mods.backends import manifest_refresh

    profile = Path(profile)
    all_layers = layers(profile) if all_layers is None else all_layers
    target, tool, _by_hand = found or overlay(profile, all_layers)
    if target is None or not (Path(target["folder"]) / REGULATION).is_file():
        return None  # nothing to rebuild into, or its parameters do not replace the combined ones
    if tool is not None:
        return tool.problem()
    gone = manifest_refresh.missing(profile, target)
    return manifest_refresh.missing_text(target["name"], gone or ["a rebuild tool beside it (a rebuild.json)"])


# ----------------------------------------------------------------------------- last runs
def _runs_file() -> Path:
    from roundtable_souls import folders

    return folders.data_root() / "merges.json"


def _runs() -> dict:
    try:
        return json.loads(_runs_file().read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}


def last_run(profile: Path) -> dict | None:
    return _runs().get(os.path.normcase(str(Path(profile).resolve())))


def note_run(profile: Path, ok: bool, message: str) -> None:
    runs = _runs()
    runs[os.path.normcase(str(Path(profile).resolve()))] = {"when": time.time(), "ok": ok, "message": message}
    out = _runs_file()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(runs, indent=1), encoding="utf-8")


# ----------------------------------------------------------------------------- health
def _combine_inputs(all_layers: list[dict], target: dict | None, combine) -> list[dict]:
    """Packs with parameters that a combine would take: before the overlay (when there is one), other than the
    overlay and the combined package."""
    skip = {x["index"] for x in (target, combine.package if combine else None) if x}
    order = [l["index"] for l in all_layers]
    stop = order.index(target["index"]) if target is not None and target["index"] in order else len(order)
    return [l for l in all_layers[:stop] if l["index"] not in skip and (l["folder"] / REGULATION).is_file()]


def _shared(all_layers: list[dict], target: dict | None, combine) -> dict[str, list[dict]]:
    """Game files two or more packages before the overlay (other than the combined package) ship."""
    from roundtable_souls.mods.backends import builtin

    skip = combine.package["index"] if combine is not None else None
    order = [l["index"] for l in all_layers]
    stop = order.index(target["index"]) if target is not None and target["index"] in order else len(order)
    return builtin.shared_files([l for l in all_layers[:stop] if l["index"] != skip])


def health(profile: Path) -> dict:
    """{state, text, packs, winner, backend, reasons, run, combine, can_combine, ...} for the profile; state None
    when this does not apply (not an Elden Ring profile, or no profile)."""
    from roundtable_souls.mods.backends import builtin
    from roundtable_souls.platform import common

    profile = Path(profile)
    out = {
        "state": None,
        "text": "",
        "packs": [],
        "winner": None,
        "backend": None,
        "reasons": [],
        "run": None,
        "overlay": None,
        "overlay_set": False,
        "combine": False,
        "can_combine": False,
    }
    if not profile.is_file() or not is_elden_ring(profile):
        return out
    all_layers = layers(profile)
    packs = [l for l in all_layers if (l["folder"] / REGULATION).is_file()]
    out["packs"] = [p["name"] for p in packs]
    out["winner"] = packs[-1]["name"] if packs else None
    target, tool, by_hand = overlay(profile, all_layers)
    combine = builtin.find(profile, all_layers)
    out["overlay"] = target["name"] if target else None
    out["overlay_set"] = by_hand
    out["combine"] = combine is not None
    inputs = _combine_inputs(all_layers, target, combine)
    shared = _shared(all_layers, target, combine)
    out["shared_files"] = sorted(o[0]["rel"] for o in shared.values())
    out["can_combine"] = len(inputs) >= 2 or (combine is not None and bool(inputs)) or bool(shared)
    reasons: list[str] = []
    blocked = setup_problem(profile, all_layers, (target, tool, by_hand))
    if blocked:
        reasons.append(blocked)
    elif target is not None and tool is None and by_hand:
        reasons.append(f"{target['name']} is set as the parameter overlay, but no rebuild tool was found next to it")
    if target is not None and tool is None:
        late = _after(all_layers, packs, target)
        if late:
            reasons.append(f"{late} loads after {target['name']}, the package that must stay last")
    if tool is None and combine is None:
        out["state"] = "stacked" if len(packs) > 1 else "single"
        out["text"] = STATE_TEXT[out["state"]]
        if shared:
            names = ", ".join(out["shared_files"][:3]) + (f" and {len(shared) - 3} more" if len(shared) > 3 else "")
            reasons.append(f"{len(shared)} game file(s) two packages ship can be merged so both apply: {names}")
        out["reasons"] = reasons
        return out
    out["backend"] = tool.label if tool is not None else combine.label
    out["run"] = last_run(profile)
    if combine is not None:
        reasons += [f"Combined files: {r}" for r in combine.reasons(all_layers, target)]
    if tool is not None:
        reasons += stale_reasons(profile, all_layers, packs, tool, common.game_dir())
    run = out["run"]
    made = max(t.report_time() for t in (tool, combine) if t is not None)
    if run and not run["ok"] and run["when"] >= made - 1:
        out["state"] = "failed"
        reasons = [run["message"], *reasons]
    elif reasons:
        out["state"] = "stale"
    elif combine is None and len(inputs) >= 2:
        out["state"] = "stacked"  # the tool takes only the last pack before it: the others' parameters are lost
        reasons = [
            f"{len(inputs)} packs ship parameters before {target['name']}, but only {inputs[-1]['name']}'s reach "
            "it. Combine them so all apply."
        ]
    else:
        out["state"] = "current"
    out["reasons"] = reasons
    out["text"] = STATE_TEXT[out["state"]]
    return out


def stale_reasons(profile: Path, all_layers: list[dict], packs: list[dict], backend, game_dir) -> list[str]:
    """Why the rebuild tool's last run no longer matches today's packages (empty when it does)."""
    target = backend.package
    late = _after(all_layers, packs, target)
    if late:
        return [f"{late} loads after {target['name']}, the package that must stay last"]
    sources = backend.sources()
    if not sources:
        return [f"{backend.label} left no list of what it merged, so it cannot be checked"]
    order = [l["index"] for l in all_layers]
    before = all_layers[: order.index(target["index"])]
    own = backend.own_folders()
    package_folders = [e for e in _package_folders(profile) if not any(_within(e, o) for o in own)]
    files = sorted(_winner_files(target["folder"]), key=len, reverse=True)
    reasons: list[str] = []
    by_file: dict[str, list[tuple[Path, str]]] = {}
    for s in sources:
        here = backends.local_path(s["path"], profile, game_dir)
        norm = os.path.normcase(str(here)).replace("\\", "/")
        rel = next((f for f in files if norm.endswith("/" + f)), None)
        if rel is not None:
            by_file.setdefault(rel, []).append((here, s["sha256"]))
    for rel in sorted(set(by_file) | {f.lower() for f in backend.merges()}):
        used = by_file.get(rel, [])
        expected = next((l for l in reversed(before) if (l["folder"] / rel).is_file()), None)
        layer_used = [
            (p, h)
            for p, h in used
            if not any(_within(p, o) for o in own)
            and (_within(p, profile.parent) or any(_within(p, f) for f in package_folders))
        ]
        if expected is not None:
            want = expected["folder"] / rel
            hit = next(((p, h) for p, h in layer_used if mod_manage.same_folder(p, want)), None)
            if hit is None:
                reasons.append(f"{rel}: {expected['name']} ships it now, but the last rebuild did not use it")
            elif sha256(want) != hit[1]:
                reasons.append(f"{rel}: {expected['name']}'s copy changed since the last rebuild")
        elif layer_used:
            p = layer_used[0][0]
            moved = next((l for l in all_layers if _within(p, l["folder"])), None)
            if moved is not None:
                reasons.append(
                    f"{rel}: {target['name']}'s build still has {moved['name']}'s copy, which now loads after it"
                )
            else:  # the package is no longer in the profile: name it by its folder (the path minus the file)
                folder = _folder_of(p, rel)
                reasons.append(
                    f"{rel}: {folder}'s copy is still in {target['name']}'s build, though {folder} is no longer loaded; "
                    "the game keeps using it until a rebuild"
                )
        else:
            for p, h in used:
                if p.is_file() and not any(_within(p, o) for o in own) and sha256(p) != h:
                    reasons.append(f"{rel}: the game's copy changed since the last rebuild (a game update?)")
                    break
    return reasons


def _folder_of(path: Path, rel: str) -> str:
    """The name of the package folder `path` (a copy of the game file `rel`) sits in."""
    depth = len(Path(rel).parts)
    return path.parents[depth - 1].name if len(path.parents) >= depth else path.parent.name


def _package_folders(profile: Path) -> list[Path]:
    """Every package folder the profile names, loaded or not."""
    return [
        mod_manage.resolve(profile, e["path"])
        for e in mod_manage.entries(profile)
        if e["kind"] == "package" and e.get("path")
    ]


def _after(all_layers: list[dict], packs: list[dict], target: dict) -> str | None:
    """The last package with parameters that loads after the overlay, if any."""
    order = [l["index"] for l in all_layers]
    if target["index"] not in order:
        return None
    at = order.index(target["index"])
    late = [p for p in packs if order.index(p["index"]) > at]
    return late[-1]["name"] if late else None


def covered(backend) -> set[str]:
    """Files (relative, lower-case) the rebuild tool took from somewhere in its last run: the ones it combines."""
    sources = backend.sources() or []
    files = _winner_files(backend.package["folder"])
    out = set()
    for s in sources:
        norm = os.path.normcase(str(s["path"])).replace("\\", "/")
        rel = next((f for f in sorted(files, key=len, reverse=True) if norm.endswith("/" + f)), None)
        if rel:
            out.add(rel)
    return out


# ----------------------------------------------------------------------------- rebuilding
class MergeError(RuntimeError):
    pass


def find_backend(profile: Path):
    """The rebuild tool declared for this profile (set by hand in Options, or found), or None. The launcher's own
    combine is not one: see rebuild()."""
    return overlay(Path(profile))[1]


def ensure_combined(profile: Path, target: dict | None):
    """The combined-parameters package: made (an empty folder with its record, and an entry right before the
    overlay, or after the last package with parameters) when the profile has none, and moved there when a pack
    ended up after it. Returns its CombineTool."""
    from roundtable_souls.mods import stay_last
    from roundtable_souls.mods.backends import builtin

    profile = Path(profile)

    def _write_keeping_last(profile: Path, text: str) -> None:
        # The entry has to be in the overlay's load_after too: me3 orders by load_after runs, so a package the
        # overlay does not list loads after it (and the overlay would win the files the combine made).
        mod_manage._write_ordered(profile, text, "combined parameters", stay_last.target(profile))

    all_layers = layers(profile)
    combine = builtin.find(profile, all_layers)
    text = mod_manage.read_text(profile)
    if mod_manage.is_array_form(text):
        text = mod_manage.to_blocks(text)
    if combine is None:
        pk_root, _nt = mod_manage.roots(profile, text)
        folder = pk_root / builtin.FOLDER
        n = 2
        while folder.exists() and not builtin.is_combined(folder):
            folder = pk_root / f"{builtin.FOLDER}-{n}"
            n += 1
        folder.mkdir(parents=True, exist_ok=True)
        if not (folder / builtin.RECORD).is_file():
            (folder / builtin.RECORD).write_text(json.dumps({"combined": 1, "packs": []}), encoding="utf-8")
        taken = {(e.get("id") or "").lower() for e in mod_manage.entries(profile) if e["kind"] == "package"}
        ident, n = builtin.FOLDER, 2
        while ident in taken:
            ident, n = f"{builtin.FOLDER}-{n}", n + 1
        row = {"kind": "package", "id": ident, "path": mod_manage.rel(profile, folder)}
        text = _place(profile, text, row, target, all_layers)
        _write_keeping_last(profile, text)
    else:
        order = [l["index"] for l in all_layers]
        at = order.index(combine.package["index"])
        shared = {o["index"] for owners in _shared(all_layers, target, combine).values() for o in owners}
        packs_after = [
            l
            for l in all_layers[at + 1 :]
            if ((l["folder"] / REGULATION).is_file() or l["index"] in shared)
            and (target is None or l["index"] != target["index"])
        ]
        before_target = target is None or order.index(target["index"]) > at
        if packs_after or not before_target:  # move it back into place
            o = mod_manage.block_options(text, combine.package["index"])
            row = {"kind": "package", "id": o["id"], "path": o["path"]}
            text = mod_manage.remove_block(text, combine.package["index"])
            _write_keeping_last(profile, text)
            text = _place(profile, mod_manage.read_text(profile), row, overlay(profile)[0], layers(profile))
            _write_keeping_last(profile, text)
    found = builtin.find(profile, layers(profile))
    if found is None:
        raise MergeError("The combined-parameters package could not be added to the profile.")
    return found


def _place(profile: Path, text: str, row: dict, target: dict | None, all_layers: list[dict]) -> str:
    """Add the combined package's entry: right before the overlay, else right after the last package with
    parameters or a file it merges (before whatever follows it), else at the end."""
    if target is not None:
        return mod_manage.insert_entry(text, "package", row, target["index"])
    shared = {o["index"] for owners in _shared(all_layers, None, None).values() for o in owners}
    packs = [l for l in all_layers if (l["folder"] / REGULATION).is_file() or l["index"] in shared]
    if packs:
        following = [
            b["index"] for b in mod_manage.blocks(text) if b["index"] > packs[-1]["index"] and b["kind"] == "package"
        ]
        if following:
            return mod_manage.insert_entry(text, "package", row, following[0])
    return mod_manage.append_entry(text, "package", row)


def rebuild(profile: Path, log, combine: bool | None = None) -> dict:
    """Bring the profile's combined parameters up to date: the launcher's own combine (made when two or more packs
    ship parameters, or when combine is True), then the overlay's rebuild tool, if there is one. Keeps the profile's
    own text when a tool only rewrote it and verifies the result. Raises MergeError (and records the failure)
    otherwise. Returns {backend, profile_note}."""
    from roundtable_souls.mods.backends import builtin
    from roundtable_souls.platform import common

    profile = Path(profile)
    if not is_elden_ring(profile):
        raise MergeError("Combined parameters are only rebuilt for Elden Ring profiles.")
    if common.game_running():
        raise MergeError("Close the game first: the rebuild rewrites files the game has open.")
    all_layers = layers(profile)
    target, tool, _by_hand = overlay(profile, all_layers)
    comb = builtin.find(profile, all_layers)
    inputs = _combine_inputs(all_layers, target, comb)
    blocked = setup_problem(profile, all_layers, (target, tool, _by_hand))
    if blocked:  # before anything is written: the profile stays exactly as it is
        raise MergeError(blocked)
    if tool is not None and not approved(tool):
        raise MergeError(f"{tool.label} has not been allowed to run yet.")
    shared = _shared(all_layers, target, comb)
    wants = combine is True or (combine is None and (comb is not None or len(inputs) >= 2 or bool(shared)))
    if tool is None and not wants:
        raise MergeError(
            "There is nothing to combine: fewer than two packs ship parameters and there is no rebuild tool."
        )
    from roundtable_souls.mods import history

    original = mod_manage.read_text(profile)
    bak = profile.with_name(profile.name + ".bak")
    bak.write_text(original, encoding="utf-8", newline="")
    before = history.snapshot(profile, "before rebuilding")
    log(f"merge: profile saved to {bak.name} and the profile history")
    labels = []
    tool_backup = None
    combined_before = None
    try:
        if wants and combine is not False:
            comb = ensure_combined(profile, target)
            all_layers = layers(profile)
            target, tool, _by_hand = overlay(profile, all_layers)
            comb.run(log, all_layers, target)
            combined_before = comb.previous
            labels.append(comb.label)
        before_tool = mod_manage.read_text(profile)
        note = "the profile was not changed by a rebuild tool"
        if tool is not None:
            log(f"merge: running {tool.label}")
            tool_started = time.time()
            tool.run(log)
            labels.append(tool.label)
            tool_backup = find_tool_backup(profile, tool_started)
            note = keep_profile_text(profile, before_tool, tool)
            log(f"merge: {note}")
    except backends.BackendError as e:
        if mod_manage.read_text(profile) != original and tool is not None:
            _put(profile, mod_manage.read_text(profile) if comb is not None else original)
        note_run(profile, False, str(e))
        raise MergeError(str(e)) from e
    note_run(profile, True, "")
    h = health(profile)
    declined = combine is False and h["state"] == "stacked"  # asked for the tool alone: stacking is known
    if h["state"] != "current" and not declined:
        why = "; ".join(h["reasons"][:3]) or h["text"]
        note_run(profile, False, f"The rebuild finished but does not match the packages: {why}")
        raise MergeError(f"The rebuild finished but does not match the packages: {why}")
    undo = {
        "type": "rebuild",
        "profile": str(profile),
        "name": "the rebuild",
        "profile_before": str(before) if before else None,
        "combined_before": str(combined_before) if combined_before else None,
        "combined_folder": str(comb.folder) if comb is not None and combined_before else None,
        "tool_restore": str(tool_backup) if tool_backup else None,
    }
    return {
        "backend": " then ".join(labels),
        "profile_note": note,
        "profile_before": before,
        "undo": undo,
    }


# ----------------------------------------------------------------------------- before Play
AUTO_KEEP = 3  # rebuild tool backups kept after an automatic rebuild (Nightreign Revive's are about 140 MB each)


def play_check(profile: Path) -> dict | None:
    """What Play has to do about the merged mods first. None: nothing, the game can start. Otherwise the profile's
    health, when a merge exists (the launcher's combine or a rebuild tool) and is out of date or its last run failed,
    with "blocked": why a rebuild cannot run (see setup_problem), or None when Play should rebuild. A profile whose
    packs are only stacked (no merge yet) is not rebuilt by itself: making a combined package is a change to the
    profile the user asks for."""
    profile = Path(profile)
    try:
        if not profile.is_file() or not is_elden_ring(profile):
            return None
        h = health(profile)
    except OSError, ValueError:
        return None
    if h["state"] not in ("stale", "failed") or not h["backend"]:
        return None
    return {**h, "blocked": setup_problem(profile) or None}


def needs_update(profile: Path) -> dict | None:
    """The profile's health when Play should rebuild first (play_check, when nothing stops the rebuild)."""
    h = play_check(profile)
    return h if h is not None and not h["blocked"] else None


def update_before_play(profile: Path, log) -> dict | None:
    """Rebuild when needs_update() says so, then keep only the newest AUTO_KEEP backups of the rebuild tool (the
    older ones go to the Recycle Bin). Returns rebuild()'s result, or None when nothing was needed. Raises MergeError
    when the rebuild fails (the previous result is still in place) or the tool has not been allowed to run."""
    h = needs_update(profile)
    if h is None:
        return None
    log(f"merge: out of date before Play ({'; '.join(h['reasons'][:2]) or h['text']}): rebuilding first")
    out = rebuild(Path(profile), log)
    moved = trim_tool_backups(Path(profile), keep=AUTO_KEEP)
    if moved:
        log(f"merge: {len(moved)} older rebuild backup(s) moved to the Recycle Bin; the newest {AUTO_KEEP} stay")
    return out


# ----------------------------------------------------------------------------- the tool's own backups
def find_tool_backup(profile: Path, since: float) -> Path | None:
    """The restore list (restore.json) a rebuild tool wrote during its run, in a folder of the profile's folder
    (at most two levels down), or None."""
    root = Path(profile).parent
    best = None
    for f in list(root.glob("*/restore.json")) + list(root.glob("*/*/restore.json")):
        try:
            t = f.stat().st_mtime
        except OSError:
            continue
        if t >= since - 1 and (best is None or t > best[0]):
            best = (t, f)
    return best[1] if best else None


def tool_backups(profile: Path) -> list[dict]:
    """The backups rebuild tools keep in the profile's folder (folders holding a restore.json), newest first:
    {folder, when, size}."""
    root = Path(profile).parent
    out = []
    for f in list(root.glob("*/restore.json")) + list(root.glob("*/*/restore.json")):
        d = f.parent
        try:
            size = sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
            when = f.stat().st_mtime
        except OSError:
            continue
        out.append({"folder": d, "when": when, "size": size})
    out.sort(key=lambda x: x["when"], reverse=True)
    return out


def trim_tool_backups(profile: Path, keep: int = 3) -> list[dict]:
    """Move all but the newest `keep` tool backups to the Recycle Bin (so even this can be undone). Returns the trash
    records of what was moved."""
    from roundtable_souls.platform import trash

    moved = []
    for b in tool_backups(profile)[keep:]:
        try:
            moved.append(trash.send(b["folder"]))
        except trash.TrashError:
            continue
    return moved


def _put(profile: Path, text: str) -> None:
    tmp = profile.with_name(profile.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="")
    tmp.replace(profile)


def _shape(profile: Path, text: str, own: list[Path]) -> tuple:
    """What a profile loads, ignoring layout, comments and the load order lists of the rebuild tool's own entries."""
    from roundtable_souls.mods import profile as profile_tools

    if mod_manage.is_array_form(text):
        text = mod_manage.to_blocks(text)
    packages, natives = [], []
    for b in mod_manage.blocks(text):
        o = mod_manage.block_options(text, b["index"])
        if not o["path"]:
            continue
        where = mod_manage._canon(mod_manage.resolve(profile, o["path"]))
        mine = any(_within(where, f) for f in own)
        deps = () if mine else (tuple((d["id"].lower(), d["optional"]) for d in o["load_after"] + o["load_before"]))
        if o["kind"] == "package":
            packages.append((str(where), (o["id"] or "").lower(), o["enabled"], deps))
        else:
            init = json.dumps(o["initializer"], sort_keys=True) if o["initializer"] else ""
            natives.append((str(where), o["enabled"], o["optional"], o["load_early"], init, o["finalizer"], deps))
    return (packages, sorted(natives), profile_tools.read_settings(text))


def keep_profile_text(profile: Path, original: str, backend) -> str:
    """After a rebuild tool rewrote the profile: when it loads the same things as before (only the rebuild tool's own entries'
    load order lists may differ), put the original text back with those lists updated. Otherwise keep the rebuild tool's
    version; the original stays in the .bak. Returns what happened, for the log."""
    now = mod_manage.read_text(profile)
    if now == original:
        return "the profile was not changed"
    own = [mod_manage._canon(f) for f in backend.own_folders()]
    if _shape(profile, now, own) != _shape(profile, original, own):
        return f"{backend.label} changed what the profile loads, so its version is kept; yours is in {profile.name}.bak"
    text = mod_manage.to_blocks(original) if mod_manage.is_array_form(original) else original
    fresh = mod_manage.to_blocks(now) if mod_manage.is_array_form(now) else now
    lists = {}
    for b in mod_manage.blocks(fresh):
        o = mod_manage.block_options(fresh, b["index"])
        where = mod_manage._canon(mod_manage.resolve(profile, o["path"])) if o["path"] else None
        if where is not None and any(_within(where, f) for f in own):
            lists[str(where)] = {"load_after": o["load_after"], "load_before": o["load_before"]}
    for b in mod_manage.blocks(text):
        o = mod_manage.block_options(text, b["index"])
        where = str(mod_manage._canon(mod_manage.resolve(profile, o["path"]))) if o["path"] else ""
        if where in lists:
            text = mod_manage.set_block_options(text, b["index"], lists[where])
    _put(profile, text)
    return "your profile's text and comments were kept; only the rebuild tool's own load order lists were updated"


# ----------------------------------------------------------------------------- install offers
def offer(profile: Path, root: Path, regulation_packages: list[dict]) -> dict:
    """For installing a package with a regulation.bin: what can be offered after the install and plain notes about
    it. merge_combine: the launcher would combine this pack's parameters with the other packs'. merge_tool: the
    overlay's rebuild tool would run. merge_target: the package new packs go before."""
    from roundtable_souls.mods.backends import builtin

    out: dict = {
        "merge_offered": False,
        "merge_label": None,
        "merge_notes": [],
        "merge_source_now": None,
        "merge_target": None,
        "merge_combine": False,
        "merge_tool": False,
    }
    profile, root = Path(profile), Path(root)
    if not is_elden_ring(profile):
        return out
    all_layers = layers(profile)
    target, backend, _by_hand = overlay(profile, all_layers)
    comb = builtin.find(profile, all_layers)
    if target is not None:
        out["merge_target"] = target["name"]  # where "Before" places the pack
    elif comb is not None:
        out["merge_target"] = comb.package["name"]
    others = [
        p
        for p in regulation_packages
        if (target is None or p["index"] != target["index"]) and (comb is None or p["index"] != comb.package["index"])
    ]
    tool_ok = backend is not None and bool(regulation_packages) and regulation_packages[-1]["index"] == target["index"]
    out["merge_combine"] = bool(others)
    out["merge_tool"] = tool_ok
    out["merge_offered"] = out["merge_combine"] or tool_ok
    if not out["merge_offered"]:
        return out
    out["merge_label"] = backend.label if tool_ok else builtin.CombineTool.__name__
    if out["merge_combine"]:
        names = ", ".join(p["name"] for p in others[:3]) + (f" and {len(others) - 3} more" if len(others) > 3 else "")
        out["merge_notes"].append(
            f"Its parameters are combined with {names}'s into one file, so all of them apply; where two packs change "
            "the same row, the later one in load order wins."
        )
    if not tool_ok:
        return out
    winner = backend.package["name"]
    mine = set(_winner_files(root))
    merged = {f.lower() for f in backend.merges()} | covered(backend)
    theirs = set(_winner_files(backend.package["folder"]))
    taken = sorted(f for f in mine & merged if f != REGULATION)
    if taken:
        talk = " (including its talk file, which holds menus such as the one at graces)" if TALK in taken else ""
        out["merge_notes"].append(
            f"{backend.label.capitalize()} also takes {_few(taken)} from this pack{talk}, since it will be the last package before {winner} with them."
        )
    replaced = sorted((mine & theirs) - merged - {REGULATION})
    if replaced:
        out["merge_notes"].append(
            f"{winner} ships {_few(replaced)} too and loads later, so its copies are used instead of this pack's."
        )
    return out


def _few(files: list[str], n: int = 3) -> str:
    shown = ", ".join(Path(f).name for f in files[:n])
    return shown + (f" and {len(files) - n} more" if len(files) > n else "")
