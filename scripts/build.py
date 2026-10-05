"""Build Roundtable Souls: tests, icon, PyInstaller (one folder), then a Velopack release with vpk, then the share
bundle (scripts/make_share.py).

uv run python scripts/build.py                     everything
uv run python scripts/build.py --no-test           skip the test run
uv run python scripts/build.py --no-pack           PyInstaller only (dist/RoundtableSouls), no vpk
uv run python scripts/build.py --identity t.json   bake an identity override into the build (isolated test builds:
                                                   own app ID, title, feed and key; see src/roundtable_souls/config/identity.py)

vpk must match the velopack package in uv.lock (VPK_VERSION); it is found as $VPK, then on PATH. Windows builds
pack for win-x64 (Setup.exe, a portable zip, packages), Linux builds an AppImage for linux-x64. A previous release's
full package in dist/vpk (vpk download github) lets vpk make a delta package.
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
VPK_VERSION = "1.2.161"  # = the velopack Python package pinned in pyproject.toml
WINDOWS = sys.platform == "win32"


def run(*args: str | Path, env: dict | None = None) -> None:
    print("+", " ".join(map(str, args)), flush=True)
    subprocess.run([str(a) for a in args], check=True, cwd=ROOT, env=env)


def project_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def find_vpk() -> str | None:
    return next((c for c in (os.environ.get("VPK"), shutil.which("vpk")) if c and Path(c).is_file()), None)


def linux_icon() -> Path:
    """vpk needs a PNG for the AppImage; the largest frame of the Windows icon."""
    from PIL import Image

    out = BUILD / "icon.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(PKG / "assets" / "icon.ico") as ico:
        ico.size = max(ico.ico.sizes())  # type: ignore[attr-defined]
        ico.save(out)
    return out


def pyinstaller(py: str, identity_file: Path | None) -> Path:
    extra: list[str | Path] = []
    if identity_file:  # added explicitly: --collect-data may read the package from wherever it is installed
        staged = BUILD / "identity" / "build-identity.json"
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(identity_file, staged)
        extra = ["--add-data", f"{staged}{os.pathsep}roundtable_souls/data"]
    # Alembic loads the migration scripts by path, so they ship as files (--collect-data leaves .py files out).
    extra += ["--add-data", f"{PKG / 'storage' / 'migrations'}{os.pathsep}roundtable_souls/storage/migrations"]
    run(
        py, "-m", "PyInstaller", "--noconfirm", "--onedir", "--windowed", "--name", EXE_NAME,
        "--icon", PKG / "assets" / "icon.ico", "--paths", ROOT / "src",
        "--collect-data", "roundtable_souls", "--collect-all", "qfluentwidgets", "--collect-all", "py7zr",
        "--collect-all", "velopack", "--exclude-module", "tkinter", *extra,
        "--distpath", DIST, "--workpath", BUILD / "work", "--specpath", BUILD, ROOT / "scripts" / "entry.py",
    )  # fmt: skip
    folder = DIST / EXE_NAME
    check_identity(folder, identity_file)
    check_migrations(folder)
    print("Built:", folder)
    return folder


def check_identity(folder: Path, identity_file: Path | None) -> None:
    """A test build must carry exactly its identity file, and a release build none: a build with the wrong identity
    would act on the wrong install."""
    found = list(folder.rglob("build-identity.json"))
    if identity_file is None:
        if found:
            raise SystemExit(f"build: a release build must not carry an identity override: {found}")
        return
    if len(found) != 1 or found[0].read_bytes() != identity_file.read_bytes():
        raise SystemExit(f"build: the identity override did not make it into the build exactly ({found})")


def check_migrations(folder: Path) -> None:
    """Every migration script and Alembic's env.py must be in the build as a file, byte for byte; without them the
    packaged program cannot create or upgrade its database. (Running the build with --check-storage then proves it
    opens one: the release workflow does.)"""
    source = PKG / "storage" / "migrations"
    wanted = [p.relative_to(source) for p in source.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    shipped = next((p for p in folder.rglob("migrations") if p.parent.name == "storage"), None)
    missing = [
        str(w)
        for w in wanted
        if shipped is None or not (shipped / w).is_file() or (shipped / w).read_bytes() != (source / w).read_bytes()
    ]
    if missing or not any(w.parts[0] == "versions" for w in wanted):
        raise SystemExit(f"build: the database migrations did not make it into the build: {missing or 'none found'}")


def check_sqlite() -> None:
    """The SQLite inside the Python being packaged must meet the storage minimum: a build below it would ship a
    program that runs without its database. Checked before anything is built."""
    import sqlite3

    sys.path.insert(0, str(ROOT / "src"))
    from roundtable_souls.storage.db import sqlite_problem

    problem = sqlite_problem(sqlite3.sqlite_version)
    if problem:
        raise SystemExit(f"build: {problem} (Python {sys.version.split()[0]} at {sys.executable}; see .python-version)")
    print(f"SQLite {sqlite3.sqlite_version} (Python {sys.version.split()[0]})")


def load_identity(path: Path | None):
    """The identity a build is packed as: the override file's values over the defaults."""
    import json
    from dataclasses import fields

    sys.path.insert(0, str(ROOT / "src"))
    from roundtable_souls.config.identity import Identity

    if path is None:
        return Identity()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Identity(**{f.name: str(raw[f.name]) for f in fields(Identity) if f.name in raw})


def pack(vpk: str, folder: Path, version: str, ident) -> Path:
    out = DIST / "vpk"
    out.mkdir(parents=True, exist_ok=True)
    args: list[str | Path] = [
        vpk, "pack", "--skip-updates", "--packId", ident.pack_id, "--packVersion", version, "--packDir", folder,
        "--packTitle", ident.title, "--packAuthors", "Carlomos7", "--outputDir", out,
    ]  # fmt: skip
    if WINDOWS:
        args += ["--mainExe", f"{EXE_NAME}.exe", "--runtime", "win-x64", "--icon", PKG / "assets" / "icon.ico"]
        args += ["--shortcuts", "StartMenuRoot"]  # as the Inno setup did; the desktop shortcut stays a user choice
    else:
        args += ["--mainExe", EXE_NAME, "--runtime", "linux-x64", "--icon", linux_icon()]
    run(*args)
    return out


def main() -> int:
    py = sys.executable
    argv = sys.argv[1:]
    identity_file = None
    if "--identity" in argv:
        identity_file = Path(argv[argv.index("--identity") + 1]).resolve()
    check_sqlite()
    if "--no-test" not in argv:
        run(py, "-m", "pytest", "-q")
    if WINDOWS:
        run(py, ROOT / "scripts" / "make_icon.py")
    shutil.rmtree(DIST / EXE_NAME, ignore_errors=True)
    folder = pyinstaller(py, identity_file)
    if "--no-pack" in argv:
        return 0
    vpk = find_vpk()
    if not vpk:
        print(f"vpk not found: skipping the Velopack release (dotnet tool install vpk --version {VPK_VERSION})")
        return 0
    ident = load_identity(identity_file)
    pack(vpk, folder, project_version(), ident)
    run(py, ROOT / "scripts" / "make_share.py", "--pack-id", ident.pack_id, "--version", project_version())
    return 0


if __name__ == "__main__":
    sys.exit(main())
