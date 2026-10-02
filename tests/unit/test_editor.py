"""Editor helpers behind Ctrl+/, Tab and Shift+Tab in the profile and share boxes."""

from roundtable_souls.services import coop as coop_service


def test_toggle_comment_toml_block_and_back():
    lines = ["[[natives]]", "  path = 'natives/x.dll'", "", "  load_early = true"]
    out = coop_service.toggle_comment(lines, "#")
    assert out == ["# [[natives]]", "#   path = 'natives/x.dll'", "", "#   load_early = true"]
    assert coop_service.toggle_comment(out, "#") == lines  # round trip, blank line untouched
    # indented block: the marker goes at the shallowest indent, not column 0
    assert coop_service.toggle_comment(["    a = 1", "      b = 2"], "#") == ["    # a = 1", "    #   b = 2"]
    # mixed block (one line already commented) comments everything, so the second press uncomments cleanly
    mixed = ["# a = 1", "b = 2"]
    assert coop_service.toggle_comment(mixed, "#") == ["# # a = 1", "# b = 2"]
    assert coop_service.toggle_comment(coop_service.toggle_comment(mixed, "#"), "#") == mixed
    # markers without the space still uncomment
    assert coop_service.toggle_comment(["#a = 1"], "#") == ["a = 1"]
    assert coop_service.toggle_comment(["", "  "], "#") == ["", "  "]


def test_toggle_comment_json_and_apply_ignores_it():
    lines = ['  "boss_health_scaling": "100",', '  "cooppassword": "x"']
    out = coop_service.toggle_comment(lines, "//")
    assert out == ['  // "boss_health_scaling": "100",', '  // "cooppassword": "x"']
    assert coop_service.toggle_comment(out, "//") == lines
    text = '{\n  "cooppassword": "friend",\n  // "boss_health_scaling": "75",\n  "allow_invaders": "1"\n}'
    assert coop_service.parse_settings_json(text) == {"cooppassword": "friend", "allow_invaders": "1"}
    assert coop_service.strip_json_comments("a\n  // b\nc") == "a\nc"


def test_indent_and_outdent():
    lines = ["a", "", "  b"]
    assert coop_service.indent_lines(lines) == ["  a", "", "    b"]
    assert coop_service.indent_lines(coop_service.indent_lines(lines), outdent=True) == lines
    assert coop_service.indent_lines([" x", "\ty", "z"], outdent=True) == ["x", "y", "z"]
    assert coop_service.COMMENT_PREFIX == {"toml": "#", "json": "//", "ini": ";", "text": "#"}
