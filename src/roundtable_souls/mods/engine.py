"""The launcher's own build of a mod that must stay last, from a recipe instead of the mod's installer: nothing of
the mod's (its installer, its merge tool) runs.

A recipe (one build of an overhaul config, data/overhauls/*.toml, see docs/Overhaul configs.md) says how to
recognise the mod's download (its setup folder: files that must be there, values in its JSON files, the versions it
was written for) and the steps that build its output folder from the packages before it:

    copy_tree / copy   files of the download, as they are
    config             a settings file of the player's: kept when it is there (new keys of a newer default are added,
                       their values never changed), else the download's default
    merge              one file merged by the launcher (merging.merger): the last package before it that ships the
                       file, then the mod's own copy (`patch`), against the game's copy; with no package shipping
                       it, the mod's copy as it is
    text               a text archive: the mod's strings (a JSON list, `texts` by `each` folder) set in one of its
                       tables (`table`) of the game's copy, then merged like `merge`
    params             the parameters (regulation.bin): the launcher's row-by-row combine of that package's and the
                       mod's copy against the game's
    hook               a script fragment: the packages' own script folders copied in load order, then the mod's
                       fragment appended to the entry file (the last package's copy, or the download's base when no
                       package has one), several in step order, each wrapping the one before (overhauls.hooks);
                       refused when that already holds a fragment's markers or is compiled (bytecode), and packages
                       shipping different entry files are a clash, recorded
    remove             leftovers (a glob below the output's mod folder)

`each` repeats a merge, text or params step per folder. Files a format rule does not cover (behaviour and animation
data, .hkx) are taken whole, three-way, as everywhere (merging.merger): changed by one package, its copy; changed
differently by several, the later one's, and a clash. Clashes are written to the build's report (merge-report.txt).

The inputs are only read: the packages' folders and the download. The build happens in a staging folder beside the
output, is checked (every output there and not empty), then swapped in by renaming. The build it replaced is kept in
.roundtable-build/previous beside it, with a restore.json, so Undo rebuild swaps it back. The manifest the mod's own
installer keeps (installation.json: the sources with their sha256) is written the same way, so the launcher's checks
and the mod's installer keep working. The profile is never written.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

from roundtable_souls import formats, overhauls
from roundtable_souls.formats import FormatError
from roundtable_souls.game import catalog as games
from roundtable_souls.game import config as game_config
from roundtable_souls.game import oodle as game_oodle
from roundtable_souls.overhauls import hooks

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations

WORK = ".roundtable-build"  # beside the output: the previous build and its restore.json
STEPS = {"copy_tree", "copy", "config", "merge", "text", "params", "hook", "remove"}


class EngineError(RuntimeError):
    pass


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------------- recipes
def validate(recipe: dict) -> list[str]:
    """What is wrong with a recipe (empty when it can be used)."""
    out = []
    if recipe.get("recipe") != overhauls.RECIPE_VERSION:
        out.append(f"not a version {overhauls.RECIPE_VERSION} recipe")
    for key in ("id", "label", "match", "output", "steps"):
        if key not in recipe:
            out.append(f"no {key}")
    for i, s in enumerate(recipe.get("steps") or []):
        if s.get("do") not in STEPS:
            out.append(f"step {i + 1}: unknown step {s.get('do')!r}")
    return out


def recipes() -> list[dict]:
    """Every usable recipe: each build of each overhaul config (overhauls.load), shipped or local."""
    out = []
    for o in overhauls.load():
        for b in o.builds:
            r = o.recipe(b)
            if not validate(r):
                out.append(r)
    return out


def _json_value(setup: Path, file: str, key: str):
    try:
        return json.loads((setup / file).read_text(encoding="utf-8-sig")).get(key)
    except OSError, ValueError, AttributeError:
        return None


def match(setup: Path | None) -> tuple[dict | None, str | None, str | None]:
    """(recipe, version, why not) for a mod's setup folder: the recipe that fits it and the version it is; or None
    and, when a recipe fits the layout but not this version, why."""
    if setup is None or not Path(setup).is_dir():
        return None, None, None
    setup = Path(setup)
    for r in recipes():
        m = r["match"]
        if not all((setup / f).is_file() for f in m.get("files") or []):
            continue
        if not all(_json_value(setup, c["file"], c["key"]) == c["equals"] for c in m.get("json") or []):
            continue
        v = m.get("version") or {}
        version = str(_json_value(setup, v["file"], v["key"]) or "") if v else ""
        if m.get("versions") and version not in m["versions"]:
            return None, version, f"{r['label']} {version or '(unknown version)'} is newer than the launcher knows"
        return r, version, None
    return None, None, None


# ----------------------------------------------------------------------------- the inputs
def layers(profile: Path, target_folder: Path) -> list[Path]:
    """The enabled packages before the target, in the order its own installer merges them: file order, each moved
    after what it loads after (and before what it loads before), taking the first that can go next."""
    from roundtable_souls.mods import checks
    from roundtable_souls.mods import profile_edit as mod_manage

    rows = [
        e
        for e in mod_manage.entries(profile)
        if e["kind"] == "package"
        and e.get("enabled", True)
        and e.get("path")
        and not checks.same_folder(mod_manage.resolve(profile, e["path"]), target_folder)
    ]
    ids = [(e.get("id") or Path(e["path"]).name) for e in rows]
    if len(set(ids)) != len(ids):
        raise EngineError("The profile loads two packages with the same id; me3 needs each id once.")
    edges: dict[str, set[str]] = {k: set() for k in ids}
    for name, row in zip(ids, rows, strict=True):
        for d in row.get("load_after") or []:
            if d["id"] in edges:
                edges[name].add(d["id"])
        for d in row.get("load_before") or []:
            if d["id"] in edges:
                edges[d["id"]].add(name)
    out, done = [], set()
    while len(out) < len(rows):
        i = next((i for i, k in enumerate(ids) if k not in done and edges[k] <= done), None)
        if i is None:
            raise EngineError("The profile's package load order loops.")
        done.add(ids[i])
        out.append(mod_manage.resolve(profile, rows[i]["path"]))
    for p in out:
        if not p.is_dir():
            raise EngineError(f"An enabled package's folder is missing: {p}")
    return out


def unmet(profile: Path, recipe: dict) -> list[str]:
    """Why the profile cannot have this build: each requirement of the recipe (another mod it needs) that is not
    present and switched on (overhauls.requirements decides), as the refusal says it."""
    from roundtable_souls.mods import profile_edit as mod_manage

    requires = [overhauls.Requirement.model_validate(r) for r in recipe.get("requires") or []]
    if not requires:
        return []
    found = overhauls.requirements.unmet(requires, mod_manage.entries(profile))
    return [overhauls.requirements.refusal(recipe["label"], req) for req, _state in found]


# ----------------------------------------------------------------------------- settings files
def merge_ini(mine: str, default: str) -> str:
    """The player's settings file with the keys a newer default adds (and whole sections it adds), each after the
    last line of its section; the player's own lines and values are never changed."""

    def parse(text):
        sections: dict[str, list[tuple[str, str]]] = {}
        order, cur = [], ""
        sections[cur] = []
        order.append(cur)
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("[") and s.endswith("]"):
                cur = s[1:-1].strip().lower()
                if cur not in sections:
                    sections[cur] = []
                    order.append(cur)
                continue
            if "=" in s and not s.startswith((";", "#")):
                sections[cur].append((s.split("=", 1)[0].strip().lower(), line))
        return sections, order

    have, _ = parse(mine)
    want, want_order = parse(default)
    nl = "\r\n" if "\r\n" in mine else "\n"
    lines = mine.splitlines()
    added_any = False
    for sec in want_order:
        missing = [line for k, line in want[sec] if k not in {x for x, _ in have.get(sec, [])}]
        if not missing:
            continue
        added_any = True
        if sec not in have:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(f"[{next(l for l in default.splitlines() if l.strip().lower() == f'[{sec}]').strip()[1:-1]}]")
            lines += missing
            continue
        at, cur = None, ""
        for i, line in enumerate(lines):
            s = line.strip()
            if s.startswith("[") and s.endswith("]"):
                cur = s[1:-1].strip().lower()
            elif cur == sec and "=" in s and not s.startswith((";", "#")):
                at = i
        if at is None:
            at = next(i for i, l in enumerate(lines) if l.strip().lower() == f"[{sec}]")
        lines[at + 1 : at + 1] = missing
    if not added_any:
        return mine
    return nl.join(lines) + (nl if mine.endswith(("\n", "\r")) or not mine else "")


# ----------------------------------------------------------------------------- building
def _fill(text: str, values: dict) -> str:
    for k, v in values.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def _named(rel: str) -> str:
    """A game path for the build's report, with what it is in plain words when the game's file-category map knows
    it: "chr/c0000.anibnd.dcx (the player character's animations)"."""
    what = game_config.load().category_of(rel)
    return f"{rel} ({what})" if what else rel


def _effective(layers_: list[Path], rel: str) -> Path | None:
    return next((p / rel for p in reversed(layers_) if (p / rel).is_file()), None)


def build(
    profile: Path,
    target_folder: Path,
    setup: Path,
    recipe: dict,
    version: str,
    log,
    game_dir: Path | None = None,
    *,
    loc: Locations,
) -> dict:
    """Build the output of `recipe` for the package in target_folder (its mod folder) from the packages before it,
    swap it in, and return {output, previous, restore, sources, seconds}. loc: the game's locations; game_dir, when
    given, is used instead of loc's game folder. Raises EngineError; the output in place is then unchanged."""
    from roundtable_souls import __version__

    started = time.time()
    profile, target_folder, setup = Path(profile), Path(target_folder), Path(setup)
    out_cfg = recipe["output"]
    if target_folder.name != out_cfg.get("mod", "mod"):
        raise EngineError(f"{recipe['label']}'s package is not in a folder named {out_cfg.get('mod', 'mod')}.")
    own = target_folder.parent
    if own.resolve() == profile.parent.resolve():
        raise EngineError(f"{recipe['label']}'s package must be in a folder of its own.")
    found = loc.game_dir()
    game_dir = Path(game_dir) if game_dir else (Path(found) if found else None)
    if game_dir is None or not game_dir.is_dir():
        raise EngineError("The game folder was not found.")
    refused = unmet(profile, recipe)
    if refused:
        raise EngineError(" ".join(refused))
    inputs = layers(profile, target_folder)
    stage = own.parent / f".{own.name}.building-{int(started)}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    mod = stage / out_cfg.get("mod", "mod")
    sources: list[dict] = []
    report: list[str] = []
    made: list[Path] = []
    hooked: set[tuple[str, str]] = set()
    log(f"engine: building {recipe['label']} {version} from {len(inputs)} package(s), {recipe['id']}")
    try:
        for step in recipe["steps"]:
            kind = step["do"]
            if kind == "copy_tree":
                src = setup / step["from"]
                for p in sorted(src.rglob("*")) if src.is_dir() else []:
                    if p.is_file():
                        dest = stage / step["to"] / p.relative_to(src)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(p, dest)
                        made.append(dest)
            elif kind == "copy":
                dest = stage / step["to"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(setup / step["from"], dest)
                made.append(dest)
            elif kind == "config":
                dest = stage / step["to"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                mine = own / step["to"]
                if mine.is_file():
                    text = mine.read_bytes().decode("utf-8", errors="replace")
                    merged = merge_ini(text, (setup / step["from"]).read_bytes().decode("utf-8", errors="replace"))
                    if merged == text:
                        shutil.copy2(mine, dest)
                    else:
                        dest.write_bytes(merged.encode("utf-8"))
                        log(f"engine: {step['to']} kept; the new settings of this version were added to it")
                else:
                    shutil.copy2(setup / step["from"], dest)
                made.append(dest)
            elif kind in ("merge", "text", "params"):
                names = _each(step, setup)
                for each in names:
                    try:
                        made.append(_launcher_step(step, each, setup, inputs, game_dir, mod, sources, report, log))
                    except FormatError as e:
                        where = _fill(step["file"], {"each": each or ""})
                        raise EngineError(f"{where} could not be merged: {e}") from e
            elif kind == "hook":
                target = (step["folder"], step["entry"])
                if target not in hooked:  # every hook step for this entry, composed at the first one
                    hooked.add(target)
                    same = [h for h in recipe["steps"] if h["do"] == "hook" and (h["folder"], h["entry"]) == target]
                    _hook_step(same, recipe["label"], setup, inputs, mod, sources, report, log)
                    made.append(mod / step["folder"] / step["entry"])
            elif kind == "remove":
                for p in sorted(mod.glob(step["glob"]), reverse=True):
                    if p.is_dir():
                        shutil.rmtree(p)
                    elif p.is_file():
                        p.unlink()
        for name in _notices(recipe, setup, stage):
            log(f"engine: {name} kept beside the mod's DLLs")
        (stage / out_cfg.get("report", "merge-report.txt")).write_text(
            f"{recipe['label']} {version}, built by Roundtable Souls {__version__} from {len(inputs)} package(s).\n"
            + ("".join(f"{line}\n" for line in report) or "No clashes.\n"),
            encoding="utf-8",
            newline="\n",
        )
        empty = [p for p in made if not p.is_file() or p.stat().st_size == 0]
        if empty:
            raise EngineError(f"The build left {empty[0].relative_to(stage)} missing or empty.")
        for row in sources:  # an input that changed while it was being merged
            if not Path(row["path"]).is_file() or _sha(Path(row["path"])) != row["sha256"]:
                raise EngineError(f"An input changed during the build; rebuild again: {row['path']}")
        manifest = _manifest(own, stage, out_cfg, recipe, version, sources, profile, setup, game_dir, __version__)
        (stage / out_cfg.get("manifest", "installation.json")).write_text(
            json.dumps(manifest, indent=2), encoding="utf-8", newline="\n"
        )
        previous, restore = _swap(own, stage, log)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    seconds = time.time() - started
    log(f"engine: {recipe['label']} built in {seconds:.0f}s; the build it replaced is kept for Undo rebuild")
    return {"output": own, "previous": previous, "restore": restore, "sources": sources, "seconds": seconds}


NOTICE_NAMES = re.compile(r"(?i)^(licen[cs]e|notice|copying|third[-_ ]?party[-_ ]?notices?)\b")
NOTICE_FOLDERS = {"licenses", "licences"}


def _notices(recipe: dict, setup: Path, stage: Path) -> list[str]:
    """Licence and notice files the download ships (LICENSE*, NOTICE*, COPYING*, third-party notices, a licenses/
    folder), copied next to the mod's DLLs when present: their licences ask for them to travel with the binaries.
    Looked for beside each DLL a copy step takes, and at the download's top; none is required. Returns what was
    copied (paths in the output)."""
    places: list[tuple[Path, Path]] = []
    for step in recipe["steps"]:
        if step["do"] == "copy" and str(step["to"]).lower().endswith(".dll"):
            dest = (stage / step["to"]).parent
            for src in ((setup / step["from"]).parent, setup):
                if (src, dest) not in places:
                    places.append((src, dest))
    out: list[str] = []
    for src, dest in places:
        for p in sorted(src.iterdir()) if src.is_dir() else []:
            target = dest / p.name
            if target.exists():
                continue
            if p.is_file() and NOTICE_NAMES.match(p.name):
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, target)
            elif p.is_dir() and p.name.lower() in NOTICE_FOLDERS:
                shutil.copytree(p, target)
            else:
                continue
            out.append(target.relative_to(stage).as_posix())
    return out


def _each(step, setup) -> list:
    if not step.get("each"):
        return [None]
    base = setup / step["each"]["folders_in"]
    skip = set(step["each"].get("except") or [])
    return sorted(p.name for p in base.iterdir() if p.is_dir() and p.name not in skip)


_oodle: dict = {}


def _codecs(game_dir: Path):
    """(decompressor, compressor) from the game's own Oodle DLL, or None each (not Windows): only files compressed
    with it need them, and merging one without them stops with the reason."""
    from roundtable_souls.game.oodle import find_oodle

    key = str(game_dir)
    if key not in _oodle:
        _oodle[key] = (find_oodle(game_dir), game_oodle.oodle_compressor(game_dir))
    return _oodle[key]


def _launcher_step(step, each, setup, inputs, game_dir, mod, sources, report, log) -> Path:
    from roundtable_souls.game import archives as gamearchive
    from roundtable_souls.merging import merger
    from roundtable_souls.merging.rules import fmg as fmg_rule
    from roundtable_souls.merging.rules import param as param_merge

    values = {"each": each or ""}
    rel = _fill(step["file"], values)
    out = mod / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    source = _effective(inputs, rel)
    dec, comp = _codecs(game_dir)
    kind = step["do"]
    if kind == "params":
        base = game_dir / rel
        if not base.is_file():
            raise EngineError(f"The game's own {rel} was not found.")
        src = source or base
        sources.append({"path": str(src), "sha256": _sha(src)})
        packs = [] if source is None else [(Path(source).parent.name, source.read_bytes())]
        packs.append(("the mod", (setup / _fill(step["patch"], values)).read_bytes()))
        log(f"  combining {rel}")
        data, _report = param_merge.combine(base.read_bytes(), packs, dec)
        out.write_bytes(data)
        return out
    vanilla = gamearchive.read(game_dir, rel)
    if vanilla is None and step.get("vanilla"):
        vanilla = (setup / _fill(step["vanilla"], values)).read_bytes()
    if kind == "text":
        if vanilla is None:
            raise EngineError(f"The game's own {rel} was not found in its archives.")
        text_map = step["texts"]
        texts_file = setup / text_map.get(each or "", text_map.get("*", ""))
        texts = {int(k): v for k, v in json.loads(texts_file.read_text(encoding="utf-8-sig")).items()}
        body, how = formats.dcx.unpack(vanilla, dec)
        fallback = game_config.load().dflt_fallback_for(rel)
        patch = formats.dcx.pack(fmg_rule.add_text(body, step["table"], texts), how, comp, fallback)
    else:
        patch = (setup / _fill(step["patch"], values)).read_bytes()
        if source is None:  # nothing to merge with: the mod's own copy, as it is
            out.write_bytes(patch)
            return out
    layers = []
    if source is not None:
        sources.append({"path": str(source), "sha256": _sha(source)})
        layers.append((Path(source).as_posix(), source.read_bytes()))
    layers.append(("the mod", patch))
    log(f"  merging {rel}")
    result = merger.merge(vanilla, layers, dec, comp, game_config.load().dflt_fallback_for(rel))
    if result.clashes:
        log(f"  {rel}: {result.summary()}")
        for where, who in sorted(result.clashes.items()):
            report.append(
                f"clash: {_named(rel)} {where}: changed differently by {', '.join(who)}; the last one's is used"
            )
    for where, said in sorted(result.notes.items()):
        report += [f"note: {rel} {where}: {n}" for n in said]
    if not result.merged:
        report.append(f"note: {rel}: could not be merged; the last copy is used whole")
    out.write_bytes(result.data)
    return out


def _hook_step(steps, label, setup, inputs, mod, sources, report, log) -> None:
    """The packages' script folder in load order (a later file of the same name replaces an earlier one), then each
    hook step's fragment appended to the entry script: the last package's copy, else the download's base."""
    first = steps[0]
    folder, name = first["folder"], first["entry"]
    dest = mod / folder
    for layer in inputs:
        src = layer / folder
        for p in sorted(src.rglob("*")) if src.is_dir() else []:
            if p.is_file():
                target = dest / p.relative_to(src)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, target)
    shipped = [(layer, (layer / folder / name).read_bytes()) for layer in inputs if (layer / folder / name).is_file()]
    if len({data for _layer, data in shipped}) > 1:
        names = ", ".join(layer.name for layer, _data in shipped)
        line = f"clash: {_named(f'{folder}/{name}')}: {names} ship different copies; the last one's is used"
        report.append(line)
        log(f"  {line}")
    entry = dest / name
    if entry.is_file():
        base_from = f"{folder}/{name} from {shipped[-1][0].name}" if shipped else f"{folder}/{name}"
        raw = entry.read_bytes()
    else:
        base_from = f"{folder}/{name} from the download"
        raw = (setup / first["base"]).read_bytes()
    try:
        base = hooks.as_text(raw, base_from)
        if not entry.is_file() and first.get("base_until"):
            base = base.split(first["base_until"])[0]
        fragments = [
            hooks.Hook(label, (setup / s["fragment"]).read_text(encoding="utf-8-sig"), s.get("markers") or [],
                       s.get("refuse_text"))
            for s in steps
        ]  # fmt: skip
        composed = hooks.compose(base, base_from, fragments)
    except hooks.HookError as e:
        raise EngineError(str(e)) from e
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(composed.text, encoding="utf-8", newline="\n")
    for layer in inputs:
        src = layer / folder
        for p in src.rglob("*") if src.is_dir() else []:
            if p.is_file():
                sources.append({"path": str(p), "sha256": _sha(p)})


_OWN_KEYS = {"version", "game", "profile", "sources", "refreshProtocol", "maintenance", "builtBy", "recipe", "buildKey"}


def _manifest(own, stage, out_cfg, recipe, version, sources, profile, setup, game_dir, launcher) -> dict:
    """The mod's own manifest, as its installer keeps it (so its checks and a later run of it work), with the new
    sources and a note of who built it."""
    try:
        old = json.loads((own / out_cfg.get("manifest", "installation.json")).read_text(encoding="utf-8"))
    except OSError, ValueError:
        old = {}
    rows = [*sources, {"path": str(profile), "sha256": _sha(profile)}]
    key = hashlib.sha256(
        json.dumps([recipe, version, [(r["path"], r["sha256"]) for r in sources]], sort_keys=True).encode()
    ).hexdigest()
    # what the download says about itself (its edition, ...), read once when it was matched: the values the
    # recipe matched on, so the download's own metadata files are not needed afterwards
    said = {c["key"]: c["equals"] for c in recipe["match"].get("json") or [] if c["key"] not in _OWN_KEYS}
    return {
        **old,
        **said,
        "version": version or old.get("version"),
        "game": old.get("game") or str(game_dir / games.ELDEN_RING.exe),
        "profile": old.get("profile") or str(profile),
        "sources": rows,
        "refreshProtocol": old.get("refreshProtocol", 1),
        "maintenance": old.get("maintenance") or str(setup),
        "builtBy": f"Roundtable Souls {launcher}",
        "recipe": recipe["id"],
        "buildKey": key,
    }


def _rename(src: Path, dst: Path) -> None:
    """A rename that retries briefly: an editor or a virus scanner can hold a folder for a moment."""
    for attempt in range(10):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.5)


def _swap(own: Path, stage: Path, log) -> tuple[Path | None, Path | None]:
    work = own.parent / WORK
    previous = work / "previous"
    work.mkdir(exist_ok=True)
    if previous.exists():
        shutil.rmtree(previous)  # the build before last: rebuildable from the download at any time
    had = own.exists()
    try:
        if had:
            _rename(own, previous)
        try:
            _rename(stage, own)
        except OSError:
            if had:
                _rename(previous, own)
            raise
    except OSError as e:
        raise EngineError(
            f"The new build could not replace {own.name} ({e}). Something has the folder open (an editor, a file "
            "window or the game); close it and rebuild. The old build is unchanged."
        ) from e
    if not had:
        return None, None
    restore = work / "restore.json"
    restore.write_text(
        json.dumps({"directories": [{"path": str(own), "original": str(previous)}]}, indent=2), encoding="utf-8"
    )
    return previous, restore
