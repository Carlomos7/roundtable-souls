"""The Velopack version is pinned in three places that must agree: the Python package in pyproject.toml, the vpk CLI the
release workflow installs, and the vpk version scripts/build.py expects."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _one(pattern: str, text: str, where: str) -> str:
    found = re.findall(pattern, text, re.M)
    assert len(found) == 1, f"{where}: expected one match for {pattern!r}, found {found}"
    return found[0]


def test_the_three_velopack_pins_agree():
    package = _one(r'^\s*"velopack==([0-9.]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), "pyproject")
    workflow = _one(
        r'^\s*VPK_VERSION:\s*"([0-9.]+)"',
        (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"),
        "release.yml",
    )
    build = _one(r'^VPK_VERSION = "([0-9.]+)"', (ROOT / "scripts" / "build.py").read_text(encoding="utf-8"), "build.py")
    assert package == workflow == build, f"pyproject {package}, release.yml {workflow}, build.py {build}"
