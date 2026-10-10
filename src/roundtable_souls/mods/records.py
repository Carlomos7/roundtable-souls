"""The launcher's records in its mod folder (mods.library), as versioned models. They are files, not database rows:
each one travels with the folder it describes (§8.8). Each keeps only what cannot be worked out again later.

    OverhaulRecord     overhauls/<id>/roundtable.json: which build of the overhaul's config it is, the download's
                       fingerprint (over exactly the files the config takes, at download paths), when and from where
                       it was installed. The label, the verified version and the profiles using it are looked up.
    SourcesRecord      sources/<id>/roundtable.json: where each translated file came from in the download, and its hash
    BuildRecord        builds/<what>/<profile>/build.json: what the build was made from (the packages' files it read,
                       the sources, the profile's order, the game's files, the overhaul's config, the merger's rules);
                       a change to any makes it out of date
    SideEffectsRecord  builds/<what>/<profile>/roundtable.json: what an install changed in entries it does not own
                       (Seamless switched on, start_online), so removing it reverts only what is still as it set

Every record has a `version`. read() takes the JSON as written and moves an older version forward one step at a time
(MIGRATIONS: version -> the function making the next version), so a file written by an earlier launcher still reads.
A newer version than this launcher knows, an unknown key or a wrong value is refused with RecordError, never guessed
at or overwritten. The JSON schemas in data/schemas are made from these models (write_schemas), never edited.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from roundtable_souls.resources import DATA_DIR

Json = str | int | float | bool | None | list[Any] | dict[str, Any]


class RecordError(ValueError):
    """A record that cannot be read: not JSON, a newer version, or not the shape its version has."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Record(_Strict):
    """A versioned record. VERSION is the version written; MIGRATIONS turns version n's JSON into version n+1's."""

    VERSION: ClassVar[int] = 1
    MIGRATIONS: ClassVar[dict[int, Callable[[dict], dict]]] = {}
    FILE: ClassVar[str] = ""  # its file name in the library
    SCHEMA: ClassVar[str] = ""  # its schema's file name in data/schemas
    # Each record declares `version: Literal[VERSION]`, the version it writes.

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Each record class gets a MIGRATIONS of its own, so a step registered on one is never another's."""
        super().__init_subclass__(**kwargs)
        if "MIGRATIONS" not in cls.__dict__:
            cls.MIGRATIONS = {}

    @classmethod
    def read(cls, data: dict | str | bytes) -> Self:
        """The record from its JSON (text or already parsed), an older version moved forward first."""
        if not isinstance(data, dict):
            try:
                data = json.loads(data)
            except ValueError as e:
                raise RecordError(f"not JSON: {e}") from e
        if not isinstance(data, dict):
            raise RecordError("not a JSON object")
        data = dict(data)
        have = data.get("version", 0)  # a record from before versions were written is version 0
        if not isinstance(have, int) or isinstance(have, bool) or have < 0:
            raise RecordError(f"version {have!r} is not a version")
        if have > cls.VERSION:
            raise RecordError(f"written by a newer launcher (version {have}; this one reads up to {cls.VERSION})")
        while have < cls.VERSION:
            step = cls.MIGRATIONS.get(have)
            if step is None:
                raise RecordError(f"version {have} can't be read by this launcher")
            data = step(data)
            have += 1
            data["version"] = have
        try:
            return cls.model_validate(data)
        except ValidationError as e:
            first = e.errors()[0]
            where = ".".join(str(x) for x in first["loc"]) or "the record"
            raise RecordError(f"{where}: {first['msg']}") from e

    @classmethod
    def load(cls, path: Path) -> Self:
        try:
            return cls.read(Path(path).read_bytes())
        except OSError as e:
            raise RecordError(f"{path} could not be read: {e}") from e

    def dump(self) -> dict:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)

    def text(self) -> str:
        """The record as it is written: indented JSON, a newline at the end."""
        return json.dumps(self.dump(), indent=1) + "\n"


# ----------------------------------------------------------------------------- overhauls/<id>/roundtable.json
class OverhaulRecord(Record):
    """An installed overhaul."""

    FILE: ClassVar[str] = "roundtable.json"
    SCHEMA: ClassVar[str] = "library-overhaul.schema.json"

    version: Literal[1] = 1
    build: str = Field(description="the config's build that was used (its id); 'default' for a form-made overhaul")
    fingerprint: str = Field(
        description="sha256 over the files the config takes from the download, at download paths, before translation"
    )
    installed: str | None = Field(default=None, description="when it was installed (UTC, ISO 8601)")
    from_: str | None = Field(default=None, alias="from", description="where the download was installed from")


# ----------------------------------------------------------------------------- sources/<id>/roundtable.json
class SourceFile(_Strict):
    from_: str = Field(alias="from", description="its path in the download")
    sha256: str


class SourcesRecord(Record):
    """Where each translated source file came from."""

    FILE: ClassVar[str] = "roundtable.json"
    SCHEMA: ClassVar[str] = "library-sources.schema.json"

    version: Literal[1] = 1
    files: dict[str, SourceFile] = Field(
        default_factory=dict, description="each file by its path in the sources folder (role/path), with its origin"
    )


# ----------------------------------------------------------------------------- builds/<what>/<profile>/build.json
class GameFiles(_Strict):
    """The game's own files a build merged against: a game update changes them."""

    archives: str = Field(description="the archive indexes' fingerprint (sizes and times of the .bhd files)")
    regulation_sha256: str | None = Field(default=None, description="the game's regulation.bin")
    regulation_version: str | None = Field(default=None, description="the version the regulation names")


class BuildFacts(_Strict):
    """How a build was made, besides the mods' files: the rules of merging and the game and config it was made for.
    merging.record.facts() makes these; a change to any but me3_version makes the build out of date."""

    merger_revision: int
    ordering: str
    game_config_sha256: str
    removal_choice: str
    me3_version: str | None = None
    game: GameFiles | None = None
    config_sha256: str | None = Field(default=None, description="the overhaul config's build, for an overhaul's build")


class InputFile(_Strict):
    path: str = Field(description="relative to the library (with /), or absolute when outside it")
    sha256: str


class BuildRecord(BuildFacts, Record):
    """What one profile's build was made from."""

    FILE: ClassVar[str] = "build.json"
    SCHEMA: ClassVar[str] = "library-build.schema.json"

    version: Literal[1] = 1
    made_by: str = Field(description="the launcher that made it, 'Roundtable Souls <version>'")
    packages: list[InputFile] = Field(default_factory=list, description="the packages' files it read, in load order")
    sources: str | None = Field(default=None, description="sha256 over the overhaul's sources record, when it read one")
    order: list[str] = Field(default_factory=list, description="the profile's entries before it, in load order")


def _build_from_legacy(old: dict) -> dict:
    """Version 0: the record a build kept before the library (Combine's combined-parameters.json, the launcher's
    build of an overhaul in its installation.json) as a build record: its facts, its inputs and the game's files."""
    facts = old.get("inputs") if isinstance(old.get("inputs"), dict) else old
    out: dict = {k: facts[k] for k in BuildFacts.model_fields if k in facts}
    if "game" not in out and old.get("archives"):
        out["game"] = {
            "archives": old["archives"],
            "regulation_sha256": old.get("base_sha256"),
            "regulation_version": old.get("base_version"),
        }
    rows = old.get("sources") if isinstance(old.get("sources"), list) else old.get("packs") or []
    out["packages"] = [
        {"path": str(r["path"]).replace("\\", "/"), "sha256": str(r["sha256"]).lower()}
        for r in rows
        if isinstance(r, dict) and r.get("path") and r.get("sha256")
    ]
    out["made_by"] = str(old.get("made_by") or old.get("builtBy") or "an earlier launcher")
    return out


BuildRecord.MIGRATIONS = {0: _build_from_legacy}


# ----------------------------------------------------------------------------- builds/<what>/<profile>/roundtable.json
class SideEffect(_Strict):
    """One change an install made outside its own entries."""

    entry: str | None = Field(default=None, description="the entry changed (its id or file name); none: the profile")
    setting: str = Field(description="the key changed, for example enabled or start_online")
    before: Json = Field(default=None, description="its value before the install")
    before_set: bool = Field(default=True, description="false when the key was not there before the install")
    after: Json = Field(description="the value the install set")


class SideEffectsRecord(Record):
    """What an install changed in entries it does not own."""

    FILE: ClassVar[str] = "roundtable.json"
    SCHEMA: ClassVar[str] = "library-side-effects.schema.json"

    version: Literal[1] = 1
    changes: list[SideEffect] = Field(default_factory=list)


RECORDS: tuple[type[Record], ...] = (OverhaulRecord, SourcesRecord, BuildRecord, SideEffectsRecord)


# ----------------------------------------------------------------------------- schemas
def schema(record: type[Record]) -> dict:
    return record.model_json_schema(by_alias=True)


def schema_path(record: type[Record]) -> Path:
    return DATA_DIR / "schemas" / record.SCHEMA


def write_schemas() -> list[Path]:
    """Regenerate each record's schema in data/schemas from its model (tests check they match)."""
    out = []
    for record in RECORDS:
        path = schema_path(record)
        path.write_text(json.dumps(schema(record), indent=1) + "\n", encoding="utf-8", newline="\n")
        out.append(path)
    return out
