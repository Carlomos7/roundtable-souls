"""Newer launcher on GitHub Releases: the check, the verified download behind Update now, and making sure an update
either starts or is undone. Installing and replacing files is Velopack's job; trusting what it installs is ours.

The check
  At most once an hour (CHECK_EVERY) on start, from /releases/latest (Stable) or /releases (Beta, which includes
  pre-releases). The answer is cached with its ETag; asking again with If-None-Match costs nothing against GitHub's
  limit when nothing changed. A failed check says why (offline, GitHub's limit, an error) and is never reported as
  "up to date"; each failure in a row doubles the wait before the next automatic one (at most a day). A version that
  failed to start and was undone is not offered again.

The download (download_update)
  Every release carries Velopack's feed for each OS (releases.win.json, releases.linux.json) and a minisign
  signature of it. The feed is accepted only when the signature checks out with the project key built into the
  launcher and its trusted comment names this release's version and this OS. Every package then fetched (the full
  package, or the delta when this copy is exactly one version behind and holds that base) must match the size and
  SHA-256 in the verified feed. Velopack is given a local folder with only those files and a feed made of entries
  copied from the verified one; it never reads anything from the network itself.

Applying it (apply_update)
  Before Velopack replaces the program, the current version's full package (Windows) or AppImage (Linux) is kept,
  and a small watchdog script starts outside the program folder. The new version marks itself ready once its window
  is up, or once a Play from a Steam shortcut gets going (mark_ready). If it does not within WATCHDOG_READY seconds
  of being applied, the watchdog stops it, removes its package (Velopack would otherwise apply it again at the next
  start), puts the kept version back and starts it; that version reports the rollback and blocks the failed one.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from roundtable_souls import __version__
from roundtable_souls.config import identity
from roundtable_souls.config.settings import (
    appimage,
    change_settings,
    identity_matches,
    is_portable,
    load_settings,
    save_settings,
    velopack_root,
)
from roundtable_souls.platform import instance
from roundtable_souls.resources import DATA_DIR
from roundtable_souls.saves import backups as folders
from roundtable_souls.updates import signing
from roundtable_souls.updates.feed import (
    USER_AGENT,
    Opener,
    UpdateError,
    fetch_release_of,
    is_newer,
    parse_version,
    same_version,
    version_key,
)

ID = identity.get()
OS_CHANNEL = "win" if sys.platform == "win32" else "linux"  # Velopack's channel for each OS's packages
FEED_NAME = f"releases.{OS_CHANNEL}.json"
SIGNATURE_NAME = FEED_NAME + ".minisig"
SIGNED_COMMENT = "roundtable-souls {version} {channel}"  # the trusted comment release.yml signs each feed with
CHECKSUMS_NAME = "SHA256SUMS.txt"  # still published, for people checking downloads by hand
WATCHDOG_APPLY = 600  # seconds the watchdog waits for Velopack to apply the update
WATCHDOG_READY = 90  # seconds the new version has, once applied, to report ready
BOOTLOADER_ENV_PREFIXES = ("_PYI_", "_MEIPASS")  # PyInstaller marks child processes through these
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._+-]+$")

Progress = Callable[[int, int], None]


def child_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    """The environment for a process this one starts, without PyInstaller's markers (a child that inherits them
    would reuse this process's unpacked files, which disappear when it exits)."""
    src = os.environ if env is None else env
    return {k: v for k, v in src.items() if not k.startswith(BOOTLOADER_ENV_PREFIXES)}


# ---------------------------------------------------------------------------- where things are kept


def updates_dir() -> Path:
    return folders.data_root() / "updates"


def state_dir() -> Path:
    """Readiness markers, the watchdog and its log, the rollback record: outside every folder an update replaces."""
    return updates_dir() / "state"


def rollback_dir() -> Path:
    return updates_dir() / "rollback"


def velopack_packages_dir() -> Path | None:
    """Where Velopack keeps the installed version's full package: <root>\\packages on Windows, /var/tmp on Linux."""
    root = velopack_root()
    if root is not None:
        return root / "packages"
    if appimage() is not None:
        return Path("/var/tmp/velopack") / ID.pack_id / "packages"
    return None


def can_self_update(info: dict) -> bool:
    """Whether Update now can do it: this copy is a Velopack install, portable copy or AppImage, and the release has
    this OS's feed and its signature (anything else goes through the releases page)."""
    assets = info.get("assets") or {}
    managed = (velopack_root() is not None or appimage() is not None) and identity_matches()
    return managed and FEED_NAME in assets and SIGNATURE_NAME in assets


# ---------------------------------------------------------------------------- download and verify


def fetch_bytes(url: str, timeout: float = 30.0, opener: Opener = urllib.request.urlopen) -> bytes:
    """A small file (a feed and its signature), whole."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener(req, timeout=timeout) as r:
            return r.read(8 * 1024 * 1024)
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


@dataclass
class Feed:
    """A release's Velopack feed for this OS, after its signature checked out."""

    version: str
    entries: list[dict]  # every asset entry, exactly as signed
    full: dict  # this version's full package
    delta: dict | None  # this version's delta, if the release has one
    base: dict | None  # the full package the delta was made against (an earlier release), if listed


def _check_entry(entry: Any) -> dict:
    if not isinstance(entry, dict):
        raise UpdateError("The release's feed has an entry that is not an object.")
    name = str(entry.get("FileName") or "")
    if not _SAFE_NAME.match(name) or name in (".", ".."):
        raise UpdateError(f"The release's feed names an unsafe file: {name!r}.")
    if entry.get("PackageId") != ID.pack_id:
        raise UpdateError(f"The release's feed is for {entry.get('PackageId')!r}, not this launcher.")
    if entry.get("Type") not in ("Full", "Delta") or not parse_version(str(entry.get("Version") or "")):
        raise UpdateError(f"The release's feed has an entry this launcher cannot read ({name}).")
    digest = str(entry.get("SHA256") or "")
    if not re.fullmatch(r"[0-9A-Fa-f]{64}", digest) or not isinstance(entry.get("Size"), int) or entry["Size"] <= 0:
        raise UpdateError(f"The release's feed has no usable size or SHA-256 for {name}.")
    return entry


def verified_feed(info: dict, fetch: Callable[[str], bytes] = fetch_bytes, key=None) -> Feed:
    """This OS's feed from a release, once its minisign signature checks out with the project key and its trusted
    comment names this release's version and this OS. Raises UpdateError otherwise."""
    assets = info.get("assets") or {}
    feed_url, sig_url = assets.get(FEED_NAME), assets.get(SIGNATURE_NAME)
    if not feed_url or not sig_url:
        raise UpdateError("This release has no signed update feed for this system; use the releases page instead.")
    raw = fetch(feed_url)
    signature = fetch(sig_url).decode("utf-8", "replace")
    try:
        comment = signing.verify(raw, signature, key or release_key())
    except signing.SignatureError as e:
        raise UpdateError(f"The release's signature did not check out: {e} Nothing was changed.") from None
    parts = comment.split()
    want = SIGNED_COMMENT.format(version=info.get("version"), channel=OS_CHANNEL).split()
    if len(parts) != 3 or parts[0] != want[0] or not same_version(parts[1], want[1]) or parts[2] != OS_CHANNEL:
        raise UpdateError(
            f"The signed feed is for '{comment}', not {info.get('version')} on {OS_CHANNEL}. Nothing was changed."
        )
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except ValueError:
        raise UpdateError("The release's feed could not be read.") from None
    entries = [_check_entry(e) for e in (doc.get("Assets") if isinstance(doc, dict) else None) or []]
    version = str(info.get("version"))
    full = next((e for e in entries if e["Type"] == "Full" and same_version(e["Version"], version)), None)
    if full is None:
        raise UpdateError(f"The release's feed has no full package of {version}.")
    delta = next((e for e in entries if e["Type"] == "Delta" and same_version(e["Version"], version)), None)
    older = [e for e in entries if e["Type"] == "Full" and is_newer(version, e["Version"])]
    base = max(older, key=lambda e: version_key(e["Version"])) if older else None
    return Feed(version=version, entries=entries, full=full, delta=delta, base=base)


def release_key():
    return signing.parse_public_key(ID.signing_key) if ID.signing_key else signing.release_key()


@dataclass
class Prepared:
    """A verified update, ready for Velopack: folder holds FEED_NAME and the package files it names."""

    version: str
    folder: Path
    files: list[str]
    delta: bool
    signed: list[dict] = field(default_factory=list)  # every entry of the verified feed
    rollback: Path | None = None


def _base_available(feed: Feed, current: str) -> bool:
    """Velopack can apply the delta: it was made against exactly this version and this copy holds that package."""
    if not feed.delta or not feed.base or not same_version(feed.base["Version"], current):
        return False
    packages = velopack_packages_dir()
    return bool(packages and (packages / feed.base["FileName"]).is_file())


def _fetch_verified(entry: dict, url: str, folder: Path, fetch_file: Callable[..., str], progress) -> Path:
    target = folder / entry["FileName"]
    if target.is_file() and target.stat().st_size == entry["Size"]:
        if _sha256_of(target).hexdigest().lower() == entry["SHA256"].lower():
            return target  # a finished earlier download is reused
    part = folder / (entry["FileName"] + ".part")
    digest = fetch_file(url, part, progress=progress)
    if digest.lower() != entry["SHA256"].lower() or part.stat().st_size != entry["Size"]:
        part.unlink(missing_ok=True)
        raise UpdateError(f"{entry['FileName']} did not match the signed feed. Nothing was changed; try again later.")
    part.replace(target)
    return target


def download_update(
    info: dict,
    fetch_file: Callable[..., str] = fetch_to_file,
    fetch: Callable[[str], bytes] = fetch_bytes,
    progress: Progress | None = None,
    workdir: Path | None = None,
    key=None,
    current: str = __version__,
    base_available: Callable[[Feed, str], bool] = _base_available,
) -> Prepared:
    """Verify a release's feed, then download and verify the package Velopack needs (the delta when it can use it,
    otherwise the full package). Returns the local folder Velopack is pointed at. Nothing running is touched."""
    version = parse_version(str(info.get("version") or ""))
    if not version or not is_newer(version, current):
        raise UpdateError(f"{info.get('version')} is not newer than this copy ({current}); nothing was changed.")
    if any(same_version(version, b) for b in load_settings().get("update_blocked") or []):
        raise UpdateError(f"{version} failed to start here before and was undone; it is not installed again.")
    feed = verified_feed(info, fetch=fetch, key=key)
    use_delta = base_available(feed, current)
    chosen = [feed.delta] if use_delta and feed.delta else [feed.full]
    folder = (workdir or updates_dir()) / version / "feed"
    folder.mkdir(parents=True, exist_ok=True)
    assets = info.get("assets") or {}
    for entry in chosen:
        url = assets.get(entry["FileName"])
        if not url:
            raise UpdateError(f"The release does not carry {entry['FileName']}, which its feed names.")
        _fetch_verified(entry, url, folder, fetch_file, progress)
    # Velopack reads only this file, made of entries copied verbatim from the signed feed (with a delta it needs the
    # target's full entry too, but not its file).
    listed = [feed.full, feed.delta] if use_delta and feed.delta else [feed.full]
    (folder / FEED_NAME).write_text(json.dumps({"Assets": listed}), encoding="utf-8")
    for stale in folder.iterdir():  # nothing else in the folder Velopack is pointed at
        if stale.name not in {FEED_NAME, *(e["FileName"] for e in chosen)}:
            stale.unlink(missing_ok=True)
    return Prepared(
        version=version, folder=folder, files=[e["FileName"] for e in chosen], delta=use_delta, signed=feed.entries
    )


def verify_prepared(prepared: Prepared) -> None:
    """Just before applying: the local feed lists only entries of the signed feed, and its files are still exactly
    what was verified."""
    try:
        listed = json.loads((prepared.folder / FEED_NAME).read_text(encoding="utf-8"))["Assets"]
    except OSError, ValueError, KeyError, TypeError:
        raise UpdateError("The verified update folder was changed; download it again.") from None
    by_name = {e["FileName"]: e for e in listed}
    names = {p.name for p in prepared.folder.iterdir()} - {FEED_NAME}
    if names != set(prepared.files):
        raise UpdateError("The verified update folder holds other files than were checked; download it again.")
    for name in prepared.files:
        entry = by_name.get(name)
        if not entry or _sha256_of(prepared.folder / name).hexdigest().lower() != entry["SHA256"].lower():
            raise UpdateError(f"{name} changed after it was checked; download it again.")
    signed = {json.dumps(e, sort_keys=True) for e in prepared.signed}
    if not listed or any(json.dumps(e, sort_keys=True) not in signed for e in listed):
        raise UpdateError("The local feed lists something the signed feed does not; download it again.")


def stage_rollback(
    current: str = __version__,
    fetch_file: Callable[..., str] = fetch_to_file,
    fetch: Callable[[str], bytes] = fetch_bytes,
    release_of: Callable[[str], dict] = fetch_release_of,
    key=None,
) -> Path:
    """Keep what puts this version back: its AppImage (Linux), or its full package, taken from Velopack's packages
    folder or (a portable copy has none) downloaded from this version's release and checked against its signed
    feed."""
    keep = rollback_dir()
    keep.mkdir(parents=True, exist_ok=True)
    image = appimage()
    if image is not None:
        target = keep / f"{ID.exe_name}-{current}.AppImage"
        if not target.is_file():
            tmp = target.with_suffix(".part")
            shutil.copy2(image, tmp)
            tmp.replace(target)
        return target
    packages = velopack_packages_dir()
    if packages is not None and packages.is_dir():
        for p in packages.glob(f"{ID.pack_id}-*-full.nupkg"):
            if same_version(p.name[len(ID.pack_id) + 1 : -len("-full.nupkg")].replace(f"-{OS_CHANNEL}", ""), current):
                target = keep / p.name
                if not target.is_file():
                    shutil.copy2(p, target)
                return target
    release = release_of(current)
    feed = verified_feed(release, fetch=fetch, key=key)
    url = (release.get("assets") or {}).get(feed.full["FileName"])
    if not url:
        raise UpdateError(f"The release of {current} does not carry {feed.full['FileName']}.")
    return _fetch_verified(feed.full, url, keep, fetch_file, None)


# ---------------------------------------------------------------------------- applying, readiness, rollback


def watchdog_script() -> Path:
    """The watchdog, copied out of the program folder (which the update replaces)."""
    name = "update-watchdog.ps1" if sys.platform == "win32" else "update-watchdog.sh"
    src = DATA_DIR / name
    dst = state_dir() / name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if sys.platform != "win32":
        dst.chmod(0o755)
    return dst


def start_watchdog(version: str, rollback: Path, popen=subprocess.Popen, ready_seconds: int = WATCHDOG_READY):
    """Start the watchdog for an update about to be applied (it outlives this process)."""
    script, state = watchdog_script(), state_dir()
    for stale in (state / f"ready-{version}", state / "rollback.json"):
        stale.unlink(missing_ok=True)
    if sys.platform == "win32":
        root = velopack_root()
        if root is None:
            raise UpdateError("This copy is not a Velopack install; it cannot be updated in place.")
        args = [
            "powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
            "-Root", str(root), "-Version", version, "-Package", str(rollback), "-State", str(state),
            "-WaitApply", str(WATCHDOG_APPLY), "-WaitReady", str(ready_seconds),
        ]  # fmt: skip
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        return popen(args, cwd=str(state), env=child_environment(), close_fds=True, creationflags=flags)
    image = appimage()
    if image is None:
        raise UpdateError("This copy is not an AppImage; it cannot be updated in place.")
    args = ["/bin/sh", str(script), str(image), version, str(rollback), str(state), str(WATCHDOG_APPLY),
            str(ready_seconds), ID.pack_id]  # fmt: skip
    return popen(args, cwd=str(state), env=child_environment(), close_fds=True, start_new_session=True)


def apply_update(
    prepared: Prepared,
    restart_args: list[str] | None = None,
    velopack_module=None,
    popen=subprocess.Popen,
    now=time.time,
) -> None:
    """Hand the verified update to Velopack: it waits for this process to exit, replaces the program and restarts
    it (with restart_args). The caller exits right after; the watchdog takes it from there."""
    vp = velopack_module or _velopack()
    if not identity_matches():
        raise UpdateError("This program's app ID is not the one its install was made for; nothing was changed.")
    verify_prepared(prepared)
    if prepared.rollback is None or not prepared.rollback.is_file():
        raise UpdateError("Nothing was kept to put this version back; the update was not applied.")
    um = vp.UpdateManager(str(prepared.folder), vp.UpdateOptions(False, 10, None))
    info = um.check_for_updates()
    if not info or not same_version(info.TargetFullRelease.Version, prepared.version):
        raise UpdateError("The update did not match what was verified; nothing was changed.")
    um.download_updates(info)  # copies from the verified local folder; Velopack checks the hashes again
    save_settings(
        update_pending={
            "version": prepared.version,
            "from": __version__,
            "started": now(),
            "rollback": str(prepared.rollback),
            "portable": is_portable(),
        },
        update_result=None,
    )
    start_watchdog(prepared.version, prepared.rollback, popen=popen)
    um.wait_exit_then_apply_updates(info, silent=True, restart=True, restart_args=list(restart_args or []))


def _velopack():
    import velopack

    return velopack


def velopack_startup() -> None:
    """First thing at start in a Velopack copy: answers Velopack's install/update/uninstall hooks (which exit), and
    never applies a downloaded package by itself: applying is Update now's, with the watchdog in place."""
    if velopack_root() is None and appimage() is None:
        return
    vp = _velopack()
    vp.App().set_auto_apply_on_startup(False).run()


def mark_ready(how: str = "window", current: str = __version__, now=time.time) -> dict | None:
    """This version started properly (its window is up, or a Play from a Steam shortcut is under way). Tells a
    waiting watchdog, and finishes a pending update: returns its result to report, or None."""
    state = state_dir()
    state.mkdir(parents=True, exist_ok=True)
    (state / f"ready-{current}").write_text(f"{how} {now():.0f}", encoding="utf-8")
    pending = load_settings().get("update_pending") or {}
    if not pending or not same_version(pending.get("version"), current):
        return None
    result = {"status": "ok", "version": current, "from": pending.get("from", ""), "when": now(), "how": how}
    save_settings(update_pending=None, update_result=result)
    return result


def update_outcome(current: str = __version__, now=time.time) -> dict | None:
    """At start: what happened to the last update, to report once ({'status': ok / rolled_back / failed, ...}).

    A rollback record from the watchdog blocks that version from being offered again. A pending update that this is
    not, with no rollback record and well past the watchdog's time, did not finish.
    """
    record = state_dir() / "rollback.json"
    if record.is_file():
        try:
            data = json.loads(record.read_text(encoding="utf-8-sig"))
        except OSError, ValueError:
            data = {}
        version = str(data.get("version") or (load_settings().get("update_pending") or {}).get("version") or "")
        result = {"status": "rolled_back", "version": version, "error": str(data.get("reason") or "")}

        def block(cur: dict) -> dict:
            blocked = [b for b in cur.get("update_blocked") or [] if not same_version(b, version)]
            return {"update_blocked": [*blocked, version] if version else blocked, "update_pending": None,
                    "update_result": result}  # fmt: skip

        change_settings(block)
        record.unlink(missing_ok=True)
        return result
    pending = load_settings().get("update_pending") or {}
    if pending and not same_version(pending.get("version"), current):
        if now() - float(pending.get("started") or 0) > WATCHDOG_APPLY + WATCHDOG_READY + 60:
            result = {"status": "failed", "version": pending.get("version", ""),
                      "error": "The update did not finish installing; this version kept running."}  # fmt: skip
            save_settings(update_pending=None, update_result=result)
            return result
        return None  # still being applied
    return load_settings().get("update_result") or None


def clear_outcome() -> None:
    """The outcome was shown; do not show it again."""
    save_settings(update_result=None)


def unblock(version: str) -> None:
    save_settings(
        update_blocked=[b for b in load_settings().get("update_blocked") or [] if not same_version(b, version)]
    )


def clean_downloads(
    keep: str | None = None, current: str = __version__, temp: Path | None = None, now=time.time
) -> int:
    """Remove finished or abandoned downloads (every updates/<version> but keep), rollback copies of other versions
    than this one, and the roundtable-update-* folders versions before 3.14 left in the temp folder."""
    removed = 0
    root = updates_dir()
    if root.is_dir():
        for p in root.iterdir():
            if p.is_dir() and p.name != keep and parse_version(p.name) == p.name:
                shutil.rmtree(p, ignore_errors=True)
                removed += not p.exists()
    keep_dir = rollback_dir()
    if keep_dir.is_dir():
        for p in keep_dir.iterdir():
            if p.is_file() and f"-{current}" not in p.name:
                p.unlink(missing_ok=True)
                removed += 1
    tmp = temp or Path(tempfile.gettempdir())
    try:
        old = [p for p in tmp.iterdir() if p.is_dir() and p.name.startswith("roundtable-update-")]
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


def busy_reason() -> str:
    """Why the program cannot be replaced right now, or ''. A Play from a Steam shortcut still uses it."""
    if instance.held(instance.PLAY):
        return "A Play started from a Steam shortcut is still running; update after it ends."
    return ""


def data_location_text() -> str:
    """One line for Settings: where this copy keeps its data, in words."""
    if os.environ.get("ROUNDTABLE_SOULS_DATA"):
        return "In the folder ROUNDTABLE_SOULS_DATA names."
    if is_portable():
        return f"Beside this portable copy, in {ID.portable_data_name}; it moves with the copy."
    if velopack_root() is not None or appimage() is not None:
        return "In this account's app data; updates and uninstalling leave it alone."
    return "Next to this program."
