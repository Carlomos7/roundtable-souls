"""mods.naming: the launcher's names for the folders it makes, and the one path-length limit."""

from __future__ import annotations

import pytest

from roundtable_souls.mods import naming, profile_edit, profile_writer


@pytest.mark.parametrize(
    ("name", "want"),
    [
        ("Elden Ring Reforged v1.4.6", "elden-ring-reforged"),
        ("Nightreign Revive 0.1.33-rc3", "nightreign-revive"),
        ("Clever's Moveset Modpack ver 2.1", "clevers-moveset-modpack"),
        ("Better Hair version 3", "better-hair"),
        ("Map for Goblins 1.2b", "map-for-goblins"),
        ("Grand Merchant 2.0 beta 4", "grand-merchant"),
        ("Hair 13-561-1-1-1648994275", "hair-13"),  # Nexus's suffix; the 13 is part of the name
        ("Seamless Co-op-510-1-9-9-1648994275", "seamless-co-op"),
        ("Épée Sounds", "epee-sounds"),
        ("  __Weird__  Name!!  ", "weird-name"),
        ("c0000 Edits", "c0000-edits"),  # not a version
        ("Revive", "revive"),
        ("v2", "mod"),  # nothing left
        ("日本語", "mod"),
        ("CON", "con-mod"),  # a Windows device name
        ("COM1 v2", "com1-mod"),
    ],
)
def test_mod_id(name, want):
    assert naming.mod_id(name) == want


def test_mod_id_is_kebab_ascii_and_short():
    out = naming.mod_id("A" * 30 + " " + "B" * 30 + " v3")
    assert len(out) <= naming.ID_LENGTH
    assert out == out.lower() and out.isascii() and not out.endswith("-")
    assert naming.unsafe(out) is None


@pytest.mark.parametrize(
    "name",
    ["CON", "con.txt", "Nul", "aux.tar.gz", "COM1", "lpt9", "COM¹", "conin$", "name.", "name ", "a<b", 'a"b',
     "a:b", "a|b", "a?b", "a*b", "a/b", "a\\b", "tab\there", "", ".", ".."],
)  # fmt: skip
def test_unsafe_names(name):
    assert naming.unsafe(name)


@pytest.mark.parametrize("name", ["console", "com10", "lpt", "nul-mod", ".roundtable", "a.b", "con-tent", "Mod 2"])
def test_safe_names(name):
    assert naming.unsafe(name) is None


def test_reserved_names_are_never_ids():
    assert "combined-parameters" in naming.RESERVED
    assert naming.unique("combined-parameters", []) == "combined-parameters-2"
    assert naming.unique("packages", []) == "packages-2"


def test_unique_ids():
    assert naming.unique("hair", []) == "hair"
    assert naming.unique("hair", ["Hair"]) == "hair-2"  # case aside
    assert naming.unique("hair", ["hair", "hair-2", "hair-3"]) == "hair-4"
    long = "x" * naming.ID_LENGTH
    out = naming.unique(long, [long])
    assert out.endswith("-2") and len(out) == naming.ID_LENGTH


def test_profile_slug_unchanged():
    """Today's installs keep their names (the case kept); the Nexus suffix comes from naming."""
    assert profile_edit.slug("Hair 13-561-1-1-1648994275") == "Hair-13"
    assert profile_edit.slug("Elden Ring Reforged v1.4.6") == "Elden-Ring-Reforged-v1.4.6"


def test_one_path_limit(tmp_path):
    """The writer's Paths rule reads the limit from naming: one place for 220."""
    assert profile_writer.Paths.MAX_PATH == naming.MAX_PATH == 220
    assert profile_writer.Paths.ROOM == naming.ROOM == 40
    short = tmp_path / "mods"
    assert naming.deepest(short) == len(str(short)) + 1 + naming.ROOM
    assert naming.deepest(short, 10) == len(str(short)) + 11
    assert naming.path_problem(short, 10) is None
    deep = tmp_path / ("d" * (naming.MAX_PATH - len(str(tmp_path))))
    problem = naming.path_problem(deep, 5)
    assert problem is not None
    assert problem.startswith(f"{deep} is too long a path for Windows (")
    assert f"{naming.MAX_PATH} are safe" in problem
