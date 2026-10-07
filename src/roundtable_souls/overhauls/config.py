"""Overhaul configs: one TOML file per overhaul mod (data/overhauls/*.toml, or the local folder) saying how to
recognise it and how the launcher builds it, as a Pydantic model.

An overhaul is a mod that must load after the others and ships merged copies of game files other mods also change
(Nightreign Revive). Its config has two parts:

    recognise   how the launcher knows it is there: its own folder beside the me3 profile (or in the game folder),
                its installer's manifest in that folder, the profile entries that mean a setup includes it, and the
                text that marks its profile entries (an offline launch can switch those off)
    builds      what the launcher can build itself, one per edition: how to recognise that edition's download and
                which versions it was written for, and the steps that build its output from the packages before it
                (the steps mods.engine runs, none of them a program of the mod's; docs/Overhaul configs.md); and,
                optionally, what installing that edition does to the me3 profile (install; overhauls.install_plan
                works out the changes, nothing here writes a profile)

The shipped configs are in data/overhauls; a file in the local folder (overhauls/ in the launcher's data folder) with
the same id replaces the shipped one, and one with a new id adds an overhaul. A file that does not read or does not
fit the model is left out, and problems() says why.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from roundtable_souls.resources import DATA_DIR

SHIPPED_DIR = DATA_DIR / "overhauls"
RECIPE_VERSION = 2  # the step format mods.engine reads (1: the former data/recipes JSON, with the mod's tool)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ----------------------------------------------------------------------------- recognising it
class Recognise(_Strict):
    folder: str  # its own folder, beside the me3 profile (or in the game folder: an edition that installs there)
    manifest: str  # its installer's manifest in that folder; a Play setup started from such a file includes it
    mod_ids: list[str] = Field(default_factory=list)  # profile entries (lower-case ids) meaning a setup includes it
    profile_marks: list[str] = Field(default_factory=list)  # text in a profile entry that marks it as this overhaul's


# ----------------------------------------------------------------------------- recognising a download
class JsonEquals(_Strict):
    file: str
    key: str
    equals: str | int | bool


class VersionKey(_Strict):
    file: str
    key: str


class Match(_Strict):
    files: list[str] = Field(default_factory=list)  # must all be in the download
    json_: list[JsonEquals] = Field(default_factory=list, alias="json")  # values its JSON files must have
    version: VersionKey | None = None  # where the download says its version
    versions: list[str] = Field(default_factory=list)  # the versions this build was written for (empty: any)


class Output(_Strict):
    mod: str = "mod"  # the package's folder name inside the output
    report: str = "merge-report.txt"
    manifest: str = "installation.json"


# ----------------------------------------------------------------------------- steps
class Each(_Strict):
    folders_in: str  # the step runs once per folder in here ({each})
    except_: list[str] = Field(default_factory=list, alias="except")


class CopyTree(_Strict):
    do: Literal["copy_tree"]
    from_: str = Field(alias="from")
    to: str


class Copy(_Strict):
    do: Literal["copy"]
    from_: str = Field(alias="from")
    to: str


class KeepConfig(_Strict):
    do: Literal["config"]
    from_: str = Field(alias="from")  # the download's default
    to: str  # the player's file: kept, with only the keys a newer default adds


class Params(_Strict):
    do: Literal["params"]
    file: str
    patch: str
    each: Each | None = None


class Merge(_Strict):
    do: Literal["merge"]
    file: str
    patch: str
    vanilla: str | None = None  # the download's copy of the game's file, when the game's archives lack it
    each: Each | None = None


class AddText(_Strict):
    do: Literal["text"]
    file: str
    table: str
    texts: dict[str, str]  # {each} folder (or "*") -> the mod's strings, a JSON object of text ID to string
    vanilla: str | None = None
    each: Each | None = None


class ScriptAppend(_Strict):
    do: Literal["script_append"]
    folder: str
    entry: str
    base: str
    base_until: str | None = None
    append: str
    refuse: list[str] = Field(default_factory=list)
    refuse_text: str | None = None


class Remove(_Strict):
    do: Literal["remove"]
    glob: str


Step = Annotated[
    CopyTree | Copy | KeepConfig | Params | Merge | AddText | ScriptAppend | Remove,
    Field(discriminator="do"),
]


# ----------------------------------------------------------------------------- installing it into a profile
class Initializer(_Strict):
    function: str  # the DLL's function me3 calls after loading it


class InstallNative(_Strict):
    """A DLL entry the install adds, with its load settings exactly as the overhaul's installer writes them."""

    file: str  # in the overhaul's own folder
    load_early: bool | None = None
    initializer: Initializer | None = None
    after_enabled_natives: bool = False  # load_after every enabled DLL already in the profile, each optional


class InstallPackage(_Strict):
    id: str
    folder: str = "mod"  # in the overhaul's own folder
    after_enabled_packages: bool = False  # load_after every enabled package already in the profile, each optional


class SetInitializer(_Strict):
    """An initializer the install gives other mods' DLLs that have none (a companion mod the overhaul knows)."""

    name_prefix: str  # DLL file names starting with this, case aside
    function: str


class Seamless(_Strict):
    """The overhaul needs Seamless Co-op's DLL switched on in the profile."""

    dll: str = "ersc.dll"
    # Where to look when the profile has none switched on, in order; {profile_dir} and {game_dir} are filled in.
    candidates: list[str] = Field(default_factory=list)


class Install(_Strict):
    """What installing one edition does to the me3 profile it is installed into (its own folder beside it)."""

    profile_settings: dict[str, str | int | bool] = Field(default_factory=dict)  # top-level keys set
    owned_package_ids: list[str] = Field(default_factory=list)  # earlier installs' entries, removed first
    owned_dlls: list[str] = Field(default_factory=list)  # DLL file names (lower-case), removed first
    seamless: Seamless | None = None
    set_initializers: list[SetInitializer] = Field(default_factory=list)
    natives: list[InstallNative] = Field(default_factory=list)  # added after the profile's own, in this order
    package: InstallPackage | None = None  # added after the profile's own
    required_files: list[str] = Field(default_factory=list)  # in its folder, after a build (its check)
    required_folders: list[str] = Field(default_factory=list)  # in its folder, not empty


class Build(_Strict):
    """One edition the launcher builds itself."""

    id: str  # written into the build's manifest (as "recipe") and its build key
    match: Match
    output: Output
    steps: list[Step]
    install: Install | None = None  # what installing it does to the profile; None: the launcher does not install it


# ----------------------------------------------------------------------------- the config
class OverhaulConfig(_Strict):
    overhaul: Literal[1]  # the version of this format
    id: str
    label: str
    short_label: str  # where space is short (the Play page's summary)
    game: str  # the game's key (data/games, game.catalog)
    recognise: Recognise
    builds: list[Build] = Field(default_factory=list)
    # Editions its installer knows that the launcher does not install, and why (edition -> reason).
    install_unsupported: dict[str, str] = Field(default_factory=dict)

    def recipe(self, build: Build) -> dict:
        """One build in the shape mods.engine reads (the former data/recipes JSON). Only what the file sets is
        included, so a build's key stays the same for the same file."""
        steps = [s.model_dump(by_alias=True, exclude_unset=True) for s in build.steps]
        return {
            "recipe": RECIPE_VERSION,
            "id": build.id,
            "label": self.label,
            "match": build.match.model_dump(by_alias=True, exclude_unset=True),
            "output": build.output.model_dump(by_alias=True, exclude_unset=True),
            "steps": steps,
        }


# ----------------------------------------------------------------------------- loading
_problems: list[str] = []


def local_dir() -> Path | None:
    """The local folder (overhauls/ in the launcher's data folder), or None before the data folder is set."""
    from roundtable_souls.platform import data_folder

    try:
        return data_folder.data_root() / "overhauls"
    except RuntimeError:
        return None


def read(path: Path) -> OverhaulConfig:
    """One config file. Raises ValueError (tomllib's and Pydantic's errors are ValueErrors) or OSError."""
    return OverhaulConfig.model_validate(tomllib.loads(Path(path).read_text(encoding="utf-8")))


def load(game: str | None = None) -> list[OverhaulConfig]:
    """Every usable config, shipped then local (a local one replaces the shipped one with its id), for one game when
    given. Files that do not read or fit are left out; problems() lists them."""
    found: dict[str, OverhaulConfig] = {}
    _problems.clear()
    for folder in (SHIPPED_DIR, local_dir()):
        if folder is None or not folder.is_dir():
            continue
        for f in sorted(folder.glob("*.toml")):
            try:
                cfg = read(f)
            except (OSError, ValueError, ValidationError) as e:
                _problems.append(f"{f}: {str(e).splitlines()[0] if str(e) else type(e).__name__}")
                continue
            found[cfg.id] = cfg
    return [c for c in found.values() if game is None or c.game == game]


def problems() -> list[str]:
    """Why config files were left out by the last load()."""
    return list(_problems)


def schema() -> dict:
    return OverhaulConfig.model_json_schema(by_alias=True)


def schema_path() -> Path:
    return DATA_DIR / "schemas" / "overhaul.schema.json"


def write_schema() -> Path:
    """Regenerate data/schemas/overhaul.schema.json from the model (tests check they match)."""
    path = schema_path()
    path.write_text(json.dumps(schema(), indent=1) + "\n", encoding="utf-8", newline="\n")
    return path
