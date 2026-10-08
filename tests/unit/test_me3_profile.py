"""The one me3 profile reader (formats.me3_profile) and the callers that read profiles through it."""

from pathlib import Path

from roundtable_souls.coop import ini as coop_ini
from roundtable_souls.formats import me3_profile
from roundtable_souls.mods import profile as profile_tools
from roundtable_souls.mods import profile_edit
from roundtable_souls.services import mods as mods_service

BLOCKS = (
    'profileVersion = "v1"\n\n'
    "[[natives]]\npath = 'natives/SeamlessCoop/ersc.dll'\nload_early = true\n\n"
    "# old armor\n# [[packages]]\n# id = \"fa-pu\"\n# path = 'mod/fa-pu'\n\n"
    "[[packages]]\nid = \"flora\"\npath = 'mod/flora'\n\n"
    "[[packages]]\nid = \"off\"\npath = 'mod/off'\nenabled = false\n"
)
ARRAY = (
    'profileVersion = "v1"\n'
    "packages = [{ id = \"flora\", path = 'mod/flora' }, { id = \"off\", path = 'mod/off', enabled = false }]\n"
    "natives = [{ path = 'natives/SeamlessCoop/ersc.dll', load_early = true }]\n"
)


def _shape(entries):
    return [(e["index"], e["kind"], e["name"], e["path"], e["enabled"]) for e in entries]


def test_both_shapes_read_alike():
    want = [
        (0, "native", "ersc.dll", "natives/SeamlessCoop/ersc.dll", True),
        (1, "package", "flora", "mod/flora", True),
        (2, "package", "off", "mod/off", False),
    ]
    assert _shape(me3_profile.entries(BLOCKS)) == want
    # the array form is numbered as to_blocks writes it (natives first), so an edit after converting finds the same
    assert _shape(me3_profile.entries(ARRAY)) == want


def test_commented_out_entry_is_a_comment_and_enabled_defaults_to_true():
    found = me3_profile.entries(BLOCKS)
    assert "fa-pu" not in {e["name"] for e in found}
    assert found[1]["enabled"] is True and found[1]["row"] == {"id": "flora", "path": "mod/flora"}


def test_a_broken_block_does_not_hide_the_others():
    text = BLOCKS.replace("path = 'mod/flora'", "path = 'mod/flora")  # unterminated string
    found = me3_profile.entries(text)
    assert [e["name"] for e in found] == ["ersc.dll", "entry 2", "off"]
    assert found[1]["row"] is None
    assert not me3_profile.parses(text)
    assert profile_tools.package_rows(text, include_disabled=True) == []  # me3 does not read it at all


def test_source_is_read_as_the_path():
    text = "[[packages]]\nid = \"a\"\nsource = 'mod/a'\n"
    assert me3_profile.entries(text)[0]["path"] == "mod/a"
    arr = "packages = [{ id = \"a\", source = 'mod/a' }]\n"
    assert me3_profile.entries(arr)[0]["path"] == "mod/a"
    assert "path = 'mod/a'" in me3_profile.to_blocks(arr)
    assert [r["path"] for r in profile_tools.package_rows(arr)] == ["mod/a"]


def test_package_rows_index_is_the_entry_index():
    rows = profile_tools.package_rows(BLOCKS, include_disabled=True)
    assert [(r["index"], r["id"]) for r in rows] == [(1, "flora"), (2, "off")]
    assert [r["id"] for r in profile_tools.package_rows(BLOCKS)] == ["flora"]


def test_callers_agree(tmp_path):
    for name, text in (("blocks.me3", BLOCKS), ("array.me3", ARRAY)):
        p = tmp_path / name
        p.write_text(text, encoding="utf-8")
        listed = profile_edit.entries(p)
        loaded = mods_service.read_profile_mods(p)
        assert [(m["index"], m["id"]) for m in loaded] == [(e["index"], e["name"]) for e in listed if e["enabled"]]


def test_coop_ini_found_through_the_reader(tmp_path):
    seamless = tmp_path / "natives" / "SeamlessCoop"
    seamless.mkdir(parents=True)
    (seamless / "ersc_settings.ini").write_text("cooppassword = x\n", encoding="utf-8")
    for name, text in (("blocks.me3", BLOCKS), ("array.me3", ARRAY)):
        p = tmp_path / name
        p.write_text(text, encoding="utf-8")
        assert coop_ini.ersc_ini_for(str(p)) == seamless / "ersc_settings.ini"
    off = tmp_path / "off.me3"
    off.write_text(BLOCKS.replace("load_early = true", "load_early = true\nenabled = false"), encoding="utf-8")
    # switched off in the entries, so only the plain-text fallback finds it (as before)
    assert coop_ini.ersc_ini_for(str(off)) == seamless / "ersc_settings.ini"


def test_switching_a_mod_off_stays_inside_its_block(tmp_path):
    p = tmp_path / "p.me3"
    p.write_bytes(b'[[packages]]\r\nid = "a"\r\npath = \'mod/a\'\r\n\r\n[[supports]]\r\ngame = "eldenring"\r\n')
    assert mods_service.set_profile_mod_enabled(p, 0, False)
    text = Path(p).read_bytes().decode()
    assert text == (
        '[[packages]]\r\nenabled = false\r\nid = "a"\r\npath = \'mod/a\'\r\n\r\n[[supports]]\r\ngame = "eldenring"\r\n'
    )
    assert mods_service.read_profile_mods(p) == []
