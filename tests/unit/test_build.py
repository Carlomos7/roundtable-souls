"""merging.build: outputs staged, checked, then put in place through a journal; an interrupted activation is undone
so the previous build stands. On temporary folders only."""

import pytest

from roundtable_souls.merging import build as B

RECORD = "record.json"


@pytest.fixture
def live(tmp_path):
    folder = tmp_path / "mod" / "combined"
    (folder / "chr").mkdir(parents=True)
    (folder / "chr" / "old.anibnd.dcx").write_bytes(b"old anims")
    (folder / "regulation.bin").write_bytes(b"old params")
    (folder / RECORD).write_text('{"build": 1}')
    return folder


def files(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def new_build(live):
    b = B.Build(live, RECORD)
    b.path("regulation.bin").write_bytes(b"new params")
    b.path("msg/menu.msgbnd.dcx").write_bytes(b"new text")
    b.path(RECORD).write_text('{"build": 2}')
    b.remove("chr/old.anibnd.dcx")
    return b


def test_a_build_is_put_in_place_with_its_record_and_leaves_nothing_behind(live):
    b = new_build(live)
    assert files(live)["regulation.bin"] == b"old params"  # staged: nothing live changed yet
    b.check(lambda rel, data: None)
    b.activate()
    assert files(live) == {"regulation.bin": b"new params", "msg/menu.msgbnd.dcx": b"new text", RECORD: b'{"build": 2}'}
    assert not b.stage.exists() and not b.backup.exists() and not (live / B.JOURNAL).exists()
    assert b.stage.name.startswith(".")  # never listed as a mod folder


def test_a_staged_output_that_does_not_read_back_changes_nothing(live):
    before = files(live)
    b = new_build(live)

    def read(rel, data):
        if rel == "regulation.bin":
            raise ValueError("not a regulation")

    with pytest.raises(B.BuildError, match="regulation.bin did not read back"):
        b.check(read)
    assert files(live) == before and not b.stage.exists()


def test_activation_is_refused_while_the_game_runs(live):
    before = files(live)
    with pytest.raises(B.BuildError, match="Close the game"):
        new_build(live).activate(lambda: "Close the game first")
    assert files(live) == before


@pytest.mark.parametrize("fail_at", ["replace", "backup"])
def test_an_interrupted_activation_is_undone_and_the_previous_build_stands(live, monkeypatch, fail_at):
    before = files(live)
    b = new_build(live)
    calls = {"n": 0}

    def flaky(real):
        def wrapped(*a, **k):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("power cut")
            return real(*a, **k)

        return wrapped

    if fail_at == "replace":
        monkeypatch.setattr(B.os, "replace", flaky(B.os.replace))
    else:
        monkeypatch.setattr(B.shutil, "copy2", flaky(B.shutil.copy2))
    with pytest.raises(OSError):
        b.activate()
    monkeypatch.undo()
    assert (live / B.JOURNAL).exists()  # interrupted: the journal is still there
    assert B.recover(live) == "an interrupted rebuild was undone: the previous result is back"
    assert files(live) == before and not b.stage.exists() and not b.backup.exists()
    assert B.recover(live) is None  # nothing left to undo


def test_a_new_build_first_undoes_an_interrupted_one(live, monkeypatch):
    before = files(live)
    b = new_build(live)
    real = B.os.replace
    n = {"i": 0}

    def once(*a, **k):
        n["i"] += 1
        if n["i"] == 2:
            raise OSError("crash")
        return real(*a, **k)

    monkeypatch.setattr(B.os, "replace", once)
    with pytest.raises(OSError):
        b.activate()
    monkeypatch.undo()
    B.Build(live, RECORD)  # the next rebuild starts here
    assert files(live) == before


def test_room_counts_the_outputs_the_backup_and_spare(live):
    b = B.Build(live, RECORD)
    live_bytes = sum(len(v) for v in files(live).values())
    b.make_room(1000, free=lambda p: 1000 + live_bytes + B.SPARE)  # exactly enough
    with pytest.raises(B.BuildError, match="not enough free space"):
        b.make_room(1000, free=lambda p: 999 + live_bytes + B.SPARE)
    assert not b.stage.exists()
