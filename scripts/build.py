"""Build RoundtableSouls.exe: tests, icon, PyInstaller, then the share bundle.

uv run python scripts/build.py            everything
uv run python scripts/build.py --no-test  skip the test run
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "roundtable_souls"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
EXE_NAME = "RoundtableSouls"


def run(*args: str) -> None:
    print("+", " ".join(args))
    subprocess.run(list(args), check=True, cwd=ROOT)


def main() -> int:
    py = sys.executable
    if "--no-test" not in sys.argv:
        run(py, "-m", "pytest", "-q")
    run(py, str(ROOT / "scripts" / "make_icon.py"))
    run(
        py,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name",
        EXE_NAME,
        "--icon",
        str(PKG / "assets" / "icon.ico"),
        "--paths",
        str(ROOT / "src"),
        "--collect-data",
        "roundtable_souls",
        "--collect-all",
        "qfluentwidgets",
        "--collect-all",
        "py7zr",
        "--exclude-module",
        "tkinter",
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD / "work"),
        "--specpath",
        str(BUILD),
        str(ROOT / "scripts" / "entry.py"),
    )
    exe = DIST / f"{EXE_NAME}.exe"
    print("Built:", exe)
    run(py, str(ROOT / "scripts" / "make_share.py"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
