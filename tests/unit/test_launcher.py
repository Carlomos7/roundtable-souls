"""The pure parts of core: ini reading/writing, JSON share text, presets, setup discovery."""

import json
from pathlib import Path

import pytest

from roundtable_souls.config.settings import LauncherSettings
from roundtable_souls.game.locate import Locations, Overrides
from roundtable_souls.platform import paths
from roundtable_souls.services import coop as coop_service
from roundtable_souls.services import mods as mods_service
from roundtable_souls.services import play as g
from roundtable_souls.services import saves as saves_service
from support import er

INI = (
    "[GAMEPLAY]\r\n; Invaders join uninvited.  0=FALSE  1=TRUE\r\nallow_invaders = 1\r\n\r\n"
    "; 0 = Normal | 1 = None | 2 = Display player ping | 3 = Display player soul level\r\noverhead_player_display = 0\r\n\r\n"
    "; Game volume before initial save load. 0 = MUTE 10 = MAX\r\ndefault_boot_master_volume = 5\r\n\r\n[SCALING]\r\n\r\n; Amount of enemy health\r\nenemy_health_scaling = 35\r\n\r\n"
    "enemy_damage_scaling = 0\r\nenemy_posture_scaling = 15\r\nboss_health_scaling = 100\r\nboss_damage_scaling = 0\r\nboss_posture_scaling = 20\r\n\r\n"
    "[PASSWORD]\r\n\r\n; Session password\r\ncooppassword = secret1\r\n"
)


def ini(tmp_path):
    p = tmp_path / "ersc_settings.ini"
    p.write_bytes(INI.encode())
    return p


def test_password_read_write_keeps_layout_and_crlf(tmp_path):
    p = ini(tmp_path)
    before = p.read_bytes()
    assert g.read_password(p) == "secret1"
    coop_service.write_password(p, "other")
    assert g.read_password(p) == "other"
    assert b"\r\n" in p.read_bytes() and p.read_bytes().count(b"\r\n") == before.count(b"\r\n")
    coop_service.write_password(p, "secret1")
    assert p.read_bytes() == before
    assert (tmp_path / "ersc_settings.ini.bak").exists()  # one backup of the previous version


def test_scaling_roundtrip_changes_only_its_lines(tmp_path):
    p = ini(tmp_path)
    before = p.read_bytes()
    assert (
        g.read_scaling(p) == coop_service.SCALING_PRESETS["Seamless default"]
        and g.preset_of(g.read_scaling(p)) == "Seamless default"
    )
    assert (
        coop_service.write_keys(
            p, dict(zip(coop_service.SCALING_KEYS, coop_service.SCALING_PRESETS["Party of 3 (Nightreign rule)"]))
        )
        == []
    )
    assert g.preset_of(g.read_scaling(p)) == "Party of 3 (Nightreign rule)"
    changed = [l for a, l in zip(before.decode().splitlines(), p.read_text().splitlines()) if a != l]
    assert len(changed) == 3
    coop_service.write_keys(p, dict(zip(coop_service.SCALING_KEYS, coop_service.SCALING_PRESETS["Seamless default"])))
    assert p.read_bytes() == before


def test_unknown_key_is_reported_not_appended(tmp_path):
    p = ini(tmp_path)
    before = p.read_bytes()
    assert coop_service.write_keys(p, {"made_up": "1"}) == ["made_up"]
    assert p.read_bytes() == before


def test_share_text_roundtrip_and_validation(tmp_path):
    p = ini(tmp_path)
    text = coop_service.export_text(p)
    flat = coop_service.parse_settings_json(text)
    assert flat["cooppassword"] == "secret1" and flat["boss_health_scaling"] == "100" and flat["allow_invaders"] == "1"
    assert coop_service.parse_settings_json('{"cooppassword": "x", "SCALING": {"boss_health_scaling": "75"}}') == {
        "cooppassword": "x",
        "boss_health_scaling": "75",
    }
    for bad in ("nope", "[1]", "{}", '{"format": "x"}'):
        with pytest.raises((ValueError, json.JSONDecodeError)):
            coop_service.parse_settings_json(bad)
    changes, unknown = coop_service.plan_import(
        p, {"cooppassword": "friend", "boss_health_scaling": "100", "bogus": "1"}
    )
    assert changes == {"cooppassword": ("secret1", "friend")} and unknown == ["bogus"]


def test_logo_follows_theme_unless_locked():
    assert g.logo_kind(True, "auto") == "dark" and g.logo_kind(False, "auto") == "light"
    assert g.logo_kind(True, "light") == "light" and g.logo_kind(False, "dark") == "dark"
    assert g.logo_path(True, "auto").name == "logo-dark.png"
    assert g.logo_path(False, "auto").name == "logo-light.png"
    assert g.TITLE == "Roundtable Souls" and g.EXE_NAME == "RoundtableSouls"


def test_save_findings_on_unreadable(tmp_path):
    missing = tmp_path / "nope.sl2"
    findings = saves_service.save_findings(missing, loc=er())
    assert findings and findings[0]["code"] == "read" and findings[0]["level"] == "error"
    junk = tmp_path / "junk.sl2"
    junk.write_bytes(b"not a save")
    info = g.save_info(junk, loc=er())
    assert info["findings"][0]["code"] == "layout" and info["error"]


def test_health_report_and_clean_gate(tmp_path):
    missing = tmp_path / "nope.co2"
    text = saves_service.health_report(missing, loc=er())
    assert "Roundtable Souls save report" in text and "ERROR" in text
    assert not g.save_analyze.findings_are_clean([{"level": "warn", "code": "x", "title": "t", "detail": ""}])
    assert g.save_analyze.findings_are_clean(
        [
            {"level": "ok", "code": "regulation", "title": "t", "detail": ""},
            {"level": "ok", "code": "layout", "title": "t", "detail": ""},
        ]
    )


def test_known_item_ids_bundled():
    ids = g.save_analyze.known_item_ids()
    assert len(ids) > 1000
    # Lordsworn's Straight Sword base id is a common vanilla weapon row
    assert any((i & 0xF0000000) == 0 for i in ids)


def test_convert_co2_refuses_dirty(tmp_path, monkeypatch):
    p = tmp_path / "ER0000.co2"
    p.write_bytes(b"not a save")
    monkeypatch.setattr(paths, "exe_running", lambda _exe: False)
    with pytest.raises(RuntimeError) as exc:
        saves_service.convert_co2_to_sl2(p, loc=er())
    assert "clean" in str(exc.value).lower() or "Findings" in str(exc.value)


def test_dead_shells_count_is_int():
    assert isinstance(saves_service.dead_shells_count(loc=er()), int) and saves_service.dead_shells_count(loc=er()) >= 0


def test_atomic_write_replaces_and_backs_up(tmp_path):
    p = tmp_path / "f.txt"
    g.atomic_write(p, "one")
    g.atomic_write(p, "two", backup=True)
    assert (
        p.read_text() == "two"
        and (tmp_path / "f.txt.bak").read_text() == "one"
        and not (tmp_path / "f.txt.tmp").exists()
    )


def test_ersc_ini_found_relative_to_profile(tmp_path):
    prof = tmp_path / "my.me3"
    (tmp_path / "natives" / "SeamlessCoop").mkdir(parents=True)
    (tmp_path / "natives" / "SeamlessCoop" / "ersc_settings.ini").write_text("cooppassword = a\n")
    prof.write_text("[[natives]]\npath = 'natives/SeamlessCoop/ersc.dll'\n")
    assert coop_service.ersc_ini_for(str(prof)) == tmp_path / "natives" / "SeamlessCoop" / "ersc_settings.ini"
    other = tmp_path / "plain.me3"
    other.write_text("[[packages]]\npath = 'mod'\n")
    assert coop_service.ersc_ini_for(str(other)) is None


def test_setup_label_is_the_profile_name(tmp_path):
    p = tmp_path / "any.me3"
    p.write_text("")
    assert g.Setup("me3", p, loc=er()).label == "any.me3"
    assert (
        g.Setup("revive", p, source=tmp_path / "installation.json", loc=er()).label == "any.me3  ·  installation.json"
    )


def test_places_are_folders_or_none(tmp_path):
    pl = g.places(None, er())
    assert set(pl) == {"me3", "game", "saves", "profile", "mods"} and pl["profile"] is None and pl["mods"] is None
    for k in ("me3", "game", "saves"):
        assert pl[k] is None or Path(pl[k]).is_dir()
    prof = tmp_path / "p.me3"
    prof.write_text('profileVersion = "v1"\n[[packages]]\npath = "mod/x"\n', encoding="utf-8")
    (tmp_path / "mod" / "x").mkdir(parents=True)
    pl = g.places(g.Setup("me3", prof, loc=er()), er())
    assert pl["profile"] == tmp_path and pl["mods"] == tmp_path / "mod"


def test_location_overrides_reach_the_tools_layer(tmp_path, monkeypatch):
    me3 = tmp_path / "me3.exe"
    me3.write_bytes(b"x")
    game = tmp_path / "g" / "eldenring.exe"
    game.parent.mkdir()
    game.write_bytes(b"x")
    prof = tmp_path / "profiles"
    prof.mkdir()
    (prof / "a.me3").write_text('profileVersion = "v1"\n')
    ER = g.games.ELDEN_RING
    loc = Locations.from_settings(
        LauncherSettings.from_raw({"me3_path": str(me3), "game_exe": str(game), "me3_profile_dir": str(prof)}), ER
    )
    assert loc.me3_exe() == me3 and loc.game_dir() == game.parent and loc.me3_profiles_dir() == prof
    assert [p.name for p in loc.me3_profiles()] == ["a.me3"] and loc.game_exe_name() == "eldenring.exe"
    s = g.Setup("me3", prof / "a.me3", loc=loc)
    assert s.launch_exe() == str(game) and not s.problems()
    cached = Locations.from_settings(LauncherSettings.from_raw({"me3_info_cache": {"profile_dir": str(prof)}}), ER)
    assert cached.overrides.in_effect()["profile_dir"] == str(prof)
    missing = Locations.from_settings(LauncherSettings.from_raw({"me3_path": str(tmp_path / "missing.exe")}), ER)
    assert missing.overrides.in_effect()["me3"] and missing.me3_exe() != tmp_path / "missing.exe"
    assert Locations.from_settings(LauncherSettings.from_raw({}), ER).overrides == Overrides()


def test_setup_from_installation_json(tmp_path):
    inst = tmp_path / "NightreignRevive" / "installation.json"
    inst.parent.mkdir()
    inst.write_text(
        json.dumps(
            {
                "profile": str(tmp_path / "revive.me3"),
                "me3": str(tmp_path / "me3.exe"),
                "game": str(tmp_path / "eldenring.exe"),
            }
        )
    )
    s = g.setup_from_path(str(inst), er())
    assert s and s.kind == "revive" and s.exe.endswith("eldenring.exe")
    assert any("missing" in x for x in s.problems())  # nothing exists in tmp, so it must say so
    assert g.setup_from_path(str(tmp_path / "nothing.txt"), er()) is None


def test_settings_meta_types_from_comments(tmp_path):
    meta = coop_service.read_settings_meta(ini(tmp_path))
    by = {i["key"]: i for sec in meta for i in sec["items"]}
    assert [sec["section"] for sec in meta] == ["GAMEPLAY", "SCALING", "PASSWORD"]
    assert (
        by["allow_invaders"]["kind"] == "bool"
        and by["allow_invaders"]["value"] == "1"
        and "Invaders" in by["allow_invaders"]["desc"]
    )
    assert by["overhead_player_display"]["kind"] == "choice" and by["overhead_player_display"]["extra"][2] == (
        2,
        "Display player ping",
    )
    assert by["default_boot_master_volume"]["kind"] == "int" and by["default_boot_master_volume"]["extra"] == (0, 10)
    assert by["enemy_health_scaling"]["kind"] == "int" and by["enemy_health_scaling"]["extra"] == (0, 500)
    assert (
        by["cooppassword"]["kind"] == "password" and coop_service.label_of("skip_splash_screens") == "Skip intro logos"
    )
    assert coop_service.label_of("allow_invaders") == "Invaders"
    assert coop_service.choice_label("overhead_player_display", 2, "Display player ping") == "Ping"
    _label, blurb, help_text = coop_service.setting_face("allow_invaders", "Invaders join.  0=FALSE  1=TRUE")
    assert "FALSE" not in blurb and "0=" not in help_text and "invade" in help_text.lower()
    _label, _blurb, fallback = coop_service.setting_face("made_up_flag", "Does a thing.  0=FALSE  1=TRUE")
    assert fallback == "Does a thing." and coop_service.label_of("made_up_flag") == "Made up flag"


PROFILE = (
    "# notes\r\nprofileVersion = \"v1\"\r\n\r\n[[packages]]\r\nid = \"flora\"\r\n# enabled = false\r\n# path = 'mod/wrong'\r\npath = 'mod/flora'\r\n\r\n"
    "# DISABLED. old armor\r\n# [[packages]]\r\n# id = \"fa-pu\"\r\n# path = 'mod/fa-pu'\r\n\r\n"
    "[[natives]]\r\npath = 'natives/SeamlessCoop/ersc.dll'\r\nload_early = true\r\n\r\n"
    "[[natives]]\r\nenabled = false\r\npath = 'natives/UnlockTheFps/UnlockTheFps.dll'\r\n\r\n"
    '[[packages]]\r\nid = "nightreign-revive"\r\npath = \'NightreignRevive/mod\'\r\nload_after = [\r\n  { id = "flora", optional = true },\r\n]\r\n'
)


def test_profile_mods_are_the_ones_me3_loads(tmp_path):
    p = tmp_path / "profile.me3"
    p.write_bytes(PROFILE.encode())
    mods = mods_service.read_profile_mods(p)
    assert [(m["kind"], m["id"], m["path"]) for m in mods] == [
        ("package", "flora", "mod/flora"),
        ("native", "ersc.dll", "natives/SeamlessCoop/ersc.dll"),
        ("package", "nightreign-revive", "NightreignRevive/mod"),
    ]
    assert mods_service.set_profile_mod_enabled(p, 1, False)
    assert [m["id"] for m in mods_service.read_profile_mods(p)] == ["flora", "nightreign-revive"]
    assert (tmp_path / "profile.me3.bak").is_file()


def test_offline_profile_disables_only_seamless():
    text = (
        "start_online = false\n\n[[packages]]\nid = \"mods\"\npath = 'mod'\n\n# camera\n[[natives]]\npath = 'natives/bettercamera.dll'\n\n"
        "# Seamless Co-op. Must load early.\n[[natives]]\npath = 'natives/SeamlessCoop/ersc.dll'\nload_early = true\n\n[[natives]]\npath = 'natives/other.dll'\n"
    )
    out = g.offline_profile_text(text)
    assert "# path = 'natives/SeamlessCoop/ersc.dll'" in out and "# load_early = true" in out
    assert (
        "\npath = 'natives/bettercamera.dll'" in out and "\npath = 'natives/other.dll'" in out and "path = 'mod'" in out
    )
    assert out.count("[[natives]]") == 3 and out.startswith("# OFFLINE COPY")
    assert "Revive disabled" not in out


def test_offline_profile_can_strip_revive():
    out = g.offline_profile_text(PROFILE, strip_revive=True)
    assert "# path = 'natives/SeamlessCoop/ersc.dll'" in out
    assert '# id = "nightreign-revive"' in out and "# path = 'NightreignRevive/mod'" in out
    assert '\nid = "flora"' in out or '\r\nid = "flora"' in out
    assert "Revive disabled" in out.splitlines()[0]


def test_revive_array_profile_lists_seamless_and_revive(tmp_path):
    """Nightreign Revive's installer writes packages = [ ] and natives = [ ], not [[blocks]]."""
    seamless = tmp_path / "SeamlessCoop"
    seamless.mkdir()
    (seamless / "ersc_settings.ini").write_text("cooppassword = room\n", encoding="utf-8")
    own = tmp_path / "NightreignRevive"
    own.mkdir()
    text = (
        'profileVersion = "v1"\nstart_online = false\n'
        'natives = [{ path = "' + seamless.joinpath("ersc.dll").as_posix() + '" }, '
        '{ path = "'
        + own.joinpath("ReviveHudBootstrap.dll").as_posix()
        + '", load_early = true, initializer = { function = "NrrHudBootstrapInitialize" } }, '
        '{ path = "'
        + own.joinpath("RevivePrototype.dll").as_posix()
        + '", initializer = { function = "NrrInitialize" }, load_after = [{ id = "ersc.dll", optional = true }] }]\n'
        'packages = [{ id = "nightreign-revive", path = "' + own.joinpath("mod").as_posix() + '", load_after = [] }]\n'
    )
    p = tmp_path / "revive.me3"
    p.write_text(text, encoding="utf-8")
    assert [(m["kind"], m["id"]) for m in mods_service.read_profile_mods(p)] == [
        ("native", "ersc.dll"),
        ("native", "ReviveHudBootstrap.dll"),
        ("native", "RevivePrototype.dll"),
        ("package", "nightreign-revive"),
    ]
    assert coop_service.ersc_ini_for(str(p)) == seamless / "ersc_settings.ini"
    off = g.offline_profile_text(text)
    assert "enabled = false" in off and "RevivePrototype.dll" in off and 'id = "ersc.dll"' in off
