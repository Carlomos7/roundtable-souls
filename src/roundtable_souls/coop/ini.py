"""The Seamless Co-op ini: password, difficulty scaling, every setting typed from its comment, and the whole-file share JSON.

Elden Ring's Seamless Co-op (ersc.dll) and Nightreign's (nrsc.dll) use the same ini format with different keys:
Nightreign's has no password and scales with three values instead of six. ScalingSpec says which keys a file has.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from roundtable_souls.files import atomic_write
from roundtable_souls.game import catalog as games


def _profile_rows(text: str):
    """(kind, row) for every package and native.

    me3 accepts two shapes. Hand-written profiles use [[packages]] / [[natives]] blocks.
    Nightreign Revive's installer writes packages = [ { ... } ] and natives = [ { ... } ] instead.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    out = []
    for key, rows in data.items():
        kind = {"packages": "package", "natives": "native"}.get(key)
        if kind is None:
            continue
        if isinstance(rows, dict):
            rows = [rows]
        if isinstance(rows, list):
            out.extend((kind, row) for row in rows if isinstance(row, dict))
    return out


def coop_ini_for(profile: str, game: games.Game | None = None) -> Path | None:
    """The settings ini of the Seamless Co-op dll this profile loads (paths in .me3 are relative to it): ersc.dll and
    ersc_settings.ini for Elden Ring, nrsc.dll and nrsc_settings.ini for Nightreign. None for games without one."""
    game = game or games.ELDEN_RING
    if not game.coop_dll or not game.coop_ini:
        return None
    dll = game.coop_dll.lower()
    try:
        text = Path(profile).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    paths = []
    rows = _profile_rows(text)
    if rows is not None:
        paths = [
            str(row.get("path") or "")
            for kind, row in rows
            if kind == "native"
            and row.get("enabled", True) is not False
            and Path(str(row.get("path") or "")).name.lower() == dll
        ]
    if not paths:
        paths = re.findall(r"""(?m)^[^#\n]*path\s*=\s*['"]([^'"]*""" + re.escape(dll) + r""")['"]""", text, re.I)
    for raw in paths:
        p = Path(raw)
        p = p if p.is_absolute() else Path(profile).parent / p
        ini = p.parent / game.coop_ini
        if ini.is_file():
            return ini
    return None


def ersc_ini_for(profile: str) -> Path | None:
    """Elden Ring's Seamless Co-op ini for this profile."""
    return coop_ini_for(profile, games.ELDEN_RING)


PW_RE = re.compile(
    r"^([ \t]*cooppassword[ \t]*=[ \t]*)(.*?)([ \t]*)(?=\r?$)", re.M | re.I
)  # [ \t] never \s (\s eats line breaks); group 3 = trailing blanks, kept; the lookahead leaves a CR in place


def _read(ini: Path) -> str:
    with open(ini, encoding="utf-8", errors="replace", newline="") as f:
        return f.read()  # keep CRLF as is


def _write(ini: Path, text: str):
    atomic_write(ini, text, backup=True)  # ersc_settings.ini.bak = the version before this write


def has_password(ini: Path) -> bool:
    """Whether this ini has a cooppassword line at all (Nightreign's Seamless Co-op has none)."""
    return bool(PW_RE.search(_read(ini)))


def read_password(ini: Path) -> str | None:
    m = PW_RE.search(_read(ini))
    return m.group(2) if m else None


def write_password(ini: Path, value: str):
    text = _read(ini)
    if not PW_RE.search(text):
        raise ValueError("no cooppassword line in " + str(ini))
    new = PW_RE.sub(lambda m: m.group(1) + value + m.group(3), text, count=1)
    if new != text:
        _write(ini, new)


def _key_re(key):
    return re.compile(r"^([ \t]*" + re.escape(key) + r"[ \t]*=[ \t]*)(.*?)([ \t]*)(?=\r?$)", re.M | re.I)


def read_keys(ini: Path, keys) -> dict:
    """key -> value string for the keys present in the ini (comments and layout untouched)."""
    text = _read(ini)
    out = {}
    for k in keys:
        m = _key_re(k).search(text)
        if m:
            out[k] = m.group(2)
    return out


def write_keys(ini: Path, values: dict):
    """Rewrite only the given keys in place; a key that is not in the file is reported, never appended."""
    text = _read(ini)
    missing = []
    for k, v in values.items():
        rx = _key_re(k)
        if rx.search(text):
            text = rx.sub(lambda m, v=v: m.group(1) + str(v) + m.group(3), text, count=1)
        else:
            missing.append(k)
    _write(ini, text)
    return missing


SECTION_TITLES = {
    "GAMEPLAY": "Gameplay",
    "SCALING": "Difficulty scaling",
    "PASSWORD": "Password",
    "SAVE": "Save file",
    "LANGUAGE": "Language",
}
_CHOICE_RE = re.compile(r"(\d+)\s*=\s*([^|]+?)\s*(?=\||$)")


def _kind_of(key: str, value: str, desc: str):
    """(kind, extra): bool | choice (list of (int, label)) | int (lo, hi) | text | password, from the comment."""
    d = desc.replace(" ", "")
    if key == "cooppassword":
        return "password", None
    if "0=FALSE" in d.upper() and "1=TRUE" in d.upper():
        return "bool", None
    choices = [(int(n), lab.strip().rstrip(".")) for n, lab in _CHOICE_RE.findall(desc)] if "|" in desc else []
    if len(choices) >= 2:
        return "choice", choices  # "0 = Normal | 1 = None | 2 = ..."
    nums = re.findall(r"(-?\d+)\s*=", desc)
    if "MAX" in desc.upper() and len(nums) >= 2:
        return "int", (int(nums[0]), int(nums[-1]))  # "0 = MUTE 10 = MAX"
    if value.strip().lstrip("-").isdigit():
        return "int", (0, 500)
    return "text", None


def read_settings_meta(ini: Path):
    """[{section, title, items: [{key, value, desc, kind, extra}]}] in file order. The comment line(s) directly
    above a key are its description; the kind is inferred from that comment so the window can show the right
    control (toggle, dropdown, number, text) without a hand-written table that would go stale."""
    out, section, pending = [], None, []
    for raw in _read(ini).splitlines():
        line = raw.rstrip("\r")
        if not line.strip():
            pending = []
            continue
        if line.lstrip().startswith((";", "#")):
            pending.append(line.lstrip(";# ").strip())
            continue
        m = SECTION_RE.match(line)
        if m:
            section = {
                "section": m.group(1),
                "title": SECTION_TITLES.get(m.group(1).upper(), m.group(1).title()),
                "items": [],
            }
            out.append(section)
            pending = []
            continue
        m = LINE_RE.match(line)
        if m and section is not None:
            key, value = m.group(1), m.group(2)
            desc = " ".join(pending)
            kind, extra = _kind_of(key, value, desc)
            section["items"].append({"key": key, "value": value, "desc": desc, "kind": kind, "extra": extra})
            pending = []
    return out


VOLUME_STOPS = ((0, "Mute"), (3, "Quiet"), (5, "Medium"), (8, "Loud"), (10, "Max"))
SAVE_KINDS = (("co2", "Co-op"), ("sl2", "Standard"))

SETTING_COPY = {
    "allow_invaders": {
        "label": "Invaders",
        "blurb": "Uninvited players can join and fight you.",
        "help": "When this is on, other players can invade your session and try to kill you and your party. Turn it off if you only want people you invited.",
    },
    "death_debuffs": {
        "label": "Death debuffs",
        "blurb": "Rot Essence after you die, until you rest.",
        "help": "When this is on, dying gives you Rot Essence. It lasts until you sit at a Site of Grace.",
    },
    "allow_summons": {
        "label": "Spirit summons",
        "blurb": "Ashes can help in multiplayer.",
        "help": "When this is on, spirit ashes work in a Seamless session the way they do when you play alone.",
    },
    "overhead_player_display": {
        "label": "Nameplates",
        "blurb": "What sits over other players.",
        "help": "Choose what appears over other players. Hidden removes the nameplate. Ping, level, and deaths help you tell people apart.",
        "choices": {0: "Name", 1: "Hidden", 2: "Ping", 3: "Level", 4: "Deaths", 5: "Level and ping"},
    },
    "skip_splash_screens": {
        "label": "Skip intro logos",
        "blurb": "Go straight to the menu when the game starts.",
        "help": "When this is on, the publisher and studio logos are skipped on boot.",
    },
    "append_steam_id_to_players": {
        "label": "Steam ID on nameplates",
        "blurb": "Show each player's Steam ID next to their name.",
        "help": "Adds the player's Steam ID to their nameplate. Useful if you need to report or block someone.",
        "choices": {0: "Off", 1: "On"},
    },
    "always_spectate_on_death": {
        "label": "Spectate after death",
        "blurb": "What you watch after you die.",
        "help": "Bosses and invasions keeps the usual Seamless camera. Until you rest keeps you watching teammates until the party wipes or someone sits at a grace.",
        "choices": {0: "Bosses and invasions", 1: "Until you rest"},
    },
    "default_boot_master_volume": {
        "label": "Menu volume",
        "blurb": "How loud the title screen is, before a save loads.",
        "help": "This is only the volume on the title screen. In-game volume is still set in the game's own options.",
    },
    "save_file_extension": {
        "label": "Save file",
        "blurb": "Which save Seamless writes.",
        "help": "Co-op uses a separate file from the standard game save, so they do not overwrite each other. Change this only if you know you need a different file. Letters and numbers only.",
    },
    "mod_language_override": {
        "label": "Language",
        "blurb": "Leave blank to use the game language.",
        "help": "Only fill this in if you have a custom locale file for Seamless. Empty means the game's current language.",
    },
}


def label_of(key: str) -> str:
    copy = SETTING_COPY.get(key)
    if copy:
        return copy["label"]
    return key.replace("_", " ").strip().capitalize()


def setting_face(key: str, desc: str = ""):
    """(label, short blurb, help). Ini numbers stay out of the window."""
    copy = SETTING_COPY.get(key) or {}
    return copy.get("label") or label_of(key), copy.get("blurb") or "", copy.get("help") or _human_ini_comment(desc)


def _human_ini_comment(desc: str) -> str:
    if not desc:
        return ""
    d = re.sub(r"\s*\d+\s*=\s*FALSE\s+\d+\s*=\s*TRUE", "", desc, flags=re.I)
    d = re.sub(r"\s*\d+\s*=\s*MUTE\s+\d+\s*=\s*MAX", "", d, flags=re.I)
    if "|" in d or re.search(r"\d+\s*=", d):
        d = re.split(r"\s*\d+\s*=", d, maxsplit=1)[0]
    d = re.sub(r"\s+", " ", d).strip(" .")
    return d + ("." if d else "")


def choice_label(key: str, n: int, raw: str) -> str:
    mapped = (SETTING_COPY.get(key) or {}).get("choices", {}).get(n)
    if mapped:
        return mapped
    t = (raw or "").strip().rstrip(".")
    t = re.sub(r"(?i)^display player ", "", t)
    low = t.lower()
    if low.startswith("will add the player's unique steam"):
        return "On"
    if low.startswith("spectate only"):
        return "Bosses and invasions"
    if low.startswith("always spectate"):
        return "Until you rest"
    if low == "no change":
        return "Off"
    if low == "soul level and ping":
        return "Level and ping"
    if low == "normal":
        return "Name"
    if low == "none":
        return "Hidden"
    t = re.sub(r"(?i)soul level", "Level", t)
    t = re.sub(r"(?i)death count", "Deaths", t)
    return t[:1].upper() + t[1:] if t else t


def nearest_volume_stop(n: int) -> int:
    return min(VOLUME_STOPS, key=lambda p: abs(p[0] - n))[0]


LINE_RE = re.compile(r"^[ \t]*([A-Za-z0-9_]+)[ \t]*=[ \t]*(.*?)[ \t]*$")
SECTION_RE = re.compile(r"^[ \t]*\[([^\]]+)\][ \t]*$")
