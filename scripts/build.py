"""Build RoundtableSouls.exe: tests, icon, PyInstaller, the installer (when Inno Setup is available), then the
share bundle and its checksums.

uv run python scripts/build.py            everything
uv run python scripts/build.py --no-test  skip the test run
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "roundtable_souls"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
EXE_NAME = "RoundtableSouls"


def run(*args: str) -> None:
    print("+", " ".join(args))
    subprocess.run(list(args), check=True, cwd=ROOT)


def find_iscc() -> str | None:
    """Inno Setup's compiler: ISCC on PATH or in ISCC, else its usual install folders."""
    candidates = [
        os.environ.get("ISCC"),
        shutil.which("ISCC"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    return next((c for c in candidates if c and Path(c).is_file()), None)


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
    exe = DIST / (f"{EXE_NAME}.exe" if sys.platform == "win32" else EXE_NAME)
    print("Built:", exe)
    iscc = find_iscc() if sys.platform == "win32" else None
    if iscc:
        version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        run(iscc, "/Q", f"/DAppVersion={version}", str(ROOT / "installer" / "RoundtableSouls.iss"))
        print("Built:", DIST / "share" / f"{EXE_NAME}-Setup.exe")
    elif sys.platform == "win32":
        print("Inno Setup not found: skipping the installer (set ISCC to its ISCC.exe)")
    run(py, str(ROOT / "scripts" / "make_share.py"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
