"""The app context and a game's Locations: values handed to the code that needs them, instead of module globals."""

from roundtable_souls.app import create_app
from roundtable_souls.config import settings
from roundtable_souls.game import catalog
from roundtable_souls.game.locate import Locations, Overrides


def test_a_custom_game_exe_decides_the_game_folder_and_the_process_name(tmp_path):
    exe = tmp_path / "Game" / "start_protected_game.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"x")
    loc = Locations(catalog.ELDEN_RING, Overrides(game_exe=str(exe)))
    assert loc.game_dir() == exe.parent and loc.game_exe_name() == "start_protected_game.exe"
    assert loc.regulation_bin() is None  # none beside the exe
    (exe.parent / "regulation.bin").write_bytes(b"r")
    assert loc.regulation_bin() == exe.parent / "regulation.bin"


def test_overrides_come_from_the_settings_per_game():
    s = settings.LauncherSettings.from_raw(
        {"me3_path": " C:/me3.exe ", "game_exe": "C:/er/eldenring.exe", "games": {"nightreign": {"game_exe": ""}},
         "me3_info_cache": {"profile_dir": "C:/profiles"}}
    )  # fmt: skip
    er = Overrides.from_settings(s, catalog.ELDEN_RING)
    nr = Overrides.from_settings(s, catalog.NIGHTREIGN)
    assert er == Overrides(me3_exe="C:/me3.exe", game_exe="C:/er/eldenring.exe", profiles_dir="C:/profiles")
    assert nr.game_exe == "" and nr.me3_exe == "C:/me3.exe"  # Elden Ring's exe is not Nightreign's


def test_a_setups_own_save_names_are_listed_once(tmp_path):
    loc = Locations(catalog.ELDEN_RING).with_setup_save_names({"standard": "ER0000.sl2", "coop": "ER0000.co3", "x": ""})
    assert loc.save_names() == ["ER0000.sl2", "ER0000.co2", "ER0000.co3"]
    assert Locations(catalog.ELDEN_RING).save_names() == ["ER0000.sl2", "ER0000.co2"]


def test_a_custom_me3_wins_when_it_exists(tmp_path):
    me3 = tmp_path / "me3.exe"
    me3.write_bytes(b"x")
    assert Locations(catalog.ELDEN_RING, Overrides(me3_exe=str(me3))).me3_exe() == me3
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "a.me3").write_text('profileVersion = "v1"\n')
    (profiles / "a-default.me3").write_text('profileVersion = "v1"\n')
    (profiles / "nr.me3").write_text('profileVersion = "v1"\n[[supports]]\ngame = "nightreign"\n')
    loc = Locations(catalog.ELDEN_RING, Overrides(profiles_dir=str(profiles)))
    assert [p.name for p in loc.me3_profiles()] == ["a.me3"]
    assert [p.name for p in loc.me3_profiles(catalog.NIGHTREIGN)] == ["nr.me3"]


def test_the_context_follows_the_game_and_the_setup():
    settings.save_game_settings("nightreign", game_exe="D:/nr/nightreign.exe")
    ctx = create_app()
    assert ctx.game is catalog.ELDEN_RING and ctx.locations.game is catalog.ELDEN_RING
    ctx.note_setup_saves({"standard": "My.sl2"})
    assert "My.sl2" in ctx.locations.save_names()
    loc = ctx.select_game(catalog.NIGHTREIGN)
    assert ctx.game is catalog.NIGHTREIGN and loc.overrides.game_exe == "D:/nr/nightreign.exe"
    assert "My.sl2" not in loc.save_names()  # another game: its setup names its own saves
    assert create_app(catalog.SEKIRO).game is catalog.SEKIRO  # --game decides for this run
