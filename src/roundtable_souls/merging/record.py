"""What a build record says about how a build was made, beyond its inputs: which merging rules, which load order
model, which game configuration, and the choices in force. A build made otherwise is out of date."""

from __future__ import annotations

import hashlib

from roundtable_souls.game import config as game_config

# Raised whenever what merging produces from the same inputs changes. 2: removals listed, colliding inner names refused,
# stored sizes from the data, ZSTD frames with a 64 KB window (2026-10-01).
MERGER_REVISION = 2
ORDERING = "me3 sort_dependencies, me3 9b1e080 (me3 0.11.0 to 0.13.0)"
# How an inner file that a mod's copy leaves out is treated. Until a policy is chosen (see docs/decisions), the rule
# the launcher has always used: it is removed. Every such removal is listed in the record, file by file.
REMOVAL_CHOICE = "removed: an inner file a mod's copy leaves out is left out of the result"


def facts(game: str = "eldenring") -> dict:
    """The fields every build record carries next to its inputs."""
    cfg = (game_config.GAMES_DIR / f"{game}.json").read_bytes()
    return {
        "merger_revision": MERGER_REVISION,
        "ordering": ORDERING,
        "game_config_sha256": hashlib.sha256(cfg).hexdigest(),
        "removal_choice": REMOVAL_CHOICE,
    }


def reasons(record: dict, game: str = "eldenring") -> list[str]:
    """Why a build made under other rules is out of date (empty for a record without these fields: older launchers
    wrote none, and their inputs are still checked)."""
    if "merger_revision" not in record:
        return []
    now = facts(game)
    out = []
    if record.get("merger_revision") != now["merger_revision"]:
        out.append("the launcher's merging changed since this was built")
    if record.get("game_config_sha256") != now["game_config_sha256"]:
        out.append("the launcher's game data changed since this was built")
    if record.get("removal_choice") != now["removal_choice"]:
        out.append("the choice for parts a mod leaves out changed since this was built")
    return out
