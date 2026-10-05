"""Unpacking a mod download: .zip, .7z and .rar archives (paths that would land outside the target refused), or a folder used where it is, into a staging folder."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from roundtable_souls.mods.profile_edit import (
    ModError,
)

ARCHIVE_EXTENSIONS = (
    ".zip",
    ".7z",
    ".rar",
)  # .7z via py7zr (bundled), .rar via an extractor on the PC


def _unsafe(name: str) -> bool:
    name = name.replace("\\", "/")
    return name.startswith("/") or ".." in name.split("/") or (len(name) > 1 and name[1] == ":")


def extract_zip(archive: Path, dest: Path) -> Path:
    """Extract a .zip into dest, refusing entries that would escape it."""
    archive = Path(archive)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if _unsafe(info.filename):
                raise ModError(f"archive entry escapes the folder: {info.filename}")
        z.extractall(dest)
    return dest


def extract_7z(archive: Path, dest: Path) -> Path:
    """.7z through py7zr (bundled in the exe); entries that would escape the folder are refused."""
    try:
        import py7zr
    except ImportError as e:
        raise ModError("7z support is missing from this build") from e
    archive = Path(archive)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with py7zr.SevenZipFile(archive, "r") as z:
            for name in z.getnames():
                if _unsafe(name):
                    raise ModError(f"archive entry escapes the folder: {name}")
            z.extractall(path=dest)
    except ModError:
        raise
    except Exception as e:
        raise ModError(f"could not read the 7z archive: {e}") from e
    return dest


def _no_window():
    try:
        from roundtable_souls.platform import proc

        return proc.NO_WINDOW
    except Exception:
        return 0


def rar_tools() -> list[list[str]]:
    """Command lines that can unpack .rar on this PC, best first: Windows' own bsdtar (libarchive reads RAR and RAR5),
    then 7-Zip, then WinRAR's UnRAR. Each takes the archive and the destination appended by extract_rar."""
    tools = []
    win = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
    if win.is_file():
        tools.append([str(win), "-xf"])
    for pf in filter(None, (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"))):
        for exe in (Path(pf) / "7-Zip" / "7z.exe", Path(pf) / "WinRAR" / "UnRAR.exe"):
            if exe.is_file():
                tools.append([str(exe), "x", "-y"])
    return tools


def extract_rar(archive: Path, dest: Path) -> Path:
    """.rar through whichever extractor the PC has. bsdtar refuses absolute and .. paths on its own; the others
    are followed by a check that nothing landed outside dest."""
    archive = Path(archive)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    tools = rar_tools()
    if not tools:
        raise ModError(
            "no .rar extractor found: Windows' tar.exe, 7-Zip or WinRAR is needed, or unpack it first and install the folder"
        )
    errors = []
    for tool in tools:
        if tool[1] == "-xf":
            cmd = tool + [str(archive), "-C", str(dest)]
        else:
            cmd = tool + [str(archive), f"-o{dest}"]
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                creationflags=_no_window(),
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            errors.append(f"{Path(tool[0]).name}: {e}")
            continue
        if r.returncode == 0 and any(dest.iterdir()):
            root = dest.resolve()
            for p in dest.rglob("*"):
                if root not in p.resolve().parents and p.resolve() != root:
                    shutil.rmtree(dest, ignore_errors=True)
                    raise ModError("archive tried to write outside the folder; refused")
            return dest
        errors.append(
            f"{Path(tool[0]).name}: {(r.stderr or r.stdout or '').strip()[:200] or 'exit ' + str(r.returncode)}"
        )
        for p in dest.iterdir():
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    raise ModError("could not unpack the .rar: " + "; ".join(errors))


def extract_archive(archive: Path, dest: Path) -> Path:
    ext = Path(archive).suffix.lower()
    if ext == ".zip":
        return extract_zip(archive, dest)
    if ext == ".7z":
        return extract_7z(archive, dest)
    if ext == ".rar":
        return extract_rar(archive, dest)
    raise ModError(f"{ext or 'that file'} is not a supported archive (zip, 7z, rar)")


def stage(source: Path, staging_root: Path) -> tuple[Path, bool]:
    """(folder to detect from, is_temporary). Archives are extracted, and a lone .dll copied, into a temp folder under
    staging_root."""
    source = Path(source)
    if source.is_dir():
        return source, False
    if source.suffix.lower() in ARCHIVE_EXTENSIONS:
        tmp = Path(tempfile.mkdtemp(prefix="install-", dir=str(staging_root)))
        try:
            extract_archive(source, tmp)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return tmp, True
    if source.suffix.lower() == ".dll" and source.is_file():  # a DLL mod on its own
        tmp = Path(tempfile.mkdtemp(prefix="install-", dir=str(staging_root)))
        (tmp / source.stem).mkdir()
        shutil.copy2(source, tmp / source.stem / source.name)
        return tmp, True
    raise ModError("pick a .zip, .7z or .rar archive, a .dll, or a folder")
