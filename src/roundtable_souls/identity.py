"""Who this build is: its Velopack app ID and title, where it looks for releases, the key releases are signed with,
and the Inno Setup install it replaces.

Release builds use the defaults below. `scripts/build.py --identity <file.json>` writes data/build-identity.json into
a build to override any of them, which is how isolated test builds get their own app ID, title, feed and key and so
can never touch a real installation. The file is never part of a release.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
OVERRIDE_FILE = DATA / "build-identity.json"


@dataclass(frozen=True)
class Identity:
    # Velopack: installs to %LOCALAPPDATA%\<pack_id> and removes that whole folder on uninstall, so it must never be
    # the launcher's data folder (data_dir_name).
    pack_id: str = "Carlomos7.RoundtableSouls"
    title: str = "Roundtable Souls"  # shortcuts, the uninstall entry, and the stub "<title>.exe" beside current\
    exe_name: str = "RoundtableSouls"  # the program inside current\ (".exe" on Windows)
    data_dir_name: str = "RoundtableSouls"  # %LOCALAPPDATA%\<this> / $XDG_DATA_HOME/<this>
    portable_data_name: str = "RoundtableSouls-data"  # a portable copy's data folder, beside Update.exe
    repo: str = "Carlomos7/roundtable-souls"
    api_base: str = "https://api.github.com/repos/Carlomos7/roundtable-souls"
    releases_page: str = "https://github.com/Carlomos7/roundtable-souls/releases"
    advisory_url: str = "https://raw.githubusercontent.com/Carlomos7/roundtable-souls/main/advisory.json"
    signing_key: str = ""  # a public key's text; empty = data/release-signing.pub
    # The Inno Setup install that releases up to 3.13.2 made, which the first Velopack start replaces.
    inno_app_id: str = "{B8463238-E9B5-4FD4-AEB5-A537E4B53D8E}"
    inno_title: str = "Roundtable Souls"
    steam_root: str = ""  # empty = detect; test builds point it at a fake Steam folder
    instance_prefix: str = "RoundtableSouls"  # named mutexes and the window's local socket
    qt_platform: str = ""  # test builds only: "offscreen" keeps their window off the screen, however they are started

    @property
    def stub_name(self) -> str:
        return f"{self.title}.exe"


@lru_cache
def get() -> Identity:
    try:
        raw = json.loads(OVERRIDE_FILE.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return Identity()
    known = {f.name for f in fields(Identity)}
    return Identity(**{k: str(v) for k, v in raw.items() if k in known})
