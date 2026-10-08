"""Overhaul configs (data/overhauls/*.toml): the shipped Nightreign Revive config builds without anything of the
mod's (since S3b), a local file replaces or adds one, a bad one is left out and said why, and the Play page's detection and the offline
launch's strip read the configs and still do what they did."""

import json
from pathlib import Path

from roundtable_souls import overhauls
from roundtable_souls.game import catalog as games
from roundtable_souls.game.locate import Locations, Overrides
from roundtable_souls.overhauls import config as overhaul_config
from roundtable_souls.services import play

TOY = """overhaul = 1
id = "toy"
label = "Toy Overhaul"
short_label = "Toy"
game = "eldenring"

[recognise]
folder = "ToyOverhaul"
manifest = "toy-install.json"
mod_ids = ["toy-overhaul"]
profile_marks = ["toyoverhaul"]
"""


def local(name: str, text: str) -> Path:
    folder = overhauls.local_dir()
    assert folder is not None
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")
    return folder / name


def test_the_shipped_config_runs_nothing_of_the_mods():
    (revive,) = overhauls.load()
    assert (revive.id, revive.game, revive.short_label) == ("nightreign-revive", "eldenring", "Revive")
    (lite,) = [revive.recipe(b) for b in revive.builds]
    assert lite["id"] == "nightreign-revive-lite" and lite["recipe"] == overhauls.RECIPE_VERSION and "tool" not in lite
    grace = [s for s in lite["steps"] if s.get("file") == "script/talk/m00_00_00_00.talkesdbnd.dcx"]
    assert [s["do"] for s in grace] == ["merge"]  # the ESD rule, not the mod's tool
    assert not any("Assets.exe" in json.dumps(s) for s in lite["steps"]) and "Assets.exe" not in json.dumps(lite)
    assert overhauls.problems() == []


def test_the_published_schema_is_the_models():
    assert json.loads(overhauls.schema_path().read_text(encoding="utf-8")) == overhauls.schema()


def test_configs_are_per_game():
    assert [o.id for o in overhauls.load("eldenring")] == ["nightreign-revive"]
    assert overhauls.load("nightreign") == []


def test_a_local_config_replaces_the_shipped_one_with_its_id_and_adds_new_ones():
    shipped = (overhaul_config.SHIPPED_DIR / "nightreign-revive.toml").read_text(encoding="utf-8")
    local("mine.toml", shipped.replace('short_label = "Revive"', 'short_label = "NRR"'))
    local("toy.toml", TOY)
    by_id = {o.id: o for o in overhauls.load()}
    assert sorted(by_id) == ["nightreign-revive", "toy"]
    assert by_id["nightreign-revive"].short_label == "NRR" and by_id["toy"].builds == []


def test_a_bad_config_is_left_out_and_problems_say_why():
    bad = local("bad.toml", TOY.replace("overhaul = 1", "overhaul = 2"))
    broken = local("broken.toml", "id = [")
    assert [o.id for o in overhauls.load()] == ["nightreign-revive"]
    said = overhauls.problems()
    assert len(said) == 2 and any(str(bad) in p for p in said) and any(str(broken) in p for p in said)


def er_world(tmp_path):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "er.me3").write_text('profileVersion = "v1"\n', encoding="utf-8")
    game = tmp_path / "Game"
    game.mkdir()
    (game / "eldenring.exe").write_bytes(b"x")
    loc = Locations(games.ELDEN_RING, Overrides(game_exe=str(game / "eldenring.exe"), profiles_dir=str(profiles)))
    return loc, profiles, game


def install(folder: Path, manifest: str, profile: Path) -> Path:
    folder.mkdir(parents=True)
    (folder / manifest).write_text(json.dumps({"profile": str(profile)}), encoding="utf-8")
    return folder / manifest


def test_play_finds_each_overhauls_installations_beside_the_profiles_and_in_the_game_folder(tmp_path):
    loc, profiles, game = er_world(tmp_path)
    beside = install(profiles / "NightreignRevive", "installation.json", profiles / "revive.me3")
    standalone = install(game / "NightreignRevive", "installation.json", game / "revive.me3")
    toy = install(profiles / "ToyOverhaul", "toy-install.json", profiles / "toy.me3")
    found = play.discover(None, loc)
    assert [(s.kind, Path(s.source)) for s in found] == [
        ("me3", profiles / "er.me3"),
        ("revive", beside),
        ("revive", standalone),
    ]
    local("toy.toml", TOY)
    assert ("revive", toy) in [(s.kind, Path(s.source)) for s in play.discover(None, loc)]
    assert play.setup_from_path(toy, loc).kind == "revive"
    nightreign = Locations(games.NIGHTREIGN, Overrides(profiles_dir=str(profiles)))
    assert play.discover(None, nightreign) == [] and play.setup_from_path(beside, nightreign) is None


def test_the_play_summary_names_the_overhauls_a_setup_includes(tmp_path):
    loc, profiles, _game = er_world(tmp_path)
    plain = play.Setup("me3", profiles / "er.me3", loc=loc)
    assert play.overhauls_in(plain) == []
    launched = install(tmp_path / "elsewhere" / "NightreignRevive", "installation.json", tmp_path / "x.me3")
    assert play.overhauls_in(play.setup_from_path(launched, loc)) == ["Revive"]
    for entry in (
        '[[packages]]\nid = "nightreign-revive"\npath = "x"\n',
        "[[natives]]\npath = 'a/RevivePrototype.dll'\n",
    ):
        (profiles / "with.me3").write_text('profileVersion = "v1"\n' + entry, encoding="utf-8")
        assert play.overhauls_in(play.Setup("me3", profiles / "with.me3", loc=loc)) == ["Revive"]
    (profiles / "NightreignRevive").mkdir()
    assert play.overhauls_in(plain) == ["Revive"]


def test_the_offline_strip_uses_each_configs_profile_marks():
    revive = "profileVersion = \"v1\"\n\n[[natives]]\npath = 'NightreignRevive/ReviveHudBootstrap.dll'\n"
    toy = 'profileVersion = "v1"\n\n[[packages]]\nid = "toy-overhaul"\npath = \'ToyOverhaul/mod\'\n'
    assert "# path = 'NightreignRevive/ReviveHudBootstrap.dll'" in play.offline_profile_text(revive, strip_revive=True)
    assert '\nid = "toy-overhaul"' in play.offline_profile_text(toy, strip_revive=True)
    local("toy.toml", TOY)
    assert '# id = "toy-overhaul"' in play.offline_profile_text(toy, strip_revive=True)
    assert '\nid = "toy-overhaul"' in play.offline_profile_text(toy)


def test_a_config_with_the_old_seamless_key_is_left_out_and_says_where_it_went():
    shipped = (overhaul_config.SHIPPED_DIR / "nightreign-revive.toml").read_text(encoding="utf-8")
    old = shipped.replace("[builds.install]\n", '[builds.install]\nseamless = { dll = "ersc.dll" }\n')
    bad = local("old.toml", old.replace('id = "nightreign-revive"', 'id = "old-revive"', 1))
    assert "old-revive" not in [o.id for o in overhauls.load()]
    (said,) = overhauls.problems()
    assert said.startswith(f"{bad}: builds.0.install.seamless: Extra inputs are not permitted")
    assert said.endswith("(seamless: since 3.20 a required mod is listed in the build's requires)")


def test_a_config_with_the_old_script_append_step_is_left_out_and_says_where_it_went():
    shipped = (overhaul_config.SHIPPED_DIR / "nightreign-revive.toml").read_text(encoding="utf-8")
    old = shipped.replace('do = "hook"', 'do = "script_append"').replace('id = "nightreign-revive"', 'id = "x"', 1)
    local("old.toml", old)
    assert "x" not in [o.id for o in overhauls.load()]
    (said,) = overhauls.problems()
    assert said.endswith(
        '(script_append: since 3.20 a script fragment is added with do = "hook" (append is fragment, refuse is markers))'
    )
