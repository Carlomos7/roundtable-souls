"""Install, update and undo as one recoverable operation (mods.operations): staged first, applied under one journal,
undone as a whole when interrupted, taken back as a set. Temporary folders only."""

import os
from pathlib import Path

import pytest

from roundtable_souls.merging import build as B
from roundtable_souls.mods import install, operations

PROFILE = (
    'profileVersion = "v1"\r\n\r\n[[supports]]\r\ngame = "eldenring"\r\n\r\n'
    "[[natives]]\r\npath = 'natives/SeamlessCoop/ersc.dll'\r\nload_early = true\r\n\r\n"
    "[[packages]]\r\nid = \"flora\"\r\npath = 'mod/flora'\r\n"
)


class Crash(BaseException):
    """The process dying: nothing after it runs, not even the undo."""


def files(folder):
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in Path(folder).rglob("*")
        if p.is_file() and not p.relative_to(folder).as_posix().startswith(B.OPS) and p.suffix != ".bak"
    }


@pytest.fixture
def profile(tmp_path):
    root = tmp_path / "profiles"
    (root / "mod" / "flora" / "parts").mkdir(parents=True)
    (root / "mod" / "flora" / "parts" / "a.partsbnd.dcx").write_bytes(b"flora")
    seamless = root / "natives" / "SeamlessCoop"
    seamless.mkdir(parents=True)
    (seamless / "ersc.dll").write_bytes(b"dll")
    (seamless / "ersc_settings.ini").write_text("cooppassword = x\n")
    p = root / "my.me3"
    p.write_bytes(PROFILE.encode())
    return p


def source(tmp_path, version: str, extra: dict | None = None):
    src = tmp_path / f"src-{version}" / "Grass"
    (src / "parts").mkdir(parents=True)
    (src / "parts" / "grass.partsbnd.dcx").write_bytes(f"grass {version}".encode())
    (src / "grass.ini").write_bytes(f"version = {version}\n".encode())
    for rel, data in (extra or {}).items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_bytes(data)
    return src


def do_install(profile, src, **kw):
    plan = install.plan_install(profile, src, name="grass")
    return install.install(profile, plan, overwrite=bool(plan.get("exists")), **kw)


def test_install_is_staged_then_applied_with_a_record(profile, tmp_path):
    out = do_install(profile, source(tmp_path, "1"))
    grass = profile.parent / "mod" / "grass"
    assert files(grass) == {"parts/grass.partsbnd.dcx": b"grass 1", "grass.ini": b"version = 1\n"}
    assert "path = 'mod/grass'" in profile.read_text()
    assert operations.pending(profile) == [] and operations.problem(profile) is None
    [kept] = operations.kept_versions(profile)
    assert kept["kind"] == "install" and kept["dir"] == out["operation"]
    assert not [p for p in grass.parent.iterdir() if ".staging" in p.name]


def test_failed_preparation_leaves_the_previous_install_untouched(profile, tmp_path, monkeypatch):
    do_install(profile, source(tmp_path, "1"))
    grass = profile.parent / "mod" / "grass"
    before = files(profile.parent)
    with monkeypatch.context() as m:
        m.setattr(install.shutil, "copytree", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
        with pytest.raises(OSError, match="disk full"):
            do_install(profile, source(tmp_path, "2"))
    assert files(profile.parent) == before
    assert files(grass)["grass.ini"] == b"version = 1\n"
    assert operations.pending(profile) == []


def test_failed_rebuild_undoes_the_whole_install(profile, tmp_path):
    before = files(profile.parent)
    seen = {}

    def rebuild():
        seen["live"] = (profile.parent / "mod" / "grass").is_dir() and "grass" in profile.read_text()
        raise RuntimeError("the rebuild failed")

    with pytest.raises(RuntimeError, match="rebuild failed"):
        do_install(profile, source(tmp_path, "1"), then=rebuild)
    assert seen["live"]  # the rebuild saw the new state
    assert files(profile.parent) == before  # and it is gone again, all of it
    assert operations.kept_versions(profile) == []


@pytest.mark.parametrize(("update", "crash_at"), [(False, 1), (False, 2), (True, 1), (True, 2)])
def test_an_interrupted_install_is_undone_on_the_next_start(profile, tmp_path, monkeypatch, update, crash_at):
    """Dies at each rename: the new folder moved in and the profile replaced (an install), the installed folder moved
    aside and the new one moved in (an update, whose entry is there already). The next start finds the journal and
    puts the state before back, all of it."""
    if update:
        do_install(profile, source(tmp_path, "1"))
    before = files(profile.parent)
    real = B.os.replace
    n = {"i": 0}

    def dying(src, dst):
        if "journal" not in str(dst) and Path(dst).is_relative_to(profile.parent):  # the profile's folder only
            n["i"] += 1
            if n["i"] == crash_at:
                raise Crash()
        return real(src, dst)

    with monkeypatch.context() as m:
        m.setattr(B.os, "replace", dying)
        m.setattr(B, "_undo", lambda op: None)
        with pytest.raises(Crash):
            do_install(profile, source(tmp_path, "2"))
    assert "did not finish" in (operations.problem(profile) or "")
    said = operations.recover(profile)
    assert said and "undone" in said[0]
    assert files(profile.parent) == before and operations.problem(profile) is None


def test_update_keeps_the_previous_version_and_rolls_back_as_a_set(profile, tmp_path):
    do_install(profile, source(tmp_path, "1"))
    v1_profile = profile.read_bytes()
    out = do_install(profile, source(tmp_path, "2", {"new.txt": b"n"}))
    grass = profile.parent / "mod" / "grass"
    assert out["update"] and files(grass)["grass.ini"] == b"version = 2\n"
    assert [k["kind"] for k in operations.kept_versions(profile)] == ["update"]  # the install's record let go
    said = operations.rollback(Path(out["operation"]))
    assert "rolled grass back" in said
    assert files(grass) == {"parts/grass.partsbnd.dcx": b"grass 1", "grass.ini": b"version = 1\n"}
    assert profile.read_bytes() == v1_profile
    [rb] = operations.kept_versions(profile)
    assert rb["kind"] == "rollback"  # the version rolled back is kept aside until kept
    aside = [p for p in grass.parent.iterdir() if p.name.startswith(".grass.previous-")]
    assert len(aside) == 1 and files(aside[0])["new.txt"] == b"n"
    operations.keep(Path(rb["dir"]))
    assert not any(p.name.startswith(".grass.") for p in grass.parent.iterdir())


def test_user_edits_survive_an_update(profile, tmp_path):
    do_install(profile, source(tmp_path, "1"))
    grass = profile.parent / "mod" / "grass"
    (grass / "grass.ini").write_text("version = 1\nmine = yes\n")
    os.utime(grass / "grass.ini", ns=(1, 1))
    (grass / "notes.txt").write_text("my notes")
    out = do_install(profile, source(tmp_path, "2"))
    assert out["kept"] == ["grass.ini", "notes.txt"]
    assert (grass / "grass.ini").read_text() == "version = 1\nmine = yes\n"
    assert (grass / "grass.ini.new").read_text() == "version = 2\n"  # the new version's copy, beside it
    assert (grass / "notes.txt").read_text() == "my notes"
    assert (grass / "parts" / "grass.partsbnd.dcx").read_bytes() == b"grass 2"


def test_fresh_install_undo_restores_the_exact_profile_and_only_unchanged_files(profile, tmp_path):
    before = profile.read_bytes()
    out = do_install(profile, source(tmp_path, "1"))
    grass = profile.parent / "mod" / "grass"
    (grass / "grass.ini").write_text("edited")
    said = operations.undo_install(Path(out["operation"]))
    assert profile.read_bytes() == before  # byte for byte
    assert files(grass) == {"grass.ini": b"edited"}  # changed since: left, and said
    assert "grass.ini" in said
    assert operations.kept_versions(profile) == []


def test_fresh_install_undo_after_a_profile_edit_takes_only_its_entries(profile, tmp_path):
    out = do_install(profile, source(tmp_path, "1"))
    edited = profile.read_text().replace('id = "flora"', 'id = "flora"\r\n# my note')
    profile.write_bytes(edited.encode())
    said = operations.undo_install(Path(out["operation"]))
    text = profile.read_text()
    assert "# my note" in text and "mod/grass" not in text and "mod/flora" in text
    assert "changed since" in said
    assert not (profile.parent / "mod" / "grass").exists()


def test_seamless_is_never_taken_out_by_an_undo(profile, tmp_path):
    """Seamless installed with a mod the user then undoes: its entry and folder stay (other mods rely on it)."""
    no_coop = PROFILE.replace("[[natives]]\r\npath = 'natives/SeamlessCoop/ersc.dll'\r\nload_early = true\r\n\r\n", "")
    profile.write_bytes(no_coop.encode())
    src = tmp_path / "src" / "SeamlessCoop"
    src.mkdir(parents=True)
    (src / "ersc.dll").write_bytes(b"dll 2")
    plan = install.plan_install(profile, src)
    out = install.install(profile, plan, overwrite=bool(plan.get("exists")))
    said = operations.undo_install(Path(out["operation"]))
    assert "ersc.dll" in profile.read_text()
    assert (profile.parent / "natives" / "SeamlessCoop" / "ersc.dll").is_file()
    assert "Seamless Co-op" in said


def test_an_unfinished_operation_blocks_play(profile, tmp_path):
    from roundtable_souls.game import catalog
    from roundtable_souls.game.locate import Locations
    from roundtable_souls.services import play

    op = operations.start(profile, "install of grass")  # prepared, never applied: as a crash leaves it
    s = play.Setup("me3", str(profile), loc=Locations(catalog.ELDEN_RING))
    assert any("did not finish" in p for p in s.problems())
    operations.recover(profile)
    assert not any("did not finish" in p for p in s.problems())
    assert not op.dir.exists()


def test_activity_takes_an_install_and_an_update_back(profile, tmp_path):
    from roundtable_souls.mods import undo

    before = profile.read_bytes()
    first = do_install(profile, source(tmp_path, "1"))
    rec = {"type": "install", "profile": str(profile), "name": "grass", "operation": first["operation"]}
    assert undo.available(rec) and undo.label(rec) == "Undo install"
    second = do_install(profile, source(tmp_path, "2"))
    assert not undo.available(rec)  # the update let the install's record go: only the newest can be taken back
    upd = {"type": "update", "profile": str(profile), "name": "grass", "operation": second["operation"]}
    assert undo.available(upd) and undo.label(upd) == "Roll back"
    said = undo.run(upd, lambda s: None)
    assert "rolled grass back" in said and not undo.available(upd)
    grass = profile.parent / "mod" / "grass"
    assert files(grass)["grass.ini"] == b"version = 1\n"
    assert profile.read_bytes() != before  # rolled back to version 1, not uninstalled


def test_removal_interrupted_before_the_folder_went_is_undone(profile, tmp_path, monkeypatch):
    from roundtable_souls.mods import remove

    do_install(profile, source(tmp_path, "1"))
    before = files(profile.parent)
    index = next(e["index"] for e in install.entries(profile) if e["name"] == "grass")
    with monkeypatch.context() as m:
        real = B.os.replace

        def dying(src, dst):
            if Path(src).name == "grass":
                raise Crash()  # the folder about to be taken aside
            return real(src, dst)

        m.setattr(B.os, "replace", dying)
        m.setattr(B, "_undo", lambda op: None)
        with pytest.raises(Crash):
            remove.uninstall(profile, index, delete_folder=True, to_trash=False)
    assert "mod/grass" not in profile.read_text()  # the profile was written, the folder not yet taken
    assert operations.problem(profile)
    assert operations.recover(profile) == ["an interrupted removal of grass was undone: the previous state is back"]
    assert files(profile.parent) == before


def test_removal_interrupted_after_the_folder_went_is_finished(profile, tmp_path, monkeypatch):
    from roundtable_souls.mods import remove

    do_install(profile, source(tmp_path, "1"))
    index = next(e["index"] for e in install.entries(profile) if e["name"] == "grass")
    with monkeypatch.context() as m:
        m.setattr(remove.shutil, "rmtree", lambda *a, **k: (_ for _ in ()).throw(Crash()))  # after the rename
        m.setattr(B, "_undo", lambda op: None)
        with pytest.raises(Crash):
            remove.uninstall(profile, index, delete_folder=True, to_trash=False)
    assert not (profile.parent / "mod" / "grass").exists()
    assert operations.recover(profile) == ["an interrupted removal of grass was finished"]
    assert "mod/grass" not in profile.read_text() and operations.problem(profile) is None
    assert operations.kept_versions(profile) == []  # the install's record went with the mod


def test_failed_removal_leaves_the_mod_installed(profile, tmp_path, monkeypatch):
    from roundtable_souls.mods import remove

    do_install(profile, source(tmp_path, "1"))
    before = files(profile.parent)
    index = next(e["index"] for e in install.entries(profile) if e["name"] == "grass")
    with monkeypatch.context() as m:
        real = B.os.replace

        def refused(src, dst):
            if Path(src).name == "grass":
                raise PermissionError("in use")
            return real(src, dst)

        m.setattr(B.os, "replace", refused)
        with pytest.raises(PermissionError):
            remove.uninstall(profile, index, delete_folder=True, to_trash=False)
    assert files(profile.parent) == before and operations.problem(profile) is None


def test_looking_for_interrupted_operations_writes_nothing(profile):
    before = sorted(p.name for p in profile.parent.iterdir())
    assert operations.recover(profile) == [] and operations.problem(profile) is None
    assert sorted(p.name for p in profile.parent.iterdir()) == before
