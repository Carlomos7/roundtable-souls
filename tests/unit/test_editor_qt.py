"""The editor and its find bar driven through real key events on an offscreen Qt platform."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtTest = pytest.importorskip("PySide6.QtTest")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from roundtable_souls.ui.dialogs.editor import code_edit  # noqa: E402

QTest = QtTest.QTest
TEXT = "alpha\nbeta\n  beta two\nend\n"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def editor(app):
    ed = code_edit("x")
    ed.resize(700, 400)
    ed.show()
    ed.setFocus()
    ed.setPlainText(TEXT)
    app.processEvents()
    yield ed
    ed.close()
    ed.deleteLater()
    app.processEvents()


def key(widget, k, mod=Qt.NoModifier):
    QTest.keyClick(widget, k, mod)
    QApplication.processEvents()


def focus():
    return QApplication.focusWidget()


def test_typing_in_the_bar_never_edits_the_document(editor):
    key(editor, Qt.Key_F, Qt.ControlModifier)
    bar = editor.find_bar
    assert bar.isVisible() and focus() is bar.search
    QTest.keyClicks(focus(), "beta")
    QApplication.processEvents()
    assert bar.search.text() == "beta" and editor.toPlainText() == TEXT
    key(focus(), Qt.Key_Return)
    assert editor.textCursor().selectedText() == "beta" and editor.toPlainText() == TEXT
    assert bar.count.text() == "1 of 2"
    key(focus(), Qt.Key_Return)
    assert bar.count.text() == "2 of 2" and editor.toPlainText() == TEXT
    key(focus(), Qt.Key_Return, Qt.ShiftModifier)
    assert bar.count.text() == "1 of 2" and editor.toPlainText() == TEXT
    key(focus(), Qt.Key_Backspace)  # editing the query, not the file
    assert bar.search.text() == "bet" and editor.toPlainText() == TEXT
    key(focus(), Qt.Key_Escape)
    assert not bar.isVisible() and focus() is editor and editor.toPlainText() == TEXT


def test_replace_flow_and_undo(editor):
    key(editor, Qt.Key_H, Qt.ControlModifier)
    bar = editor.find_bar
    assert bar.replace.isVisible()
    bar.search.setText("beta")
    bar.replace.setFocus()
    QTest.keyClicks(bar.replace, "gamma")
    key(bar.replace, Qt.Key_Return)  # nothing highlighted yet: Enter in Replace only finds the first match
    assert editor.textCursor().selectedText() == "beta" and editor.toPlainText() == TEXT
    key(bar.replace, Qt.Key_Return)  # now it replaces that one and moves on
    assert editor.toPlainText().count("gamma") == 1 and editor.toPlainText().count("beta") == 1
    bar.replace_all()
    assert "beta" not in editor.toPlainText() and bar.count.text() == "Replaced 1"
    editor.undo()
    editor.undo()
    assert editor.toPlainText() == TEXT


def test_regex_case_and_invalid_pattern(editor):
    bar = editor.find_bar
    bar.open()
    bar.case_btn.setChecked(True)
    bar.search.setText("Beta")
    assert bar.count.text() == "No matches"
    bar.case_btn.setChecked(False)
    assert bar.count.text() == "2 matches"
    bar.regex_btn.setChecked(True)
    bar.search.setText("beta(")
    assert bar.count.text() == "Invalid pattern" and bar.matches == []
    bar.step()  # nothing to step to, no crash
    bar.search.setText(r"^\s+(\w+)")
    bar.replace.setText(r"\1")
    bar.replace_all()
    assert "  beta two" not in editor.toPlainText() and "beta two" in editor.toPlainText()


def test_document_edits_refresh_the_count_and_tab_still_indents(editor):
    bar = editor.find_bar
    bar.open()
    bar.search.setText("end")
    assert bar.count.text() == "1 match"
    editor.appendPlainText("the end")
    assert bar.count.text() == "2 matches"
    bar.close_bar()
    c = editor.textCursor()
    c.setPosition(0)
    c.setPosition(len("alpha\nbeta"), c.MoveMode.KeepAnchor)
    editor.setTextCursor(c)
    key(editor, Qt.Key_Tab)
    assert editor.toPlainText().startswith("  alpha\n  beta")


def test_selection_seeds_the_query_and_bar_stays_inside(editor):
    c = editor.textCursor()
    c.setPosition(6)
    c.setPosition(10, c.MoveMode.KeepAnchor)
    editor.setTextCursor(c)
    key(editor, Qt.Key_F, Qt.ControlModifier)
    bar = editor.find_bar
    assert bar.search.text() == "beta" and bar.count.text() == "1 of 2"
    editor.resize(200, 300)
    QApplication.processEvents()
    assert bar.x() >= 0 and bar.width() >= 240
