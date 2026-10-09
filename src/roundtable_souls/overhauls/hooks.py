"""Script hooks: a mod's script fragment added to the game's entry script (the player character's c0000.hks), worked
out on texts alone so it can be checked without files.

compose() takes the entry script the packages leave (the last package's copy, else the base a download ships) and
the hooks in load order, and returns the composed text with a record of which lines came from where. Each hook's
fragment is appended after the text so far; a fragment that wraps the game's Update (keeps the current one and
defines its own that calls it, as Nightreign Revive's does) therefore wraps the previous hook's. Code is never
merged: the game's own script is compiled, so there is no common base to merge against, and two scripts that each
define Update would run and misbehave.

The guardrails, each a HookError with the reason:
    a compiled entry script (Lua bytecode)       nothing can be appended to it
    an entry script that is not UTF-8 text       likewise
    the text so far already holding a hook's     a package before it already contains that mod's script (a copy of
    markers                                      an earlier build, or the mod merged by hand); appending again would
                                                 run it twice
Line endings become \\n, as the mods' own installers read the script.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

COMPILED_LUA = b"\x1bLua"  # a compiled script starts with this; text cannot be appended to it


class HookError(ValueError):
    pass


@dataclass(frozen=True)
class Hook:
    """One mod's fragment for an entry script. who: how messages name it (the mod). markers: text meaning the script
    already contains it; refuse_text: the refusal then (a plain default otherwise)."""

    who: str
    text: str
    markers: Sequence[str] = ()
    refuse_text: str | None = None


@dataclass(frozen=True)
class Part:
    """Where one piece of the composed script is: lines first..last (1-based, inclusive)."""

    who: str
    first: int
    last: int


@dataclass
class Composed:
    text: str
    parts: list[Part] = field(default_factory=list)  # the base first, then each hook, in order

    def part_at(self, line: int) -> Part | None:
        """The piece a line of the composed script came from."""
        return next((p for p in self.parts if p.first <= line <= p.last), None)


def as_text(raw: bytes, where: str) -> str:
    """An entry script read as text, or a HookError saying why it cannot take a hook. where: how messages name it
    ("action/script/c0000.hks from anims")."""
    if raw.startswith(COMPILED_LUA):
        raise HookError(
            f"{where} is compiled (bytecode), so a mod's script cannot be added to it. A package with the script as "
            "text is needed."
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise HookError(f"{where} is not UTF-8 text, so a mod's script cannot be added to it.") from e
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _lines(text: str) -> int:
    return text.count("\n") + (0 if text.endswith("\n") or not text else 1)


def compose(base: str, base_from: str, hooks: Sequence[Hook]) -> Composed:
    """The base script (from base_from: how messages name it) with each hook appended, in the order given (load
    order). Raises HookError when the text so far already holds a hook's markers."""
    text = base.replace("\r\n", "\n").replace("\r", "\n")
    parts = [Part(base_from, 1, max(_lines(text), 1))]
    for hook in hooks:
        if any(m and m in text for m in hook.markers):
            raise HookError(hook.refuse_text or f"A mod before {hook.who} already contains its script.")
        fragment = hook.text.removeprefix("﻿").replace("\r\n", "\n").replace("\r", "\n")
        first = text.count("\n") + 2  # after the text so far and the newline that separates them
        text = text + "\n" + fragment
        parts.append(Part(hook.who, first, max(_lines(text), first)))
    return Composed(text, parts)
