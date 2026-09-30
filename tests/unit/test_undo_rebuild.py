"""Undoing a rebuild: the combine's earlier output kept in the data folder, the rebuild tool's own backup swapped
back by renaming (restore.json), the profile from its history, and redo; plus trimming a tool's old backups."""

import json
import os
import shutil
import time

from test_mod_merge import World
from test_param_merge import pack, set_word, vanilla

from roundtable_souls.mods import merge, undo
from roundtable_souls.mods.backends import builtin
from roundtable_souls.system import logging as rl


def tool_that_backs_itself_up(w: World):
    """Like a real overlay installer: before writing, it keeps its folder and the profile in a backup folder of the
    profile's folder, with a restore.json naming them."""
    real = w.fake_run

    def run(backend, *a, **k):
        stamp = f"{time.time():.6f}".replace(".", "")
        backup = w.base / "Tool Backups" / stamp
        backup.mkdir(parents=True)
        shutil.copytree(w.base / "Merger", backup / "previous")
        shutil.copy2(w.profile, backup / "file-0")
        (backup / "restore.json").write_text(
            json.dumps(
                {
                    "files": [{"path": str(w.profile), "original": "file-0"}],
                    "directories": [{"path": str(w.base / "Merger"), "original": str(backup / "previous")}],
                }
            ),
            encoding="utf-8",
        )
        (w.winner / "regulation.bin").write_bytes(b"MERGED " + stamp.encode())
        return real(backend, *a, **k)

    return run


def test_undo_swaps_the_tools_output_and_the_profile_back_and_redo_swaps_again(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    monkeypatch.setattr("roundtable_souls.mods.backends.Tool.run", lambda b, log: tool_that_backs_itself_up(w)(b))
    w.pack("params")
    output_before = (w.winner / "regulation.bin").read_bytes()
    profile_before = w.profile.read_text(encoding="utf-8")
    out = merge.rebuild(w.profile, lambda s: None, combine=False)
    u = out["undo"]
    assert u["type"] == "rebuild" and u["tool_restore"] and u["profile_before"]
    output_after = (w.winner / "regulation.bin").read_bytes()
    profile_after = w.profile.read_text(encoding="utf-8")
    assert output_after != output_before and undo.available(u) and undo.label(u) == "Undo rebuild"
    said = undo.run(u, lambda s: None)
    assert "the rebuild tool's output" in said and "the profile" in said
    assert (w.winner / "regulation.bin").read_bytes() == output_before
    assert w.profile.read_text(encoding="utf-8") == profile_before
    assert merge.health(w.profile)["state"] == "stale"  # honest: the output no longer matches the packs
    redo = {**u, "redo": True}
    assert undo.label(redo) == "Redo rebuild"
    undo.run(redo, lambda s: None)
    assert (w.winner / "regulation.bin").read_bytes() == output_after
    assert w.profile.read_text(encoding="utf-8") == profile_after


def test_a_restore_list_pointing_outside_the_profile_is_not_used(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    listing = w.base / "Tool Backups" / "x" / "restore.json"
    listing.parent.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    listing.write_text(json.dumps({"directories": [{"path": str(elsewhere), "original": str(listing.parent)}]}))
    u = {"type": "rebuild", "profile": str(w.profile), "tool_restore": str(listing)}
    assert not undo.available(u) and undo._tool_swaps(u) is None
    assert elsewhere.is_dir()


def test_the_combine_keeps_its_earlier_outputs_and_undo_puts_one_back(tmp_path, monkeypatch):
    from roundtable_souls.system import common

    game = tmp_path / "Game"
    game.mkdir()
    (game / "regulation.bin").write_bytes(vanilla())
    monkeypatch.setattr(common, "game_dir", lambda: game)
    monkeypatch.setattr(common, "game_running", lambda: False)
    monkeypatch.setattr(builtin, "HISTORY_KEEP", 2)
    base = tmp_path / "p"
    for name in ("a", "b"):
        (base / "mod" / name).mkdir(parents=True)
    prof = base / "p.me3"
    prof.write_text("[[packages]]\nid = \"a\"\npath = 'mod/a'\n\n[[packages]]\nid = \"b\"\npath = 'mod/b'\n")
    outputs, undos = [], []
    for value in (11, 22, 33, 44):
        (base / "mod" / "a" / "regulation.bin").write_bytes(pack({"EquipParamWeapon": set_word(1000, 0, value)}))
        (base / "mod" / "b" / "regulation.bin").write_bytes(pack({"EquipParamWeapon": set_word(2000, 1, value)}))
        res = merge.rebuild(prof, lambda s: None, combine=True)
        outputs.append((base / "mod" / "combined-parameters" / "regulation.bin").read_bytes())
        undos.append(res["undo"])
        time.sleep(1.1)  # kept copies are named by the second
    assert undos[0]["combined_before"] is None  # the first combine replaced nothing
    kept = sorted(os.listdir(builtin.history_root(prof)))
    assert len(kept) == 2  # the newest HISTORY_KEEP
    said = undo.run(undos[-1], lambda s: None)
    assert "the combined parameters" in said
    assert (base / "mod" / "combined-parameters" / "regulation.bin").read_bytes() == outputs[-2]


def test_old_tool_backups_go_to_the_recycle_bin_keeping_the_newest(tmp_path, monkeypatch):
    from roundtable_souls.system import trash

    if not trash.available():
        return
    w = World(tmp_path, monkeypatch)
    folders = []
    for i in range(5):
        d = w.base / "Tool Backups" / f"2026092{i}"
        d.mkdir(parents=True)
        (d / "restore.json").write_text("{}")
        (d / "big.bin").write_bytes(b"x" * 1000)
        os.utime(d / "restore.json", (1_700_000_000 + i, 1_700_000_000 + i))
        folders.append(d)
    listed = merge.tool_backups(w.profile)
    assert [b["folder"].name for b in listed] == [f"2026092{i}" for i in (4, 3, 2, 1, 0)]
    assert listed[0]["size"] >= 1000
    moved = merge.trim_tool_backups(w.profile, keep=3)
    assert len(moved) == 2 and not folders[0].exists() and not folders[1].exists() and folders[4].exists()
    assert all(trash.exists(r) for r in moved)  # in the bin, restorable (the tests' own bin items are purged after)


def test_an_undone_job_no_longer_offers_undo():
    job = rl.begin_job("rebuild combined parameters")
    rl.set_undo({"type": "rebuild", "profile": "x"})
    rl.end_job(job)
    assert rl.read_jobs()[0]["undo"]
    rl.mark_undone(job.id)
    rec = rl.read_jobs()[0]
    assert rec["undo"] is None and rec["undone"]
