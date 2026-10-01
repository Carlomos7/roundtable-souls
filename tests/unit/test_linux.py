"""Linux and Steam Deck detection, exercised on fake home folders so it runs on any OS."""

from roundtable_souls import updates
from roundtable_souls.system import common


def linux(monkeypatch, home):
    monkeypatch.setattr(common, "IS_WINDOWS", False)
    monkeypatch.setattr(common, "IS_LINUX", True)
    monkeypatch.setattr(common.Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(common.shutil, "which", lambda name: None)
    monkeypatch.setattr(common, "PROFILE_DIR_OVERRIDE", None)
    monkeypatch.setattr(common, "ME3_OVERRIDE", None)
    monkeypatch.setattr(common, "GAME_EXE_OVERRIDE", None)


def fake_proc(root, pid, argv, comm, rss_kb):
    d = root / str(pid)
    d.mkdir(parents=True)
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    (d / "comm").write_text(comm + "\n")
    (d / "status").write_text(f"Name:\t{comm}\nVmRSS:\t {rss_kb} kB\n")


def test_proton_game_and_steam_are_found_in_proc(tmp_path):
    proc = tmp_path / "proc"
    fake_proc(
        proc,
        100,
        ["Z:\\home\\deck\\.steam\\steam\\steamapps\\common\\ELDEN RING\\Game\\eldenring.exe"],
        "eldenring.exe",
        5_000_000,
    )
    fake_proc(proc, 101, ["/home/deck/.local/share/Steam/ubuntu12_32/steam", "-silent"], "steam", 300_000)
    fake_proc(proc, 102, ["/usr/bin/python3"], "python3", 10_000)
    (proc / "self").mkdir()
    assert common._linux_processes("eldenring.exe", proc) == [(100, 5_000_000)]
    assert common._linux_processes("steam", proc) == [(101, 300_000)]
    assert common._linux_processes("missing.exe", proc) == []


def test_steam_library_saves_and_sign_in(tmp_path, monkeypatch):
    home = tmp_path / "home"
    linux(monkeypatch, home)
    steam = home / ".local" / "share" / "Steam"
    (steam / "steamapps" / "common" / "ELDEN RING" / "Game").mkdir(parents=True)
    (steam / "steamapps" / "common" / "ELDEN RING" / "Game" / "eldenring.exe").write_bytes(b"x")
    sd = tmp_path / "sdcard"
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n "1"\n {{\n  "path"\t\t"{sd.as_posix()}"\n }}\n}}\n'
    )
    saves = (
        sd
        / "steamapps"
        / "compatdata"
        / "1245620"
        / "pfx"
        / "drive_c"
        / "users"
        / "steamuser"
        / "AppData"
        / "Roaming"
        / "EldenRing"
        / "76561190000000000"
    )
    saves.mkdir(parents=True)
    (saves / "ER0000.sl2").write_bytes(b"s")
    (saves / "ER0000.co2").write_bytes(b"c")
    assert common.steam_root() == steam.resolve()
    assert common.game_dir() == steam / "steamapps" / "common" / "ELDEN RING" / "Game"
    assert [p.name for p in common.save_files()] == ["ER0000.sl2", "ER0000.co2"]  # the prefix on the SD card
    assert not common.steam_logged_in()
    (home / ".steam").mkdir()
    (home / ".steam" / "registry.vdf").write_text('"Registry"\n{\n "ActiveProcess"\n {\n  "ActiveUser"\t\t"0"\n }\n}\n')
    assert not common.steam_logged_in()
    (home / ".steam" / "registry.vdf").write_text('"ActiveUser"\t\t"123456"\n')
    assert common.steam_logged_in()
    assert common.dead_game_shells() == []  # a Windows-only problem


def test_me3_paths_follow_its_linux_layout(tmp_path, monkeypatch):
    home = tmp_path / "home"
    linux(monkeypatch, home)
    assert common.me3_profiles_dir() == home / ".config" / "me3" / "profiles"
    assert common.me3_exe() is None
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".local" / "bin" / "me3").write_bytes(b"#!/bin/sh\n")
    common.clear_detection_cache()  # detection is cached per session; the app clears it on every game switch
    assert common.me3_exe() == home / ".local" / "bin" / "me3"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert common.me3_profiles_dir() == tmp_path / "cfg" / "me3" / "profiles"


def test_linux_update_file_and_parked_names(tmp_path):
    """The download itself is covered in test_updates (test_linux_update_unpacks_the_program)."""
    assert updates.update_asset(False, "linux") == updates.LINUX_ASSET_NAME
    assert (
        updates.update_asset(True, "win32") == updates.SETUP_NAME
        and updates.update_asset(False, "win32") == updates.ASSET_NAME
    )
    assert updates.parked_path(tmp_path / "RoundtableSouls").name == "RoundtableSouls.old"
    assert updates.parked_path(tmp_path / "RoundtableSouls.exe").name == "RoundtableSouls.old.exe"
