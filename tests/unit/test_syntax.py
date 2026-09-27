"""The GUI module is not imported by the other tests (it needs a display), so at least make sure every module compiles."""

import py_compile
from pathlib import Path

import roundtable_souls


def test_every_module_compiles():
    root = Path(roundtable_souls.__file__).resolve().parent
    files = sorted(root.rglob("*.py"))
    assert any(p.name == "window.py" for p in files)
    for p in files:
        py_compile.compile(str(p), doraise=True)
