"""ui/theme.py reads its colours from the generated ui/theme_tokens.py: every key the Widgets views use comes from a
role, the roles theme.py names exist in every theme, and theme_tokens stays plain data (no Qt)."""

import ast
from pathlib import Path

import pytest

from roundtable_souls.ui import theme_tokens

pytest.importorskip("PySide6.QtGui")
from PySide6.QtGui import QColor  # noqa: E402

from roundtable_souls.ui import theme  # noqa: E402


def test_theme_tokens_imports_nothing_but_future():
    tree = ast.parse(Path(theme_tokens.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name if isinstance(node, ast.Import) else node.module
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imported <= {"__future__"}


@pytest.mark.parametrize("name", list(theme_tokens.THEMES))
def test_every_legacy_key_names_a_colour_role(name):
    roles = theme_tokens.THEMES[name]
    for key, role in theme_tokens.LEGACY.items():
        assert isinstance(roles[role], str) and QColor(roles[role]).isValid(), (key, role)


def test_widget_tokens_come_from_the_roles():
    for tokens, roles in ((theme.tokens_dark(), theme_tokens.DARK), (theme.tokens_light(), theme_tokens.LIGHT)):
        for key, role in theme_tokens.LEGACY.items():
            value = tokens[key]
            got = value if isinstance(value, QColor) else QColor(value)
            assert got == QColor(roles[role]), key
        assert tokens["accent_off"] == "transparent"


def test_the_roles_theme_py_names_exist_in_every_theme():
    named = {role for pair in theme._TONES.values() for role in pair} | set(theme._SYNTAX.values())
    named |= {"accent", "textSecondary", "textPrimary", "surfaceBar"}  # ACCENT, HINT, TEXT_LIGHT, BG_*
    for roles in theme_tokens.THEMES.values():
        assert named <= set(roles)


def test_constants_follow_the_tokens():
    assert theme.ACCENT == theme_tokens.DARK["accent"]
    assert theme.ACCENT_LIGHT == theme_tokens.LIGHT["accent"]
    assert theme.TEXT_LIGHT == theme_tokens.LIGHT["textPrimary"]
