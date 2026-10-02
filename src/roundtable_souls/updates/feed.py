"""The release feed: versions, asking GitHub for the newest release on a channel (with backoff and ETags),
the project's minimum-version notice, and the release notes shown with an offer. Nothing here downloads or
installs; apply.py does that."""

from __future__ import annotations

import json
import random
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from roundtable_souls import __version__
from roundtable_souls.config import identity
from roundtable_souls.config.settings import (
    change_settings,
    load_settings,
    save_settings,
)

ID = identity.get()
RELEASES_URL = ID.releases_page
RELEASES_LATEST = f"{ID.api_base}/releases/latest"
RELEASES_LIST = f"{ID.api_base}/releases?per_page=20"
RELEASE_BY_TAG = f"{ID.api_base}/releases/tags/v{{version}}"
ADVISORY_URL = ID.advisory_url
CHECK_EVERY = 3600  # seconds between automatic checks (60 unauthenticated GitHub API requests an hour are allowed)
MAX_BACKOFF = 24 * 3600  # the longest wait after failed checks
USER_AGENT = f"Roundtable Souls/{__version__}"

Opener = Callable[..., Any]


class UpdateError(RuntimeError):
    """Something about the release or the download is not right; nothing was changed."""


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


def same_version(a: str | None, b: str | None) -> bool:
    ka, kb = version_key(a), version_key(b)
    return bool(ka) and ka == kb


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
            return Fetched("error", reason="GitHub has no such release for this project")
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


def fetch_release_of(version: str, opener: Opener = urllib.request.urlopen) -> dict:
    """One release by its version (its tag v<version>); raises UpdateError when GitHub does not have it."""
    got = _get_json(RELEASE_BY_TAG.format(version=version), opener=opener)
    release = release_from_json(got.data) if got.status == "ok" else None
    if not release:
        raise UpdateError(f"The release of {version} could not be read from GitHub ({got.reason or 'no release'}).")
    return release


@dataclass
class UpdateCheck:
    """What a check found.

    status: fresh (GitHub answered now), cached (the answer from the last hour), waiting (backing off after failed
    checks), off (checks are turned off), or a failure of this check: offline, rate_limited, error.
    offer: the release to show a notice for, or None. checked: when GitHub last answered (0 when never).
    blocked: the newest release, when it is a version that failed to start here and is not offered again.
    """

    status: str
    offer: dict | None = None
    checked: float = 0.0
    reason: str = ""
    retry_at: float = 0.0
    blocked: str = ""

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

    force (Check for updates) asks GitHub now, ignoring the off switch, the backoff and a skipped version; a version
    that failed to start here stays blocked either way.
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
    offer, blocked = None, ""
    if cached and is_newer(cached.get("version"), current):
        version = str(cached.get("version"))
        if any(same_version(version, b) for b in s.get("update_blocked") or []):
            blocked = version
        elif force or str(s.get("launcher_update_skipped") or "") != version:
            offer = {k: v for k, v in cached.items() if k != "channel"}
            offer["url"] = offer.get("url") or RELEASES_URL
            offer["assets"] = offer.get("assets") or {}
    return UpdateCheck(status, offer=offer, checked=checked, reason=reason, retry_at=retry_at, blocked=blocked)


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
        line = re.sub(r"^[-*+]\s+", "• ", line)
        line = line.replace("**", "").replace("`", "")
        if not line or line.startswith("<!--"):
            continue
        out.append(line if len(line) <= 160 else line[:157] + "...")
        if len(out) >= lines:
            break
    return "\n".join(out)
