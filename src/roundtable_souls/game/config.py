"""What the launcher knows about a game's files, from data/games/<game>.json, as a Pydantic model."""

from __future__ import annotations

import json
from fnmatch import fnmatchcase
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


class FileCategory(BaseModel):
    """One rule of the file-category map: game paths matching pattern are called label (a few plain words)."""

    model_config = ConfigDict(extra="forbid")
    pattern: str  # a glob on a game path, lower-case with forward slashes; * also matches across folders
    label: str  # what such a file is, in plain words ("characters", "text")


class GameConfig(BaseModel):
    """One game's files: its archives (names and the RSA public keys of their headers), the Oodle library it ships,
    the DCX layouts the launcher writes for it, the file types it loads as DFLT in place of KRAK, and how its mods are
    laid out (the folders a package serves game files from, the DLLs in a download that are not mods), and a short
    plain name for what a game file is, by its path."""

    model_config = ConfigDict(extra="forbid")
    game: str
    note: str = ""
    archive_names: list[str]
    archives: dict[str, str]  # archive name -> PEM public key of its header
    oodle_library: str  # a glob in the game folder
    dcx_writer: DcxWriter
    dflt_fallback: list[str]  # file name endings, lower-case
    mod_folders: list[str]  # top-level folders of a package that me3 serves game files from, lower-case
    file_categories: list[FileCategory]  # in order: the first rule that matches a path names it
    ignored_dlls: list[str]  # DLLs in a mod download that are not mods (loaders, runtimes), lower-case

    def dflt_fallback_for(self, rel: str) -> bool:
        """Whether rel may be written as DFLT when the game's Oodle library is not available."""
        low = rel.replace("\\", "/").lower()
        return any(low.endswith(end) for end in self.dflt_fallback)

    def category_of(self, rel: str) -> str | None:
        """What the game file at rel is, in plain words, from the first rule that matches it; None when none does.
        Case and the kind of slash in rel do not matter."""
        low = rel.replace("\\", "/").lower()
        return next((c.label for c in self.file_categories if fnmatchcase(low, c.pattern.lower())), None)


@cache
def load(game: str = "eldenring") -> GameConfig:
    return GameConfig.model_validate(json.loads((GAMES_DIR / f"{game}.json").read_text(encoding="utf-8")))


def schema() -> dict:
    return GameConfig.model_json_schema()


def schema_path() -> Path:
    return DATA_DIR / "schemas" / "game.schema.json"
