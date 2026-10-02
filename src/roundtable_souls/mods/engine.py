"""The launcher's own build of a mod that must stay last, from a recipe instead of the mod's installer.

A recipe (data/recipes/*.json, see docs/Rebuild tools.md) says how to recognise the mod's download (its setup folder:
files that must be there, values in its JSON files, the versions it was written for) and the steps that build its
output folder from the packages before it:

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
    tool               one file merged by the mod's own tool, where the launcher cannot merge it yet: {source} is
                       that file from the last package before it that ships it (else what `missing` says: the game's
                       copy, the download's vanilla copy, or the patch copied as it is), {patch}, {out}, {setup},
                       {text}; `each` repeats any step per folder
    script_append      a script: the packages' own script folders copied in load order, then the mod's text appended
                       to the entry file (or to the download's base when no package has one)
    remove             leftovers of the tool (a glob below the output's mod folder)

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
import shutil
import subprocess
import time
from pathlib import Path

from roundtable_souls import formats
from roundtable_souls.formats import FormatError
from roundtable_souls.game import config as game_config
from roundtable_souls.game import oodle as game_oodle
from roundtable_souls.resources import DATA_DIR

RECIPES_DIR = DATA_DIR / "recipes"
WORK = ".roundtable-build"  # beside the output: the previous build and its restore.json
STEPS = {"copy_tree", "copy", "config", "tool", "merge", "text", "params", "script_append", "remove"}


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
    if recipe.get("recipe") != 1:
        out.append("not a version 1 recipe")
    for key in ("id", "label", "match", "tool", "output", "steps"):
        if key not in recipe:
            out.append(f"no {key}")
    for i, s in enumerate(recipe.get("steps") or []):
        if s.get("do") not in STEPS:
            out.append(f"step {i + 1}: unknown step {s.get('do')!r}")
        elif s["do"] == "tool" and not (s.get("file") and s.get("args")):
            out.append(f"step {i + 1}: a tool step needs file and args")
    return out


def recipes() -> list[dict]:
    """Every usable recipe the launcher ships."""
    out = []
    for f in sorted(RECIPES_DIR.glob("*.json")) if RECIPES_DIR.is_dir() else []:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except OSError, ValueError:
            continue
        if isinstance(r, dict) and not validate(r):
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


def _seamless(profile: Path) -> Path | None:
    from roundtable_souls.mods import profile_edit as mod_manage

    for e in mod_manage.entries(profile):
        if e["kind"] == "native" and e.get("enabled", True) and Path(e.get("path") or "").name.lower() == "ersc.dll":
            return mod_manage.resolve(profile, e["path"])
    return None


# ----------------------------------------------------------------------------- the tool
def run_tool(exe: Path, args: list[str], env: dict, timeout: int, cwd: Path) -> tuple[int, str]:
    """Run the mod's tool once: (exit code, its output)."""
    from roundtable_souls.platform import proc

    try:
        p = subprocess.run(
            [str(exe), *args],
            env={**os.environ, **env},
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=proc.NO_WINDOW,
        )
    except subprocess.TimeoutExpired as e:
        raise EngineError(f"{Path(exe).name} took longer than {timeout // 60} minutes and was stopped.") from e
    except OSError as e:
        raise EngineError(f"{Path(exe).name} could not start: {e}") from e
    return p.returncode, (p.stdout or "") + (p.stderr or "")


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
) -> dict:
    """Build the output of `recipe` for the package in target_folder (its mod folder) from the packages before it,
    swap it in, and return {output, previous, restore, sources, seconds}. Raises EngineError; the output in place is
    then unchanged."""
    from roundtable_souls import __version__
    from roundtable_souls.platform import paths as common

    started = time.time()
    profile, target_folder, setup = Path(profile), Path(target_folder), Path(setup)
    out_cfg = recipe["output"]
    if target_folder.name != out_cfg.get("mod", "mod"):
        raise EngineError(f"{recipe['label']}'s package is not in a folder named {out_cfg.get('mod', 'mod')}.")
    own = target_folder.parent
    if own.resolve() == profile.parent.resolve():
        raise EngineError(f"{recipe['label']}'s package must be in a folder of its own.")
    game_dir = Path(game_dir) if game_dir else (Path(common.game_dir()) if common.game_dir() else None)
    if game_dir is None or not game_dir.is_dir():
        raise EngineError("The game folder was not found.")
    if _seamless(profile) is None:
        raise EngineError(f"{recipe['label']} needs Seamless Co-op (ersc.dll) switched on in the profile.")
    inputs = layers(profile, target_folder)
    tool = recipe["tool"]
    exe = setup / tool["path"]
    env = {k: _fill(v, {"game_dir": game_dir}) for k, v in (tool.get("env") or {}).items()}
    timeout = int(tool.get("timeout") or 900)
    stage = own.parent / f".{own.name}.building-{int(started)}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    mod = stage / out_cfg.get("mod", "mod")
    sources: list[dict] = []
    report: list[str] = []
    made: list[Path] = []
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
                        made.append(_launcher_step(step, each, setup, inputs, game_dir, mod, sources, log))
                    except FormatError as e:
                        where = _fill(step["file"], {"each": each or ""})
                        raise EngineError(f"{where} could not be merged: {e}") from e
            elif kind == "tool":
                if step.get("each"):
                    base = setup / step["each"]["folders_in"]
                    skip = set(step["each"].get("except") or [])
                    names = sorted(p.name for p in base.iterdir() if p.is_dir() and p.name not in skip)
                else:
                    names = [None]
                for each in names:
                    made.append(
                        _tool_step(step, each, setup, inputs, game_dir, mod, exe, env, timeout, sources, report, log)
                    )
            elif kind == "script_append":
                _script_step(step, setup, inputs, mod, sources)
                made.append(mod / step["folder"] / step["entry"])
            elif kind == "remove":
                for p in sorted(mod.glob(step["glob"]), reverse=True):
                    if p.is_dir():
                        shutil.rmtree(p)
                    elif p.is_file():
                        p.unlink()
        (stage / out_cfg.get("report", "merge-report.txt")).write_text(
            "\n".join(report), encoding="utf-8", newline="\n"
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


def _launcher_step(step, each, setup, inputs, game_dir, mod, sources, log) -> Path:
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
    out.write_bytes(result.data)
    return out


def _tool_step(step, each, setup, inputs, game_dir, mod, exe, env, timeout, sources, report, log) -> Path:
    values = {"each": each or ""}
    rel = _fill(step["file"], values)
    out = mod / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    source = _effective(inputs, rel)
    missing = step.get("missing", "copy_patch")
    patch = setup / _fill(step["patch"], values) if step.get("patch") else None
    if source is None:
        if missing == "game":
            source = game_dir / rel
            if not source.is_file():
                raise EngineError(f"The game's own {rel} was not found.")
        elif missing == "copy_patch":
            if patch is None:
                raise EngineError(f"The recipe's step for {rel} has no patch to copy.")
            log(f"  {rel}: no package ships it; the mod's own copy is used")
            shutil.copy2(patch, out)
            return out
        else:
            source = setup / _fill(missing, values)
    sources.append({"path": str(source), "sha256": _sha(source)})
    text = ""
    if step.get("text"):
        text_map = step["text"]
        text = str(setup / text_map.get(each or "", text_map.get("*", "")))
    args = [
        _fill(a, {"source": source, "patch": patch or "", "out": out, "setup": setup, "text": text, "each": each or ""})
        for a in step["args"]
    ]
    log(f"  merging {rel}")
    code, said = run_tool(exe, args, env, timeout, setup)
    report.append(said)
    if code != 0:
        raise EngineError(f"{Path(exe).name} could not merge {rel} (exit {code}): {said.strip()[-300:]}")
    return out


def _script_step(step, setup, inputs, mod, sources) -> None:
    dest = mod / step["folder"]
    for layer in inputs:
        src = layer / step["folder"]
        for p in sorted(src.rglob("*")) if src.is_dir() else []:
            if p.is_file():
                target = dest / p.relative_to(src)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, target)
    entry = dest / step["entry"]
    if entry.is_file():
        original = entry.read_text(encoding="utf-8-sig")
    else:
        original = (setup / step["base"]).read_text(encoding="utf-8-sig")
        if step.get("base_until"):
            original = original.split(step["base_until"])[0]
    if any(m in original for m in step.get("refuse") or []):
        raise EngineError(step.get("refuse_text") or "A package before it already contains its script.")
    extension = (setup / step["append"]).read_text(encoding="utf-8-sig")
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(original + "\n" + extension, encoding="utf-8", newline="\n")
    for layer in inputs:
        src = layer / step["folder"]
        for p in src.rglob("*") if src.is_dir() else []:
            if p.is_file():
                sources.append({"path": str(p), "sha256": _sha(p)})


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
    return {
        **old,
        "version": version or old.get("version"),
        "game": old.get("game") or str(game_dir / "eldenring.exe"),
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
