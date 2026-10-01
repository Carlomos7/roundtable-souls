"""What the launcher knows about a game's files, from data/games/<game>.json, as a Pydantic model."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from roundtable_souls.resources import DATA_DIR

GAMES_DIR = DATA_DIR / "games"


class KrakenLayout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: int  # Oodle level of the payload
    header_level: int  # the level the DCX header names


class DfltLayout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: int
    header_level: int


class ZstdLayout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: int
    window_log: int  # the game's decoder keeps this much history (2**window_log bytes)
    content_size: bool  # whether the frame header names the content size


class DcxWriter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    krak: KrakenLayout
    dflt: DfltLayout
    zstd: ZstdLayout


class GameConfig(BaseModel):
    """One game's files: its archives (names and the RSA public keys of their headers), the Oodle library it ships,
    the DCX layouts the launcher writes for it, and the file types it loads as DFLT in place of KRAK."""

    model_config = ConfigDict(extra="forbid")
    game: str
    note: str = ""
    archive_names: list[str]
    archives: dict[str, str]  # archive name -> PEM public key of its header
    oodle_library: str  # a glob in the game folder
    dcx_writer: DcxWriter
    dflt_fallback: list[str]  # file name endings, lower-case

    def dflt_fallback_for(self, rel: str) -> bool:
        """Whether rel may be written as DFLT when the game's Oodle library is not available."""
        low = rel.replace("\\", "/").lower()
        return any(low.endswith(end) for end in self.dflt_fallback)


@cache
def load(game: str = "eldenring") -> GameConfig:
    return GameConfig.model_validate(json.loads((GAMES_DIR / f"{game}.json").read_text(encoding="utf-8")))


def schema() -> dict:
    return GameConfig.model_json_schema()


def schema_path() -> Path:
    return DATA_DIR / "schemas" / "game.schema.json"
