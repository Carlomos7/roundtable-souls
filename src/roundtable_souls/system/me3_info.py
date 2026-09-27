"""Read-only facts about the installed me3: version, `me3 info` directories, and the latest release on GitHub.
Every call is bounded by a timeout and never raises for a missing or broken me3."""
from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from pathlib import Path

RELEASES_LATEST = "https://api.github.com/repos/garyttierney/me3/releases/latest"
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def _no_window():
    try:
        from roundtable_souls.system import common
        return common.NO_WINDOW
    except Exception:
        return 0


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text or "")


def parse_version(text: str) -> str | None:
    m = _VERSION.search(strip_ansi(text or ""))
    return ".".join(m.groups()) if m else None


def version_tuple(v: str | None) -> tuple:
    m = _VERSION.search(v or "")
    return tuple(int(x) for x in m.groups()) if m else ()


def me3_version(me3: Path | str | None) -> str | None:
    if not me3 or not Path(me3).is_file():
        return None
    try:
        out = subprocess.run([str(me3), "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8, creationflags=_no_window())
        return parse_version(out.stdout or out.stderr)
    except (OSError, subprocess.TimeoutExpired):
        return None


def parse_info(output: str) -> dict:
    """'Key: value' lines from `me3 info` (ANSI stripped), keyed by a slug: profile_dir, logs_dir, install_prefix, steam..."""
    keys = {"profile directory": "profile_dir", "logs directory": "logs_dir", "installation prefix": "install_prefix",
            "boot boost": "boot_boost", "skip startup logos": "skip_logos", "skip steam init": "skip_steam_init",
            "custom executable": "custom_exe", "path": "steam_path", "status": "status"}
    out = {}
    section = ""
    for raw in strip_ansi(output).splitlines():
        line = raw.strip()
        if not line:
            continue
        if ":" not in line:
            section = line.lower(); continue
        k, v = line.split(":", 1)
        k = k.strip().lower(); v = v.strip()
        slug = keys.get(k)
        if not slug:
            continue
        if slug == "status":
            slug = "steam_status" if "steam" in section else "install_status"
        if slug == "steam_path" and "steam" not in section:
            continue
        out[slug] = v
    return out


def me3_info(me3: Path | str | None) -> dict:
    if not me3 or not Path(me3).is_file():
        return {}
    try:
        out = subprocess.run([str(me3), "info"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, creationflags=_no_window())
        return parse_info(out.stdout or "")
    except (OSError, subprocess.TimeoutExpired):
        return {}


def latest_release(timeout: float = 6.0) -> dict | None:
    """{'version': '0.13.0', 'url': html_url} from GitHub, or None when offline."""
    try:
        req = urllib.request.Request(RELEASES_LATEST, headers={"User-Agent": "Roundtable Souls", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            doc = json.loads(r.read().decode("utf-8"))
        v = parse_version(str(doc.get("tag_name") or doc.get("name") or ""))
        return {"version": v, "url": doc.get("html_url") or ""} if v else None
    except Exception:
        return None


def update_available(installed: str | None, latest: str | None) -> bool:
    a, b = version_tuple(installed), version_tuple(latest)
    return bool(a and b and b > a)
