"""Merge health: which package's regulation.bin me3 uses, whether the profile declares a rebuild tool that folds earlier
packages into it, and whether that merge still matches today's packages.

me3 serves one regulation.bin: the last enabled package in effective load order that has one. A pack placed before
that package keeps its file on disk but applies only if a rebuild tool rebuilds the combined file from it; a pack placed
last replaces the other one's. The launcher never merges files itself. It finds a rebuild tool next to the package that
must stay last (see mods.backends), runs it on request, and checks the list of sources (path + sha256) the rebuild tool
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
    from roundtable_souls.system import common

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
    for row in profile_tools.effective_order(profile_tools.package_rows(text)):
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


def overlay_mark(profile: Path) -> dict | None:
    """What Options set for this profile: {package: folder, rebuild: a rebuild.json or None}, or None (the overlay
    is found from its files)."""
    from roundtable_souls.settings import load_settings

    got = (load_settings().get("parameter_overlays") or {}).get(_key(profile))  # read fresh: Options just set it
    if isinstance(got, str) and got:  # before rebuild.json could be picked
        return {"package": Path(got), "rebuild": None}
    if isinstance(got, dict) and got.get("package"):
        return {"package": Path(got["package"]), "rebuild": Path(got["rebuild"]) if got.get("rebuild") else None}
    return None


def overlay_override(profile: Path) -> Path | None:
    """The package folder set as this profile's parameter overlay in Options, or None."""
    mark = overlay_mark(profile)
    return mark["package"] if mark else None


def set_overlay_override(profile: Path, folder: Path | None, rebuild_file: Path | None = None) -> None:
    from roundtable_souls.settings import get_settings, load_settings, save_settings

    marks = dict(load_settings().get("parameter_overlays") or {})
    if folder is None:
        marks.pop(_key(profile), None)
    else:
        marks[_key(profile)] = {"package": str(Path(folder)), "rebuild": str(rebuild_file) if rebuild_file else None}
    save_settings(parameter_overlays=marks)
    get_settings.cache_clear()


def approved(tool) -> bool:
    """Whether the user allowed this rebuild tool (this version of it) to run."""
    from roundtable_souls.settings import load_settings

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
    return (backend.package if backend else None), backend, False


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
def health(profile: Path) -> dict:
    """{state, text, packs, winner, backend, reasons, run} for the profile; state None when this does not apply
    (not an Elden Ring profile, or no profile)."""
    from roundtable_souls.system import common

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
    }
    if not profile.is_file() or not is_elden_ring(profile):
        return out
    all_layers = layers(profile)
    packs = [l for l in all_layers if (l["folder"] / REGULATION).is_file()]
    out["packs"] = [p["name"] for p in packs]
    out["winner"] = packs[-1]["name"] if packs else None
    target, backend, by_hand = overlay(profile, all_layers)
    out["overlay"] = target["name"] if target else None
    out["overlay_set"] = by_hand
    if backend is None:
        out["state"] = "stacked" if len(packs) > 1 else "single"
        out["text"] = STATE_TEXT[out["state"]]
        if target is not None:
            out["reasons"] = [
                f"{target['name']} is set as the parameter overlay, but no rebuild tool was found next to it"
            ]
            late = _after(all_layers, packs, target)
            if late:
                out["reasons"].append(f"{late} loads after {target['name']}, the package that must stay last")
        return out
    out["backend"] = backend.label
    out["run"] = last_run(profile)
    reasons = stale_reasons(profile, all_layers, packs, backend, common.game_dir())
    run = out["run"]
    if run and not run["ok"] and run["when"] >= backend.report_time() - 1:
        out["state"] = "failed"
        reasons = [run["message"], *reasons]
    else:
        out["state"] = "stale" if reasons else "current"
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
            gone = next((l for l in all_layers if _within(p, l["folder"])), None)
            who = gone["name"] if gone else p.parent.name
            reasons.append(
                f"{rel}: the last rebuild used {who}'s copy, which is no longer loaded before {target['name']}"
            )
        else:
            for p, h in used:
                if p.is_file() and not any(_within(p, o) for o in own) and sha256(p) != h:
                    reasons.append(f"{rel}: the game's copy changed since the last rebuild (a game update?)")
                    break
    return reasons


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
    """The rebuild tool declared for this profile (set by hand in Options, or found), or None."""
    return overlay(Path(profile))[1]


def rebuild(profile: Path, log) -> dict:
    """Run the profile's rebuild tool, keep the profile's own text (comments, layout) when the rebuild tool only rewrote it, and
    verify the result from the rebuild tool's list of sources. Raises MergeError (and records the failure) otherwise.
    Returns {backend, profile_note}."""
    from roundtable_souls.system import common

    profile = Path(profile)
    if not is_elden_ring(profile):
        raise MergeError("Combined parameters are only rebuilt for Elden Ring profiles.")
    if common.game_running():
        raise MergeError("Close the game first: the rebuild tool rewrites files the game has open.")
    backend = find_backend(profile)
    if backend is None:
        raise MergeError("This profile has no rebuild tool for combined parameters.")
    if not approved(backend):
        raise MergeError(f"{backend.label} has not been allowed to run yet.")
    original = mod_manage.read_text(profile)
    bak = profile.with_name(profile.name + ".bak")
    bak.write_text(original, encoding="utf-8", newline="")
    log(f"merge: profile saved to {bak.name}; running {backend.label}")
    try:
        backend.run(log)
    except backends.BackendError as e:
        if mod_manage.read_text(profile) != original:
            _put(profile, original)
        note_run(profile, False, str(e))
        raise MergeError(str(e)) from e
    note = keep_profile_text(profile, original, backend)
    log(f"merge: {note}")
    note_run(profile, True, "")
    h = health(profile)
    if h["state"] != "current":
        why = "; ".join(h["reasons"][:3]) or h["text"]
        note_run(profile, False, f"The rebuild finished but does not match the packages: {why}")
        raise MergeError(f"The rebuild finished but does not match the packages: {why}")
    return {"backend": backend.label, "profile_note": note}


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
    """For installing a package with a regulation.bin: whether a rebuild can be offered, and plain notes on what
    the rebuild tool and the package that must stay last will do with this pack's files. Placement before that package is
    what a rebuild needs; the dialog offers it only then."""
    out: dict = {
        "merge_offered": False,
        "merge_label": None,
        "merge_notes": [],
        "merge_source_now": None,
        "merge_target": None,
    }
    profile, root = Path(profile), Path(root)
    if not is_elden_ring(profile):
        return out
    target, backend, _by_hand = overlay(profile)
    if target is not None:
        out["merge_target"] = target["name"]  # where "Before" places the pack
    if backend is None or not regulation_packages:
        return out
    if regulation_packages[-1]["index"] != target["index"]:
        return out  # another pack already loads after the overlay: nothing honest to offer
    winner = backend.package["name"]
    out["merge_offered"] = True
    out["merge_label"] = backend.label
    if len(regulation_packages) > 1:
        out["merge_source_now"] = regulation_packages[-2]["name"]
    out["merge_label"] = backend.label
    mine = set(_winner_files(root))
    merged = {f.lower() for f in backend.merges()} | covered(backend)
    theirs = set(_winner_files(backend.package["folder"]))
    taken = sorted(f for f in mine & merged if f != REGULATION)
    if taken:
        talk = " (including its talk file, which holds menus such as the one at graces)" if TALK in taken else ""
        out["merge_notes"].append(
            f"The rebuild also takes {_few(taken)} from this pack{talk}, since it will be the last package before {winner} with them."
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
