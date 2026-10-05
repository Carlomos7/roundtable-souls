"""Several games: picking one by name, where each one lives, per-game settings, Nightreign's co-op ini and saves."""

import os
import struct

import pytest

from roundtable_souls.config import settings
from roundtable_souls.config.settings import LauncherSettings
from roundtable_souls.game import catalog as games
from roundtable_souls.game.locate import Locations, Overrides, installed_dir
from roundtable_souls.platform import paths as common
from roundtable_souls.platform import steam
from roundtable_souls.saves import container
from roundtable_souls.saves import nightreign as nr
from roundtable_souls.services import coop as coop_service
from roundtable_souls.services import play as core
from roundtable_souls.services import saves

NR = games.NIGHTREIGN
ER = games.ELDEN_RING

NRSC_INI = (
    "[GAMEPLAY]\r\n\r\n[SCALING]\r\n\r\nhealth_scaling = 100\r\n\r\ndamage_scaling = 90\r\n\r\nposture_scaling = 80\r\n\r\n"
    "[SAVE]\r\n\r\n;Your save file extension (in the vanilla game this is .sl2)\r\nsave_file_extension = co2\r\n"
)


def test_game_names_resolve_from_keys_aliases_and_app_ids():
    assert games.resolve("NR") is NR and games.resolve("nightreign") is NR and games.resolve("2622380") is NR
    assert games.resolve("er") is ER and games.resolve(" Eldenring ") is ER
    assert games.resolve("ds3") is games.DARK_SOULS_3 and games.resolve("sdt") is games.SEKIRO
    assert games.resolve("bloodborne") is None and games.resolve("") is None
    assert games.get("made-up") is ER  # a stored key from a newer build falls back
    assert games.for_save("C:/x/NR0000.co2") is NR and games.for_save("ER0000.sl2.bak") is ER
    assert games.for_save("notes.txt") is None
    assert [g.ready for g in games.GAMES] == [True, True, False, False]


def test_game_from_args(monkeypatch):
    assert core.game_from_args(["x", "--game", "nr", "--play"]) is NR
    assert core.game_from_args(["x", "--game=ds3"]) is games.DARK_SOULS_3
    assert core.game_from_args(["x", "--game", "nope"]) is None
    assert (
        core.game_from_args(["x", "--play"], LauncherSettings.from_raw({"game": "nightreign"})) is NR
    )  # no flag: the last tab used
    assert core.game_from_args(["x"], LauncherSettings.from_raw({"game": "eldenring"})) is ER


def test_each_game_finds_its_own_install_and_saves(tmp_path, monkeypatch):
    lib = tmp_path / "Steam"
    for g in (ER, NR):
        d = lib / "steamapps" / "common" / g.install_dir
        d.mkdir(parents=True)
        (d / g.exe).write_bytes(b"")
    appdata = tmp_path / "Roaming"
    for g in (ER, NR):
        acct = appdata / g.save_dir / "7656"
        acct.mkdir(parents=True)
        for name in g.save_names:
            (acct / name).write_bytes(b"x")
    monkeypatch.setattr(steam, "steam_libraries", lambda: [lib])
    monkeypatch.setattr(common, "IS_WINDOWS", True)
    monkeypatch.setenv("APPDATA", str(appdata))
    nr = Locations(NR)
    assert nr.game_dir() == lib / "steamapps" / "common" / NR.install_dir
    assert sorted(p.name for p in nr.save_files()) == ["NR0000.co2", "NR0000.sl2"]
    assert nr.game_exe_name() == "nightreign.exe"
    assert sorted(p.name for p in Locations(ER).save_files()) == ["ER0000.co2", "ER0000.sl2"]
    assert installed_dir(games.SEKIRO) is None and Locations(games.SEKIRO).save_files() == []


def test_profiles_are_listed_for_the_game_they_support(tmp_path, monkeypatch):
    root = tmp_path / "profiles"
    root.mkdir()
    (root / "er.me3").write_text('profileVersion = "v1"\n[[supports]]\ngame = "eldenring"\n', encoding="utf-8")
    (root / "nr.me3").write_text('profileVersion = "v1"\n[[supports]]\ngame = "nightreign"\n', encoding="utf-8")
    (root / "old.me3").write_text('profileVersion = "v1"\n', encoding="utf-8")  # names no game: Elden Ring's
    (root / "nightreign-default.me3").write_text('[[supports]]\ngame = "nightreign"\n', encoding="utf-8")
    loc = Locations(NR, Overrides(profiles_dir=str(root)))
    assert [p.name for p in loc.me3_profiles(ER)] == ["er.me3", "old.me3"]
    assert [p.name for p in loc.me3_profiles()] == ["nr.me3"]
    setups = core.discover(None, loc)
    assert [s.label for s in setups] == ["nr.me3"] and setups[0].game is NR
    wrong = core.Setup("me3", root / "er.me3", loc=loc)
    assert any("for Elden Ring, not Nightreign" in p for p in wrong.problems())


def test_settings_are_kept_per_game():
    settings.save_game_settings("eldenring", setup="er.me3", game_exe="C:/er/eldenring.exe")
    settings.save_game_settings("nightreign", setup="nr.me3")
    s = settings.load_settings()
    assert s.setup == "er.me3"  # Elden Ring stays where older builds read it
    assert settings.game_setting(s, "nightreign", "setup") == "nr.me3"
    assert settings.game_setting(s, "nightreign", "game_exe", "") == ""
    assert core.remembered_setup(s, NR) == "nr.me3" and core.remembered_setup(s, ER) == "er.me3"
    assert Locations.from_settings(s, NR).overrides.game_exe == ""  # Elden Ring's custom exe is not Nightreign's
    assert Locations.from_settings(s, ER).overrides.game_exe == "C:/er/eldenring.exe"


def test_forget_setup_only_touches_its_own_game():
    settings.save_game_settings("eldenring", setup="er.me3")
    settings.save_game_settings("nightreign", setup="nr.me3")
    core.forget_setup(NR)
    s = settings.load_settings()
    assert core.remembered_setup(s, NR) is None and core.remembered_setup(s, ER) == "er.me3"


def test_same_source_matches_remembered_paths_loosely():
    assert core.same_source("a/b.me3", "a/b.me3")
    assert not core.same_source("a/b.me3", None) and not core.same_source(None, "a/b.me3")
    if os.name == "nt":  # normcase folds case and slash direction on Windows only
        assert core.same_source("C:/profiles/Er.me3", "c:\\profiles\\er.me3")


def test_setup_reads_its_coop_ini_once_and_only_on_use(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(core, "coop_ini_for", lambda *a: calls.append(a))
    s = core.Setup("me3", tmp_path / "a.me3", loc=Locations(ER))
    assert calls == []  # discover() builds a Setup per profile on disk; none reads its file until picked
    assert s.ini is None and s.ini is None
    assert len(calls) == 1  # looked once, remembered the answer, even "this profile has none"


def test_nightreign_coop_ini_has_three_scaling_values_and_no_password(tmp_path):
    folder = tmp_path / "natives" / "SeamlessCoop"
    folder.mkdir(parents=True)
    ini = folder / "nrsc_settings.ini"
    ini.write_bytes(NRSC_INI.encode())
    profile = tmp_path / "nr.me3"
    profile.write_text(
        'profileVersion = "v1"\n[[supports]]\ngame = "nightreign"\n[[natives]]\n'
        "path = 'natives/SeamlessCoop/nrsc.dll'\nload_early = true\n",
        encoding="utf-8",
    )
    assert core.coop_ini_for(str(profile), NR) == ini
    assert core.coop_ini_for(str(profile), ER) is None  # it loads nrsc.dll, not ersc.dll
    assert core.coop_ini_for(str(profile), games.SEKIRO) is None
    spec = core.scaling_spec(ini)
    assert spec is coop_service.NIGHTREIGN_SCALING
    assert core.read_scaling(ini, spec) == (100, 90, 80) and core.preset_of((100, 90, 80), spec) == coop_service.CUSTOM
    assert not core.has_password(ini) and core.read_password(ini) is None
    before = ini.read_bytes()
    assert coop_service.write_keys(ini, dict(zip(spec.keys, (120, 90, 80), strict=True))) == []
    assert core.read_scaling(ini) == (120, 90, 80)
    assert len(ini.read_bytes()) == len(before)  # 100 -> 120: same length, nothing else touched


def test_offline_copy_turns_off_the_games_own_coop_dll():
    text = (
        '[[natives]]\npath = "natives/SeamlessCoop/nrsc.dll"\nload_early = true\n\n'
        '[[natives]]\npath = "natives/UnlockTheFps/UnlockTheFps.dll"\n'
    )
    out = core.offline_profile_text(text, coop_dll="nrsc.dll")
    assert '# path = "natives/SeamlessCoop/nrsc.dll"' in out
    assert '\npath = "natives/UnlockTheFps/UnlockTheFps.dll"' in out
    assert core.offline_profile_text(text, coop_dll="ersc.dll").endswith(text)  # Elden Ring's dll is not in it


def test_steam_shortcut_names_the_game():
    _target, options = core.play_command(NR)
    assert options.endswith("--game nightreign --play")


def container_bytes(names, sizes, truncate=0):
    count = len(names)
    table_end = 0x40 + 0x20 * count
    name_blob, name_offsets = b"", []
    for n in names:
        name_offsets.append(table_end + len(name_blob))
        name_blob += n.encode("utf-16-le") + b"\0\0"
    data_at = table_end + len(name_blob)
    head = bytearray(0x40)
    head[:4] = b"BND4"
    struct.pack_into("<i", head, 0x0C, count)
    struct.pack_into("<q", head, 0x20, 0x20)
    entries, blobs = b"", b""
    for size, name_off in zip(sizes, name_offsets, strict=True):
        entries += struct.pack("<iiqII8x", 0x40, -1, size, data_at + len(blobs), name_off)
        blobs += bytes(size)
    data = bytes(head) + entries + name_blob + blobs
    return data[: len(data) - truncate] if truncate else data


def nr_save(tmp_path, name="NR0000.co2", **kw):
    payloads = [(b"RSLT" + bytes(12)) if i == 12 else bytes([i]) + bytes(15) for i in range(14)]
    data = nr.pack_save(payloads)
    if kw.get("truncate"):
        data = data[: len(data) - kw["truncate"]]
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_container_check():
    names = [f"USER_DATA{i:03d}" for i in range(14)]
    found = container.check(container_bytes(names, [32] * 14), 14)
    assert [s.name for s in found] == names and all(s.size == 32 for s in found)
    with pytest.raises(container.ContainerError):
        container.check(container_bytes(names, [32] * 14, truncate=10), 14)
    with pytest.raises(container.ContainerError):
        container.check(container_bytes(names[:12], [32] * 12), 14)
    with pytest.raises(container.ContainerError):
        container.check(b"not a save" * 10)


def test_nightreign_save_info_checks_checksums_and_regulation(tmp_path):
    info = saves.save_info(nr_save(tmp_path), loc=Locations(NR))
    assert info["kind"] == "Seamless Co-op" and info["error"] is None and info["characters"] == []
    assert [f["code"] for f in info["findings"]] == ["layout", "checksum", "regulation"]
    assert all(f["level"] == "ok" for f in info["findings"])
    assert info["convert_ok"] and not info["needs_repair"] and not saves.repair_available(info)
    assert saves.save_summary(info) == [
        ("File is whole", "success"),
        ("Section checksums match", "success"),
        ("Regulation OK", "success"),
    ]
    broken = saves.save_info(nr_save(tmp_path, "NR0000.sl2", truncate=40), loc=Locations(NR))
    assert broken["error"] and broken["findings"][0]["title"] == "Damaged save file"


def test_nightreign_copies_and_restore(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "exe_running", lambda _exe: False)
    co2 = nr_save(tmp_path)
    os.utime(co2, (1_700_000_000, 1_700_000_000))  # settled long ago: the write lock does not wait
    sl2 = saves.convert_co2_to_sl2(co2, co2.with_suffix(".sl2"), loc=Locations(NR))
    assert sl2.read_bytes() == co2.read_bytes()
    junk = tmp_path / "elsewhere" / "NR0000.co2.20260101-000000.bak"
    junk.parent.mkdir()
    junk.write_bytes(b"BND4 but not really")
    with pytest.raises(RuntimeError, match="not a whole Nightreign save"):
        saves.restore_backup(junk, co2, loc=Locations(NR))


def test_placeholder_games_cannot_play():
    s = LauncherSettings.from_raw({})
    assert core.play_headless(s, Locations(games.DARK_SOULS_3)) == 1
    assert core.play_headless(s, Locations(games.SEKIRO)) == 1
