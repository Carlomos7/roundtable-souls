"""The launcher's own parameter combine: a package it manages (combined-parameters) holding one regulation.bin that
applies every pack's changes to the game's own file (see mods.param_merge), and a record of what went in.

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

from roundtable_souls.mods.backends import BackendError

RECORD = "combined-parameters.json"
FOLDER = "combined-parameters"
REGULATION = "regulation.bin"


def _sha(p: Path) -> str:
    from roundtable_souls.mods import merge

    return merge.sha256(p) or ""


def is_combined(folder: Path) -> bool:
    try:
        data = json.loads((Path(folder) / RECORD).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return False
    return isinstance(data, dict) and data.get("combined") == 1


def find(profile: Path, all_layers: list[dict]) -> CombineTool | None:
    layer = next((l for l in all_layers if is_combined(l["folder"])), None)
    return CombineTool(Path(profile), layer) if layer is not None else None


def game_regulation() -> Path | None:
    from roundtable_souls.system import common

    d = common.game_dir()
    p = Path(d) / REGULATION if d else None
    return p if p is not None and p.is_file() else None


HISTORY_KEEP = 3  # earlier combined outputs kept for Undo rebuild (about 2 MB each)


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

        if not (self.folder / REGULATION).is_file():
            return None
        root = history_root(self.profile)
        dest = root / time.strftime("%Y%m%d-%H%M%S")
        n = 2
        while dest.exists():
            dest = root / f"{time.strftime('%Y%m%d-%H%M%S')}-{n}"
            n += 1
        try:
            dest.mkdir(parents=True)
            for name in (REGULATION, RECORD):
                if (self.folder / name).is_file():
                    shutil.copy2(self.folder / name, dest / name)
        except OSError:
            return None
        for old in sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True)[HISTORY_KEEP:]:
            shutil.rmtree(old, ignore_errors=True)
        return dest

    def reasons(self, all_layers: list[dict], until: dict | None) -> list[str]:
        """Why the combined file no longer matches today's packages."""
        rec = self.record()
        want = self.inputs(all_layers, until)
        had = rec.get("packs") or []
        have = {os.path.normcase(str(Path(l["folder"]) / REGULATION)): l for l in want}
        was = {os.path.normcase(str(Path(p["path"]))): p for p in had if isinstance(p, dict) and p.get("path")}
        out = []
        if not (self.folder / REGULATION).is_file() or not had and want:
            return ["the combined parameters have not been built yet"]
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
        from roundtable_souls.mods import merge, param_merge
        from roundtable_souls.system import common

        base = game_regulation()
        if base is None:
            raise BackendError(self.problem() or "no base regulation")
        layers = merge.layers(self.profile) if all_layers is None else all_layers
        packs = self.inputs(layers, until)
        log(
            f"combine: {len(packs)} packs onto the game's regulation.bin: {', '.join(p['name'] for p in packs) or 'none'}"
        )
        start = time.time()
        game_dir = common.game_dir()
        oodle = None
        try:
            from roundtable_souls.gamefiles import find_oodle

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
        self.previous = self._keep_previous()
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.folder / (REGULATION + ".tmp")
        tmp.write_bytes(out)
        tmp.replace(self.folder / REGULATION)
        record = {
            "combined": 1,
            "made_by": f"Roundtable Souls {__version__}",
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
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
        tmp = self.folder / (RECORD + ".tmp")
        tmp.write_text(json.dumps(record, indent=1), encoding="utf-8")
        tmp.replace(self.folder / RECORD)
        log(f"combine: done in {time.time() - start:.1f}s ({len(report.conflicts)} overlapping rows)")
        return record
