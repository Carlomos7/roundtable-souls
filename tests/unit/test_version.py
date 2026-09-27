"""The version the window shows must be the version the package is built as."""

import tomllib
from pathlib import Path

import roundtable_souls


def test_package_version_matches_pyproject():
    pyproject = Path(roundtable_souls.__file__).resolve().parents[2] / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    assert project["version"] == roundtable_souls.__version__
