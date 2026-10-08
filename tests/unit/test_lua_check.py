"""overhauls.lua_check: a composed character script is compiled as Lua 5.1 (never run) before a build is used; a
broken one is refused naming the file, the line and the part that introduced it. Texts only."""

from roundtable_souls.overhauls import lua_check
from roundtable_souls.overhauls.hooks import Hook, compose

ENTRY = "action/script/c0000.hks"
BASE = "-- the game's script\nfunction Update()\n    Move()\nend\n"
GOOD = "local FirstOriginalUpdate = Update\nfunction Update()\n    FirstOriginalUpdate()\nend\n"
BROKEN = "local SecondOriginalUpdate = Update\nfunction Update()\n    if ready then\n        Second()\nend\n"


def checked(base, hooks):
    return lua_check.check(ENTRY, base, "c0000.hks from anims", hooks, compose(base, "c0000.hks from anims", hooks))


def test_a_good_composition_compiles():
    assert checked(BASE, [Hook("First", GOOD)]) is None


def test_the_script_is_only_compiled_never_run():
    assert lua_check.syntax_error('error("this would stop if it ran")\nos.exit(1)\n') is None


def test_a_broken_fragment_is_named_with_its_own_line():
    said = checked(BASE, [Hook("First", GOOD), Hook("Second", BROKEN)])
    assert said is not None
    assert said.startswith(
        "action/script/c0000.hks would not load in game: Second's script has a syntax error at its line 5 ("
    )
    assert "'end' expected" in said


def test_a_broken_base_is_named():
    said = checked("function Update()\n", [Hook("First", GOOD)])
    assert said is not None and said.startswith(
        "action/script/c0000.hks would not load in game: c0000.hks from anims has a syntax error at line 1 ("
    )


def test_parts_that_compile_alone_but_not_together_are_traced_to_the_part():
    # Lua 5.1 allows return only as a block's last statement: each part compiles, the two joined do not
    base, fragment = "x = 1\nreturn x\n", "y = 2\n"
    assert lua_check.syntax_error(base) is None and lua_check.syntax_error(fragment) is None
    said = checked(base, [Hook("First", fragment)])
    assert said is not None
    assert said.startswith(
        "action/script/c0000.hks would not load in game: a syntax error at line 4, in what First added ("
    )
    assert said.endswith("Each part reads on its own, so it comes from putting them together.")


def test_an_error_line_maps_to_the_part_it_came_from():
    composed = compose(BASE, "c0000.hks from anims", [Hook("First", GOOD), Hook("Second", BROKEN)])
    found = lua_check.syntax_error(composed.text)
    assert found is not None
    part = composed.part_at(found.line)
    assert part is not None and part.who == "Second"


def test_syntax_errors_carry_the_line():
    for text, line in [
        ("local a = 1\nlocal b = = 2\n", 2),
        ('local s = "abc\nprint(s)\n', 1),
        ("x = (1 + 2))\n", 1),
        ("function f()\n  if x then\n    y = 1\n", 3),  # at the end: the last real line
    ]:
        found = lua_check.syntax_error(text)
        assert found is not None and found.line == line, (text, found)
