"""Names for items the game does not define, read from the mods installed on this PC.

Seamless Co-op keeps its item names in its own locale file (locale/<language>.json) under keys like
MODGOODSNAME_HOSTINGITEM; which goods ID each key belongs to follows from the mod's item table (see SEAMLESS_GOODS).
Other mods that add items ship item text tables (msg/<language>/item*.msgbnd.dcx) inside their package folders; those
are read with the game's own Oodle library, so on Linux such items keep their kind-and-ID label.

Nothing here is bundled: every name comes from files the player already has.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from roundtable_souls import formats
from roundtable_souls.game import oodle as game_oodle

GOODS = 0x40000000
SEAMLESS = "Seamless Co-op"
# Goods IDs Seamless Co-op registers, in the order of its item table, and the locale key of each name.
SEAMLESS_GOODS = {
    8380001: "HOSTINGITEM",
    8380002: "JOININGITEM",
    8380003: "BREAKINITEM",
    8380004: "LEAVINGITEM",
    8380005: "GAMERULECHANGEITEM",
    8380006: "RUNEARCITEM",
    8380007: "ROTITEM01",
    8380008: "ROTITEM02",
    8380009: "ROTITEM03",
    8380010: "ROTITEM04",
    8380011: "ROTITEM05",
    8380012: "DRIEDFINGERITEM",
}
# Item text tables and the category bits of the IDs they name. DLC variants end in _dlc01 / _dlc02.
NAME_TABLES = {
    "WeaponName": 0x00000000,
    "ProtectorName": 0x10000000,
    "AccessoryName": 0x20000000,
    "GoodsName": 0x40000000,
    "GemName": 0x80000000,
}
LANGUAGES = ("english", "engus")


@dataclass
class ItemNames:
    """Full item ID -> (name, source)."""

    names: dict[int, tuple[str, str]] = field(default_factory=dict)

    def get(self, item_id: int) -> tuple[str, str] | None:
        if item_id in self.names:
            return self.names[item_id]
        raw = item_id & 0x0FFFFFFF
        if item_id >> 28 == 0 and raw % 100:  # a weapon's upgrade level: name the base row
            hit = self.names.get(item_id - raw % 100)
            if hit:
                return f"{hit[0]} +{raw % 100}", hit[1]
        return None


def _seamless_folders(game: Path | None, profiles: Path | None) -> list[Path]:
    folders = []
    if game and (Path(game) / "SeamlessCoop").is_dir():
        folders.append(Path(game) / "SeamlessCoop")
    if profiles and profiles.is_dir():
        folders.extend(dll.parent for dll in profiles.rglob("ersc.dll"))
    return folders


def seamless_names(game: Path | None, profiles: Path | None) -> dict[int, tuple[str, str]]:
    out: dict[int, tuple[str, str]] = {}
    for folder in _seamless_folders(game, profiles):
        locale = folder / "locale"
        files = [locale / f"{lang}.json" for lang in LANGUAGES] + sorted(locale.glob("*.json"))
        for path in files:
            try:
                table = json.loads(path.read_text(encoding="utf-8"))
            except OSError, ValueError:
                continue
            for goods_id, key in SEAMLESS_GOODS.items():
                name = table.get(f"MODGOODSNAME_{key}")
                if isinstance(name, str) and name.strip():
                    out.setdefault(GOODS | goods_id, (name.strip(), SEAMLESS))
            if out:
                return out
    # Seamless not installed on this PC: its IDs are still known to be its items.
    return {GOODS | goods_id: (f"Seamless Co-op item {goods_id}", SEAMLESS) for goods_id in SEAMLESS_GOODS}


def _package_name(msgbnd: Path) -> str:
    """The mod's folder: the parent of the msg folder the file sits in."""
    for parent in msgbnd.parents:
        if parent.name.lower() == "msg":
            return parent.parent.name
    return msgbnd.parent.name


def mod_text_names(roots: list[Path], oodle) -> dict[int, tuple[str, str]]:
    out: dict[int, tuple[str, str]] = {}
    for root in roots:
        for msgbnd in sorted(root.rglob("item*.msgbnd.dcx")):
            if msgbnd.parent.name.lower() != "engus":
                continue
            try:
                files = formats.bnd4.bnd4_files(formats.dcx.dcx_decompress(msgbnd.read_bytes(), oodle))
            except OSError, formats.FormatError, ValueError, IndexError:
                continue
            source = _package_name(msgbnd)
            for name, blob in files:
                table = name.split(".", 1)[0].split("_dlc", 1)[0]
                bits = NAME_TABLES.get(table)
                if bits is None:
                    continue
                try:
                    entries = formats.fmg.fmg_entries(blob)
                except ValueError, IndexError:
                    continue
                for text_id, text in entries.items():
                    out.setdefault(bits | text_id, (text, source))
    return out


RECHECK_SECONDS = 15.0
_CACHE: tuple[tuple, ItemNames] | None = None
_CHECKED_AT = 0.0


def _fingerprint(paths: list[Path]) -> tuple:
    out = []
    for p in paths:
        try:
            out.append((str(p), p.stat().st_mtime_ns))
        except OSError:
            continue
    return tuple(out)


def item_names(game: Path | None, profiles: Path | None, refresh: bool = False) -> ItemNames:
    """Names for the mods installed right now (game: the game's folder; profiles: me3's profiles folder). The mod
    folders are looked at again at most every few seconds (or on refresh), and the names are rebuilt only when the
    files behind them changed."""
    global _CACHE, _CHECKED_AT
    now = time.monotonic()
    where = (str(game or ""), str(profiles or ""))
    if _CACHE and _CACHE[0][0] == where and not refresh and now - _CHECKED_AT < RECHECK_SECONDS:
        return _CACHE[1]
    _CHECKED_AT = now
    roots = [profiles] if profiles and profiles.is_dir() else []
    watched = _seamless_folders(game, profiles) + [m for r in roots for m in r.rglob("item*.msgbnd.dcx")]
    key = (where, _fingerprint(watched))
    if _CACHE and _CACHE[0] == key:
        return _CACHE[1]
    names: dict[int, tuple[str, str]] = {}
    names.update(mod_text_names(roots, game_oodle.find_oodle(game)))
    names.update(seamless_names(game, profiles))
    result = ItemNames(names)
    _CACHE = (key, result)
    return result
