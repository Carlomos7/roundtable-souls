"""overhauls.install_plan: what installing an overhaul does to a me3 profile, worked out without writing anything.
The expected results are Revive's installer's (LITE 0.1.33-rc3, installer/installer.py), worked out by hand from the
lines cited; tools outside the repository compare the plan with that installer itself on more profiles."""

import tomllib
from pathlib import Path

import pytest

from roundtable_souls import overhauls
from roundtable_souls.overhauls import install_plan
from roundtable_souls.overhauls.install_plan import Change, apply, check, plan

PROFILE = Path("C:/Games/me3/profiles/my.me3")
OWN = PROFILE.parent / "NightreignRevive"
SEAMLESS = Path("C:/Games/ELDEN RING/Game/SeamlessCoop/ersc.dll")
ANY_DIR = lambda _p: True  # noqa: E731  (every package folder is there)


def revive():
    config = next(c for c in overhauls.load() if c.id == "nightreign-revive")
    build, problem = install_plan.install_of(config, "LITE")
    assert problem is None and build is not None and build.install is not None
    return config, build.install


def planned(text: str, **kw) -> tuple[install_plan.Plan, dict]:
    _, install = revive()
    kw.setdefault("is_dir", ANY_DIR)
    p = plan(text, PROFILE, install, OWN, **kw)
    return p, apply(tomllib.loads(text), p.changes)


ORDINARY = """profileVersion = "v1"
start_online = false

# my mods
[[packages]]
id = "body"
path = 'mod/body'

[[packages]]
id = "dash"
path = 'mod/dash'
load_after = [{ id = "body", optional = true }]

[[packages]]
id = "off"
path = 'mod/off'
enabled = false

[[natives]]
path = 'natives/SeamlessCoop/ersc.dll'
load_early = true

[[natives]]
path = 'natives/Camera/bettercamera.dll'

[[natives]]
id = "fix"
path = 'natives/Fix/fix.dll'
enabled = false
"""


def test_an_ordinary_profile_gets_revives_dlls_and_package_last():
    p, result = planned(ORDINARY, seamless=SEAMLESS)
    assert p.ok and p.problems == []
    # patched_profile: the HUD bootstrap loads early with its initializer; RevivePrototype loads after every enabled
    # DLL (deps: native id, else the file name), each optional; the package after every enabled package
    assert [c.action for c in p.changes] == ["add", "add", "add"]
    assert result["natives"][-2:] == [
        {
            "path": f"{OWN.as_posix()}/ReviveHudBootstrap.dll",
            "load_early": True,
            "initializer": {"function": "NrrHudBootstrapInitialize"},
        },
        {
            "path": f"{OWN.as_posix()}/RevivePrototype.dll",
            "initializer": {"function": "NrrInitialize"},
            "load_after": [{"id": "ersc.dll", "optional": True}, {"id": "bettercamera.dll", "optional": True}],
        },
    ]
    assert result["packages"][-1] == {
        "id": "nightreign-revive",
        "path": f"{OWN.as_posix()}/mod",
        "load_after": [{"id": "body", "optional": True}, {"id": "dash", "optional": True}],
    }
    assert result["packages"][:3] == tomllib.loads(ORDINARY)["packages"]  # the player's own entries as written


def test_settings_are_set_only_where_they_differ():
    p, result = planned("start_online = true\n", seamless=SEAMLESS)
    sets = [c for c in p.changes if c.action == "set"]
    assert sets == [
        Change("set", "setting", "profileVersion", {"profileVersion": "v1"}, "the overhaul's installer sets it"),
        Change("set", "setting", "start_online", {"start_online": False}, "the overhaul's installer sets it"),
    ]  # patched_profile: result['profileVersion']='v1'; result['start_online']=False
    assert result["profileVersion"] == "v1" and result["start_online"] is False


def test_an_earlier_installs_entries_are_removed_first():
    text = """profileVersion = "v1"
start_online = false
[[packages]]
id = "a"
path = 'mod/a'
[[packages]]
id = "nightreign-revive"
path = 'NightreignRevive/mod'
[[packages]]
id = "zz_NightreignRevive"
path = 'addons/zz_NightreignRevive'
[[natives]]
path = 'natives/SeamlessCoop/ersc.dll'
[[natives]]
path = 'NightreignRevive/RevivePrototype.dll'
[[natives]]
path = 'dll/offline/NightreignRevive.dll'
"""
    p, result = planned(text)
    # clean_owned: packages with id OWN_ID or ADDON_ID, natives whose file is in OWN_DLLS
    removed = [(c.kind, c.key) for c in p.changes if c.action == "remove"]
    assert removed == [
        ("package", "nightreign-revive"),
        ("package", "zz_NightreignRevive"),
        ("native", "NightreignRevive/RevivePrototype.dll"),
        ("native", "dll/offline/NightreignRevive.dll"),
    ]
    assert [r["id"] for r in result["packages"]] == ["a", "nightreign-revive"]  # the new one, after "a" only
    assert result["packages"][-1]["load_after"] == [{"id": "a", "optional": True}]
    assert [Path(n["path"]).name for n in result["natives"]] == [
        "ersc.dll",
        "ReviveHudBootstrap.dll",
        "RevivePrototype.dll",
    ]


def test_seamless_switched_off_is_switched_on_and_pointed_at_the_one_found():
    text = "profileVersion = \"v1\"\nstart_online = false\n[[natives]]\npath = 'old/ersc.dll'\nenabled = false\n"
    p, result = planned(text, seamless=SEAMLESS)
    # patched_profile: disabled['enabled']=True; disabled['path']=seamless.as_posix()
    assert p.changes[0] == Change(
        "update", "native", "old/ersc.dll", {"enabled": True, "path": SEAMLESS.as_posix()}, "Seamless is required"
    )
    assert result["natives"][0] == {"path": SEAMLESS.as_posix(), "enabled": True}
    assert result["natives"][-1]["load_after"] == [{"id": "ersc.dll", "optional": True}]


def test_without_seamless_the_candidates_are_tried_in_order_and_one_is_added():
    text = 'profileVersion = "v1"\nstart_online = false\n'
    game = Path("C:/Games/ELDEN RING/Game")
    there = {game / "SeamlessCoop/ersc.dll"}
    # install(): candidates root/dll/offline/ersc.dll, root/SeamlessCoop/ersc.dll, game.parent/SeamlessCoop/ersc.dll
    p, result = planned(text, game_dir=game, is_file=lambda q: Path(q) in there)
    assert result["natives"][0] == {"path": (game / "SeamlessCoop/ersc.dll").as_posix()}
    beside = {PROFILE.parent / "SeamlessCoop/ersc.dll", game / "SeamlessCoop/ersc.dll"}
    p, result = planned(text, game_dir=game, is_file=lambda q: Path(q) in beside)
    assert result["natives"][0] == {"path": (PROFILE.parent / "SeamlessCoop/ersc.dll").as_posix()}


def test_no_seamless_anywhere_stops_the_install():
    p, _ = planned('profileVersion = "v1"\n', is_file=lambda _q: False)
    assert not p.ok and [x.code for x in p.problems] == ["seamless-missing"]


def test_movement_dlls_get_their_initializer_only_when_they_have_none():
    text = """profileVersion = "v1"
start_online = false
[[natives]]
path = 'natives/SeamlessCoop/ersc.dll'
[[natives]]
path = 'natives/NightreignMovement.dll'
[[natives]]
path = 'natives/nightreignmovement_extra.dll'
initializer = { function = "Own" }
"""
    p, result = planned(text)
    # patched_profile: n.setdefault('initializer', {'function': 'NrmInitialize'}) for nightreignmovement* DLLs
    updates = [c for c in p.changes if c.action == "update"]
    assert updates == [
        Change("update", "native", "natives/NightreignMovement.dll", {"initializer": {"function": "NrmInitialize"}},
               "its initializer")
    ]  # fmt: skip
    assert result["natives"][2]["initializer"] == {"function": "Own"}


def test_both_spellings_of_the_lists_are_read():
    text = 'profileVersion = "v1"\nstart_online = false\npackage = [{ id = "a", path = \'mod/a\' }]\n'
    text += "native = [{ path = 'natives/SeamlessCoop/ersc.dll' }]\n"
    _, result = planned(text)
    assert "package" not in result and [r["id"] for r in result["packages"]] == ["a", "nightreign-revive"]
    assert result["natives"][-1]["load_after"] == [{"id": "ersc.dll", "optional": True}]


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("[[packages]]\nid = 'a'\npath = 'm/a'\n[[packages]]\nid = 'a'\npath = 'm/b'\n", "duplicate-ids"),
        (
            "[[packages]]\nid='a'\npath='m/a'\nload_after=['b']\n[[packages]]\nid='b'\npath='m/b'\nload_after=['a']\n",
            "order-cycle",
        ),
        ("profileVersion = \n", "profile-unreadable"),
    ],
)
def test_profiles_the_install_cannot_use_are_refused(text, code):
    p = plan(text, PROFILE, revive()[1], OWN, seamless=SEAMLESS, is_dir=ANY_DIR)
    assert code in [x.code for x in p.problems] and not p.ok


def test_a_missing_package_folder_stops_the_install():
    there = {Path(install_plan.absolute(PROFILE, "mod/body"))}
    p, _ = planned(ORDINARY, seamless=SEAMLESS, is_dir=lambda q: Path(q) in there)
    assert [x.code for x in p.problems] == ["package-missing"]  # dash; "off" is switched off
    assert "mod/dash" in p.problems[0].message


def test_other_editions_are_recorded_as_not_installed():
    config, _ = revive()
    for edition in ("STANDALONE", "CONVERGENCE", "REFORGED"):
        build, problem = install_plan.install_of(config, edition)
        assert build is None and problem is not None and problem.code == "edition-unsupported"


def test_planning_writes_nothing(tmp_path):
    profile = tmp_path / "my.me3"
    profile.write_text(ORDINARY, encoding="utf-8")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*")}
    plan(ORDINARY, profile, revive()[1], tmp_path / "NightreignRevive", seamless=SEAMLESS, is_dir=ANY_DIR)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*")} == before


def test_the_check_after_an_install():
    _, install = revive()
    _, result = planned(ORDINARY, seamless=SEAMLESS)
    files = {OWN / f for f in install.required_files}
    text = _toml(result)
    every_dll = lambda q: Path(q) in files or str(q).endswith(".dll")  # noqa: E731
    assert check(text, PROFILE, install, OWN, is_file=every_dll, is_dir=ANY_DIR, has_files=ANY_DIR) == []
    off = text.replace('id = "nightreign-revive"', 'id = "nightreign-revive"\nenabled = false')
    problems = check(off, PROFILE, install, OWN, is_file=lambda _q: False, is_dir=ANY_DIR, has_files=lambda _p: False)
    assert {p.code for p in problems} == {"file-missing", "folder-empty", "not-enabled", "dll-missing"}


def _toml(data: dict) -> str:
    """A small TOML writer for the test's own profiles (plain values, inline tables, arrays of tables)."""

    def value(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, str):
            return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
        if isinstance(v, list):
            return "[" + ", ".join(value(x) for x in v) + "]"
        if isinstance(v, dict):
            return "{ " + ", ".join(f"{k} = {value(x)}" for k, x in v.items()) + " }"
        return str(v)

    lines = [f"{k} = {value(v)}" for k, v in data.items() if not isinstance(v, list)]
    for kind in ("packages", "natives"):
        for row in data.get(kind, []):
            lines += [f"[[{kind}]]", *(f"{k} = {value(v)}" for k, v in row.items())]
    text = "\n".join(lines) + "\n"
    assert tomllib.loads(text) == data
    return text
