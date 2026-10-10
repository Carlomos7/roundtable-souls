"""What a build record says about how a build was made, beyond its inputs: which merging rules, which load order
model, which game configuration, and the choices in force. A build made otherwise is out of date.

When a build is out of date (what play checks before starting the game):
    rules        the merger revision, the ordering model, the game configuration or the removal choice differ
    inputs       a mod's copy of a merged file, or a pack's regulation.bin, differs from its recorded sha256; which
                 packages ship it, or their order, changed
    game         the game's regulation.bin differs from its recorded sha256; an archive index (.bhd) changed size or
                 modification time (a game update rewrites them; the archives themselves are too large to hash)
    config       an overhaul's build: the build in its config (data/overhauls) differs from the one it was made with
The game's files and the config are recorded by game_files() and the overhaul's build (config_sha256 in facts());
reasons() compares them with today's when it is given them. Combine (mods.backends.builtin) and the launcher's
overhaul build (mods.engine) both take their facts from here.
The me3 version is recorded but does not make a build out of date: the ordering model is what decides, and it is the
same for every me3 version the launcher supports (mods.order.supported).

File hashes are remembered by path, size and modification time (mods.merge.sha256): a file whose size or
modification time changes is hashed again; one rewritten with the same size and time is not noticed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from roundtable_souls.game import archives as game_archives
from roundtable_souls.game import config as game_config

# Raised whenever what merging produces from the same inputs changes. 2: removals listed, colliding inner names refused,
# stored sizes from the data, ZSTD frames with a 64 KB window (2026-10-01). 3: talk scripts (ESD) merged state by
# state (2026-10-02). 4: animation events (TAE) merged animation by animation (2026-10-05). 5: an archive the game
# lists by ID keeps that order with added inner files placed by ID, not appended (2026-10-06).
MERGER_REVISION = 5
ORDERING = "me3 sort_dependencies, me3 9b1e080 (me3 0.11.0 to 0.13.0)"
# How an inner file that a mod's copy leaves out is treated. Until a policy is chosen (see docs/decisions), the rule
# the launcher has always used: it is removed. Every such removal is listed in the record, file by file.
REMOVAL_CHOICE = "removed: an inner file a mod's copy leaves out is left out of the result"
# A build whose record does not say which game files and config it was made for (made before 3.21): rebuilt once.
UNNOTED = "made by an earlier version of the launcher, which did not note the game and config it was built for"


def facts(
    game: str = "eldenring",
    me3_version: str | None = None,
    *,
    game_files: dict | None = None,
    config_sha256: str | None = None,
) -> dict:
    """The fields every build record carries next to its inputs; with game_files (what game_files() returns) and
    config_sha256 (an overhaul's build, overhauls.recipe_sha256) when the build records them."""
    cfg = (game_config.GAMES_DIR / f"{game}.json").read_bytes()
    out = {
        "merger_revision": MERGER_REVISION,
        "ordering": ORDERING,
        "me3_version": me3_version,
        "game_config_sha256": hashlib.sha256(cfg).hexdigest(),
        "removal_choice": REMOVAL_CHOICE,
    }
    if game_files is not None:
        out["game"] = game_files
    if config_sha256 is not None:
        out["config_sha256"] = config_sha256
    return out


def game_files(game_dir: Path | None, regulation: str, sha256: Callable[[Path], str | None], *, version=False) -> dict:
    """The game's own files a build merges against: the archive indexes' fingerprint and the regulation's sha256
    (sha256: the hasher, remembered by size and time in mods.rebuild), with the version the regulation names when
    asked (it is decrypted for that, so only when a build is made)."""
    reg = Path(game_dir) / regulation if game_dir else None
    out: dict = {
        "archives": game_archives.index_fingerprint(game_dir),
        "regulation_sha256": sha256(reg) if reg is not None and reg.is_file() else None,
    }
    if version:
        out["regulation_version"] = regulation_version(reg)
    return out


def regulation_version(path: Path | None) -> str | None:
    """The version a regulation.bin names (e.g. 11711000), or None when it can't be read."""
    from roundtable_souls import formats

    try:
        return formats.regulation.read_regulation(Path(path).read_bytes()).version or None  # type: ignore[arg-type]
    except Exception:
        return None


def reasons(record: dict, game: str = "eldenring", *, now: dict | None = None, label: str = "the mod") -> list[str]:
    """Why a build made under other rules is out of date. A record without these fields was written by a launcher
    up to 3.14.0: out of date when it merged files, since merging changed after it. now: today's facts(), with the
    game's files and the config (an overhaul's build); the record is then also out of date when the game was updated
    or label's config changed since, and when it does not say (made before 3.21)."""
    if "merger_revision" not in record:
        built = any(isinstance(f, dict) and f.get("output") for f in (record.get("files") or {}).values())
        return ["made by an earlier version of the launcher, which merged differently"] if built else []
    current = facts(game)
    out = []
    if record.get("merger_revision") != current["merger_revision"]:
        out.append("the launcher's merging changed since this was built")
    if record.get("ordering") != current["ordering"]:
        out.append("the launcher's load order model changed since this was built")
    if record.get("game_config_sha256") != current["game_config_sha256"]:
        out.append("the launcher's game data changed since this was built")
    if record.get("removal_choice") != current["removal_choice"]:
        out.append("the choice for parts a mod leaves out changed since this was built")
    if now is None:
        return out
    if ("game" in now and "game" not in record) or ("config_sha256" in now and "config_sha256" not in record):
        out.append(UNNOTED)
        return out
    had, has = record.get("game") or {}, now.get("game") or {}
    if any(has.get(k) and had.get(k) != has[k] for k in ("archives", "regulation_sha256")):
        out.append("the game was updated since the last build")
    if "config_sha256" in now and record.get("config_sha256") != now["config_sha256"]:
        out.append(f"{label}'s config changed since the last build")
    return out
