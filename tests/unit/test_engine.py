"""The launcher's own build of a mod that must stay last, from a recipe: the launcher's merges on tiny game files,
and a fake tool for the one step still left to the mod's own tool (the real one never runs in tests). Checked on a
real PC against the mod's installer: the same content."""

import json
import shutil
from pathlib import Path

import pytest
from fakegame import bnd, dcx, files_of, fmg, texts_of
from test_param_merge import pack, rows_of, set_word, vanilla

from roundtable_souls.config import settings
from roundtable_souls.game import locate
from roundtable_souls.mods import backends, engine
from roundtable_souls.mods import rebuild as merge
from roundtable_souls.mods.backends import manifest_refresh
from roundtable_souls.platform import paths as common

RECIPE = json.loads((engine.RECIPES_DIR / "nightreign-revive-lite.json").read_text(encoding="utf-8"))
PROFILE = """profileVersion = "v1"

[[packages]]
id = "body"
path = 'mod/body'

[[packages]]
id = "anims"
path = 'mod/anims'

[[packages]]
id = "off"
path = 'mod/off'
enabled = false

[[packages]]
id = "nightreign-revive"
path = 'NightreignRevive/mod'
load_after = [{ id = "body", optional = true }, { id = "anims", optional = true }]

[[natives]]
path = 'natives/SeamlessCoop/ersc.dll'
load_early = true

[[natives]]
path = 'NightreignRevive/RevivePrototype.dll'
initializer = { function = "NrrInitialize" }
"""
PAYLOAD = [
    "payload/RevivePrototype.dll",
    "payload/ReviveHudBootstrap.dll",
    "payload/audio/revive.wav",
    "payload/ui/base.png",
    "payload/settings/m00_00_00_00.talkesdbnd.dcx",
    "payload/settings/vanilla/script/talk/m00_00_00_00.talkesdbnd.dcx",
    "tools/merge/Assets.exe",
    "tools/defs/SpEffect.xml",
]
ARCHIVES = ["chr/c0000.anibnd.dcx", "chr/c0000.behbnd.dcx", "chr/c0000_a00_hi.anibnd.dcx", "chr/c0000_a00_md.anibnd.dcx",
            "chr/c0000_a00_lo.anibnd.dcx", "sfx/sfxbnd_commoneffects.ffxbnd.dcx"]  # fmt: skip
GAME_CLIPS = {"a000_000.hkx": b"walk", "a000_001.hkx": b"run", "a000_002.hkx": b"roll"}


def game_files() -> dict[str, bytes]:
    files = {rel: dcx(bnd(GAME_CLIPS)) for rel in ARCHIVES}
    for lang in ("engus", "rusru"):
        files[f"msg/{lang}/menu_dlc02.msgbnd.dcx"] = dcx(
            bnd({"EventTextForTalk.fmg": fmg({1000: "Rest", 1001: None}), "Other.fmg": fmg({5: "x"})})
        )
    return files


class Revive:
    """A profile folder with a Revive-like mod: its download (setup folder), an installed build, packages before it,
    Seamless, and a game; the merge tool is faked (each output names what it merged)."""

    def __init__(self, tmp_path, monkeypatch):
        self.base = tmp_path / "profiles" / "er"
        self.game = tmp_path / "Game"
        self.game.mkdir(parents=True)
        (self.game / "regulation.bin").write_bytes(vanilla())
        (self.game / "eldenring.exe").write_bytes(b"x")
        import fakegame

        fakegame.game(monkeypatch, game_files())
        monkeypatch.setattr(locate, "installed_dir", lambda _game: self.game)
        monkeypatch.setattr(common, "exe_running", lambda _exe: False)
        self.setup = self.base / ".nightreign-revive-setup"
        for f in PAYLOAD:
            (self.setup / f).parent.mkdir(parents=True, exist_ok=True)
            (self.setup / f).write_bytes(f"stock {f}".encode())
        (self.setup / "payload/RevivePrototype.ini").write_text("[Coop]\nEnabled=1\n[UI]\nLanguage=auto\n")
        for rel in ARCHIVES:  # the mod's copies: the game's with one clip of its own added
            (self.setup / "payload/mod" / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.setup / "payload/mod" / rel).write_bytes(dcx(bnd({**GAME_CLIPS, "revive.hkx": b"revive"})))
        (self.setup / "payload/mod/regulation.bin").write_bytes(pack({"EquipParamWeapon": set_word(2000, 1, 77)}))
        (self.setup / "payload/settings/engus.json").write_text('{"99002000": "Revive: session settings"}')
        (self.setup / "payload/settings/rusru.json").write_text('{"99002000": "Revive ru"}', encoding="utf-8")
        for lang in ("engus", "rusru"):
            (self.setup / f"payload/settings/vanilla/msg/{lang}").mkdir(parents=True)
        (self.setup / "payload/mod/action/script").mkdir(parents=True)
        (self.setup / "payload/mod/action/script/c0000.hks").write_text(
            "-- vanilla\nfunction Update() end\n-- Wrap the current mod's Update;\nrevive stock wrapper\n"
        )
        (self.setup / "installer").mkdir()
        (self.setup / "installer/revive.hks").write_text("-- revive extension\n")
        (self.setup / "installer/installer.py").write_text("# the mod's installer")
        (self.setup / "tools/python").mkdir(parents=True)
        (self.setup / "tools/python/python.exe").write_bytes(b"py")
        (self.setup / "edition.json").write_text('{"version": "0.1.33-rc3", "edition": "LITE"}')
        (self.setup / "revive-maintenance.json").write_text('{"protocol": 1, "version": "0.1.33-rc3"}')
        body = self.base / "mod" / "body"
        (body / "parts").mkdir(parents=True)
        anims = self.base / "mod" / "anims"
        (anims / "chr").mkdir(parents=True)
        # the animation mod changes one clip and removes another
        (anims / "chr/c0000_a00_hi.anibnd.dcx").write_bytes(
            dcx(bnd({"a000_000.hkx": b"sekiro walk", "a000_002.hkx": b"roll"}))
        )
        (anims / "regulation.bin").write_bytes(pack({"EquipParamWeapon": set_word(1000, 0, 55)}))
        (anims / "msg/engus").mkdir(parents=True)
        (anims / "msg/engus/menu_dlc02.msgbnd.dcx").write_bytes(
            dcx(bnd({"EventTextForTalk.fmg": fmg({1000: "Rest here", 1001: None}), "Other.fmg": fmg({5: "x"})}))
        )
        (anims / "action/script").mkdir(parents=True)
        (anims / "action/script/c0000.hks").write_bytes(b"-- anims script\r\nfunction Update() end\r\n")
        (self.base / "mod" / "off").mkdir()
        (self.base / "natives/SeamlessCoop").mkdir(parents=True)
        (self.base / "natives/SeamlessCoop/ersc.dll").write_bytes(b"d")
        self.own = self.base / "NightreignRevive"
        (self.own / "mod").mkdir(parents=True)
        (self.own / "mod/regulation.bin").write_bytes(b"OLD BUILD")
        (self.own / "RevivePrototype.dll").write_bytes(b"old")
        (self.own / "RevivePrototype.ini").write_text("[Coop]\nEnabled=0\n")
        (self.own / "installation.json").write_text(
            json.dumps(
                {
                    "version": "0.1.33-rc3",
                    "edition": "LITE",
                    "refreshProtocol": 1,
                    "maintenance": str(self.setup),
                    "game": str(self.game / "eldenring.exe"),
                    "seamless": str(self.base / "natives/SeamlessCoop/ersc.dll"),
                    "sources": [],
                }
            )
        )
        self.profile = self.base / "p.me3"
        self.profile.write_text(PROFILE, encoding="utf-8")
        self.calls = []
        monkeypatch.setattr(engine, "run_tool", self.fake_tool)

    def fake_tool(self, exe, args, env, timeout, cwd):
        self.calls.append((args[0], Path(args[1]).name if len(args) > 1 else "", env))
        out = Path(args[3] if args[0] != "merge-archive" else args[4])
        if args[0] in ("merge-regulation", "merge-grace", "merge-menu-text"):
            out = Path(args[3])
        src = Path(args[1] if args[0] != "merge-archive" else args[2])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"MERGED " + args[0].encode() + b" " + src.read_bytes())
        return 0, f"merged {out.name}"

    def build(self, log=lambda s: None):
        recipe, version, _ = engine.match(self.setup)
        return engine.build(self.profile, self.own / "mod", self.setup, recipe, version, log)


@pytest.fixture
def world(tmp_path, monkeypatch):
    return Revive(tmp_path, monkeypatch)


def test_the_bundled_recipe_is_valid_and_fits_the_download(world):
    assert engine.validate(RECIPE) == []
    recipe, version, why = engine.match(world.setup)
    assert recipe["id"] == "nightreign-revive-lite" and version == "0.1.33-rc3" and why is None


def test_a_newer_version_is_not_built_and_says_why(world):
    (world.setup / "revive-maintenance.json").write_text('{"protocol": 1, "version": "0.2.0"}')
    recipe, version, why = engine.match(world.setup)
    assert recipe is None and version == "0.2.0" and "newer than the launcher knows" in why


def test_another_edition_is_not_matched(world):
    (world.setup / "edition.json").write_text('{"edition": "REFORGED"}')
    assert engine.match(world.setup)[0] is None


def test_the_launcher_merges_the_mods_files_with_the_packages_before_it(world):
    world.build()
    own = world.own
    # the animation mod's change and removal, and the mod's own clip, in one archive
    assert files_of((own / "mod/chr/c0000_a00_hi.anibnd.dcx").read_bytes()) == {
        "a000_000.hkx": b"sekiro walk",
        "a000_002.hkx": b"roll",
        "revive.hkx": b"revive",
    }
    # no package ships this one: the mod's own copy as it is
    behavior = world.setup / "payload/mod/chr/c0000.behbnd.dcx"
    assert (own / "mod/chr/c0000.behbnd.dcx").read_bytes() == behavior.read_bytes()
    # parameters: both packs' rows
    rows = rows_of((own / "mod/regulation.bin").read_bytes(), "EquipParamWeapon")
    word = lambda r, i: int.from_bytes(r.data[i * 4 : i * 4 + 4], "little")  # noqa: E731
    assert word(rows[1000], 0) == 55 and word(rows[2000], 1) == 77
    # the grace menu is still the mod's own tool's job
    assert [c[0] for c in world.calls] == ["merge-grace"]
    assert world.calls[0][2]["NRR_GAME_DIRECTORY"] == str(world.game)
    assert (own / "audio/revive.wav").is_file() and (own / "ui/base.png").is_file()
    assert (own / "RevivePrototype.dll").read_bytes() == b"stock payload/RevivePrototype.dll"


def test_the_menu_text_keeps_the_packages_text_and_adds_the_mods_in_each_language(world):
    world.build()
    en = texts_of((world.own / "mod/msg/engus/menu_dlc02.msgbnd.dcx").read_bytes(), "EventTextForTalk.fmg")
    ru = texts_of((world.own / "mod/msg/rusru/menu_dlc02.msgbnd.dcx").read_bytes(), "EventTextForTalk.fmg")
    assert en == {1000: "Rest here", 1001: None, 99002000: "Revive: session settings"}
    assert ru == {1000: "Rest", 1001: None, 99002000: "Revive ru"}


def test_the_script_is_the_last_packages_with_the_mods_text_appended(world):
    world.build()
    hks = (world.own / "mod/action/script/c0000.hks").read_bytes()
    assert hks == b"-- anims script\nfunction Update() end\n\n-- revive extension\n"  # line endings as the installer's


def test_without_a_packages_script_the_downloads_base_is_used(world):
    shutil.rmtree(world.base / "mod/anims/action")
    world.build()
    hks = (world.own / "mod/action/script/c0000.hks").read_text()
    assert hks == "-- vanilla\nfunction Update() end\n\n-- revive extension\n"


def test_a_package_that_already_contains_it_is_refused(world):
    (world.base / "mod/anims/action/script/c0000.hks").write_text("local NrrOriginalUpdate = Update\n")
    with pytest.raises(engine.EngineError, match="already contains"):
        world.build()
    assert (world.own / "mod/regulation.bin").read_bytes() == b"OLD BUILD"  # the build in place is unchanged


def test_the_players_settings_are_kept_and_new_keys_added(world):
    world.build()
    ini = (world.own / "RevivePrototype.ini").read_text()
    assert "Enabled=0" in ini and "Enabled=1" not in ini  # the player's value
    assert "[UI]\nLanguage=auto" in ini  # a section the new version adds


def test_the_manifest_lists_the_sources_and_keeps_the_rest(world):
    world.build()
    m = json.loads((world.own / "installation.json").read_text())
    assert m["edition"] == "LITE" and m["refreshProtocol"] == 1 and m["builtBy"].startswith("Roundtable Souls")
    paths = [Path(r["path"]).name for r in m["sources"]]
    assert paths[0] == "regulation.bin" and paths[-1] == "p.me3" and "c0000.hks" in paths


def test_the_previous_build_is_kept_and_undo_swaps_it_back(world):
    from roundtable_souls.mods import undo

    out = world.build()
    assert (out["previous"] / "mod/regulation.bin").read_bytes() == b"OLD BUILD"
    u = {"type": "rebuild", "profile": str(world.profile), "tool_restore": str(out["restore"])}
    assert undo.available(u)
    undo.run(u, lambda s: None)
    assert (world.own / "mod/regulation.bin").read_bytes() == b"OLD BUILD"
    undo.run({**u, "redo": True}, lambda s: None)
    assert (world.own / "mod/regulation.bin").read_bytes() != b"OLD BUILD"


def test_a_failed_merge_leaves_the_build_in_place_and_no_staging(world, monkeypatch):
    monkeypatch.setattr(engine, "run_tool", lambda *a, **k: (3, "could not read the archive"))
    with pytest.raises(engine.EngineError, match="exit 3"):
        world.build()
    assert (world.own / "mod/regulation.bin").read_bytes() == b"OLD BUILD"
    assert not list(world.base.glob(".NightreignRevive.building-*"))


def test_a_damaged_file_stops_the_build_with_its_name(world):
    (world.base / "mod/anims/chr/c0000_a00_hi.anibnd.dcx").write_bytes(b"DCX\0 broken")
    with pytest.raises(engine.EngineError, match="c0000_a00_hi"):
        world.build()
    assert (world.own / "mod/regulation.bin").read_bytes() == b"OLD BUILD"
    assert not list(world.base.glob(".NightreignRevive.building-*"))


def test_seamless_is_required(world):
    world.profile.write_text(
        PROFILE.replace(
            "path = 'natives/SeamlessCoop/ersc.dll'", "path = 'natives/SeamlessCoop/ersc.dll'\nenabled = false"
        )
    )
    with pytest.raises(engine.EngineError, match="Seamless"):
        world.build()


def test_the_inputs_are_only_read(world):
    def snapshot():
        return {p: p.read_bytes() for p in (world.base / "mod").rglob("*") if p.is_file()} | {
            p: p.read_bytes() for p in world.setup.rglob("*") if p.is_file()
        }

    before = snapshot()
    profile_before = world.profile.read_bytes()
    world.build()
    assert snapshot() == before and world.profile.read_bytes() == profile_before


def test_a_rebuild_uses_the_engine_only_with_the_switch_on(world, monkeypatch):
    ran = []
    monkeypatch.setattr(backends.Tool, "run", lambda self, log: ran.append(self.recipe.engine is not None))
    layer = next(l for l in merge.layers(world.profile) if l["name"] == "nightreign-revive")
    r = manifest_refresh.recipe(world.profile, layer)
    assert r is not None and r.engine is None and r.command  # off: the mod's installer runs
    settings.save_settings(build_merges=True)
    r = manifest_refresh.recipe(world.profile, layer)
    assert r.engine is not None and r.label == "the launcher's build of nightreign-revive"
    assert (
        "builds nightreign" in backends.Tool(r).describe().lower() or "Nightreign Revive" in backends.Tool(r).describe()
    )


def test_a_whole_rebuild_through_the_engine_is_current_and_can_be_undone(world):
    settings.save_settings(build_merges=True)
    tool = merge.find_backend(world.profile)
    merge.approve(tool)
    out = merge.rebuild(world.profile, lambda s: None)
    assert out["undo"]["tool_restore"] and out["undo"]["tool_restore"].endswith("restore.json")
    assert merge.health(world.profile)["state"] == "current"
    assert world.profile.read_text(encoding="utf-8") == PROFILE  # never rewritten


def test_a_second_recipe_needs_no_code(world, tmp_path, monkeypatch):
    """Nothing about Revive is in the engine: a made-up mod with other names builds from its recipe alone."""
    other = tmp_path / "recipes"
    other.mkdir()
    toy = {
        "recipe": 1,
        "id": "toy",
        "label": "Toy",
        "match": {"files": ["toy.json"]},
        "tool": {"path": "bin/merge.exe"},
        "output": {"mod": "mod"},
        "steps": [
            {"do": "copy", "from": "payload/toy.dll", "to": "toy.dll"},
            {
                "do": "tool",
                "file": "regulation.bin",
                "missing": "game",
                "args": ["merge-regulation", "{source}", "{setup}/x", "{out}"],
            },
        ],
    }
    (other / "toy.json").write_text(json.dumps(toy))
    monkeypatch.setattr(engine, "RECIPES_DIR", other)
    setup = tmp_path / "toysetup"
    (setup / "payload").mkdir(parents=True)
    (setup / "toy.json").write_text("{}")
    (setup / "payload/toy.dll").write_bytes(b"toy")
    recipe, version, _ = engine.match(setup)
    assert recipe["id"] == "toy"
    target = world.base / "Toy" / "mod"
    target.mkdir(parents=True)
    world.profile.write_text(PROFILE + "\n[[packages]]\nid = \"toy\"\npath = 'Toy/mod'\n")
    engine.build(world.profile, target, setup, recipe, version, lambda s: None)
    assert (world.base / "Toy/toy.dll").read_bytes() == b"toy"
    assert (target / "regulation.bin").read_bytes().startswith(b"MERGED merge-regulation")


def test_merge_ini_adds_only_what_is_new():
    mine = "; mine\r\n[Coop]\r\nEnabled=0\r\n[Input]\r\nKeyboardEnabled=0\r\n"
    default = "[Coop]\nEnabled=1\nRescue=60\n[Input]\nKeyboardEnabled=1\n[New]\nX=1\n"
    out = engine.merge_ini(mine, default)
    assert out.startswith("; mine\r\n[Coop]\r\nEnabled=0\r\nRescue=60\r\n[Input]\r\nKeyboardEnabled=0\r\n")
    assert out.endswith("[New]\r\nX=1\r\n")
    assert engine.merge_ini(mine, "[Coop]\nEnabled=1\n") == mine  # nothing new: byte for byte
