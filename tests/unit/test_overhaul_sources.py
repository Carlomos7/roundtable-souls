"""overhauls.sources: an overhaul's download in the launcher's layout (sources by role, runtime files), from its
config's [builds.sources] and [builds.runtime], and the fingerprint over the files the config takes."""

from __future__ import annotations

import random

import pytest
from pydantic import ValidationError

from roundtable_souls import overhauls
from roundtable_souls.mods import records
from roundtable_souls.overhauls import sources
from roundtable_souls.overhauls.config import Build

LANGS = ["araae", "deude", "engus", "frafr", "itait", "jpnjp", "korkr", "polpl", "porbr", "rusru", "spaar", "spaes",
         "thath", "zhocn", "zhotw"]  # fmt: skip
GAME_FILES = ["chr/c0000.anibnd.dcx", "chr/c0000.behbnd.dcx", "chr/c0000_a00_hi.anibnd.dcx",
              "chr/c0000_a00_lo.anibnd.dcx", "chr/c0000_a00_md.anibnd.dcx", "regulation.bin",
              "sfx/sfxbnd_commoneffects.ffxbnd.dcx"]  # fmt: skip

# Revive 0.1.33-rc3 LITE's download as it is laid out (.nightreign-revive-setup), its merge tool abridged
DOWNLOAD = [
    "edition.json",
    "revive-maintenance.json",
    "installer/__pycache__/installer.cpython-313.pyc",
    "installer/installer.py",
    "installer/Launch.ps1",
    "installer/load-convergence.hks",
    "installer/load-reforged.hks",
    "installer/Me3Manager.ps1",
    "installer/revive.hks",
    *[f"payload/audio/{n}.wav" for n in ("ambient-bed", "ambient-pulse-a", "ambient-pulse-b", "fall", "hit", "revive")],
    "payload/mod/action/script/c0000.hks",
    *[f"payload/mod/{f}" for f in GAME_FILES],
    "payload/mod/sfx/sfxbnd_commoneffects.ffxbnd.dcx.manifest.json",
    "payload/ReviveHudBootstrap.dll",
    "payload/RevivePrototype.dll",
    "payload/RevivePrototype.ini",
    "payload/settings/engus.json",
    "payload/settings/m00_00_00_00.talkesdbnd.dcx",
    "payload/settings/rusru.json",
    "payload/settings/vanilla/script/talk/m00_00_00_00.talkesdbnd.dcx",
    *[f"payload/settings/vanilla/msg/{lang}/menu_dlc02.msgbnd.dcx" for lang in LANGS],
    *[
        f"payload/ui/{n}"
        for n in (
            "base.png",
            "clock.png",
            "clock-yellow.png",
            "font.ttf",
            "giveup-keyboard.png",
            "giveup-playstation.png",
            "giveup-xbox.png",
            "rim.png",
            "segment0.png",
            "segment1.png",
            "segment2.png",
        )
    ],  # fmt: skip
    "tools/defs/NpcParam.xml",
    "tools/merge/Assets.exe",
    "tools/merge/Res/HavokTypeRegistry20180100.xml",
]


def revive() -> Build:
    (cfg,) = [o for o in overhauls.load() if o.id == "nightreign-revive"]
    (build,) = cfg.builds
    return build


def test_revives_download_by_role():
    t = sources.translate(DOWNLOAD, revive())
    assert t.role("merge") == {
        **{f: f"payload/mod/{f}" for f in GAME_FILES},
        "script/talk/m00_00_00_00.talkesdbnd.dcx": "payload/settings/m00_00_00_00.talkesdbnd.dcx",
    }
    assert t.role("text") == {"engus.json": "payload/settings/engus.json", "rusru.json": "payload/settings/rusru.json"}
    assert t.role("hooks") == {"revive.hks": "installer/revive.hks"}
    assert t.role("base") == {"action/script/c0000.hks": "payload/mod/action/script/c0000.hks"}
    assert set(t.runtime) == {
        "RevivePrototype.dll",
        "ReviveHudBootstrap.dll",
        "RevivePrototype.ini",
        *[f"audio/{n}.wav" for n in ("ambient-bed", "ambient-pulse-a", "ambient-pulse-b", "fall", "hit", "revive")],
        *[
            f"ui/{n}"
            for n in (
                "base.png",
                "clock.png",
                "clock-yellow.png",
                "font.ttf",
                "giveup-keyboard.png",
                "giveup-playstation.png",
                "giveup-xbox.png",
                "rim.png",
                "segment0.png",
                "segment1.png",
                "segment2.png",
            )
        ],  # fmt: skip
    }
    assert all(t.runtime[k] == f"payload/{k}" for k in t.runtime)
    # the per-language fallback copies are dropped, and so are the merge tool's notes
    assert sorted(t.dropped) == sorted(
        [
            "payload/mod/sfx/sfxbnd_commoneffects.ffxbnd.dcx.manifest.json",
            "payload/settings/vanilla/script/talk/m00_00_00_00.talkesdbnd.dcx",
            *[f"payload/settings/vanilla/msg/{lang}/menu_dlc02.msgbnd.dcx" for lang in LANGS],
        ]
    )
    assert not any("vanilla" in v for v in [*t.sources.values(), *t.runtime.values()])
    # the installer, its metadata and its merge tool are not the overhaul's to keep
    assert sorted(t.untaken) == sorted(f for f in DOWNLOAD if f.startswith(("installer/", "tools/", "edition", "revive-"))
                                       and f != "installer/revive.hks")  # fmt: skip


def test_every_file_the_build_reads_from_the_download_is_taken():
    """What the steps read (other than the vanilla copies the spec drops) is in the role layout or the runtime, so a
    build reading sources by role (3.22) finds everything."""
    build = revive()
    t = sources.translate(DOWNLOAD, build)
    taken = set(t.taken())
    read: set[str] = set()
    for step in build.steps:
        s = step.model_dump(by_alias=True)
        for key in ("from", "patch", "base", "fragment"):
            if isinstance(s.get(key), str) and s[key].startswith(("payload/", "installer/")):
                read.add(s[key])
        read |= set((s.get("texts") or {}).values())
    trees = {r for r in read if not any(f == r for f in DOWNLOAD)}  # copy_tree folders
    assert trees == {"payload/audio", "payload/ui"}
    assert read - trees <= taken
    assert all(any(f.startswith(tree + "/") for f in taken) for tree in trees)


def test_the_fingerprint_is_stable_and_order_independent(tmp_path):
    build = revive()
    for i, rel in enumerate(DOWNLOAD):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(f"file {i} {rel}".encode())
    first = sources.fingerprint(tmp_path, build)
    assert first == sources.fingerprint(tmp_path, build)
    hashes = {rel: records_sha(tmp_path / rel) for rel in sources.translate(DOWNLOAD, build).taken()}
    shuffled = list(hashes.items())
    random.Random(7).shuffle(shuffled)
    assert sources.fingerprint_of(dict(shuffled)) == first
    assert sources.fingerprint_of({k.replace("/", "\\"): v.upper() for k, v in hashes.items()}) == first
    # a file the config doesn't take changes nothing; one it takes changes it
    (tmp_path / "tools/merge/Assets.exe").write_bytes(b"another tool")
    (tmp_path / "payload/settings/vanilla/msg/engus/menu_dlc02.msgbnd.dcx").write_bytes(b"dropped")
    (tmp_path / "payload/RevivePrototype.log").write_text("written while running")
    assert sources.fingerprint(tmp_path, build) == first
    (tmp_path / "payload/RevivePrototype.dll").write_bytes(b"a newer DLL")
    assert sources.fingerprint(tmp_path, build) != first


def records_sha(path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_sources_record_from_a_translation(tmp_path):
    """The record sources/<id>/roundtable.json keeps: each translated file's origin and hash."""
    t = sources.translate(["installer/revive.hks", "payload/settings/engus.json"], revive())
    rec = records.SourcesRecord(
        files={
            place: records.SourceFile.model_validate({"from": origin, "sha256": "0" * 64})
            for place, origin in t.sources.items()
        }  # fmt: skip
    )
    assert records.SourcesRecord.read(rec.text()).files["hooks/revive.hks"].from_ == "installer/revive.hks"


def build_with(src: dict[str, str], runtime: dict[str, str] | None = None) -> Build:
    return Build.model_validate(
        {"id": "x", "match": {}, "output": {}, "steps": [], "sources": src, "runtime": runtime or {}}
    )


def test_patterns():
    b = build_with(
        {"a/**": "merge/**", "a/*.txt": "text/*.txt", "a/x/*/y.bin": "base/*/z.bin", "a/**/*.skip": ""},
        {"a/*.dll": "bin/*.dll"},
    )
    t = sources.translate(["a/one.txt", "a/x/q/y.bin", "a/deep/er/f.dcx", "a/b/c.skip", "a/k.dll", "b/other"], b)
    assert t.sources == {
        "text/one.txt": "a/one.txt",
        "base/q/z.bin": "a/x/q/y.bin",
        "merge/deep/er/f.dcx": "a/deep/er/f.dcx",
        "merge/k.dll": "a/k.dll",  # a file may be both a source and a runtime file
    }
    assert t.runtime == {"bin/k.dll": "a/k.dll"}
    assert (t.dropped, t.untaken) == (["a/b/c.skip"], ["b/other"])
    assert sources.translate(["A\\One.TXT"], b).sources == {"text/One.txt": "A/One.TXT"}  # case aside, \ read as /


def test_equal_patterns_and_two_files_in_one_place_are_refused():
    with pytest.raises(sources.TranslateError, match="equally"):
        sources.translate(["a/b.txt"], build_with({"a/*.txt": "text/*.txt", "*/b.txt": "merge/*.txt"}))
    with pytest.raises(sources.TranslateError, match="would both become merge/f"):
        sources.translate(["a/f", "b/f"], build_with({"a/f": "merge/f", "b/f": "merge/f"}))


@pytest.mark.parametrize(
    ("table", "why"),
    [
        ({"a/*": "payload/*"}, "must start with one of merge, text, hooks, base"),
        ({"a/*": "merge/b"}, "repeat the pattern's wildcards"),
        ({"a/**": "merge/*"}, "repeat the pattern's wildcards"),
        ({"../a": "merge/a"}, "relative path"),
        ({"a": "merge/../b"}, "relative path"),
        ({"C:/a": "merge/a"}, "relative path"),
        ({"a\\b": "merge/b"}, "relative path"),
        ({"a/x**": "merge/x**"}, "whole folder name"),
    ],
)
def test_bad_tables_are_refused(table, why):
    with pytest.raises(ValidationError, match=why.replace("(", r"\(")):
        build_with(table)


def test_runtime_targets_have_no_roles():
    assert build_with({}, {"payload/*.dll": "*.dll"}).runtime == {"payload/*.dll": "*.dll"}


def test_the_tables_dont_change_what_the_build_does():
    """The engine reads the download as before: the tables are not in the recipe, so adding them changes neither a
    build nor whether it is out of date."""
    (cfg,) = [o for o in overhauls.load() if o.id == "nightreign-revive"]
    recipe = cfg.recipe(cfg.builds[0])
    assert "sources" not in recipe and "runtime" not in recipe


def _imports(module: str) -> set[str]:
    import ast
    import importlib.util

    spec = importlib.util.find_spec(module)
    assert spec is not None and spec.origin
    tree = ast.parse(open(spec.origin, encoding="utf-8").read())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            # from roundtable_souls import formats -> roundtable_souls.formats
            out |= (
                {f"{node.module}.{a.name}" for a in node.names} if node.module == "roundtable_souls" else {node.module}
            )
        elif isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
    return {m for m in out if m.startswith("roundtable_souls")}


@pytest.mark.parametrize(
    ("module", "allowed"),
    [
        ("roundtable_souls.overhauls.sources", ("roundtable_souls.overhauls",)),
        (
            "roundtable_souls.overhauls.config",
            ("roundtable_souls.overhauls", "roundtable_souls.resources", "roundtable_souls.platform"),
        ),  # fmt: skip
        ("roundtable_souls.merging.record", ("roundtable_souls.game", "roundtable_souls.formats")),
        ("roundtable_souls.game.archives", ("roundtable_souls.game", "roundtable_souls.platform")),
        ("roundtable_souls.mods.naming", ()),
        ("roundtable_souls.mods.records", ("roundtable_souls.resources",)),
        (
            "roundtable_souls.mods.library",
            ("roundtable_souls.formats", "roundtable_souls.platform", "roundtable_souls.game.locate"),
        ),  # fmt: skip
    ],
)
def test_the_new_modules_keep_the_layers(module, allowed):
    """§8.6: mods may import overhauls, merging, game and formats, never the reverse; nothing here imports Qt or the
    services. (lint-imports checks the whole tree; this pins the modules the library foundations added or moved.)"""
    found = _imports(module)
    assert all(m.startswith(allowed) for m in found), found - {m for m in found if m.startswith(allowed)}
    assert not any(m.startswith(("PySide6", "roundtable_souls.ui", "roundtable_souls.services")) for m in found)
