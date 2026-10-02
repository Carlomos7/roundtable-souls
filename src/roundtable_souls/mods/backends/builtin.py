"""The launcher's own combine: a package it manages (combined-parameters) holding one regulation.bin that applies
every pack's changes to the game's own file (see merging.rules.param), every other game file two or more packages ship
merged the same way (see merging.merger: archives file by file, text entry by entry), and a record of what went in.

It sits after the last package that ships parameters, or, when a package that must stay last has a rebuild tool of
its own, right before that package, so that tool takes the combined file as its source. It is found by its record,
never by a name: moving or renaming the folder keeps it working.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from roundtable_souls import formats
from roundtable_souls.game import config as game_config
from roundtable_souls.game import oodle as game_oodle
from roundtable_souls.merging import record as merge_record
from roundtable_souls.merging.build import Build, BuildError
from roundtable_souls.mods.backends import BackendError

RECORD = "combined-parameters.json"
FOLDER = "combined-parameters"
REGULATION = "regulation.bin"


def _sha(p: Path) -> str:
    from roundtable_souls.mods import merge

    return merge.sha256(p) or ""


def _me3_version() -> str | None:
    """The installed me3's version, for the record (None when it cannot be asked)."""
    from roundtable_souls.platform import common, me3_info

    try:
        return me3_info.me3_version(common.me3_exe())
    except Exception:
        return None


def is_combined(folder: Path) -> bool:
    try:
        data = json.loads((Path(folder) / RECORD).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return False
    return isinstance(data, dict) and data.get("combined") == 1


def find(profile: Path, all_layers: list[dict]) -> CombineTool | None:
    """The combined package's tool. A rebuild of it that was interrupted while being put in place is undone first,
    so what is read (its record, its files, its health) is one whole build."""
    from roundtable_souls.merging.build import recover

    layer = next((l for l in all_layers if is_combined(l["folder"])), None)
    if layer is None:
        return None
    try:
        recover(Path(layer["folder"]))
    except OSError:
        pass  # left for the next rebuild, which tries again before it starts
    return CombineTool(Path(profile), layer)


def game_regulation() -> Path | None:
    from roundtable_souls.platform import common

    d = common.game_dir()
    p = Path(d) / REGULATION if d else None
    return p if p is not None and p.is_file() else None


HISTORY_KEEP = 3  # earlier combined outputs kept for Undo rebuild


def _shipped(folder: Path) -> list[str]:
    """Game files a package ships that the merger can take: compressed game files (archives, text), relative, with /."""
    out = []
    for dirpath, _dirs, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(".dcx"):
                out.append(os.path.relpath(os.path.join(dirpath, f), folder).replace("\\", "/"))
    return out


def shared_files(layers: list[dict]) -> dict[str, list[dict]]:
    """Files (lower-case relative path) two or more of these packages ship -> those packages, in load order."""
    owners: dict[str, list[dict]] = {}
    for layer in layers:
        for rel in _shipped(Path(layer["folder"])):
            owners.setdefault(rel.lower(), []).append({**layer, "rel": rel})
    return {k: v for k, v in owners.items() if len(v) > 1}


def archives_fingerprint(game_dir) -> str:
    """Changes when the game's archives do (a game update): the merged files are then merged again."""
    from roundtable_souls.game import archives as gamearchive

    parts = []
    for name in gamearchive.ARCHIVES:
        try:
            st = (Path(game_dir) / f"{name}.bhd").stat()
            parts.append(f"{name}:{st.st_size}:{st.st_mtime_ns}")
        except OSError, TypeError:
            parts.append(f"{name}:-")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def history_root(profile: Path) -> Path:
    """Where earlier combined outputs of one profile are kept: the data folder, never beside the profile."""
    import hashlib
    import os

    from roundtable_souls import folders

    key = hashlib.sha1(os.path.normcase(os.path.abspath(profile)).encode()).hexdigest()[:8]
    return folders.data_root() / "mods" / "combined-history" / f"{Path(profile).stem}-{key}"


class CombineTool:
    builtin = True
    previous: Path | None = None  # where the output this run replaced was kept

    def __init__(self, profile: Path, layer: dict):
        self.profile = profile
        self.package = layer
        self.label = "the launcher's parameter combine"
        self.folder = Path(layer["folder"])

    # -------------------------------------------------------------- record
    def record(self) -> dict:
        try:
            return json.loads((self.folder / RECORD).read_text(encoding="utf-8"))
        except OSError, ValueError:
            return {}

    def own_folders(self) -> list[Path]:
        return [self.folder]

    def merges(self) -> set[str]:
        return {REGULATION}

    def sources(self) -> list[dict] | None:
        rows = self.record().get("sources")
        return rows if isinstance(rows, list) and rows else None

    def report_time(self) -> float:
        try:
            return (self.folder / RECORD).stat().st_mtime
        except OSError:
            return 0.0

    def problem(self) -> str | None:
        if game_regulation() is None:
            return "The game's own regulation.bin was not found (it is the base every pack is compared with)."
        return None

    def approval_key(self) -> str:
        return "builtin"

    def describe(self) -> str:
        return "the launcher combines the packs' parameters itself"

    # -------------------------------------------------------------- what goes in
    def inputs(self, all_layers: list[dict], until: dict | None) -> list[dict]:
        """The packs to combine, in load order: every enabled package with a regulation.bin before `until` (the
        package that must stay last, when there is one) other than this one."""
        order = [l["index"] for l in all_layers]
        stop = order.index(until["index"]) if until is not None and until["index"] in order else len(order)
        return [
            l
            for l in all_layers[:stop]
            if l["index"] != self.package["index"] and (Path(l["folder"]) / REGULATION).is_file()
        ]

    def _keep_previous(self) -> Path | None:
        """Keep the output about to be replaced (for Undo rebuild); the newest HISTORY_KEEP are kept."""
        import shutil

        rec = self.record()
        if not (rec.get("packs") or rec.get("files")):  # nothing was built yet: the new package's empty record
            return None
        root = history_root(self.profile)
        dest = root / time.strftime("%Y%m%d-%H%M%S")
        n = 2
        while dest.exists():
            dest = root / f"{time.strftime('%Y%m%d-%H%M%S')}-{n}"
            n += 1
        try:
            dest.mkdir(parents=True)
            for f in self.folder.rglob("*"):
                if f.is_file() and not f.name.endswith(".tmp"):
                    (dest / f.relative_to(self.folder)).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dest / f.relative_to(self.folder))
        except OSError:
            return None
        for old in sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True)[HISTORY_KEEP:]:
            shutil.rmtree(old, ignore_errors=True)
        return dest

    def file_inputs(self, all_layers: list[dict], until: dict | None) -> list[dict]:
        """The packages whose shared files are merged: every enabled package before `until` other than this one."""
        order = [l["index"] for l in all_layers]
        stop = order.index(until["index"]) if until is not None and until["index"] in order else len(order)
        return [l for l in all_layers[:stop] if l["index"] != self.package["index"]]

    def file_reasons(self, all_layers: list[dict], until: dict | None) -> list[str]:
        """Why the merged files no longer match today's packages."""
        from roundtable_souls.platform import common

        rec = self.record()
        done = rec.get("files") or {}
        shared = shared_files(self.file_inputs(all_layers, until))
        out = []
        if (done or shared) and rec.get("archives") and rec["archives"] != archives_fingerprint(common.game_dir()):
            return ["the game's own files changed since they were merged (a game update?)"]
        for low, owners in sorted(shared.items()):
            had = done.get(low)
            now = [os.path.normcase(str(Path(o["folder"]) / o["rel"])) for o in owners]
            names = " and ".join(o["name"] for o in owners)
            if had is None:
                out.append(f"{names} both ship {owners[0]['rel']}; it is not merged yet")
            elif [os.path.normcase(s["path"]) for s in had.get("sources") or []] != now:
                out.append(f"{owners[0]['rel']}: which packages ship it, or their order, changed since it was merged")
            elif any(_sha(Path(s["path"])) != s["sha256"] for s in had.get("sources") or []):
                out.append(f"{owners[0]['rel']}: {names}'s copies changed since it was merged")
        for low, had in done.items():
            if low not in shared and had.get("output"):
                out.append(f"{had.get('rel') or low} no longer needs merging")
        return out

    def reasons(self, all_layers: list[dict], until: dict | None) -> list[str]:
        """Why the combined files no longer match today's packages."""
        rec = self.record()
        want = self.inputs(all_layers, until)
        had = rec.get("packs") or []
        have = {os.path.normcase(str(Path(l["folder"]) / REGULATION)): l for l in want}
        was = {os.path.normcase(str(Path(p["path"]))): p for p in had if isinstance(p, dict) and p.get("path")}
        out = merge_record.reasons(rec) + self.file_reasons(all_layers, until)
        if not want and not had:
            return out
        if not (self.folder / REGULATION).is_file() or not had and want:
            return ["the combined parameters have not been built yet", *out]
        for k, l in have.items():
            if k not in was:
                out.append(f"{l['name']} ships parameters now but was not combined")
            elif _sha(Path(k)) != was[k].get("sha256"):
                out.append(f"{l['name']}'s regulation.bin changed since it was combined")
        for k, p in was.items():
            if k not in have:
                out.append(f"{p.get('name') or Path(k).parent.name} was combined but is no longer loaded before it")
        if not out and [os.path.normcase(str(p["path"])) for p in had] != list(have):
            out.append("the packs' load order changed; where two change the same row, the later one wins")
        base = game_regulation()
        if base is not None and rec.get("base_sha256") and _sha(base) != rec["base_sha256"]:
            out.append("the game's own regulation.bin changed since the last combine (a game update?)")
        order = [l["index"] for l in all_layers]
        if self.package["index"] in order:
            at = order.index(self.package["index"])
            late = [
                l
                for l in all_layers[at + 1 :]
                if (Path(l["folder"]) / REGULATION).is_file() and (until is None or l["index"] != until["index"])
            ]
            if late and until is None:
                out.append(f"{late[-1]['name']} loads after the combined parameters and replaces them")
        return out

    # -------------------------------------------------------------- running
    def run(self, log, all_layers: list[dict] | None = None, until: dict | None = None) -> dict:
        from roundtable_souls import __version__
        from roundtable_souls.merging.rules import param as param_merge
        from roundtable_souls.mods import merge
        from roundtable_souls.platform import common

        layers = merge.layers(self.profile) if all_layers is None else all_layers
        packs = self.inputs(layers, until)
        build = Build(self.folder, RECORD)  # finishes undoing an interrupted rebuild first, if there was one
        try:
            build.make_room(self._estimate(layers, until, packs))
        except BuildError as e:
            raise BackendError(f"The rebuild was not started: {e}. The previous result is unchanged.") from e
        self.previous = self._keep_previous()
        files = self._merge_files(log, layers, until, build)
        base = game_regulation()
        if not packs:
            build.remove(REGULATION)
            record = self._write_record(files, None, [], None, __version__, build=build)
            self._activate(build)
            return record
        if base is None:
            raise BackendError(self.problem() or "no base regulation")
        log(
            f"combine: {len(packs)} packs onto the game's regulation.bin: {', '.join(p['name'] for p in packs) or 'none'}"
        )
        start = time.time()
        game_dir = common.game_dir()
        oodle = None
        try:
            from roundtable_souls.game.oodle import find_oodle

            oodle = find_oodle(Path(game_dir)) if game_dir else None
        except Exception:
            oodle = None
        try:
            out, report = param_merge.combine(
                base.read_bytes(),
                [(p["name"], (Path(p["folder"]) / REGULATION).read_bytes()) for p in packs],
                oodle,
            )
        except Exception as e:
            raise BackendError(f"Combining parameters failed: {e}") from e
        for line in report.lines():
            log(f"  {line}")
        build.path(REGULATION).write_bytes(out)
        record = self._write_record(files, base, packs, report, __version__, out, build=build)
        self._activate(build)
        log(f"combine: done in {time.time() - start:.1f}s ({len(report.conflicts)} overlapping rows)")
        return record

    def _estimate(self, layers: list[dict], until: dict | None, packs: list[dict]) -> int:
        """About how many bytes the outputs take: per merged file its largest copy, plus a regulation.bin."""

        def size(p: Path) -> int:
            try:
                return p.stat().st_size
            except OSError:
                return 0

        shared = shared_files(self.file_inputs(layers, until))
        total = sum(max(size(Path(o["folder"]) / o["rel"]) for o in owners) for owners in shared.values())
        if packs:
            base = game_regulation()
            total += max([size(base) if base else 0] + [size(Path(p["folder"]) / REGULATION) for p in packs])
        return total

    def _write_record(
        self, files: dict, base, packs, report, version, out: bytes | None = None, build: Build | None = None
    ) -> dict:
        from roundtable_souls.platform import common

        record = {
            "combined": 1,
            "made_by": f"Roundtable Souls {version}",
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "files": files,
            "archives": archives_fingerprint(common.game_dir()),
        } | merge_record.facts(me3_version=_me3_version())
        if base is None:
            self._put_record(record, build)
            return record
        record |= {
            "base": str(base),
            "base_sha256": _sha(base),
            "base_version": report.base_version,
            "packs": [
                {
                    "name": p["name"],
                    "path": str(Path(p["folder"]) / REGULATION),
                    "sha256": _sha(Path(p["folder"]) / REGULATION),
                }
                for p in packs
            ],
            "sources": [{"path": str(base), "sha256": _sha(base)}]
            + [
                {"path": str(Path(p["folder"]) / REGULATION), "sha256": _sha(Path(p["folder"]) / REGULATION)}
                for p in packs
            ],
            "report": report.lines(limit=200),
            "output_sha256": hashlib.sha256(out).hexdigest(),
        }
        self._put_record(record, build)
        return record

    def _put_record(self, record: dict, build: Build | None) -> None:
        if build is not None:
            build.path(RECORD).write_text(json.dumps(record, indent=1), encoding="utf-8")
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.folder / (RECORD + ".tmp")
        tmp.write_text(json.dumps(record, indent=1), encoding="utf-8")
        tmp.replace(self.folder / RECORD)

    def _activate(self, build: Build) -> None:
        """Read every staged output back, then put them in place (refused while the game runs)."""
        from roundtable_souls.game.oodle import find_oodle
        from roundtable_souls.platform import common

        game_dir = common.game_dir()
        dec = find_oodle(Path(game_dir)) if game_dir else None

        def read(rel: str, data: bytes) -> None:
            if rel == REGULATION:
                formats.regulation.read_regulation(data, dec)
                return
            body = formats.dcx.unpack(data, dec)[0]
            if formats.bnd4.is_bnd4(body):
                formats.bnd4.read_bnd4(body)

        try:
            build.check(read)
            build.activate(lambda: "Close the game first: it has these files open." if common.game_running() else None)
        except BuildError as e:
            raise BackendError(f"The rebuild was not put in place: {e}. The previous result is unchanged.") from e

    def _merge_files(self, log, layers: list[dict], until: dict | None, build: Build) -> dict:
        """Merge every file two or more packages before `until` ship into this package; drop merged files no longer
        needed. Returns the record's files: {rel (lower): {rel, sources, output, parts, clashes | skipped}}."""
        from roundtable_souls.game import archives as gamearchive
        from roundtable_souls.game.oodle import find_oodle
        from roundtable_souls.merging import merger
        from roundtable_souls.platform import common

        shared = shared_files(self.file_inputs(layers, until))
        before = self.record().get("files") or {}
        for low, had in before.items():  # merged before, not needed now
            if low not in shared and had.get("output"):
                build.remove(had["rel"])
        if not shared:
            return {}
        game_dir = common.game_dir()
        dec = find_oodle(Path(game_dir)) if game_dir else None
        comp = game_oodle.oodle_compressor(Path(game_dir)) if game_dir else None
        out: dict = {}
        for low, owners in sorted(shared.items()):
            rel = owners[0]["rel"]
            sources = [
                {"path": str(Path(o["folder"]) / o["rel"]), "sha256": _sha(Path(o["folder"]) / o["rel"])}
                for o in owners
            ]
            entry = {"rel": rel, "sources": sources, "output": False}
            try:
                vanilla = gamearchive.read(Path(game_dir), rel) if game_dir else None
                if vanilla is None:
                    entry["skipped"] = "the game has no such file, so there is nothing to compare the copies with"
                else:
                    layers_ = [(o["name"], (Path(o["folder"]) / o["rel"]).read_bytes()) for o in owners]
                    fallback = game_config.load().dflt_fallback_for(rel)
                    result = merger.merge(vanilla, layers_, dec, comp, fallback)
                    if not result.merged:
                        entry["skipped"] = "not an archive or a text table the launcher can merge yet"
                    else:
                        build.path(rel).write_bytes(result.data)
                        entry |= {
                            "output": True,
                            "parts": len(result.changed),
                            "clashes": result.clashes,
                            "removed": result.removed,
                            "notes": result.notes,
                        }
                        log(f"  merged {rel} from {' and '.join(o['name'] for o in owners)}: {result.summary()}")
                        if result.removed:
                            log(f"    {len(result.removed)} part(s) left out by a mod's copy are left out")
                        for part, who in list(result.clashes.items())[:5]:
                            log(f"    {part}: changed by {', '.join(who)}; {who[-1]}'s is used")
            except (OSError, formats.FormatError, gamearchive.ArchiveError) as e:
                entry["skipped"] = f"could not be merged: {e}"
            if entry.get("skipped"):
                build.remove(rel)
                log(f"  {rel}: {entry['skipped']}; the later package's copy is used")
            out[low] = entry
        return out
