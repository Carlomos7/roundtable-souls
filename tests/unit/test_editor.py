"""Editor helpers behind Ctrl+/, Tab and Shift+Tab in the profile and share boxes."""
from roundtable_souls import core as g


def test_toggle_comment_toml_block_and_back():
    lines = ["[[natives]]", "  path = 'natives/x.dll'", "", "  load_early = true"]
    out = g.toggle_comment(lines, "#")
    assert out == ["# [[natives]]", "#   path = 'natives/x.dll'", "", "#   load_early = true"]
    assert g.toggle_comment(out, "#") == lines                       # round trip, blank line untouched
    # indented block: the marker goes at the shallowest indent, not column 0
    assert g.toggle_comment(["    a = 1", "      b = 2"], "#") == ["    # a = 1", "    #   b = 2"]
    # mixed block (one line already commented) comments everything, so the second press uncomments cleanly
    mixed = ["# a = 1", "b = 2"]
    assert g.toggle_comment(mixed, "#") == ["# # a = 1", "# b = 2"]
    assert g.toggle_comment(g.toggle_comment(mixed, "#"), "#") == mixed
    # markers without the space still uncomment
    assert g.toggle_comment(["#a = 1"], "#") == ["a = 1"]
    assert g.toggle_comment(["", "  "], "#") == ["", "  "]


def test_toggle_comment_json_and_apply_ignores_it():
    lines = ['  "boss_health_scaling": "100",', '  "cooppassword": "x"']
    out = g.toggle_comment(lines, "//")
    assert out == ['  // "boss_health_scaling": "100",', '  // "cooppassword": "x"']
    assert g.toggle_comment(out, "//") == lines
    text = '{\n  "cooppassword": "friend",\n  // "boss_health_scaling": "75",\n  "allow_invaders": "1"\n}'
    assert g.parse_settings_json(text) == {"cooppassword": "friend", "allow_invaders": "1"}
    assert g.strip_json_comments("a\n  // b\nc") == "a\nc"


def test_indent_and_outdent():
    lines = ["a", "", "  b"]
    assert g.indent_lines(lines) == ["  a", "", "    b"]
    assert g.indent_lines(g.indent_lines(lines), outdent=True) == lines
    assert g.indent_lines([" x", "\ty", "z"], outdent=True) == ["x", "y", "z"]
    assert g.COMMENT_PREFIX == {"toml": "#", "json": "//"}
