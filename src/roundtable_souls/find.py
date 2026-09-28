"""Find and replace over plain text: the pure part of the editor's find bar, so it can be tested without Qt."""

from __future__ import annotations

import re

Span = tuple[int, int]


def compile_query(query: str, *, regex: bool = False, case: bool = False) -> re.Pattern[str] | None:
    """The pattern for a query, or None when the query is empty or not a valid regular expression."""
    if not query:
        return None
    flags = re.MULTILINE | (0 if case else re.IGNORECASE)
    try:
        return re.compile(query if regex else re.escape(query), flags)
    except re.error:
        return None


def find_all(text: str, query: str, *, regex: bool = False, case: bool = False) -> list[Span]:
    """Every non-empty match as (start, end) offsets, in document order."""
    rx = compile_query(query, regex=regex, case=case)
    if rx is None:
        return []
    return [(m.start(), m.end()) for m in rx.finditer(text) if m.end() > m.start()]


def next_match(matches: list[Span], position: int, *, backward: bool = False) -> Span | None:
    """The first match starting at or after position, or the last one starting before it when backward; wraps around."""
    if not matches:
        return None
    if backward:
        before = [m for m in matches if m[0] < position]
        return before[-1] if before else matches[-1]
    after = [m for m in matches if m[0] >= position]
    return after[0] if after else matches[0]


def replace_one(
    text: str, span: Span, query: str, replacement: str, *, regex: bool = False, case: bool = False
) -> str | None:
    """What one match becomes (group references like \\1 work in regex mode), or None when span is not a match."""
    rx = compile_query(query, regex=regex, case=case)
    if rx is None:
        return None
    m = rx.match(text, span[0])
    if m is None or m.end() != span[1]:
        return None
    if not regex:
        return replacement
    try:
        return m.expand(replacement)
    except re.error, IndexError:
        return None


def replace_all(text: str, query: str, replacement: str, *, regex: bool = False, case: bool = False) -> tuple[str, int]:
    """(new text, number of replacements). A bad group reference in the replacement replaces nothing."""
    rx = compile_query(query, regex=regex, case=case)
    if rx is None:
        return text, 0
    try:
        return rx.subn(replacement if regex else (lambda m: replacement), text)
    except re.error, IndexError:
        return text, 0
