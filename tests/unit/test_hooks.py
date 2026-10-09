"""overhauls.hooks: mods' script fragments added to an entry script, on texts alone: several hooks in load order, each
wrapping the one before, and the guardrails (compiled or non-text base, a hook already there)."""

import pytest

from roundtable_souls.overhauls import hooks
from roundtable_souls.overhauls.hooks import Hook, HookError, compose

BASE = "-- the game's script, as text\nfunction Update()\n    Move()\nend\n"
FIRST = "local FirstOriginalUpdate = Update\nfunction Update()\n    FirstOriginalUpdate()\n    First()\nend\n"
SECOND = "local SecondOriginalUpdate = Update\nfunction Update()\n    SecondOriginalUpdate()\n    Second()\nend\n"


def test_two_hooks_are_appended_in_load_order_each_wrapping_the_previous():
    out = compose(BASE, "c0000.hks from anims", [Hook("First", FIRST), Hook("Second", SECOND)])
    assert out.text == BASE + "\n" + FIRST + "\n" + SECOND
    # the second wraps the first's Update, which wraps the game's: the order is the load order
    assert out.text.index("local FirstOriginalUpdate") < out.text.index("local SecondOriginalUpdate")
    lines = out.text.split("\n")
    assert [(p.who, lines[p.first - 1], lines[p.last - 1]) for p in out.parts] == [
        ("c0000.hks from anims", "-- the game's script, as text", "end"),
        ("First", "local FirstOriginalUpdate = Update", "end"),
        ("Second", "local SecondOriginalUpdate = Update", "end"),
    ]
    assert out.part_at(5) is None  # the blank line between the base and the first hook
    assert out.part_at(6).who == "First" and out.part_at(len(lines) - 1).who == "Second"


def test_line_ranges_hold_without_final_newlines_and_with_crlf():
    out = compose("a\r\nb", "base", [Hook("One", "x\r\ny"), Hook("Two", "z")])
    assert out.text == "a\nb\nx\ny\nz"
    assert [(p.who, p.first, p.last) for p in out.parts] == [("base", 1, 2), ("One", 3, 4), ("Two", 5, 5)]


def test_a_hook_whose_markers_are_already_there_is_refused():
    marked = Hook("First", FIRST, markers=["local FirstOriginalUpdate = Update"], refuse_text="First is already in it.")
    with pytest.raises(HookError, match="First is already in it."):
        compose(BASE + FIRST, "base", [marked])
    # a later hook's markers found in an earlier hook's fragment: the same mod twice in the load order
    twice = Hook("First again", FIRST, markers=["local FirstOriginalUpdate = Update"])
    with pytest.raises(HookError, match="A mod before First again already contains its script."):
        compose(BASE, "base", [Hook("First", FIRST), twice])


def test_a_compiled_or_non_text_entry_script_takes_no_hook():
    with pytest.raises(HookError, match=r"c0000.hks from anims is compiled \(bytecode\)"):
        hooks.as_text(b"\x1bLuaQ\x00\x01compiled", "c0000.hks from anims")
    with pytest.raises(HookError, match="is not UTF-8 text"):
        hooks.as_text(b"\xff\xfe-- utf-16", "c0000.hks")
    assert hooks.as_text(b"\xef\xbb\xbf-- with a BOM\r\nx\r\n", "c0000.hks") == "-- with a BOM\nx\n"
