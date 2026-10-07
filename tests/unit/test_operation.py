"""merging.build.Operation: a mod's folder, a profile's bytes and a build changed as one. Prepared beside the live
files, applied under one journal, undone as a whole when interrupted. On temporary folders only."""

import pytest

from roundtable_souls.merging import build as B

RECORD = "record.json"


class Crash(BaseException):
    """The process dying: nothing after it runs, not even the undo."""


def files(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / "profiles"
    mod = root / "mod" / "flora"
    mod.mkdir(parents=True)
    (mod / "regulation.bin").write_bytes(b"flora 1")
    (mod / "flora.ini").write_text("x = 1")
    combined = root / "mod" / "combined"
    combined.mkdir()
    (combined / "regulation.bin").write_bytes(b"combined 1")
    (combined / RECORD).write_text('{"build": 1}')
    profile = root / "p.me3"
    profile.write_bytes(b"[[packages]]\r\nid = \"flora\"\r\npath = 'mod/flora'\r\n")
    return root, mod, combined, profile


def snapshot(root):
    """Everything live under root (the operations' own records and lock aside)."""
    return {k: v for k, v in files(root).items() if not k.startswith(B.OPS)}


def prepare(root, mod, combined, profile):
    op = B.Operation(root, "update of flora")
    staged = mod.with_name(".flora.staging")
    staged.mkdir()
    (staged / "regulation.bin").write_bytes(b"flora 2")
    op.replace_folder(mod, staged)
    op.write_file(profile, b"[[packages]]\r\nid = \"flora\"\r\npath = 'mod/flora'\r\nload_after = []\r\n")
    b = B.Build(combined, RECORD)
    b.path("regulation.bin").write_bytes(b"combined 2")
    b.path(RECORD).write_text('{"build": 2}')
    op.activate_build(b)
    return op


def test_preparing_changes_nothing_live_and_commit_applies_everything(setup):
    root, mod, combined, profile = setup
    before = files(mod), files(combined), profile.read_bytes()
    op = prepare(*setup)
    assert (files(mod), files(combined), profile.read_bytes()) == before
    assert B.pending(root) == ["update of flora"]  # not applied yet: an incomplete setup
    op.commit()
    assert files(mod) == {"regulation.bin": b"flora 2"}
    assert files(combined) == {"regulation.bin": b"combined 2", RECORD: b'{"build": 2}'}
    assert b"load_after" in profile.read_bytes()
    assert B.pending(root) == [] and [o.id for o in B.active(root)] == [op.id]
    prev = mod.with_name(f".flora.previous-{op.id}")
    assert files(prev) == {"regulation.bin": b"flora 1", "flora.ini": b"x = 1"}  # kept for a rollback
    op.release()
    assert not prev.exists() and B.active(root) == []


def test_a_failed_step_undoes_the_steps_before_it(setup, monkeypatch):
    root, mod, combined, profile = setup
    before = snapshot(root)
    op = prepare(*setup)
    with monkeypatch.context() as m:
        m.setattr(B.Build, "activate", lambda self, refuse=None, operation=None: (_ for _ in ()).throw(OSError("full")))
        with pytest.raises(OSError):
            op.commit()
    assert snapshot(root) == before
    assert not (root / B.OPS).exists() or not any((root / B.OPS).iterdir())


def test_refused_commit_changes_nothing(setup):
    root, *_ = setup
    before = snapshot(root)
    op = prepare(*setup)
    with pytest.raises(B.BuildError, match="Close the game"):
        op.commit(lambda: "Close the game first")
    assert snapshot(root) == before


@pytest.mark.parametrize("crash_at", range(1, 6))
def test_an_interrupted_operation_is_undone_as_a_whole(setup, monkeypatch, crash_at):
    """The process dies at each rename the commit makes (the folder aside, the staged folder in, the profile, the
    build's files): the next start puts the previous state back, everything of it."""
    root, mod, combined, profile = setup
    before = snapshot(root)
    op = prepare(*setup)
    real = B.os.replace
    n = {"i": 0}

    def dying(src, dst):
        if "journal" not in str(dst):
            n["i"] += 1
            if n["i"] == crash_at:
                raise Crash()
        return real(src, dst)

    with monkeypatch.context() as m:
        m.setattr(B.os, "replace", dying)
        m.setattr(B, "_undo", lambda op: None)  # dead: no undo runs
        with pytest.raises(Crash):
            op.commit()
    assert B.pending(root) == ["update of flora"]
    said = B.recover_operations(root)
    assert said == ["an interrupted update of flora was undone: the previous state is back"]
    assert snapshot(root) == before
    assert B.pending(root) == [] and B.active(root) == []


def test_a_crash_after_the_commit_point_is_finished_not_undone(setup, monkeypatch):
    root, mod, combined, profile = setup
    op = prepare(*setup)
    real_unlink = B.Path.unlink

    def dying(self, *a, **k):
        if self.name == B.JOURNAL:
            raise Crash()  # every file is in place and the operation marked done; the build's journal outlives it
        return real_unlink(self, *a, **k)

    with monkeypatch.context() as m:
        m.setattr(B.Path, "unlink", dying)
        with pytest.raises(Crash):
            op.commit()
    assert (combined / B.JOURNAL).exists()
    assert B.recover_operations(root) == []
    assert files(combined) == {"regulation.bin": b"combined 2", RECORD: b'{"build": 2}'}
    assert files(mod) == {"regulation.bin": b"flora 2"} and b"load_after" in profile.read_bytes()
    B.Build(combined, RECORD).discard()  # the next rebuild's own recovery agrees
    assert files(combined) == {"regulation.bin": b"combined 2", RECORD: b'{"build": 2}'}


def test_prepared_but_never_applied_is_cleaned_up(setup):
    root, mod, *_ = setup
    before = snapshot(root)
    prepare(*setup)
    assert B.recover_operations(root) == ["the update of flora, prepared but never applied, was cleaned up"]
    assert snapshot(root) == before


def test_a_fresh_folder_is_taken_back_out(setup, monkeypatch):
    root, mod, combined, profile = setup
    before = snapshot(root)
    op = B.Operation(root, "install of grass")
    staged = root / "mod" / ".grass.staging"
    staged.mkdir()
    (staged / "a.txt").write_text("a")
    op.replace_folder(root / "mod" / "grass", staged)
    op.write_file(profile, b"new")
    real = B.os.replace
    n = {"i": 0}

    def dying(src, dst):
        if "journal" not in str(dst):
            n["i"] += 1
            if n["i"] == 2:
                raise Crash()
        return real(src, dst)

    with monkeypatch.context() as m:
        m.setattr(B.os, "replace", dying)
        m.setattr(B, "_undo", lambda op: None)
        with pytest.raises(Crash):
            op.commit()
    assert (root / "mod" / "grass").is_dir()
    B.recover_operations(root)
    assert snapshot(root) == before and not (root / "mod" / "grass").exists()
