"""A syntax check of the scripts a hook composes (overhauls.hooks), so a broken composition is refused when the
build is made instead of failing silently in the game.

The game's character scripts (HKS) are Lua 5.1 with Havok's additions. The check compiles the text with Lua 5.1
itself (lupa's lua51 module: the reference compiler, loaded only, never run): nothing of the script executes. The
scripts known to be used (the game's own as text, Nightreign Revive's and the owner's mods') use no Havok-only syntax;
a script that does would be refused here, naming the line, rather than accepted unread (docs/decisions/0006).

check() parses the base and each hook's fragment on its own first, so a broken fragment is named as the cause even
when the whole would also fail, then the composed text, whose error line is traced back to the part it came from.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from roundtable_souls.overhauls.hooks import Composed, Hook

_WHERE = re.compile(r'^\[string "[^"]*"\]:(\d+):\s*(.*)$', re.S)


@dataclass(frozen=True)
class SyntaxProblem:
    line: int  # 1-based, in the text checked
    message: str  # Lua's own words ("'end' expected (to close 'if' at line 2) near <eof>")


def syntax_error(text: str) -> SyntaxProblem | None:
    """The first syntax error in a Lua 5.1 chunk, or None when it compiles."""
    from lupa import lua51

    runtime = lua51.LuaRuntime(unpack_returned_tuples=False)  # nothing is run: the defaults do not matter
    try:
        runtime.compile(text)
    except lua51.LuaSyntaxError as e:
        said = str(e).strip()
        m = _WHERE.match(said)
        if m is None:
            return SyntaxProblem(0, said)
        # an error at the end of the text is reported on the line after its last newline: the last real line
        last = max(text.count("\n") + (0 if text.endswith("\n") else 1), 1)
        return SyntaxProblem(min(int(m.group(1)), last), m.group(2).strip())
    return None


def check(entry: str, base: str, base_from: str, hooks: Sequence[Hook], composed: Composed) -> str | None:
    """Why the composed entry script would not load, naming the file, the line and the part that introduced it; None
    when it compiles. entry: how the file is named ("action/script/c0000.hks")."""
    found = syntax_error(base)
    if found is not None:
        return f"{entry} would not load in game: {base_from} has a syntax error at line {found.line} ({found.message})."
    for hook in hooks:
        found = syntax_error(hook.text.removeprefix("﻿"))
        if found is not None:
            return (
                f"{entry} would not load in game: {hook.who}'s script has a syntax error at its line {found.line} "
                f"({found.message})."
            )
    found = syntax_error(composed.text)
    if found is None:
        return None
    part = composed.part_at(found.line)
    who = part.who if part is not None else "the joins between the scripts"
    return (
        f"{entry} would not load in game: a syntax error at line {found.line}, in what {who} added "
        f"({found.message}). Each part reads on its own, so it comes from putting them together."
    )
