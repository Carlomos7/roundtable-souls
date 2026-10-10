"""mods.library: the launcher's mod folder for one game (rs-<game>), its layout, making folders and what a scan finds."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from roundtable_souls.game import catalog as games
from roundtable_souls.game.locate import Locations, Overrides
from roundtable_souls.mods import library
from roundtable_souls.mods.library import ModLibrary
from roundtable_souls.platform import files, paths
from roundtable_souls.services import play


def test_layout_paths(tmp_path):
    loc = Locations(games.ELDEN_RING, Overrides(profiles_dir=str(tmp_path)))
    lib = ModLibrary.for_game(loc)
    assert lib is not None
    r = tmp_path / "rs-eldenring"
    assert (lib.root, lib.game) == (r, "eldenring")
    assert lib.profile("coop") == r / "profiles" / "coop.me3"
    assert lib.package("hair") == r / "packages" / "hair"
    assert lib.native("seamless-co-op") == r / "natives" / "seamless-co-op"
    assert lib.overhaul("nightreign-revive") == r / "overhauls" / "nightreign-revive"
    assert lib.overhaul_record("nightreign-revive") == r / "overhauls" / "nightreign-revive" / "roundtable.json"
    src = lib.sources("nightreign-revive")
    s = r / "sources" / "nightreign-revive"
    assert (src.merge, src.text, src.hooks, src.base, src.record) == (
        s / "merge",
        s / "text",
        s / "hooks",
        s / "base",
        s / "roundtable.json",
    )
    assert src.role("hooks") == s / "hooks"
    with pytest.raises(ValueError):
        src.role("payload")
    b = lib.build("combined-parameters", "coop")
    d = r / "builds" / "combined-parameters" / "coop"
    assert (b.root, b.record, b.report, b.previous, b.side_effects) == (
        d,
        d / "build.json",
        d / "merge-report.txt",
        d / ".previous",
        d / "roundtable.json",
    )
    st = lib.state
    h = r / ".roundtable"
    assert (st.root, st.settings, st.backups, st.previous, st.ops, st.ops_lock) == (
        h,
        h / "settings.json",
        h / "backups",
        h / "previous",
        h / "ops",
        h / "ops.lock",
    )
    assert ModLibrary.at(tmp_path, "nightreign").root == tmp_path / "rs-nightreign"


def test_no_library_without_a_profiles_folder(monkeypatch):
    loc = Locations(games.ELDEN_RING)
    with monkeypatch.context() as m:
        m.setattr(paths, "me3_profiles_dir", lambda override=None: None)
        assert ModLibrary.for_game(loc) is None


def test_nothing_is_made_until_asked(tmp_path):
    lib = ModLibrary.at(tmp_path, "eldenring")
    lib.scan()
    _ = lib.sources("x"), lib.build("x", "p"), lib.state
    assert not lib.root.exists()


def test_ensure_makes_only_what_is_asked_and_hides_the_launchers_folders(tmp_path):
    lib = ModLibrary.at(tmp_path, "eldenring")
    made = lib.ensure(lib.packages)
    assert made == [lib.root, lib.packages]
    assert sorted(p.name for p in lib.root.iterdir()) == ["packages"]
    b = lib.build("nightreign-revive", "coop")
    lib.ensure(b.previous, lib.state.ops)
    assert b.previous.is_dir() and lib.state.ops.is_dir()
    assert not lib.state.backups.exists() and not lib.natives.exists()
    assert files.is_hidden(lib.state.root) and files.is_hidden(b.previous)
    if os.name == "nt":
        assert not files.is_hidden(lib.packages) and not files.is_hidden(b.root)
    assert lib.ensure(lib.packages) == []  # already there
    with pytest.raises(ValueError):
        lib.ensure(tmp_path / "elsewhere")


def _profile(path: Path, *entries: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = 'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n\n' + "\n".join(entries)
    path.write_text(body, encoding="utf-8")
    return path


def _library(tmp_path) -> ModLibrary:
    """A synthetic library: two profiles sharing a package and a native, an overhaul with one build, an unused
    package, an entry outside the library."""
    lib = ModLibrary.at(tmp_path, "eldenring")
    for folder in (
        lib.package("hair"),
        lib.package("map-for-goblins"),
        lib.package("unused"),
        lib.native("seamless-co-op"),
        lib.overhaul("nightreign-revive"),
        lib.build("nightreign-revive", "coop").root,
        lib.build("combined-parameters", "solo").root,
        lib.state.backups,
    ):
        lib.ensure(folder)
    (lib.native("seamless-co-op") / "ersc.dll").write_bytes(b"x")
    pkg = '[[packages]]\nid = "{id}"\npath = "{path}"\n'
    _profile(
        lib.profile("solo"),
        pkg.format(id="hair", path="../packages/hair"),
        pkg.format(id="map", path="../packages/map-for-goblins"),
        pkg.format(id="combined", path="../builds/combined-parameters/solo"),
        '[[packages]]\nid = "elsewhere"\npath = "C:/Mods/elsewhere"\n',
    )
    _profile(
        lib.profile("coop"),
        pkg.format(id="hair", path="../packages/hair"),
        '[[natives]]\npath = "../natives/seamless-co-op/ersc.dll"\nenabled = false\n',
        pkg.format(id="nightreign-revive", path="../builds/nightreign-revive/coop"),
    )
    return lib


def test_scan_lists_the_library_and_who_uses_what(tmp_path):
    lib = _library(tmp_path)
    found = lib.scan()
    assert found.profiles == [lib.profile("coop"), lib.profile("solo")]
    assert found.mods == {
        "packages": ["hair", "map-for-goblins", "unused"],
        "natives": ["seamless-co-op"],
        "overhauls": ["nightreign-revive"],
    }
    assert found.builds == {"combined-parameters": ["solo"], "nightreign-revive": ["coop"]}
    assert found.used_by("packages", "hair") == [lib.profile("coop"), lib.profile("solo")]
    assert found.used_by("natives", "seamless-co-op") == [lib.profile("coop")]
    assert [u.enabled for u in found.users[("natives", "seamless-co-op")]] == [False]  # listed, switched off
    assert found.used_by("builds", "nightreign-revive") == [lib.profile("coop")]
    assert found.unused("packages") == ["unused"]
    assert [(u.profile.name, u.name) for u in found.outside] == [("solo.me3", "elsewhere")]
    assert ".roundtable" not in str(found.mods)


def test_place_of(tmp_path):
    lib = ModLibrary.at(tmp_path, "eldenring")
    assert lib.place_of(lib.native("x") / "x.dll") == ("natives", "x")
    assert lib.place_of(lib.package("hair") / "chr" / "c0000.anibnd.dcx") == ("packages", "hair")
    assert lib.place_of(lib.profiles / "a.me3") is None
    assert lib.place_of(lib.packages) is None
    assert lib.place_of(tmp_path / "eldenring-mods" / "mod") is None


def test_play_and_the_profile_scan_already_see_library_profiles(tmp_path):
    """rs-<game>/profiles/*.me3 sits at depth 2 of me3's profiles folder, which both scans reach; mod folders below
    are not walked into."""
    lib = _library(tmp_path)
    (lib.package("hair") / "deep").mkdir()
    (lib.package("hair") / "deep" / "stray.me3").write_text("", encoding="utf-8")  # depth 3: not a profile
    assert paths.find_profiles(tmp_path, "eldenring", "eldenring") == [lib.profile("coop"), lib.profile("solo")]
    loc = Locations(games.ELDEN_RING, Overrides(profiles_dir=str(tmp_path)))
    found = [Path(s.source) for s in play.discover(None, loc) if s.kind == "me3"]
    assert found == [lib.profile("coop"), lib.profile("solo")]


def test_the_launchers_names_are_reserved():
    from roundtable_souls.mods import naming

    assert {"profiles", "packages", "natives", "overhauls", "sources", "builds"} <= naming.RESERVED
    assert set(library.COLLECTIONS) <= naming.RESERVED
