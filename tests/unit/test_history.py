"""Profile history, and removing an entry with exactly its own comments so it can be put back where it was."""

import time

import pytest

from roundtable_souls.mods import history, remove
from roundtable_souls.mods import profile_edit as M
from roundtable_souls.services import mods as service
from support import er

SF_VOICE = """profileVersion = "v1"

# voice pack: English lines
[[packages]]
id = "voice-pack"
path = 'mod/voice-pack'


# =====
#  4. INTERFACE
# =====

# HUD overlay, interface files only
[[packages]]
id = "hud-overlay"
path = 'mod/hud-overlay'
"""


# ----------------------------------------------------------------------------- an entry's own span
def test_removing_an_entry_keeps_the_next_entrys_comments_and_takes_its_own():
    new, chunk, _where = M.remove_entry(SF_VOICE, 0)
    assert "4. INTERFACE" in new and "# HUD overlay" in new  # the next entry's notes stay
    assert "voice pack" not in new and chunk.startswith("# voice pack")  # its own go with it
    assert [M.block_options(new, b["index"])["id"] for b in M.blocks(new)] == ["hud-overlay"]


def test_a_note_that_mentions_a_setting_is_still_a_note():
    text = (
        "# Widens the camera view. max_distance = 0 in camera.ini.\n[[natives]]\npath = 'natives/Camera/camera.dll'\n"
    )
    _new, chunk, _ = M.remove_entry(text, 0)
    assert chunk.startswith("# Widens the camera view")


def test_commented_out_entries_above_are_not_taken():
    text = '# [[packages]]\n# id = "old"\n# Notes for the live one\n[[packages]]\nid = "live"\npath = \'mod/live\'\n'
    new, chunk, _ = M.remove_entry(text, 0)
    assert new.startswith('# [[packages]]\n# id = "old"\n') and chunk.startswith("# Notes for the live one")


def test_comments_inside_an_entry_go_with_it_and_trailing_ones_stay():
    text = (
        "[[packages]]\nid = \"a\"\n# keep this\npath = 'mod/a'\n# about b\n[[packages]]\nid = \"b\"\npath = 'mod/b'\n"
    )
    new, chunk, _ = M.remove_entry(text, 0)
    assert "# keep this" in chunk and "# about b" in new and "# about b" not in chunk


@pytest.mark.parametrize("index", [0, 1, 2])
def test_first_middle_and_last_round_trip_exactly(index):
    text = SF_VOICE + "\n[[natives]]\npath = 'natives/x.dll'\n"
    new, chunk, where = M.remove_entry(text, index)
    assert M.restore_entry(new, chunk, where) == text


def test_windows_line_endings_round_trip():
    text = SF_VOICE.replace("\n", "\r\n")
    new, chunk, where = M.remove_entry(text, 0)
    assert "\r\n" in new and "\n" not in new.replace("\r\n", "")
    assert M.restore_entry(new, chunk, where) == text


def test_restore_finds_its_place_when_lines_around_repeat_and_neighbours_changed():
    text = "".join(f"[[packages]]\nid = \"{n}\"\npath = 'mod/{n}'\nenabled = false\n\n" for n in ("a", "b", "c", "d"))
    new, chunk, where = M.remove_entry(text, 2)  # c, between b and d, among identical-looking lines
    new = M.set_block_options(new, 0, {"enabled": True})  # an unrelated change meanwhile
    back = M.restore_entry(new, chunk, where)
    assert [M.block_options(back, b["index"])["id"] for b in M.blocks(back)] == ["a", "b", "c", "d"]


def test_restore_falls_back_to_the_next_entry_then_the_end():
    text = SF_VOICE
    new, chunk, where = M.remove_entry(text, 0)
    rewritten = new.replace("# =====\n#  4. INTERFACE\n# =====\n\n", "")  # its surroundings edited away
    back = M.restore_entry(rewritten, chunk, where)
    ids = [M.block_options(back, b["index"])["id"] for b in M.blocks(back)]
    assert ids == ["voice-pack", "hud-overlay"]
    gone = M.remove_block(new, 0)  # the next entry was removed too: the lines around still place it
    back = M.restore_entry(gone, chunk, where)
    assert back.index("voice-pack") < back.index("4. INTERFACE")
    elsewhere = "profileVersion = \"v2\"\n\n[[natives]]\npath = 'natives/x.dll'\n"  # nothing around it is left
    back = M.restore_entry(elsewhere, chunk, where)
    assert back.index("x.dll") < back.index("voice-pack") and back.endswith("path = 'mod/voice-pack'\n")


def test_uninstall_returns_what_restore_needs(tmp_path):
    p = tmp_path / "p.me3"
    (tmp_path / "mod" / "voice-pack").mkdir(parents=True)
    p.write_text(SF_VOICE, encoding="utf-8")
    out = remove.uninstall(p, 0, delete_folder=False, loc=er())
    assert out["name"] == "voice-pack" and out["entry_text"].startswith("# voice pack")
    assert M.restore_entry(p.read_text(encoding="utf-8"), out["entry_text"], out["where"]) == SF_VOICE


# ----------------------------------------------------------------------------- history
def test_every_launcher_write_keeps_a_copy_first(tmp_path):
    p = tmp_path / "p.me3"
    (tmp_path / "mod" / "voice-pack").mkdir(parents=True)
    p.write_text(SF_VOICE, encoding="utf-8")
    M.set_options(p, 0, {"enabled": False}, loc=er())
    service.write_profile_setting(p, "mem_patch", True)
    remove.uninstall(p, 0, delete_folder=False, loc=er())
    whys = [v["why"] for v in history.versions(p)]
    assert whys == ["before removing voice-pack", "before changing mem_patch", "before turning voice-pack off"]
    assert history.versions(p)[-1]["path"].read_text(encoding="utf-8") == SF_VOICE


def test_an_unchanged_profile_is_not_copied_twice(tmp_path):
    p = tmp_path / "p.me3"
    p.write_text(SF_VOICE, encoding="utf-8")
    a = history.snapshot(p, "one")
    b = history.snapshot(p, "two")
    assert a == b and len(history.versions(p)) == 1


def test_history_keeps_the_newest_copies(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "KEEP", 5)
    p = tmp_path / "p.me3"
    for i in range(8):
        p.write_text(SF_VOICE + f"# {i}\n", encoding="utf-8")
        history.snapshot(p, f"change {i}")
        time.sleep(0.002)
    history.prune(p, keep=history.KEEP)
    kept = [v["why"] for v in history.versions(p)]
    assert kept == [f"change {i}" for i in (7, 6, 5, 4, 3)]


def test_restoring_keeps_the_replaced_version_so_it_can_be_undone(tmp_path):
    p = tmp_path / "p.me3"
    p.write_text("old\n", encoding="utf-8")
    first = history.snapshot(p, "before editing")
    p.write_text("new\n", encoding="utf-8")
    before = history.restore(p, first)
    assert p.read_text(encoding="utf-8") == "old\n" and before.read_text(encoding="utf-8") == "new\n"
    history.restore(p, before)
    assert p.read_text(encoding="utf-8") == "new\n"


def test_two_profiles_with_the_same_name_keep_separate_histories(tmp_path):
    a, b = tmp_path / "er" / "p.me3", tmp_path / "nr" / "p.me3"
    for f, t in ((a, "er\n"), (b, "nr\n")):
        f.parent.mkdir()
        f.write_text(t)
        history.snapshot(f, "x")
    assert history.folder(a) != history.folder(b)
    assert history.versions(a)[0]["path"].read_text() == "er\n"


def test_a_history_that_cannot_be_written_never_stops_a_change(tmp_path, monkeypatch):
    blocker = tmp_path / "blocked"
    blocker.write_text("x")
    monkeypatch.setattr(history, "folder", lambda profile: blocker / "sub")
    p = tmp_path / "p.me3"
    p.write_text(SF_VOICE, encoding="utf-8")
    assert history.snapshot(p) is None
    M.set_options(p, 0, {"enabled": False}, loc=er())  # still written
    assert "enabled = false" in p.read_text(encoding="utf-8")
