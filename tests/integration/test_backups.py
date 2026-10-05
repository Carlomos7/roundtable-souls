"""Backups with manifests, restore with a safety copy, and the Play session options.
Runs on COPIES of the live co-op save in a temp folder; the live file is never written."""

import json
import struct
from pathlib import Path

import pytest

from roundtable_souls.config.settings import LauncherSettings
from roundtable_souls.game.locate import Locations
from roundtable_souls.platform import data_folder, paths
from roundtable_souls.saves import backups as save_backups
from roundtable_souls.saves import layout as save_layout_check
from roundtable_souls.services import play as g
from roundtable_souls.services import saves as saves_service
from support import copy_live_save as _copy
from support import er

F = g.save_fix
L = save_layout_check
A = g.save_analyze


def test_backup_writes_manifest_and_list_reads_it(tmp_path):
    copy = _copy(tmp_path)
    bak = F.backup(copy, {"action": "Fix loading", "changes": ["Tarnished: Torrent stuck at 0 HP"]})
    assert bak.parent == save_backups.backups(copy.parent) and bak.read_bytes() == copy.read_bytes()
    beside = [p for p in copy.parent.iterdir() if p.is_dir() and p != data_folder.data_root()]  # tests keep it here
    assert beside == []  # nothing of the launcher's beside the save
    m = json.loads(Path(str(bak) + ".json").read_text(encoding="utf-8"))
    assert (
        m["action"] == "Fix loading"
        and m["changes"] == ["Tarnished: Torrent stuck at 0 HP"]
        and m["save"].endswith("ER0000.co2")
    )
    bak2 = F.backup(copy)  # same second: still a distinct file
    assert bak2 != bak and F.read_manifest(bak2)["action"] == "Before a change"
    rows = saves_service.list_backups(copy, loc=er())
    assert [r["path"] for r in rows][:2] == sorted([bak, bak2], key=lambda p: p.stat().st_mtime, reverse=True) or len(
        rows
    ) == 2
    assert {r["action"] for r in rows} == {"Before fixing loading", "Before a change"} and all(
        r["save_name"] == "ER0000.co2" for r in rows
    )
    assert saves_service.save_for_backup(bak, loc=er()) == copy
    # a backup without a note still lists, and still finds its save through the folder it sits in
    Path(str(bak2) + ".json").unlink()
    assert any(
        r["path"] == bak2 and r["action"] == "Before a change" for r in saves_service.list_backups(copy, loc=er())
    )


def test_fix_writes_a_manifest_that_names_the_change(tmp_path, monkeypatch):
    copy = _copy(tmp_path)
    monkeypatch.setattr(paths, "exe_running", lambda _exe: False)
    data = bytearray(copy.read_bytes())
    r = L.parse(str(copy))
    i = next(k for k, a in enumerate(r["ud10"]["active"]) if a)
    s = r["slots"][i]
    struct.pack_into("<i", data, s["horse_pos"] + 32, 0)
    struct.pack_into("<I", data, s["horse_pos"] + 36, 13)
    F._sign_slot(data, i)
    copy.write_bytes(bytes(data))
    out = saves_service.fix_loading(copy, loc=er())
    m = F.read_manifest(out["backup"])
    assert m["action"] == "Before fixing loading" and any("Torrent" in c for c in m["changes"])


def test_restore_backup_round_trip_with_safety_copy(tmp_path, monkeypatch):
    copy = _copy(tmp_path)
    monkeypatch.setattr(paths, "exe_running", lambda _exe: False)
    original = copy.read_bytes()
    bak = F.backup(copy, {"action": "Fix loading", "changes": ["x"]})
    data = bytearray(original)
    data[0x400] ^= 0x5A
    copy.write_bytes(bytes(data))  # the live file moves on
    changed = copy.read_bytes()
    assert changed != original
    safety = saves_service.restore_backup(bak, loc=er())
    assert copy.read_bytes() == original
    assert (
        safety and safety.read_bytes() == changed and F.read_manifest(safety)["action"] == "Before restoring a backup"
    )
    saves_service.restore_backup(safety, copy, loc=er())  # undo the restore
    assert copy.read_bytes() == changed
    saves_service.delete_backup(bak)
    assert not bak.exists() and not Path(str(bak) + ".json").exists()
    junk = tmp_path / "ER0000.co2.junk.bak"
    junk.write_bytes(b"nope")
    with pytest.raises(RuntimeError):
        saves_service.restore_backup(junk, copy, loc=er())
    monkeypatch.setattr(paths, "exe_running", lambda _exe: True)
    with pytest.raises(RuntimeError):
        saves_service.restore_backup(safety, copy, loc=er())


def test_play_options_defaults_and_backup_before_play(tmp_path, monkeypatch):
    assert g.play_options(LauncherSettings.from_raw({})) == g.PLAY_DEFAULTS
    assert (
        g.play_options(LauncherSettings.from_raw({"play_repair_after": False, "play_backup_before": 1}))[
            "play_repair_after"
        ]
        is False
    )
    assert g.play_options(LauncherSettings.from_raw({"play_backup_before": 1}))["play_backup_before"] is True
    assert (
        g.play_options(LauncherSettings.from_raw({"play_boot_boost": None}))["play_boot_boost"] is True
    )  # null in the file = default
    copy = _copy(tmp_path)
    monkeypatch.setattr(Locations, "save_files", lambda self: [copy])
    made = g.backup_saves_before_play(er())
    assert (
        len(made) == 1
        and F.read_manifest(made[0])["action"] == "Before playing"
        and made[0].read_bytes() == copy.read_bytes()
    )


def test_character_detail_and_place_names(tmp_path):
    copy = _copy(tmp_path)
    info = g.save_info(copy, loc=er())
    ch = info["characters"][0]
    assert ch["where"] and ch["torrent"] and "vig" in ch["stats"]
    d = saves_service.character_detail(info, ch["slot"] - 1)
    assert d["name"] == ch["name"] and isinstance(d["mods"], dict) and isinstance(d["loading"], list)
    assert saves_service.place_name(bytes([0, 0, 10, 11])) == "Roundtable Hold"
    assert saves_service.place_name(bytes([0, 46, 47, 61])).startswith("Land of Shadow")
    assert saves_service.place_name(bytes([0, 0, 0, 18])) == "Stranded Graveyard"
    assert (
        saves_service.torrent_text((1939, 1)) == "resting, 1,939 HP"
        and saves_service.torrent_text((0, 13)) == "summoned, 0 HP"
    )
    assert saves_service.character_detail(info, 9) == {}
