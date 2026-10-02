"""What a build record says about how a build was made, beyond its inputs: which merging rules, which load order
model, which game configuration, and the choices in force. A build made otherwise is out of date.

When a build is out of date (what play checks before starting the game):
    rules        the merger revision, the ordering model, the game configuration or the removal choice differ
    inputs       a mod's copy of a merged file, or a pack's regulation.bin, differs from its recorded sha256; which
                 packages ship it, or their order, changed
    game         the game's regulation.bin differs from its recorded sha256; an archive index (.bhd) changed size or
                 modification time (a game update rewrites them; the archives themselves are too large to hash)
The me3 version is recorded but does not make a build out of date: the ordering model is what decides, and it is the
same for every me3 version the launcher supports (mods.order.supported).

File hashes are remembered by path, size and modification time (mods.merge.sha256): a file whose size or
modification time changes is hashed again; one rewritten with the same size and time is not noticed.
"""

from __future__ import annotations

import hashlib

from roundtable_souls.game import config as game_config

# Raised whenever what merging produces from the same inputs changes. 2: removals listed, colliding inner names refused,
# stored sizes from the data, ZSTD frames with a 64 KB window (2026-10-01). 3: talk scripts (ESD) merged state by
# state (2026-10-02).
MERGER_REVISION = 3
ORDERING = "me3 sort_dependencies, me3 9b1e080 (me3 0.11.0 to 0.13.0)"
# How an inner file that a mod's copy leaves out is treated. Until a policy is chosen (see docs/decisions), the rule
# the launcher has always used: it is removed. Every such removal is listed in the record, file by file.
REMOVAL_CHOICE = "removed: an inner file a mod's copy leaves out is left out of the result"


def facts(game: str = "eldenring", me3_version: str | None = None) -> dict:
    """The fields every build record carries next to its inputs."""
    cfg = (game_config.GAMES_DIR / f"{game}.json").read_bytes()
    return {
        "merger_revision": MERGER_REVISION,
        "ordering": ORDERING,
        "me3_version": me3_version,
        "game_config_sha256": hashlib.sha256(cfg).hexdigest(),
        "removal_choice": REMOVAL_CHOICE,
    }


def reasons(record: dict, game: str = "eldenring") -> list[str]:
    """Why a build made under other rules is out of date. A record without these fields was written by a launcher
    up to 3.14.0: out of date when it merged files, since merging changed after it."""
    if "merger_revision" not in record:
        built = any(isinstance(f, dict) and f.get("output") for f in (record.get("files") or {}).values())
        return ["made by an earlier version of the launcher, which merged differently"] if built else []
    now = facts(game)
    out = []
    if record.get("merger_revision") != now["merger_revision"]:
        out.append("the launcher's merging changed since this was built")
    if record.get("ordering") != now["ordering"]:
        out.append("the launcher's load order model changed since this was built")
    if record.get("game_config_sha256") != now["game_config_sha256"]:
        out.append("the launcher's game data changed since this was built")
    if record.get("removal_choice") != now["removal_choice"]:
        out.append("the choice for parts a mod leaves out changed since this was built")
    return out
