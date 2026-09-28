"""Newer launcher on GitHub Releases: the once-a-day check, and the download / verify / swap behind Update now."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

from roundtable_souls import __version__
from roundtable_souls.settings import load_settings, save_settings
from roundtable_souls.system import me3_info

REPO = "Carlomos7/roundtable-souls"
RELEASES_URL = f"https://github.com/{REPO}/releases"
RELEASES_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_EVERY = 3600  # seconds between GitHub calls (60 unauthenticated requests an hour are allowed)
ASSET_NAME = "RoundtableSouls.zip"
LINUX_ASSET_NAME = "RoundtableSouls-linux-x86_64.tar.gz"
SETUP_NAME = "RoundtableSouls-Setup.exe"
SILENT_SETUP_ARGS = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/RELAUNCH=1")
CHECKSUMS_NAME = "SHA256SUMS.txt"
PARKED_SUFFIX = ".old.exe"
BOOTLOADER_ENV_PREFIXES = ("_PYI_", "_MEIPASS")  # PyInstaller marks child processes through these


def child_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    """The environment for the relaunched exe, without PyInstaller's markers.

    A one-file exe started by another one-file exe at the same path inherits those markers and then reuses the
    parent's unpacked folder instead of unpacking its own. The parent is exiting, the folder disappears, and the
    child dies on its first import. Stripping the markers makes the new exe unpack itself like a fresh start.
    """
    src = os.environ if env is None else env
    return {k: v for k, v in src.items() if not k.startswith(BOOTLOADER_ENV_PREFIXES)}


Progress = Callable[[int, int], None]


class UpdateError(RuntimeError):
    """Something about the release or the download is not right; nothing was changed."""


def launcher_update(
    settings: dict | None = None,
    fetch: Callable[[str], dict | None] = me3_info.latest_release,
    now: Callable[[], float] = time.time,
    force: bool = False,
) -> dict | None:
    """{'version', 'url', 'assets'} when a newer release exists and the user has not skipped it, else None.

    The GitHub answer is cached in the settings for an hour; offline the cached answer (if any) is used.
    force asks GitHub regardless of the cache and ignores a skipped version (the Check now button).
    """
    s = load_settings() if settings is None else settings
    if not force and not bool(s.get("check_launcher_updates", True)):
        return None
    cached = s.get("launcher_latest")
    when = float(s.get("launcher_latest_checked") or 0)
    if force or not isinstance(cached, dict) or now() - when > CHECK_EVERY:
        rel = fetch(RELEASES_LATEST)
        if rel:
            cached = rel
            save_settings(launcher_latest=rel, launcher_latest_checked=now())
    if not isinstance(cached, dict):
        return None
    latest = str(cached.get("version") or "")
    if not me3_info.update_available(__version__, latest):
        return None
    if not force and str(s.get("launcher_update_skipped") or "") == latest:
        return None
    assets = cached.get("assets") if isinstance(cached.get("assets"), dict) else {}
    return {"version": latest, "url": str(cached.get("url") or RELEASES_URL), "assets": assets}


def skip_update(version: str) -> None:
    """Stop mentioning this version; the next one shows again."""
    save_settings(launcher_update_skipped=version)


# ---------------------------------------------------------------------------- download and swap


def fetch_bytes(url: str, timeout: float = 30.0, progress: Progress | None = None) -> bytes:
    """Download a URL in chunks, reporting (done, total) bytes; total is 0 when the server does not say."""
    req = urllib.request.Request(url, headers={"User-Agent": "Roundtable Souls"})
    chunks: list[bytes] = []
    done = 0
    with urllib.request.urlopen(req, timeout=timeout) as r:
        total = int(r.headers.get("Content-Length") or 0)
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    return b"".join(chunks)


def parse_checksums(text: str) -> dict[str, str]:
    """{file name: sha256 hex} from the 'hex  name' lines sha256sum and the build script write."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 64:
            out[parts[1].lstrip("*").strip()] = parts[0].lower()
    return out


def update_asset(installed: bool, platform: str = sys.platform) -> str:
    """The release file this copy updates from: the setup for an installed Windows copy, the zip for a portable one,
    the tar.gz on Linux."""
    if platform.startswith("linux"):
        return LINUX_ASSET_NAME
    return SETUP_NAME if installed else ASSET_NAME


def can_self_update(info: dict, installed: bool, platform: str = sys.platform) -> bool:
    assets = info.get("assets") or {}
    return update_asset(installed, platform) in assets and CHECKSUMS_NAME in assets


def download_update(
    info: dict,
    opener: Callable[..., bytes] = fetch_bytes,
    progress: Progress | None = None,
    workdir: Path | None = None,
    installed: bool = False,
    platform: str = sys.platform,
) -> Path:
    """Fetch the release file for this kind of copy and check its SHA-256 against the release's checksum file.

    Returns, inside a fresh temp folder, the setup to run (installed copy) or the exe unpacked from the zip (portable
    copy). Raises UpdateError when the release lacks the files or the checksum does not match; nothing that is
    running is touched here.
    """
    name = update_asset(installed, platform)
    assets = info.get("assets") or {}
    file_url, sums_url = assets.get(name), assets.get(CHECKSUMS_NAME)
    if not file_url or not sums_url:
        raise UpdateError(
            f"This release has no {name} or no checksum file; download it from the releases page instead."
        )
    sums = parse_checksums(opener(sums_url).decode("utf-8", "replace"))
    expected = sums.get(name)
    if not expected:
        raise UpdateError(f"{CHECKSUMS_NAME} does not list {name}.")
    data = opener(file_url, progress=progress) if progress else opener(file_url)
    if hashlib.sha256(data).hexdigest() != expected:
        raise UpdateError("The download did not match its checksum. Nothing was changed; try again later.")
    folder = Path(tempfile.mkdtemp(prefix="roundtable-update-", dir=workdir))
    if name == SETUP_NAME:
        setup = folder / SETUP_NAME
        setup.write_bytes(data)
        return setup
    archive = folder / name
    archive.write_bytes(data)
    if name.endswith(".tar.gz"):
        with tarfile.open(archive, "r:gz") as tar:
            member = next((m for m in tar.getmembers() if m.isfile() and m.name == "RoundtableSouls"), None)
            if member is None:
                raise UpdateError("The archive holds no RoundtableSouls program.")
            tar.extract(member, folder, filter="data")
        program = folder / member.name
        program.chmod(0o755)
        return program
    with zipfile.ZipFile(archive) as z:
        exe_name = next((n for n in z.namelist() if n.lower().endswith(".exe") and "/" not in n), None)
        if not exe_name:
            raise UpdateError("The zip holds no exe.")
        z.extract(exe_name, folder)
    return folder / exe_name


def apply_update(new_exe: Path, current_exe: Path, restart: bool = True) -> Path:
    """Park the running exe as .old.exe, put the new one in its place and start it. Returns the parked path.

    Windows lets a running exe be renamed but not overwritten, which is what makes this work without a helper.
    On any failure the original is put back before the error is raised.
    """
    new_exe, current_exe = Path(new_exe), Path(current_exe)
    parked = parked_path(current_exe)
    if parked.exists():
        parked.unlink()
    current_exe.rename(parked)
    try:
        shutil.move(str(new_exe), str(current_exe))
        if current_exe.suffix != ".exe":
            current_exe.chmod(0o755)
    except Exception:
        parked.rename(current_exe)
        raise
    if restart:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(
            [str(current_exe)],
            cwd=str(current_exe.parent),
            env=child_environment(),
            close_fds=True,
            creationflags=flags,
        )
    return parked


def run_installer(setup: Path) -> None:
    """Start the downloaded setup silently. It closes this app, installs over the same folder and reopens it."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [str(setup), *SILENT_SETUP_ARGS],
        cwd=str(Path(setup).parent),
        env=child_environment(),
        close_fds=True,
        creationflags=flags,
    )


def parked_path(current_exe: Path) -> Path:
    """Where an update parks the running program: RoundtableSouls.old.exe on Windows, RoundtableSouls.old on Linux."""
    current_exe = Path(current_exe)
    if current_exe.suffix.lower() == ".exe":
        return current_exe.with_name(current_exe.stem + PARKED_SUFFIX)
    return current_exe.with_name(current_exe.name + ".old")


def remove_parked_exe(current_exe: Path) -> bool:
    """Delete the program an update parked; False when it is still in use (the old process is exiting)."""
    parked = parked_path(current_exe)
    if not parked.exists():
        return True
    try:
        parked.unlink()
        return True
    except OSError:
        return False
