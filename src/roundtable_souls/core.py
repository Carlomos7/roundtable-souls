"""Model layer of the launcher: setups, the Seamless Co-op ini (password, scaling, whole-file share JSON),
read-only save info, the session jobs, atomic file writes and error reporting. No UI in here; ui/window.py
is the window and tests/ exercise this module directly.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import time
import tomllib
import traceback
from pathlib import Path

from roundtable_souls import __version__
from roundtable_souls.mods import manage as mod_manage
from roundtable_souls.mods import profile as profile_tools
from roundtable_souls.resources import ASSETS_DIR
from roundtable_souls.saves import analyze as save_analyze
from roundtable_souls.saves import fix as save_fix
from roundtable_souls.saves import layout as save_layout_check
from roundtable_souls.saves import loading as save_loading
from roundtable_souls.saves import regulation as repair_regulation
from roundtable_souls.saves import vanilla as save_vanilla
from roundtable_souls.settings import FROZEN, data_dir, exe_dir, load_settings, save_settings
from roundtable_souls.system import common, me3_info
from roundtable_souls.system import logging as run_logging
from roundtable_souls.system import session as me3_session

HERE = exe_dir()
DATA_DIR = data_dir()
SETTINGS = DATA_DIR / "launcher_settings.json"
LOGS = DATA_DIR / "logs"
__all__ = ["FROZEN", "load_settings", "save_settings"]


def atomic_write(path: Path, data, backup=False):
    """Write to a temp file next to the target and rename over it (atomic on Windows), keeping one .bak."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    if isinstance(data, str):
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(data)
    else:
        tmp.write_bytes(data)
    if backup and path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    os.replace(tmp, path)


def report_exception(exc_type, exc, tb, where="launcher"):
    """Every uncaught error, in the UI thread or a worker, goes to logs/launcher-errors.log and a message box."""
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        with open(LOGS / "launcher-errors.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  [{where}]\n{text}\n")
    except OSError:
        pass
    if NOTIFY is not None:
        try:
            NOTIFY(TITLE, "Something went wrong:\n" + str(exc) + "\n\nDetails are in logs\\launcher-errors.log")
        except Exception:
            pass


GAME = "eldenring"
TITLE = "Roundtable Souls"
VERSION = __version__
EXE_NAME = "RoundtableSouls"
NOTIFY = None  # the window sets this to a function (title, message) that shows an error to the user


def logo_kind(theme_dark: bool, logo: str = "auto") -> str:
    """Which mark to show. auto follows the window theme; dark and light stay put."""
    if logo == "light":
        return "light"
    if logo == "dark":
        return "dark"
    return "dark" if theme_dark else "light"


def logo_path(theme_dark: bool, logo: str = "auto") -> Path:
    p = ASSETS_DIR / f"logo-{logo_kind(theme_dark, logo)}.png"
    return p if p.is_file() else ASSETS_DIR / "icon.ico"


# ----------------------------------------------------------------------------- settings
PATH_SETTINGS = ("me3_path", "game_exe", "me3_profile_dir")  # Tools > Locations; blank = detect


def apply_overrides(settings: dict | None = None) -> dict:
    """Push the location settings into the tools layer. The profile folder falls back to what `me3 info` last
    reported (cached in settings), then to me3's default. Returns what is in effect."""
    s = load_settings() if settings is None else settings
    me3 = str(s.get("me3_path") or "").strip()
    game = str(s.get("game_exe") or "").strip()
    prof = (
        str(s.get("me3_profile_dir") or "").strip()
        or str((s.get("me3_info_cache") or {}).get("profile_dir") or "").strip()
    )
    common.ME3_OVERRIDE = me3 or None
    common.GAME_EXE_OVERRIDE = game or None
    common.PROFILE_DIR_OVERRIDE = prof or None
    return {"me3": me3, "game_exe": game, "profile_dir": prof}


# ----------------------------------------------------------------------------- setups
class Setup:
    """What to launch and how. kind: 'me3' (installed me3, --game) or 'revive' (installation.json, --exe)."""

    def __init__(self, kind, profile, me3=None, exe=None, source=None, ini=None):
        self.kind, self.profile, self.me3, self.exe, self.source = kind, str(profile), me3, exe, str(source or profile)
        self.ini = ini or ersc_ini_for(self.profile)

    @property
    def label(self):
        name = Path(self.profile).name
        if self.kind == "revive":
            return f"{name}  ·  installation.json"
        return name

    def me3_path(self):
        return Path(self.me3) if self.me3 else common.me3_exe()

    def summary(self):
        me3 = self.me3_path()
        game = Path(self.exe).name if self.exe else "Elden Ring (Steam)"
        return f"me3: {me3 if me3 else 'not found'}    game: {game}"

    def problems(self):
        out = []
        if not Path(self.profile).is_file():
            out.append(f"profile missing: {self.profile}")
        if self.me3 and not Path(self.me3).is_file():
            out.append(f"me3 missing: {self.me3}")
        if not self.me3 and not common.me3_exe():
            out.append("me3 is not installed on this PC (not on PATH, not in its default folder, not set on Tools)")
        if self.exe and not Path(self.exe).is_file():
            out.append(f"game exe missing: {self.exe}")
        if common.GAME_EXE_OVERRIDE and not Path(common.GAME_EXE_OVERRIDE).is_file():
            out.append(f"game exe set on Tools is missing: {common.GAME_EXE_OVERRIDE}")
        return out

    def launch_exe(self):
        """What me3 launches with --exe: the installation's own exe, else the custom exe from Tools, else Steam (--game)."""
        return self.exe or common.GAME_EXE_OVERRIDE


def setup_from_installation(path: Path) -> Setup | None:
    try:
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    if not cfg.get("profile"):
        return None
    ini = None
    if cfg.get("seamless"):
        cand = Path(cfg["seamless"]).parent / "ersc_settings.ini"
        if cand.is_file():
            ini = cand
    return Setup("revive", cfg["profile"], cfg.get("me3"), cfg.get("game"), source=path, ini=ini)


def setup_from_path(p: str) -> Setup | None:
    p = Path(p)
    if p.name.lower() == "installation.json":
        return setup_from_installation(p)
    if p.suffix.lower() == ".me3" and p.is_file():
        return Setup("me3", p)
    return None


def discover(remembered: str | None):
    """me3 profiles + every Nightreign Revive installation next to them (+ the remembered one)."""
    found, seen = [], set()

    def add(s):
        if s and s.source.lower() not in seen:
            seen.add(s.source.lower())
            found.append(s)

    if remembered:
        add(setup_from_path(remembered))
    for prof in common.me3_profiles():
        if prof.name.lower().endswith(".offline.me3"):
            continue  # our own generated copies
        add(Setup("me3", prof))
        inst = prof.parent / "NightreignRevive" / "installation.json"
        if inst.is_file():
            add(setup_from_installation(inst))
    # Revive's Standalone edition installs into the game folder itself (Launch.cmd next to eldenring.exe)
    try:
        gd = common.game_dir()
    except Exception:
        gd = None
    if gd:
        inst = Path(gd) / "NightreignRevive" / "installation.json"
        if inst.is_file():
            add(setup_from_installation(inst))
    return found


# ----------------------------------------------------------------------------- password
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


def ersc_ini_for(profile: str) -> Path | None:
    """The ersc_settings.ini of the Seamless Co-op dll this profile loads (paths in .me3 are relative to it)."""
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
            and Path(str(row.get("path") or "")).name.lower() == "ersc.dll"
        ]
    if not paths:
        paths = re.findall(r"""(?m)^[^#\n]*path\s*=\s*['"]([^'"]*ersc\.dll)['"]""", text, re.I)
    for raw in paths:
        p = Path(raw)
        p = p if p.is_absolute() else Path(profile).parent / p
        ini = p.parent / "ersc_settings.ini"
        if ini.is_file():
            return ini
    return None


PW_RE = re.compile(
    r"^([ \t]*cooppassword[ \t]*=[ \t]*)(.*?)([ \t]*)(?=\r?$)", re.M | re.I
)  # [ \t] never \s (\s eats line breaks); group 3 = trailing blanks, kept; the lookahead leaves a CR in place


def _read(ini: Path) -> str:
    with open(ini, encoding="utf-8", errors="replace", newline="") as f:
        return f.read()  # keep CRLF as is


def _write(ini: Path, text: str):
    atomic_write(ini, text, backup=True)  # ersc_settings.ini.bak = the version before this write


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


# ----------------------------------------------------------------------------- difficulty scaling (same ini)
SCALING_KEYS = (
    "enemy_health_scaling",
    "enemy_damage_scaling",
    "enemy_posture_scaling",
    "boss_health_scaling",
    "boss_damage_scaling",
    "boss_posture_scaling",
)
SCALING_LABELS = ("Enemy HP", "Enemy damage", "Enemy posture", "Boss HP", "Boss damage", "Boss posture")
SCALING_PRESETS = {  # % per extra player (Seamless applies each value once per player beyond the host)
    "Seamless default": (35, 0, 15, 100, 0, 20),
    # Nightreign's own rule, from datamined values: enemy and boss HP scale linearly with the party (a Nightlord has
    # 3x its solo HP with three players, so +100 % per extra player, mobs the same), damage does NOT change with
    # player count, and poise goes from 80 solo to 130 with three (about +30 % per extra player).
    "Party of 3 (Nightreign rule)": (100, 0, 30, 100, 0, 30),
    # Larger parties: Seamless keeps adding the per-player value for every extra player, so with these numbers a full
    # party of 4 or 5 lands on the same total as Nightreign's trio (3x HP, ~1.6x poise) instead of 4x or 5x HP.
    "Party of 4": (67, 0, 20, 67, 0, 20),
    "Party of 5": (50, 0, 15, 50, 0, 15),
    "Party of 6": (40, 0, 12, 40, 0, 12),
}
CUSTOM = "Custom"


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


def read_scaling(ini: Path):
    vals = read_keys(ini, SCALING_KEYS)
    try:
        return tuple(int(vals[k]) for k in SCALING_KEYS)
    except KeyError, ValueError:
        return None


def preset_of(values):
    return next((n for n, v in SCALING_PRESETS.items() if tuple(v) == tuple(values)), CUSTOM)


# ----------------------------------------------------------------------------- every setting, typed from its comment
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


# ----------------------------------------------------------------------------- whole-file import / export
JSON_FORMAT = "seamless-coop-settings"
LINE_RE = re.compile(r"^[ \t]*([A-Za-z0-9_]+)[ \t]*=[ \t]*(.*?)[ \t]*$")
SECTION_RE = re.compile(r"^[ \t]*\[([^\]]+)\][ \t]*$")


def read_all_settings(ini: Path) -> dict:
    """{section: {key: value}} for every `key = value` line (comments and blank lines skipped)."""
    out, section = {}, ""
    for raw in _read(ini).splitlines():
        line = raw.rstrip("\r")
        if not line.strip() or line.lstrip().startswith((";", "#")):
            continue
        m = SECTION_RE.match(line)
        if m:
            section = m.group(1)
            out.setdefault(section, {})
            continue
        m = LINE_RE.match(line)
        if m:
            out.setdefault(section, {})[m.group(1)] = m.group(2)
    return out


def export_settings(ini: Path, out: Path):
    doc = {
        "format": JSON_FORMAT,
        "version": 1,
        "exported": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": ini.name,
        "settings": read_all_settings(ini),
    }
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return sum(len(v) for v in doc["settings"].values())


def export_text(ini: Path) -> str:
    doc = {
        "format": JSON_FORMAT,
        "version": 1,
        "exported": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": ini.name,
        "settings": read_all_settings(ini),
    }
    return json.dumps(doc, indent=2)


COMMENT_PREFIX = {"toml": "#", "json": "//"}


def strip_json_comments(text: str) -> str:
    """Drops whole lines that start with // (what Ctrl+/ writes in the share box); JSON itself has no comments."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("//"))


def toggle_comment(lines: list, prefix: str) -> list:
    """Ctrl+/ on a block: if every non-blank line is already commented, uncomment; otherwise comment each non-blank
    line at the block's shallowest indent. Blank lines are left alone. One space follows the marker."""
    mark = prefix + " "
    content = [l for l in lines if l.strip()]
    if not content:
        return list(lines)
    if all(l.lstrip().startswith(prefix) for l in content):
        out = []
        for l in lines:
            if not l.strip():
                out.append(l)
                continue
            indent = len(l) - len(l.lstrip())
            rest = l[indent:]
            rest = rest[len(mark) :] if rest.startswith(mark) else rest[len(prefix) :]
            out.append(l[:indent] + rest)
        return out
    col = min(len(l) - len(l.lstrip()) for l in content)
    return [(l[:col] + mark + l[col:]) if l.strip() else l for l in lines]


def indent_lines(lines: list, outdent: bool = False, width: int = 2) -> list:
    """Tab / Shift+Tab on a selection: shift every non-blank line by `width` spaces (me3 profiles use two)."""
    if outdent:
        out = []
        for l in lines:
            n = 0
            while n < width and n < len(l) and l[n] == " ":
                n += 1
            if n == 0 and l.startswith("\t"):
                n = 1
            out.append(l[n:])
        return out
    return [(" " * width + l) if l.strip() else l for l in lines]


def parse_settings_json(text: str) -> dict:
    """{key: value} flattened from exported JSON text. Accepts the full export, or a bare {section: {key: value}}
    / {key: value} object someone typed by hand. Lines starting with // are ignored. Raises ValueError on anything else."""
    doc = json.loads(strip_json_comments(text))
    if not isinstance(doc, dict):
        raise ValueError("expected a JSON object")
    body = doc.get("settings") if doc.get("format") == JSON_FORMAT else doc
    if not isinstance(body, dict):
        raise ValueError("not a Seamless Co-op settings export")
    flat = {}
    for k, v in body.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                flat[str(k2)] = str(v2)
        elif k not in ("format", "version", "exported", "source"):
            flat[str(k)] = str(v)
    if not flat:
        raise ValueError("no settings in that text")
    return flat


def load_settings_json(path: Path) -> dict:
    return parse_settings_json(Path(path).read_text(encoding="utf-8"))


def plan_import(ini: Path, incoming: dict):
    """(changes {key: (old, new)}, unknown keys) against the current file; keys not in the file are never added."""
    current = {k: v for sec in read_all_settings(ini).values() for k, v in sec.items()}
    changes = {k: (current[k], v) for k, v in incoming.items() if k in current and current[k] != v}
    unknown = sorted(k for k in incoming if k not in current)
    return changes, unknown


# ----------------------------------------------------------------------------- saves (read-only findings + repair)
def save_info(path: Path):
    """One save file: type, modified time, findings, and its active characters."""
    path = Path(path)
    info = dict(
        path=path,
        name=path.name,
        kind="Seamless Co-op" if path.suffix.lower() == ".co2" else "Standard",
        modified="?",
        characters=[],
        block="?",
        findings=[],
        error=None,
        needs_repair=False,
        convert_ok=False,
        quest_fixes=[],
        checksum_fixes={"slots": [], "ud10": False},
        vanilla_plan=[],
        loading_plan=[],
    )
    try:
        info["modified"] = datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError as e:
        info["error"] = str(e)[:120]
        info["findings"] = [{"level": "error", "code": "read", "title": "Cannot read this save", "detail": str(e)}]
        return info
    try:
        data = path.read_bytes()
    except OSError as e:
        info["error"] = str(e)[:120]
        info["findings"] = [{"level": "error", "code": "read", "title": "Cannot read this save", "detail": str(e)}]
        return info

    if not repair_regulation.is_pc_save(data):
        info["error"] = "Not a PC Elden Ring save"
        info["findings"] = [
            {
                "level": "error",
                "code": "layout",
                "title": "Not a PC Elden Ring save",
                "detail": "Magic or size does not match.",
            }
        ]
        return info

    healthy, used, _hdr = repair_regulation.block_status(data)
    info["needs_repair"] = not healthy
    info["block"] = "needs repair" if not healthy else "OK"
    findings = []
    if healthy:
        findings.append(
            {
                "level": "ok",
                "code": "regulation",
                "title": "Regulation block OK",
                "detail": f"{used:#x} bytes of real regulation data.",
            }
        )
    else:
        findings.append(
            {
                "level": "warn",
                "code": "regulation",
                "title": "Regulation block needs repair",
                "detail": "me3 left garbage here. Repair puts the game's regulation.bin back. The game does not mind; save editors do.",
            }
        )

    try:
        r = save_layout_check.parse(str(path))
        findings.append(
            {
                "level": "ok",
                "code": "layout",
                "title": "Save layout OK",
                "detail": "Parses the way the Rust save editor expects.",
            }
        )
        bad = [str(i + 1) for i, ok in enumerate(r["slot_md5_ok"]) if not ok and r["ud10"]["active"][i]]
        if bad:
            findings.append(
                {
                    "level": "warn",
                    "code": "slot_checksum",
                    "title": "Character checksum mismatch",
                    "detail": f"Active slot(s) {', '.join(bad)}. The character still shows; some editors refuse to write that slot.",
                }
            )
        if not r["ud10_md5_ok"]:
            findings.append(
                {
                    "level": "warn",
                    "code": "ud10_checksum",
                    "title": "Profile summary checksum mismatch",
                    "detail": "UserData10 MD5 does not match. Unusual; regulation repair does not rewrite this block.",
                }
            )
        for i, why in sorted((r.get("unreadable") or {}).items()):
            if not r["ud10"].get("active_raw", r["ud10"]["active"])[i]:
                continue
            if not (0 < why["ver"] <= 81):
                continue  # current layout that fails to parse = torn write (analyzer)
            name, level = r["ud10"]["profiles"][i] if i < len(r["ud10"]["profiles"]) else ("", 0)
            info["unreadable"] = info.get("unreadable", []) + [
                {"slot": i + 1, "name": name, "level": level, "ver": why["ver"], "error": why["error"]}
            ]
            findings.append(
                {
                    "level": "warn",
                    "code": "old_slot",
                    "title": f"Cannot read slot {i + 1}" + (f" ({name})" if name else ""),
                    "detail": (
                        f"Its layout is save version {why['ver']}, which this reader does not know (the other characters read fine). "
                        f"Load that character once in the game to bring it up to date, then Refresh. Nothing on this page touches it. "
                        f"Parser said: {why['error']}"
                    ),
                }
            )
        for i, s in enumerate(r["slots"]):
            if not r["ud10"]["active"][i]:
                continue
            p = s["pgd"]
            info["characters"].append(
                dict(
                    slot=i + 1,
                    name=p["name"],
                    level=p["level"],
                    body="Type B" if p.get("gender") == 1 else "Type A",
                    hp=p["max_health"],
                    runes=p["souls"],
                    ok=r["slot_md5_ok"][i],
                    where=place_name(s["map_id"]),
                    torrent=torrent_text(s.get("horse")),
                    stats=dict(
                        vig=p["vig"],
                        mind=p["mind"],
                        end=p["end"],
                        str=p["str"],
                        dex=p["dex"],
                        int=p["int"],
                        fai=p["fai"],
                        arc=p["arc"],
                    ),
                )
            )
        dlc = dlc_owned()
        tarn = tarnished_setting()
        info["tarnished_flag"] = save_analyze.tarnished_flag(r)
        info["tarnished_owned"] = save_analyze.tarnished_owned(r, tarn)
        for ch, s in zip(info["characters"], (s for i, s in enumerate(r["slots"]) if r["ud10"]["active"][i])):
            ch["pack_items"] = save_analyze.count_pack_items(s)
        findings.extend(save_analyze.analyze_parsed(r, dlc_owned=dlc, raw=data, tarnished=tarn))
        info["loading_plan"] = save_loading.plan_loading_fixes(r, dlc)  # what "Fix loading" would do (read-only plan)
        info["quest_fixes"] = save_fix.plan_quest_fixes(r)  # what "Fix quest flags" would do (read-only plan)
        info["checksum_fixes"] = save_fix.plan_checksum_fixes(r)
        info["dlc_owned"] = dlc
        info["vanilla_plan"] = save_vanilla.plan_restore(
            r, tarn, dlc
        )  # what "Remove mod items" would do (read-only plan)
    except save_layout_check.ParseError as e:
        findings.append({"level": "error", "code": "layout", "title": "Save layout failed", "detail": str(e)})
        info["error"] = str(e)[:120]
    except Exception as e:
        findings.append(
            {"level": "error", "code": "layout", "title": "Could not parse this save", "detail": str(e)[:200]}
        )
        info["error"] = str(e)[:120]
    info["findings"] = findings
    info["convert_ok"] = path.suffix.lower() == ".co2" and save_analyze.findings_are_clean(findings)
    return info


AREA_NAMES = {
    10: "Stormveil Castle",
    11: "Leyndell",
    12: "Crumbling Farum Azula",
    13: "Ainsel River",
    14: "Academy of Raya Lucaria",
    15: "Miquella's Haligtree",
    16: "Volcano Manor",
    18: "Stranded Graveyard",
    19: "Erdtree",
    20: "Belurat",
    21: "Shadow Keep",
    22: "Specimen Storehouse",
    60: "The Lands Between",
    61: "Land of Shadow",
}


def place_name(map_id) -> str:
    """Readable place from the 4-byte map id (m<prefix>_<b2>_<b1>_<b0>)."""
    try:
        b = list(map_id)
    except TypeError:
        return "?"
    if len(b) != 4:
        return "?"
    if b[3] == 11 and b[2] == 10:
        return "Roundtable Hold"
    name = AREA_NAMES.get(b[3])
    if b[3] in (60, 61):
        return f"{name} (tile {b[2]}, {b[1]})"
    if 30 <= b[3] <= 59:
        return f"Dungeon m{b[3]}_{b[2]:02d}"
    return name or f"m{b[3]}_{b[2]:02d}_{b[1]:02d}_{b[0]:02d}"


def torrent_text(horse) -> str:
    if not horse:
        return "?"
    hp, state = horse
    return {1: "resting", 3: "dead", 13: "summoned"}.get(state, f"state {state}") + f", {hp:,} HP"


def character_detail(info: dict, slot_index: int) -> dict:
    """Everything the workshop's About card shows for one character (0-based slot)."""
    ch = next((c for c in info.get("characters") or [] if c["slot"] == slot_index + 1), None)
    if not ch:
        return {}
    mods = {}
    for p in info.get("vanilla_plan") or []:
        if p["slot"] != slot_index:
            continue
        for e in list(p.get("strip") or []) + list(p.get("blocked") or []):
            mods[e.get("source") or "Other mod"] = mods.get(e.get("source") or "Other mod", 0) + 1
    loading = [l for p in info.get("loading_plan") or [] if p["slot"] == slot_index for l in p["labels"]]
    quest = [l for p in info.get("quest_fixes") or [] if p["slot"] == slot_index for l in p["labels"]]
    return {**ch, "mods": mods, "loading": loading, "quest": quest, "pack_items": ch.get("pack_items", 0)}


def save_findings(path: Path) -> list:
    """Read-only findings for one save. Never writes."""
    return save_info(path)["findings"]


def health_report(path: Path | None = None, info: dict | None = None) -> str:
    """Copyable plain-text health report for one save (or pass a save_info dict)."""
    if info is None:
        if path is None:
            raise ValueError("path or info required")
        info = save_info(path)
    return save_analyze.format_health_report(info)


def saves_needing_attention(infos: list | None = None) -> list:
    """Saves with repair needed or warn/error findings. Used for the Play pre-glance."""
    if infos is None:
        try:
            infos = [save_info(p) for p in common.save_files()]
        except Exception:
            return []
    out = []
    for s in infos:
        if s.get("needs_repair") or any(f.get("level") in ("warn", "error") for f in s.get("findings") or []):
            out.append(s)
    return out


# ----------------------------------------------------------------------------- backups (list, restore, delete)
BACKUP_FOLDERS = ("save-fix-backups", "regulation-fix-backups", "co2-to-sl2-backups")
FOLDER_ACTIONS = {
    "save-fix-backups": "Save fix",
    "regulation-fix-backups": "Repair regulation block",
    "co2-to-sl2-backups": "To .sl2",
}


def list_backups(save: Path | None = None) -> list:
    """Every backup next to the save(s), newest first: {path, save_name, when, action, changes, size, folder}."""
    paths = [Path(save)] if save else list(common.save_files())
    seen = set()
    out = []
    for p in paths:
        for folder in BACKUP_FOLDERS:
            d = p.parent / folder
            if not d.is_dir() or d in seen:
                continue
            seen.add(d)
            for f in d.iterdir():
                if f.suffix not in (".bak", ".src") or (save and not f.name.startswith(p.name + ".")):
                    continue
                m = save_fix.read_manifest(f) or {}
                try:
                    st = f.stat()
                except OSError:
                    continue
                when = m.get("when") or datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                action = m.get("action") or (
                    FOLDER_ACTIONS.get(folder, "Backup") + (" (source copy)" if f.suffix == ".src" else "")
                )
                out.append(
                    {
                        "path": f,
                        "save_name": f.name.split(".")[0] + "." + f.name.split(".")[1],
                        "when": when,
                        "action": action,
                        "changes": list(m.get("changes") or []),
                        "size": st.st_size,
                        "folder": folder,
                        "mtime": st.st_mtime,
                    }
                )
    out.sort(key=lambda b: b["mtime"], reverse=True)
    return out


def save_for_backup(bak: Path) -> Path:
    """The live save a backup belongs to: same folder as the backup folder's parent, first two name parts."""
    bak = Path(bak)
    parts = bak.name.split(".")
    return bak.parent.parent / (parts[0] + "." + parts[1])


def restore_backup(bak: Path, save: Path | None = None) -> Path:
    """Put a backup back over the live save. The current file is backed up first (so a restore can be undone).
    Returns the path of that safety copy."""
    bak = Path(bak)
    save = Path(save) if save else save_for_backup(bak)
    assert_writable(save)
    if not bak.is_file():
        raise RuntimeError(f"Backup not found: {bak}")
    data = bak.read_bytes()
    if not repair_regulation.is_pc_save(data):
        raise RuntimeError("That backup is not a PC Elden Ring save.")
    safety = None
    if save.exists():
        safety = save_fix.backup(save, {"action": "Before restoring a backup", "changes": [f"restored {bak.name}"]})
    tmp = save.with_name(save.name + ".roundtable.tmp")
    tmp.write_bytes(data)
    tmp.replace(save)
    common.log(f"restored {bak.name} over {save.name}" + (f" (safety copy: {safety.name})" if safety else ""))
    return safety


def delete_backup(bak: Path) -> None:
    bak = Path(bak)
    for p in (bak, Path(str(bak) + ".json")):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


# ----------------------------------------------------------------------------- play session options
PLAY_DEFAULTS = {
    "play_backup_before": False,
    "play_repair_after": True,
    "play_clear_before": True,
    "play_clear_after": True,
    "warn_dead_shells": True,
    "play_boot_boost": True,
    "play_show_logos": False,
    "play_diagnostics": False,
    "check_me3_updates": True,
}


FLAGS_SINCE = (0, 13, 0)  # --no-boot-boost / --show-logos / --diagnostics as used here exist from me3 0.13


def launch_extra_args(opts: dict, version: str | None = None) -> list:
    """me3 launch flags from the Play session options. A me3 older than 0.13 (a Revive bundle, say) gets none,
    so an unknown flag can never stop the launch; an unknown version is treated as current."""
    args = []
    if not opts.get("play_boot_boost", True):
        args.append("--no-boot-boost")
    if opts.get("play_show_logos"):
        args.append("--show-logos")
    if opts.get("play_diagnostics"):
        args.append("--diagnostics")
    v = me3_info.version_tuple(version)
    if args and v and v < FLAGS_SINCE:
        common.log(
            f"me3 {version} is older than {'.'.join(map(str, FLAGS_SINCE))}: launch flags {' '.join(args)} skipped"
        )
        return []
    return args


def play_options(settings: dict | None = None) -> dict:
    s = load_settings() if settings is None else settings
    return {
        k: bool(v if s.get(k) is None else s.get(k)) for k, v in PLAY_DEFAULTS.items()
    }  # a null in the file means default


def backup_saves_before_play() -> list:
    """One dated copy of every save under %APPDATA%/EldenRing, tagged 'Backup before Play'."""
    made = []
    for p in common.save_files():
        try:
            made.append(save_fix.backup(p, {"action": "Backup before Play", "changes": []}))
            common.log(f"backup: {made[-1]}")
        except OSError as e:
            common.log(f"backup failed for {p.name}: {e}")
    return made


def repair_save(path: Path) -> bool:
    """Repair one save's regulation block from the game's regulation.bin. Returns True if rewritten."""
    path = Path(path)
    assert_writable(path)
    source = common.regulation_bin()
    if not source:
        raise RuntimeError("Could not find the game's regulation.bin through Steam.")
    reg, header = repair_regulation.load_regulation(source)
    if not repair_regulation.plausible_regulation(reg):
        raise RuntimeError(f"{source}: regulation length does not look right.")
    return bool(repair_regulation.repair(path, reg, header))


def assert_writable(path: Path, settle_seconds: float = 4.0) -> None:
    """The lock every write goes through: the game must be closed, and the file must not have changed in the
    last few seconds (the game flushes saves for a moment after quitting)."""
    if common.game_running():
        raise RuntimeError("Elden Ring is running. Close it before changing saves.")
    path = Path(path)
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return
    if age < settle_seconds:
        time.sleep(settle_seconds - age)
        if common.game_running():
            raise RuntimeError("Elden Ring started while waiting. Close it before changing saves.")


def fix_quest_flags(path: Path, slots: list | None = None, selection: dict | None = None) -> dict:
    """Clear detected quest soft-locks on a save (all active characters, or the given slot indexes).
    Backs up first, re-signs the touched slots, verifies before replacing. Returns save_fix's result dict."""
    path = Path(path)
    assert_writable(path)
    return save_fix.apply_quest_fixes(path, slots, log=common.log, selection=selection)


def fix_checksums(path: Path) -> dict:
    """Recompute stale character / profile-summary checksums. Backs up first and verifies before replacing."""
    path = Path(path)
    assert_writable(path)
    return save_fix.repair_checksums(path, log=common.log)


TARNISHED_CHOICES = ("auto", "yes", "no")


def tarnished_setting() -> str | None:
    """Tools > Tarnished Edition gear: 'auto' (read the pack flag from the save), 'yes', 'no'."""
    v = str(load_settings().get("tarnished_owned", "auto")).lower()
    return None if v not in ("yes", "no") else v


def dlc_setting() -> str | None:
    """Tools > Shadow of the Erdtree: 'auto' (DLC.bdt in the game folder), 'yes', 'no'."""
    v = str(load_settings().get("dlc_owned", "auto")).lower()
    return None if v not in ("yes", "no") else v


def dlc_owned() -> bool | None:
    """Shadow of the Erdtree available for this save? The Tools override wins; else DLC.bdt next to the game;
    None when the game folder is unknown (treated as installed)."""
    o = dlc_setting()
    if o == "yes":
        return True
    if o == "no":
        return False
    try:
        return save_loading.dlc_installed(common.game_dir())
    except Exception:
        return None


def fix_loading(path: Path, slots: list | None = None, selection: dict | None = None) -> dict:
    """Apply the loading-screen fixes (Torrent, position, DLC flags, weather). Backs up, re-signs, verifies."""
    path = Path(path)
    assert_writable(path)
    return save_loading.apply_loading_fixes(path, slots, dlc_owned=dlc_owned(), log=common.log, selection=selection)


def restore_vanilla(path: Path, slots: list | None = None, selection: dict | None = None) -> dict:
    """Strip non-vanilla items, clear leftover rows and quest soft-locks on a save (all active characters,
    or the given slot indexes). Backs up first, re-signs, verifies before replacing. Returns save_vanilla's result."""
    path = Path(path)
    assert_writable(path)
    return save_vanilla.apply_restore(
        path, slots, log=common.log, selection=selection, tarnished=tarnished_setting(), dlc_owned=dlc_owned()
    )


remove_mod_items = restore_vanilla  # the button is called Remove mod items; the backend keeps its name


def restore_available(info: dict) -> bool:
    """True when Restore vanilla would change something (items to strip, rows to clear, or quest flags)."""
    return save_vanilla.restore_needed(info.get("vanilla_plan") or [])


def repair_available(info: dict) -> bool:
    """True when Roundtable Souls itself can fix something in this save (block repair, restore, quest flags, checksums).
    The Saves nav badge uses this."""
    cs = info.get("checksum_fixes") or {}
    return bool(
        info.get("needs_repair")
        or info.get("quest_fixes")
        or cs.get("slots")
        or cs.get("ud10")
        or restore_available(info)
        or info.get("loading_plan")
    )


def save_summary(info: dict) -> list:
    """Three calm status chips for a save card: (text, tone). Tones: success, warn, muted."""
    chips = []
    if info.get("error") and not info.get("characters"):
        return [("Could not read", "warn")]
    torn = any(f.get("code") == "layout" and f.get("level") == "error" for f in info.get("findings") or [])
    if torn:
        chips.append(("Damaged file", "warn"))
    elif info.get("loading_plan"):
        n = len(info["loading_plan"])
        chips.append((f"May not load ({n} character{'s' if n != 1 else ''})", "warn"))
    else:
        chips.append(("Loads fine", "success"))
    plan = info.get("vanilla_plan") or []
    holders = [p for p in plan if p.get("strip") or p.get("blocked")]
    if holders:
        chips.append((f"Mod items on {len(holders)} character{'s' if len(holders) != 1 else ''}", "muted"))
    else:
        chips.append(("Vanilla items", "success"))
    cs = info.get("checksum_fixes") or {}
    if info.get("needs_repair") or cs.get("slots") or cs.get("ud10"):
        chips.append(("Editors need Repair", "muted"))
    else:
        chips.append(("Editors OK", "success"))
    return chips


def convert_co2_to_sl2(path: Path, dest: Path | None = None, *, force: bool = False) -> Path:
    """Copy a .co2 to .sl2 only when findings are clean (or force=True after an explicit confirm).

    Never overwrites a live ER0000.sl2 without a backup. Default dest is ER0000.sl2.next-to-co2
    with a timestamp if the standard name already exists — callers pass dest for the live file.
    """
    path = Path(path)
    if path.suffix.lower() != ".co2":
        raise RuntimeError("Only Seamless Co-op .co2 files can be converted this way.")
    if common.game_running():
        raise RuntimeError("Elden Ring is running. Close it before converting saves.")
    info = save_info(path)
    if not force and not save_analyze.findings_are_clean(info["findings"]):
        raise RuntimeError("Findings are not clean. Repair or clear warnings first, or use force after confirming.")
    dest = Path(dest) if dest else path.with_suffix(".sl2")
    folder = dest.parent / "co2-to-sl2-backups"
    folder.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if dest.exists():
        bak = folder / f"{dest.name}.{stamp}.bak"
        shutil.copy2(dest, bak)
    shutil.copy2(path, dest)
    # Keep a copy of the source too
    shutil.copy2(path, folder / f"{path.name}.{stamp}.src")
    return dest


def dead_shells_count() -> int:
    try:
        return len(common.dead_game_shells())
    except Exception:
        return 0


def backups_folder(path: Path):
    """The newest backups folder next to the save: quest/checksum fixes or regulation repairs."""
    cands = [path.parent / save_fix.BACKUP_DIR, path.parent / repair_regulation.BACKUP_DIR]
    have = [c for c in cands if c.is_dir()]
    if not have:
        return cands[1]
    return max(have, key=lambda c: c.stat().st_mtime)


# ----------------------------------------------------------------------------- profile mods (packages and natives)
_BLOCK_HEADER = re.compile(r"^[ \t]*\[\[(packages|natives)\]\][ \t]*$", re.I)
_TOML_BODY = re.compile(r"^(?:\[\[|#?\s*[A-Za-z0-9_]+\s*=|\{|\}|\])")


def _plain_line(line: str) -> str:
    return re.sub(r"^[ \t]*#[ \t]?", "", line.rstrip("\r\n")).strip()


def _profile_blocks(text: str):
    """(start, end, kind) for each real [[packages]] / [[natives]] block, in file order. Commented lines are comments, not mods."""
    lines = text.splitlines(keepends=True)
    starts = [
        (i, "package" if m.group(1).lower() == "packages" else "native")
        for i, line in enumerate(lines)
        if (m := _BLOCK_HEADER.match(line.rstrip("\r\n")))
    ]
    blocks = []
    for n, (i, kind) in enumerate(starts):
        j = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        blocks.append((i, j, kind, lines))
    return blocks


def _toml_lines(lines) -> str:
    """Real keys only. A line whose first character is # is a comment, whatever it says."""
    kept = []
    for ln in lines:
        body = ln.rstrip("\r\n").strip()
        if body and not body.startswith("#"):
            kept.append(body)
    return "\n".join(kept)


def _mods_from_blocks(text: str):
    out = []
    for index, (i, j, kind, lines) in enumerate(_profile_blocks(text)):
        body = _toml_lines(lines[i:j])
        en_m = re.search(r"(?m)^enabled\s*=\s*(true|false)\b", body, re.I)
        if en_m and en_m.group(1).lower() == "false":
            continue
        id_m = re.search(r"(?m)^id\s*=\s*['\"]([^'\"]+)['\"]", body)
        path_m = re.search(r"(?m)^path\s*=\s*['\"]([^'\"]+)['\"]", body)
        path = path_m.group(1) if path_m else ""
        if not id_m and not path:
            continue
        ident = id_m.group(1) if id_m else Path(path).name
        out.append(dict(index=index, kind=kind, id=ident, path=path, name=ident))
    return out


def read_profile_mods(profile):
    """Mods me3 will load, in file order.

    An entry loads unless it sets enabled = false. enabled defaults to true.
    Commented-out blocks are comments, not entries. Both me3 shapes are read:
    [[packages]] blocks, and the packages = [ { ... } ] form Revive's installer writes.
    """
    try:
        text = _read(Path(profile))
    except OSError:
        return []
    if _profile_blocks(text):
        return _mods_from_blocks(text)
    rows = _profile_rows(text)
    if rows is None:
        return []
    out = []
    for index, (kind, row) in enumerate(rows):
        if row.get("enabled", True) is False:
            continue
        path = str(row.get("path") or "")
        ident = str(row.get("id") or (Path(path).name if path else ""))
        if not ident and not path:
            continue
        out.append(dict(index=index, kind=kind, id=ident, path=path, name=ident))
    return out


def _rewrite_block(block_lines, enabled: bool):
    lines = []
    for line in block_lines:
        nl = "\r\n" if line.endswith("\r\n") else ("\n" if line.endswith("\n") else "")
        body = line[: -len(nl)] if nl else line
        if enabled:
            m = re.match(r"^([ \t]*)#[ \t]?(.*)$", body)
            inner = m.group(2).strip() if m else ""
            if m and (inner.startswith("[[") or re.match(r"^[A-Za-z0-9_]+\s*=", inner) or inner[:1] in "{]}"):
                body = m.group(1) + m.group(2)
        lines.append(body + nl)
    val = "true" if enabled else "false"
    for i, line in enumerate(lines):
        if re.search(r"enabled\s*=", _plain_line(line), re.I):
            lines[i] = re.sub(r"(enabled\s*=\s*)(true|false)", r"\g<1>" + val, line, count=1, flags=re.I)
            return lines
    nl = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    lines.insert(1, f"enabled = {val}{nl}")
    return lines


def set_profile_mod_enabled(profile, index: int, enabled: bool) -> bool:
    """Turn one package or native on or off. Commented-out blocks are uncommented when turned on. Returns whether it changed."""
    path = Path(profile)
    text = _read(path)
    blocks = _profile_blocks(text)
    if index < 0 or index >= len(blocks):
        raise IndexError(index)
    i, j, _kind, lines = blocks[index]
    new_block = _rewrite_block(lines[i:j], enabled)
    if new_block == lines[i:j]:
        return False
    lines[i:j] = new_block
    atomic_write(path, "".join(lines), backup=True)
    return True


# ----------------------------------------------------------------------------- jobs
# ----------------------------------------------------------------------------- me3 facts and profile settings
def me3_facts(setup) -> dict:
    """Installed version, `me3 info` folders, and (cached daily) the latest release. Never raises."""
    me3 = setup.me3_path() if setup else common.me3_exe()
    facts = {
        "path": str(me3) if me3 else "",
        "version": me3_info.me3_version(me3),
        "info": me3_info.me3_info(me3),
        "latest": None,
        "update": False,
    }
    s = load_settings()
    if facts["info"].get("profile_dir") or facts["info"].get("logs_dir"):
        cache = {k: facts["info"].get(k, "") for k in ("profile_dir", "logs_dir", "install_prefix")}
        if cache != s.get("me3_info_cache"):
            save_settings(me3_info_cache=cache)
            s["me3_info_cache"] = cache
        apply_overrides(s)
    if bool(s.get("check_me3_updates", True)):
        cached = s.get("me3_latest")
        when = float(s.get("me3_latest_checked") or 0)
        if not cached or time.time() - when > 86400:
            rel = me3_info.latest_release()
            if rel:
                cached = rel
                save_settings(me3_latest=rel, me3_latest_checked=time.time())
        if isinstance(cached, dict):
            facts["latest"] = cached
            facts["update"] = me3_info.update_available(facts["version"], cached.get("version"))
    return facts


def read_profile_settings(profile) -> dict:
    try:
        return profile_tools.read_settings(_read(Path(profile)))
    except OSError:
        return {}


def write_profile_setting(profile, key: str, value) -> bool:
    """Set (or None: remove) one top-level me3 setting in the profile text, keeping comments; one .bak. Returns whether it changed."""
    path = Path(profile)
    text = _read(path)
    new = profile_tools.set_setting(text, key, value)
    if new == text:
        return False
    atomic_write(path, new, backup=True)
    return True


def scan_profile_conflicts(profile) -> dict:
    return profile_tools.scan_conflicts(Path(profile))


# ----------------------------------------------------------------------------- mods: install / remove / options, profiles
def profile_entries(profile) -> list:
    """Every package and native block, enabled or not, with options (mod_manage.entries)."""
    try:
        return mod_manage.entries(Path(profile))
    except Exception:
        return []


def plan_mod_install(profile, source, name=None) -> dict:
    return mod_manage.plan_install(Path(profile), Path(source), name)


def install_mod(profile, plan, overwrite=False) -> dict:
    out = mod_manage.install(Path(profile), plan, overwrite=overwrite)
    common.log(f"installed {plan['kind']} {plan['name']} -> {out['dest']}")
    return out


def uninstall_mod(profile, index: int, delete_folder=True) -> dict:
    out = mod_manage.uninstall(Path(profile), index, delete_folder=delete_folder)
    common.log(
        f"removed {out['kind']} {out['path']}" + (f" and its folder {out['folder']}" if out["removed_folder"] else "")
    )
    return out


def set_mod_options(profile, index: int, opts: dict):
    return mod_manage.set_options(Path(profile), index, opts)


def create_profile(name: str, copy_from=None) -> Path:
    folder = common.me3_profiles_dir()
    if not folder:
        raise RuntimeError("me3's profile folder is unknown on this PC (no LOCALAPPDATA).")
    return mod_manage.create_profile(folder, name, copy_from=copy_from)


def delete_profile(path) -> Path:
    return mod_manage.delete_profile(Path(path))


# ----------------------------------------------------------------------------- places (for the folder buttons)
def places(setup=None) -> dict:
    """Folders worth a button: me3, game, saves, this setup's profile and its mod folder. Missing ones are None."""
    out = {"me3": None, "game": None, "saves": None, "profile": None, "mods": None}
    try:
        me3 = setup.me3_path() if setup else common.me3_exe()
        if me3 and Path(me3).is_file():
            out["me3"] = Path(me3).parent
    except Exception:
        pass
    try:
        g = common.game_dir()
        if g and Path(g).is_dir():
            out["game"] = Path(g)
    except Exception:
        pass
    try:
        saves = common.save_files()
        if saves:
            out["saves"] = saves[0].parent
        else:
            appdata = os.environ.get("APPDATA")
            if appdata and (Path(appdata) / "EldenRing").is_dir():
                out["saves"] = Path(appdata) / "EldenRing"
    except Exception:
        pass
    if setup and Path(setup.profile).is_file():
        out["profile"] = Path(setup.profile).parent
        try:
            text = Path(setup.profile).read_bytes().decode("utf-8", "replace")
            pk, _nt = mod_manage.roots(Path(setup.profile), text)
            out["mods"] = pk if pk.is_dir() else out["profile"]
        except Exception:
            out["mods"] = out["profile"]
    return out


def route_logs(sink):
    """Send every logged line to the window as well as the run log."""
    run_logging.attach_sink(sink)


def _after_play(opts):
    if opts["play_repair_after"]:
        me3_session.repair_all()
    else:
        common.log("repair after quitting is off (Tools > Play session)")
    if opts["play_clear_after"]:
        me3_session.clear_dead_shells("after exit")
    else:
        common.log("clearing leftover processes after quitting is off (Tools > Play session)")


def job_play(setup: Setup):
    common.start_log("launcher: play")
    opts = play_options()
    if opts["play_backup_before"]:
        backup_saves_before_play()
    me3_session.ensure_steam(120)
    if opts["play_clear_before"]:
        me3_session.clear_dead_shells("before launch")
    me3_session.launch(
        GAME,
        setup.profile,
        me3=setup.me3,
        exe=setup.launch_exe(),
        extra_args=launch_extra_args(opts, me3_info.me3_version(setup.me3_path())),
    )
    time.sleep(3)
    _after_play(opts)


NATIVE_BLOCK_RE = re.compile(r"(^[ \t]*\[\[natives\]\].*?)(?=^[ \t]*\[\[|\Z)", re.M | re.S)
PACKAGE_BLOCK_RE = re.compile(r"(^[ \t]*\[\[packages\]\].*?)(?=^[ \t]*\[\[|\Z)", re.M | re.S)
REVIVE_MARK = re.compile(r"nightreign-revive|reviveprototype|revivehud|reviveerss|nrrinitialize|nrrhud", re.I)


def _comment_block(block: str) -> str:
    return "".join(
        ("# " + ln if ln.strip() and not ln.lstrip().startswith("#") else ln) for ln in block.splitlines(keepends=True)
    )


def _ensure_disabled(body: str) -> str:
    if re.search(r"enabled\s*=\s*false", body, re.I):
        return body
    if re.search(r"enabled\s*=\s*true", body, re.I):
        return re.sub(r"enabled\s*=\s*true", "enabled = false", body, count=1, flags=re.I)
    return "{ enabled = false, " + body[1:]


def _disable_objects_matching(text: str, mark) -> str:
    """Set enabled = false on { ... } objects whose path matches, including nested braces."""
    i, n, out = 0, len(text), []
    while i < n:
        if text[i] != "{":
            out.append(text[i])
            i += 1
            continue
        depth, j = 0, i
        while j < n:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    body = text[i : j + 1]
                    if mark.search(body) and re.search(r"path\s*=", body, re.I):
                        body = _ensure_disabled(body)
                    out.append(body)
                    i = j + 1
                    break
            j += 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def offline_profile_text(text: str, strip_revive: bool = False) -> str:
    """A throwaway copy of the me3 profile with Seamless (and optionally Revive) turned off.
    Seamless refuses to run without a signed-in, online Steam; without it the game uses the standard save."""

    def strip_ersc(m):
        block = m.group(1)
        if "ersc.dll" not in block.lower():
            return block
        return _comment_block(block)

    out = NATIVE_BLOCK_RE.sub(strip_ersc, text)
    out = re.sub(
        r"\{[^{}]*path\s*=\s*['\"][^'\"]*ersc\.dll['\"][^{}]*\}",
        lambda m: _ensure_disabled(m.group(0)),
        out,
        flags=re.I,
    )
    if strip_revive:

        def strip_rev(m):
            block = m.group(1)
            if not REVIVE_MARK.search(block):
                return block
            return _comment_block(block)

        out = NATIVE_BLOCK_RE.sub(strip_rev, out)
        out = PACKAGE_BLOCK_RE.sub(strip_rev, out)
        out = _disable_objects_matching(out, REVIVE_MARK)
    note = "Seamless Co-op disabled."
    if strip_revive:
        note += " Revive disabled."
    return f"# OFFLINE COPY written by the launcher: {note} Regenerated on every offline launch.\n" + out


def offline_profile_for(profile: str, strip_revive: bool = False) -> Path:
    """Write <profile>.offline.me3 next to the profile (relative paths keep working) and return it."""
    src = Path(profile)
    dst = src.with_name(src.stem + ".offline.me3")
    atomic_write(
        dst, offline_profile_text(src.read_text(encoding="utf-8", errors="replace"), strip_revive=strip_revive)
    )
    return dst


def steam_state():
    """(running, signed_in) from the process list and Steam's own registry flag."""
    try:
        running = bool(common.processes("steam.exe"))
    except Exception:
        running = False
    try:
        signed = bool(common.steam_logged_in())
    except Exception:
        signed = False
    return running, signed


def job_play_offline(setup, strip_revive=False, start_steam=True):
    common.start_log("launcher: play offline")
    opts = play_options()
    if opts["play_backup_before"]:
        backup_saves_before_play()
    if start_steam:
        me3_session.ensure_steam_running(60)
    if opts["play_clear_before"]:
        me3_session.clear_dead_shells("before launch")
    me3_session.launch(
        GAME,
        str(offline_profile_for(setup.profile, strip_revive=strip_revive)),
        me3=setup.me3,
        exe=setup.launch_exe(),
        extra_args=("--skip-steam-init", "true", *launch_extra_args(opts, me3_info.me3_version(setup.me3_path()))),
    )
    time.sleep(3)
    _after_play(opts)


def job_repair(setup):
    common.start_log("launcher: repair")
    me3_session.repair_all()


def job_clear(setup):
    common.start_log("launcher: clear dead shells")
    me3_session.clear_dead_shells("manual")


def run_job(job, setup, sink, done):
    try:
        job(setup)
        done(True, "Finished")
    except SystemExit:
        done(False, "Stopped (see details)")
    except Exception:
        sink("error:\n" + traceback.format_exc())
        done(False, "Error (see details)")


apply_overrides()


def check():  # `roundtable-souls --check` prints this
    settings = load_settings()
    setups = discover(settings.get("setup"))
    print(f"{TITLE} {VERSION}")
    print("setups found:", len(setups))
    for s in setups:
        sc = read_scaling(s.ini) if s.ini else None
        print(
            f"  [{s.kind}] {s.label}\n      {s.summary()}\n      ini: {s.ini}  password: {read_password(s.ini) if s.ini else None}\n      scaling: {preset_of(sc) if sc else None} {sc}"
            + ("\n      PROBLEMS: " + "; ".join(s.problems()) if s.problems() else "")
        )
    print("remembered:", settings.get("setup"))
    print("steam:", common.steam_exe())
    print(
        "data folder:",
        DATA_DIR,
        "(next to the exe)" if DATA_DIR == HERE else "(exe folder not writable, using LOCALAPPDATA)",
    )
    for p in common.save_files():
        i = save_info(p)
        print(
            f"  save {i['name']}: {i['kind']}, block {i['block']}, modified {i['modified']}"
            + (f", error {i['error']}" if i["error"] else "")
        )
        for c in i["characters"]:
            print(f"      slot {c['slot']}: {c['name']} lvl {c['level']} {c['body']} hp {c['hp']} runes {c['runes']}")
