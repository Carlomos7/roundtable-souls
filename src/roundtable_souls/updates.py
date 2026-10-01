"""Newer launcher on GitHub Releases: the check, the download / verify / swap behind Update now, and making sure an
update either lands or is reported.

The check
  At most once an hour (CHECK_EVERY) on start, from /releases/latest (Stable) or /releases (Beta, which includes
  pre-releases). The answer is cached with its ETag; asking again with If-None-Match costs nothing against GitHub's
  limit when nothing changed. A failed check says why (offline, GitHub's limit, an error) and is never reported as
  "up to date"; each failure in a row doubles the wait before the next automatic one (at most a day).

The download
  The release file for this kind of copy (setup, zip or tar.gz) streams into the data folder's updates/<version>
  as a .part file, hashed while it is written, and resumes after an interruption. Before any hash is trusted, the
  checksum file's minisign signature is checked against the project key shipped inside the launcher, and its trusted
  comment must name the version being installed. A release that is not newer than this copy is refused.

Applying it
  Installed copy: the setup runs silently with a log, into this copy's folder; it reopens the launcher whether it
  succeeds or not, and the next start compares the running version with the one that was pending.
  Portable copy: the running exe is parked as .old.exe, the new one takes its place and starts, and this process
  waits for it to report that its window opened. If it exits without reporting, the old exe is put back.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roundtable_souls import __version__, folders, signing
from roundtable_souls.settings import change_settings, load_settings, save_settings
from roundtable_souls.system import instance

REPO = "Carlomos7/roundtable-souls"
RELEASES_URL = f"https://github.com/{REPO}/releases"
RELEASES_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_LIST = f"https://api.github.com/repos/{REPO}/releases?per_page=20"
ADVISORY_URL = f"https://raw.githubusercontent.com/{REPO}/main/advisory.json"
CHECK_EVERY = 3600  # seconds between automatic checks (60 unauthenticated GitHub API requests an hour are allowed)
MAX_BACKOFF = 24 * 3600  # the longest wait after failed checks
ASSET_NAME = "RoundtableSouls.zip"
LINUX_ASSET_NAME = "RoundtableSouls-linux-x86_64.tar.gz"
SETUP_NAME = "RoundtableSouls-Setup.exe"
CHECKSUMS_NAME = "SHA256SUMS.txt"
SIGNATURE_NAME = "SHA256SUMS.txt.minisig"
SIGNED_COMMENT = "roundtable-souls {version}"  # the trusted comment release.yml signs with
SILENT_SETUP_ARGS = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS")
PARKED_SUFFIX = ".old.exe"
FAILED_SUFFIX = ".failed.exe"
WAIT_FOR_NEW = 90.0  # seconds the old copy waits for the new one to report that it started
OLD_TEMP_PREFIX = "roundtable-update-"  # where versions before this one left their downloads
BOOTLOADER_ENV_PREFIXES = ("_PYI_", "_MEIPASS")  # PyInstaller marks child processes through these
USER_AGENT = f"Roundtable Souls/{__version__}"

Progress = Callable[[int, int], None]
Opener = Callable[..., Any]


class UpdateError(RuntimeError):
    """Something about the release or the download is not right; nothing was changed."""


def child_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    """The environment for the relaunched exe, without PyInstaller's markers.

    A one-file exe started by another one-file exe at the same path inherits those markers and then reuses the
    parent's unpacked folder instead of unpacking its own. The parent is exiting, the folder disappears, and the
    child dies on its first import. Stripping the markers makes the new exe unpack itself like a fresh start.
    """
    src = os.environ if env is None else env
    return {k: v for k, v in src.items() if not k.startswith(BOOTLOADER_ENV_PREFIXES)}


# ---------------------------------------------------------------------------- versions

_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:[-.]?(dev|alpha|beta|preview|pre|rc|a|b|c)[.-]?(\d*))?", re.I)
_PRE_RANK = {"dev": 0, "a": 1, "alpha": 1, "b": 2, "beta": 2, "c": 3, "pre": 3, "preview": 3, "rc": 3}
_PRE_NAME = {0: "dev", 1: "alpha", 2: "beta", 3: "rc"}


def version_key(text: str | None) -> tuple:
    """A sortable key: 3.14.0-dev < -alpha < -beta < -rc.1 < -rc.2 < 3.14.0 < 3.14.1. () when there is no version."""
    m = _VERSION.search(text or "")
    if not m:
        return ()
    major, minor, patch = (int(x) for x in m.group(1, 2, 3))
    if m.group(4) is None:
        return (major, minor, patch, 1, 0, 0)
    return (major, minor, patch, 0, _PRE_RANK[m.group(4).lower()], int(m.group(5) or 0))


def parse_version(text: str | None) -> str | None:
    """The version in a tag or text, written one way: '3.14.0' or '3.14.0-rc.1'."""
    key = version_key(text)
    if not key:
        return None
    base = f"{key[0]}.{key[1]}.{key[2]}"
    return base if key[3] else f"{base}-{_PRE_NAME[key[4]]}.{key[5]}"


def is_newer(candidate: str | None, current: str | None = __version__) -> bool:
    a, b = version_key(candidate), version_key(current)
    return bool(a and b and a > b)


def is_prerelease(version: str | None) -> bool:
    key = version_key(version)
    return bool(key) and not key[3]


# ---------------------------------------------------------------------------- asking GitHub


@dataclass
class Fetched:
    """One answer from the network. status: ok, not_modified, offline, rate_limited or error."""

    status: str
    data: Any = None
    etag: str = ""
    reason: str = ""
    retry_at: float = 0.0


def _get_json(url: str, etag: str = "", timeout: float = 8.0, opener: Opener = urllib.request.urlopen, now=time.time):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    if etag:
        headers["If-None-Match"] = etag
    req = urllib.request.Request(url, headers=headers)
    try:
        with opener(req, timeout=timeout) as r:
            body = r.read()
            new_etag = str(r.headers.get("ETag") or "")
    except urllib.error.HTTPError as e:
        hdrs = e.headers or {}
        if e.code == 304:
            return Fetched("not_modified", etag=etag)
        if e.code == 429 or (e.code == 403 and str(hdrs.get("X-RateLimit-Remaining", "")) == "0"):
            retry_at = 0.0
            try:
                if hdrs.get("Retry-After"):
                    retry_at = now() + float(hdrs["Retry-After"])
                elif hdrs.get("X-RateLimit-Reset"):
                    retry_at = float(hdrs["X-RateLimit-Reset"])
            except TypeError, ValueError:
                pass
            return Fetched(
                "rate_limited", reason="GitHub's hourly limit for this network is used up", retry_at=retry_at
            )
        if e.code == 404:
            return Fetched("error", reason="GitHub has no release for this project")
        return Fetched("error", reason=f"GitHub answered {e.code} {e.reason}")
    except urllib.error.URLError as e:
        return Fetched("offline", reason=f"GitHub could not be reached ({e.reason})")
    except OSError as e:
        return Fetched("offline", reason=f"GitHub could not be reached ({e})")
    try:
        return Fetched("ok", data=json.loads(body.decode("utf-8")), etag=new_etag)
    except ValueError:
        return Fetched("error", reason="GitHub's answer could not be read")


def release_from_json(doc: Any) -> dict | None:
    """{'version', 'tag', 'url', 'assets', 'notes', 'prerelease'} from one GitHub release; None for a draft or a
    release without a version in its tag."""
    if not isinstance(doc, dict) or doc.get("draft"):
        return None
    version = parse_version(str(doc.get("tag_name") or doc.get("name") or ""))
    if not version:
        return None
    assets = {
        str(a.get("name")): str(a.get("browser_download_url"))
        for a in doc.get("assets") or []
        if isinstance(a, dict) and a.get("name") and a.get("browser_download_url")
    }
    return {
        "version": version,
        "tag": str(doc.get("tag_name") or ""),
        "url": str(doc.get("html_url") or RELEASES_URL),
        "assets": assets,
        "notes": str(doc.get("body") or "")[:20000],
        "prerelease": bool(doc.get("prerelease")) or is_prerelease(version),
    }


def pick_release(data: Any, channel: str) -> dict | None:
    """The release a channel offers: Stable takes /releases/latest as it is; Beta the highest version of the list."""
    if channel == "beta":
        found = [r for r in (release_from_json(d) for d in data) if r] if isinstance(data, list) else []
        return max(found, key=lambda r: version_key(r["version"]), default=None)
    release = release_from_json(data)
    return release if release and not release["prerelease"] else None


def fetch_release(channel: str = "stable", etag: str = "", opener: Opener = urllib.request.urlopen, now=time.time):
    """Fetched with data = the release the channel offers (or None when it has none)."""
    url = RELEASES_LIST if channel == "beta" else RELEASES_LATEST
    got = _get_json(url, etag=etag, opener=opener, now=now)
    if got.status == "ok":
        got.data = pick_release(got.data, channel)
    return got


@dataclass
class UpdateCheck:
    """What a check found.

    status: fresh (GitHub answered now), cached (the answer from the last hour), waiting (backing off after failed
    checks), off (checks are turned off), or a failure of this check: offline, rate_limited, error.
    offer: the release to show a notice for, or None. checked: when GitHub last answered (0 when never).
    """

    status: str
    offer: dict | None = None
    checked: float = 0.0
    reason: str = ""
    retry_at: float = 0.0

    @property
    def failed(self) -> bool:
        return self.status in ("offline", "rate_limited", "error")


def _backoff(failures: int, rand: Callable[[], float]) -> float:
    return min(CHECK_EVERY * 2 ** max(failures - 1, 0), MAX_BACKOFF) * (1 + 0.2 * rand())


def check_launcher_update(
    settings: dict | None = None,
    fetch: Callable[..., Fetched] = fetch_release,
    now: Callable[[], float] = time.time,
    force: bool = False,
    rand: Callable[[], float] = random.random,
    current: str = __version__,
) -> UpdateCheck:
    """Ask (or reuse the last hour's answer) whether a newer release exists on the chosen channel.

    force (Check for updates) asks GitHub now, ignoring the off switch, the backoff and a skipped version.
    """
    s = load_settings() if settings is None else settings
    if not force and not bool(s.get("check_launcher_updates", True)):
        return UpdateCheck("off")
    channel = "beta" if s.get("launcher_channel") == "beta" else "stable"
    cached = s.get("launcher_latest")
    if not isinstance(cached, dict) or cached.get("channel") != channel:
        cached = None  # another channel's answer says nothing about this one
    checked = float(s.get("launcher_latest_checked") or 0) if cached else 0.0
    status, reason, retry_at = "cached", "", 0.0
    due = force or cached is None or now() - checked > CHECK_EVERY
    if due and not force and now() < float(s.get("launcher_next_check") or 0):
        due, status = False, "waiting"
        reason = str(s.get("launcher_check_error") or "")
        retry_at = float(s.get("launcher_next_check") or 0)
    if due:
        got = fetch(channel=channel, etag=str(s.get("launcher_latest_etag") or "") if cached else "")
        when = now()
        if got.status in ("ok", "not_modified"):
            if got.status == "ok":
                cached = {**(got.data or {"version": ""}), "channel": channel}
            save_settings(
                launcher_latest=cached,
                launcher_latest_checked=when,
                launcher_latest_etag=got.etag,
                launcher_check_failures=0,
                launcher_next_check=0.0,
                launcher_check_error="",
            )
            status, checked = "fresh", when
        else:

            def failed(cur: dict) -> dict:
                failures = int(cur.get("launcher_check_failures") or 0) + 1
                wait = max(got.retry_at - when, 60.0) if got.retry_at else _backoff(failures, rand)
                return {
                    "launcher_check_failures": failures,
                    "launcher_next_check": when + wait,
                    "launcher_check_error": got.reason,
                }

            wrote = change_settings(failed)
            status, reason, retry_at = got.status, got.reason, float(wrote["launcher_next_check"])
    offer = None
    if cached and is_newer(cached.get("version"), current):
        if force or str(s.get("launcher_update_skipped") or "") != cached.get("version"):
            offer = {k: v for k, v in cached.items() if k != "channel"}
            offer["url"] = offer.get("url") or RELEASES_URL
            offer["assets"] = offer.get("assets") or {}
    return UpdateCheck(status, offer=offer, checked=checked, reason=reason, retry_at=retry_at)


def skip_update(version: str) -> None:
    """Stop mentioning this version; the next one shows again."""
    save_settings(launcher_update_skipped=version)


def fetch_advisory(etag: str = "", opener: Opener = urllib.request.urlopen, now=time.time) -> Fetched:
    """The project's minimum-version notice (advisory.json on main): {'minimum': version or None, 'message', 'url'}."""
    got = _get_json(ADVISORY_URL, etag=etag, opener=opener, now=now)
    if got.status == "ok":
        doc = got.data if isinstance(got.data, dict) else {}
        got.data = {
            "minimum": parse_version(str(doc.get("minimum") or "")),
            "message": str(doc.get("message") or "")[:500],
            "url": str(doc.get("url") or RELEASES_URL),
        }
    return got


def check_advisory(
    settings: dict | None = None,
    fetch: Callable[..., Fetched] = fetch_advisory,
    now: Callable[[], float] = time.time,
    force: bool = False,
    current: str = __version__,
) -> dict | None:
    """The notice when this version is below the project's minimum, else None. Fetched at most hourly with the
    update check (from raw.githubusercontent.com, which does not use GitHub's API limit). It only warns: nothing is
    installed because of it."""
    s = load_settings() if settings is None else settings
    if not force and not bool(s.get("check_launcher_updates", True)):
        return None
    cached = s.get("launcher_advisory") if isinstance(s.get("launcher_advisory"), dict) else None
    if force or cached is None or now() - float(s.get("launcher_advisory_checked") or 0) > CHECK_EVERY:
        got = fetch(etag=str(s.get("launcher_advisory_etag") or "") if cached else "")
        if got.status == "ok":
            cached = got.data
            save_settings(launcher_advisory=cached, launcher_advisory_etag=got.etag, launcher_advisory_checked=now())
        elif got.status == "not_modified":
            save_settings(launcher_advisory_checked=now())
    if cached and cached.get("minimum") and is_newer(cached["minimum"], current):
        return cached
    return None


def release_notes(notes: str, lines: int = 6) -> str:
    """The first lines of a release's notes as plain text (headings, links and list marks taken out)."""
    out = []
    for raw in (notes or "").splitlines():
        line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", raw).strip()
        line = re.sub(r"^#+\s*", "", line)
        line = re.sub(r"^[-*+]\s+", "\u2022 ", line)
        line = line.replace("**", "").replace("`", "")
        if not line or line.startswith("<!--"):
            continue
        out.append(line if len(line) <= 160 else line[:157] + "...")
        if len(out) >= lines:
            break
    return "\n".join(out)


# ---------------------------------------------------------------------------- download


def fetch_bytes(url: str, timeout: float = 30.0, opener: Opener = urllib.request.urlopen) -> bytes:
    """A small file (the checksums and their signature), whole."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener(req, timeout=timeout) as r:
            return r.read(4 * 1024 * 1024)
    except urllib.error.HTTPError as e:
        raise UpdateError(f"Downloading {url.rsplit('/', 1)[-1]} failed: {e.code} {e.reason}.") from None
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError(f"Downloading failed: {getattr(e, 'reason', e)}. Nothing was changed.") from None


def _sha256_of(path: Path) -> Any:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h


def fetch_to_file(
    url: str,
    part: Path,
    progress: Progress | None = None,
    timeout: float = 30.0,
    opener: Opener = urllib.request.urlopen,
) -> str:
    """Stream url into part, continuing a partial file with a Range request; returns the SHA-256 of the whole file.

    A server that ignores the Range (200 instead of 206) or refuses it (416) gets a fresh download."""
    for attempt in (1, 2):
        have = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": USER_AGENT}
        if have:
            headers["Range"] = f"bytes={have}-"
        req = urllib.request.Request(url, headers=headers)
        try:
            with opener(req, timeout=timeout) as r:
                if have and int(getattr(r, "status", 200) or 200) != 206:
                    have = 0
                h = _sha256_of(part) if have else hashlib.sha256()
                length = int(r.headers.get("Content-Length") or 0)
                total = have + length if length else 0  # 0: the server did not say
                done = have
                with part.open("ab" if have else "wb") as out:
                    while chunk := r.read(256 * 1024):
                        out.write(chunk)
                        h.update(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, max(total, done) if total else 0)
                return h.hexdigest()
        except urllib.error.HTTPError as e:
            if e.code == 416 and attempt == 1:
                part.unlink(missing_ok=True)
                continue
            raise UpdateError(f"Downloading failed: {e.code} {e.reason}. Nothing was changed.") from None
        except (urllib.error.URLError, OSError) as e:
            raise UpdateError(
                f"Downloading stopped ({getattr(e, 'reason', e)}). Nothing was changed; Update now continues where "
                "it stopped."
            ) from None
    raise UpdateError("Downloading failed. Nothing was changed.")


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
    """Whether Update now can do it: the release has this copy's file, the checksums and their signature (releases
    from before signing go through the releases page)."""
    assets = info.get("assets") or {}
    return all(n in assets for n in (update_asset(installed, platform), CHECKSUMS_NAME, SIGNATURE_NAME))


def updates_dir() -> Path:
    return folders.data_root() / "updates"


def verified_checksums(info: dict, fetch: Callable[[str], bytes] = fetch_bytes, key=None) -> dict[str, str]:
    """The release's checksums, once their signature checks out with the project key and its trusted comment names
    this release's version (so an older release's signed checksums cannot be passed off as this one's)."""
    assets = info.get("assets") or {}
    sums_url, sig_url = assets.get(CHECKSUMS_NAME), assets.get(SIGNATURE_NAME)
    if not sums_url or not sig_url:
        raise UpdateError("This release is not signed; download it from the releases page instead.")
    sums = fetch(sums_url)
    signature = fetch(sig_url).decode("utf-8", "replace")
    try:
        comment = signing.verify(sums, signature, key or signing.release_key())
    except signing.SignatureError as e:
        raise UpdateError(f"The release's signature did not check out: {e} Nothing was changed.") from None
    prefix = SIGNED_COMMENT.format(version="")
    signed = comment[len(prefix) :] if comment.startswith(prefix) else ""
    if not signed or version_key(signed) != version_key(str(info.get("version"))):
        raise UpdateError(
            f"The signed checksums are for {signed or 'another release'}, not {info.get('version')}. "
            "Nothing was changed."
        )
    return parse_checksums(sums.decode("utf-8", "replace"))


def download_update(
    info: dict,
    fetch_file: Callable[..., str] = fetch_to_file,
    fetch: Callable[[str], bytes] = fetch_bytes,
    progress: Progress | None = None,
    workdir: Path | None = None,
    installed: bool = False,
    platform: str = sys.platform,
    key=None,
    current: str = __version__,
) -> Path:
    """Fetch and verify the release file for this kind of copy. Returns the setup to run (installed copy) or the
    program unpacked from the archive (portable copy). Raises UpdateError when the release is not newer, is not
    signed with the project key, or the download does not match; nothing that is running is touched here."""
    version = parse_version(str(info.get("version") or ""))
    if not version or not is_newer(version, current):
        raise UpdateError(f"{info.get('version')} is not newer than this copy ({current}); nothing was changed.")
    name = update_asset(installed, platform)
    file_url = (info.get("assets") or {}).get(name)
    if not file_url:
        raise UpdateError(f"This release has no {name}; download it from the releases page instead.")
    expected = verified_checksums(info, fetch=fetch, key=key).get(name)
    if not expected:
        raise UpdateError(f"{CHECKSUMS_NAME} does not list {name}.")
    folder = (workdir or updates_dir()) / version
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    if not (target.is_file() and _sha256_of(target).hexdigest() == expected):  # a finished earlier download is reused
        part = folder / (name + ".part")
        digest = fetch_file(file_url, part, progress=progress)
        if digest != expected:
            part.unlink(missing_ok=True)
            raise UpdateError("The download did not match its checksum. Nothing was changed; try again later.")
        part.replace(target)
    if name == SETUP_NAME:
        return target
    out = folder / "new"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    if name.endswith(".tar.gz"):
        with tarfile.open(target, "r:gz") as tar:
            member = next((m for m in tar.getmembers() if m.isfile() and m.name == "RoundtableSouls"), None)
            if member is None:
                raise UpdateError("The archive holds no RoundtableSouls program.")
            tar.extract(member, out, filter="data")
        program = out / member.name
        program.chmod(0o755)
        return program
    with zipfile.ZipFile(target) as z:
        exe_name = next((n for n in z.namelist() if n.lower().endswith(".exe") and "/" not in n), None)
        if not exe_name:
            raise UpdateError("The zip holds no exe.")
        z.extract(exe_name, out)
    return out / exe_name


def clean_downloads(keep: str | None = None, now: Callable[[], float] = time.time, temp: Path | None = None) -> int:
    """Remove finished or abandoned downloads: every updates/<version> folder except keep (an update still pending),
    and the roundtable-update-* folders older versions left in the temp folder for over a day. Returns how many."""
    removed = 0
    root = updates_dir()
    if root.is_dir():
        for p in root.iterdir():
            if p.is_dir() and p.name != keep and parse_version(p.name) == p.name:
                shutil.rmtree(p, ignore_errors=True)
                removed += not p.exists()
    tmp = temp or Path(tempfile.gettempdir())
    try:
        old = [p for p in tmp.iterdir() if p.is_dir() and p.name.startswith(OLD_TEMP_PREFIX)]
    except OSError:
        old = []
    for p in old:
        try:
            if now() - p.stat().st_mtime > 24 * 3600:
                shutil.rmtree(p, ignore_errors=True)
                removed += not p.exists()
        except OSError:
            pass
    return removed


# ---------------------------------------------------------------------------- applying, and knowing it worked


def parked_path(current_exe: Path) -> Path:
    """Where an update parks the running program: RoundtableSouls.old.exe on Windows, RoundtableSouls.old on Linux."""
    current_exe = Path(current_exe)
    if current_exe.suffix.lower() == ".exe":
        return current_exe.with_name(current_exe.stem + PARKED_SUFFIX)
    return current_exe.with_name(current_exe.name + ".old")


def failed_path(current_exe: Path) -> Path:
    """Where a new program that did not start is kept after the old one is put back (for a bug report)."""
    current_exe = Path(current_exe)
    if current_exe.suffix.lower() == ".exe":
        return current_exe.with_name(current_exe.stem + FAILED_SUFFIX)
    return current_exe.with_name(current_exe.name + ".failed")


def busy_reason() -> str:
    """Why the program cannot be replaced right now, or ''. A Play from a Steam shortcut, or a setup, still uses it."""
    if instance.held(instance.PLAY):
        return "A Play started from a Steam shortcut is still running; update after it ends."
    if instance.held(instance.SETUP):
        return "An update is already being installed."
    return ""


def _detached_flags() -> int:
    return getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def apply_update(
    new_exe: Path, current_exe: Path, version: str, restart: bool = True, popen=subprocess.Popen, now=time.time
):
    """Park the running program, put the new one in its place and start it. Returns (parked path, process or None).

    Windows lets a running exe be renamed but not overwritten, which is what makes this work without a helper.
    On any failure before the new program starts, the original is put back before the error is raised. The update
    stays pending until the new program confirms (confirm_started) or this one rolls back (roll_back).
    """
    new_exe, current_exe = Path(new_exe), Path(current_exe)
    parked = parked_path(current_exe)
    if parked.exists():
        parked.unlink()
    failed_path(current_exe).unlink(missing_ok=True)  # a failed program kept from an earlier attempt
    current_exe.rename(parked)
    try:
        shutil.move(str(new_exe), str(current_exe))
        if current_exe.suffix != ".exe":
            current_exe.chmod(0o755)
    except Exception:
        if current_exe.exists():
            current_exe.unlink()
        parked.rename(current_exe)
        raise
    save_settings(
        update_pending={"version": version, "from": __version__, "kind": "portable", "started": now()},
        update_result=None,
    )
    if not restart:
        return parked, None
    try:
        proc = popen(
            [str(current_exe)],
            cwd=str(current_exe.parent),
            env=child_environment(),
            close_fds=True,
            creationflags=_detached_flags(),
        )
    except Exception as e:
        roll_back(current_exe, f"the new version could not be started ({e})")
        raise UpdateError(f"The new version could not be started ({e}). This version was put back.") from None
    return parked, proc


def wait_for_new_version(
    proc, version: str, timeout: float = WAIT_FOR_NEW, sleep=time.sleep, now=time.monotonic
) -> str:
    """After apply_update: 'ok' once the new program confirms, 'exited' when it ends without confirming, 'slow' when
    it is still running at the timeout (then it is left alone: it may still be unpacking on a slow disk)."""

    def confirmed() -> bool:
        result = load_settings().get("update_result") or {}
        return result.get("status") == "ok" and version_key(result.get("version")) == version_key(version)

    deadline = now() + timeout
    while True:
        if confirmed():
            return "ok"
        if proc.poll() is not None:
            return "ok" if confirmed() else "exited"  # it may have confirmed just before it ended
        if now() >= deadline:
            return "slow"
        sleep(0.25)


def roll_back(current_exe: Path, why: str) -> bool:
    """Put the parked program back after the new one failed to start; the new one is kept as .failed.exe."""
    current_exe = Path(current_exe)
    parked, failed = parked_path(current_exe), failed_path(current_exe)
    if not parked.exists():
        return False
    try:
        failed.unlink(missing_ok=True)
        if current_exe.exists():
            current_exe.rename(failed)
        parked.rename(current_exe)
    except OSError:
        return False
    pending = load_settings().get("update_pending") or {}
    save_settings(
        update_pending=None,
        update_result={"status": "rolled_back", "version": pending.get("version", ""), "error": why},
    )
    return True


def confirm_started(current: str = __version__, now=time.time) -> dict | None:
    """Called by a freshly started window once it is up: an update to this version is done. Returns the result to
    report, or None when nothing was pending."""
    pending = load_settings().get("update_pending") or {}
    if not pending or version_key(pending.get("version")) != version_key(current):
        return None
    result = {"status": "ok", "version": current, "from": pending.get("from", ""), "when": now()}
    save_settings(update_pending=None, update_result=result)
    return result


def installer_args(app_dir: Path | str, log: Path | str, relaunch: bool = True) -> list[str]:
    """The silent setup's arguments: into this copy's folder, with a log, reopening the launcher afterwards (the new
    version on success, this one on failure, so the outcome is always shown)."""
    return [*SILENT_SETUP_ARGS, f"/DIR={app_dir}", f"/LOG={log}", f"/RELAUNCH={int(relaunch)}"]


def run_installer(setup: Path, version: str, app_dir: Path, popen=subprocess.Popen, now=time.time) -> Path:
    """Start the downloaded setup silently and return its log. It installs over app_dir and reopens the launcher; the
    caller exits right away, after releasing the window's name (the setup will not run while it is held)."""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now()))
    log = folders.data_root() / "logs" / f"setup-{stamp}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    save_settings(
        update_pending={
            "version": version,
            "from": __version__,
            "kind": "installed",
            "started": now(),
            "log": str(log),
        },
        update_result=None,
    )
    try:
        popen(
            [str(setup), *installer_args(app_dir, log)],
            cwd=str(Path(setup).parent),
            env=child_environment(),
            close_fds=True,
            creationflags=_detached_flags(),
        )
    except Exception:
        save_settings(update_pending=None)
        raise
    return log


def setup_log_summary(log: str | Path | None, lines: int = 4) -> str:
    """The lines of a setup log that say what went wrong (or its last lines), without the timestamps."""
    try:
        text = Path(log).read_text(encoding="utf-8", errors="replace") if log else ""
    except OSError:
        return ""
    rows = [re.sub(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+\s+", "", ln).strip() for ln in text.splitlines()]
    rows = [r for r in rows if r]
    bad = [r for r in rows if re.search(r"error|fail|abort|cannot|denied|newer version|running", r, re.I)]
    return "\n".join((bad or rows)[-lines:])


def update_outcome(
    current: str = __version__, now=time.time, setup_wait: float = 20.0, sleep=time.sleep, held=instance.held
) -> dict | None:
    """At start: what happened to the last update, to report once. {'status': ok / failed / rolled_back, 'version',
    'error', 'log'}; None when there is nothing to say.

    An installed copy's pending update is done when this is that version; otherwise the setup did not finish (it
    reopened the old version, or the user did). A setup still running (it reopens the launcher just before it ends)
    is waited for up to setup_wait seconds. A portable update is confirmed by the new window (confirm_started).
    """
    pending = load_settings().get("update_pending") or {}
    if pending.get("kind") == "installed":
        if version_key(pending.get("version")) == version_key(current):
            return confirm_started(current, now)
        waited = 0.0
        while held(instance.SETUP) and waited < setup_wait:
            sleep(0.5)
            waited += 0.5
        if held(instance.SETUP):
            return None  # still installing; the next start reports it
        result = {
            "status": "failed",
            "version": pending.get("version", ""),
            "log": pending.get("log", ""),
            "error": setup_log_summary(pending.get("log")) or "The setup ended before installing anything.",
        }
        save_settings(update_pending=None, update_result=result)
        return result
    if pending.get("kind") == "portable" and version_key(pending.get("version")) != version_key(current):
        if now() - float(pending.get("started") or 0) > 600:  # abandoned: neither confirmed nor rolled back
            save_settings(update_pending=None)
    return load_settings().get("update_result") or None


def clear_outcome() -> None:
    """The outcome was shown; do not show it again."""
    save_settings(update_result=None)


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
