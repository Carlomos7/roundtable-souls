"""Model layer facade: setups, the play session jobs, error reporting, and the names the window and the
tests reach for. The Seamless ini lives in coop.py, save info and repairs in saves/service.py, profile mods in
mods/service.py; they are re-exported here so callers have one import.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

from roundtable_souls import __version__, coop
from roundtable_souls.coop import (
    COMMENT_PREFIX,
    CUSTOM,
    JSON_FORMAT,
    LINE_RE,
    PW_RE,
    SAVE_KINDS,
    SCALING_KEYS,
    SCALING_LABELS,
    SCALING_PRESETS,
    SECTION_RE,
    SECTION_TITLES,
    SETTING_COPY,
    VOLUME_STOPS,
    _read,
    choice_label,
    ersc_ini_for,
    export_settings,
    export_text,
    indent_lines,
    label_of,
    load_settings_json,
    nearest_volume_stop,
    parse_settings_json,
    plan_import,
    preset_of,
    read_all_settings,
    read_keys,
    read_password,
    read_scaling,
    read_settings_meta,
    setting_face,
    strip_json_comments,
    toggle_comment,
    write_keys,
    write_password,
)
from roundtable_souls.files import (
    atomic_write,
)
from roundtable_souls.mods import manage as mod_manage
from roundtable_souls.mods import profile as profile_tools
from roundtable_souls.mods import service as mods_service
from roundtable_souls.mods.service import (
    create_profile,
    delete_profile,
    install_mod,
    me3_facts,
    plan_mod_install,
    profile_entries,
    read_profile_mods,
    read_profile_settings,
    scan_profile_conflicts,
    set_mod_options,
    set_profile_mod_enabled,
    uninstall_mod,
    write_profile_setting,
)
from roundtable_souls.resources import ASSETS_DIR
from roundtable_souls.saves import analyze as save_analyze
from roundtable_souls.saves import fix as save_fix
from roundtable_souls.saves import layout as save_layout_check
from roundtable_souls.saves import loading as save_loading
from roundtable_souls.saves import regulation as repair_regulation
from roundtable_souls.saves import service as saves_service
from roundtable_souls.saves import vanilla as save_vanilla
from roundtable_souls.saves.service import (
    AREA_NAMES,
    BACKUP_FOLDERS,
    FOLDER_ACTIONS,
    assert_writable,
    backups_folder,
    character_detail,
    convert_co2_to_sl2,
    convert_sl2_to_co2,
    dead_shells_count,
    delete_backup,
    dlc_owned,
    fix_checksums,
    fix_loading,
    health_report,
    list_backups,
    place_name,
    remove_mod_items,
    repair_available,
    repair_save,
    restore_available,
    restore_backup,
    restore_vanilla,
    save_findings,
    save_for_backup,
    save_info,
    save_summary,
    saves_needing_attention,
    torrent_text,
)
from roundtable_souls.settings import FROZEN, data_dir, exe_dir, load_settings, save_settings
from roundtable_souls.system import common, me3_info
from roundtable_souls.system import logging as run_logging
from roundtable_souls.system import processes as clear_dead_game_shells
from roundtable_souls.system import session as me3_session
from roundtable_souls.system.common import PATH_SETTINGS, apply_overrides
from roundtable_souls.updates import (
    RELEASES_URL,
    apply_update,
    can_self_update,
    download_update,
    launcher_update,
    run_installer,
    skip_update,
)

HERE = exe_dir()
DATA_DIR = data_dir()
SETTINGS = DATA_DIR / "launcher_settings.json"
LOGS = DATA_DIR / "logs"


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


def setup_from_path(p: str | Path) -> Setup | None:
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
        running = common.steam_running()
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


def play_command() -> tuple[str, str]:
    """(target, launch options) for a Steam shortcut that runs Play without the window."""
    if FROZEN:
        return sys.executable, "--play"
    return sys.executable, "-m roundtable_souls --play"


def play_headless() -> int:
    """`roundtable-souls --play`: the Play button without the window. Uses the setup Play last used (or the only one),
    runs the same session (Steam, me3, wait, save repair, cleanup) and exits. For Steam shortcuts and Gaming Mode."""
    settings = load_settings()
    apply_overrides(settings)
    setups = [s for s in discover(settings.get("setup")) if not s.problems()]
    remembered = settings.get("setup")
    setup = next((s for s in setups if s.source == remembered), setups[0] if setups else None)
    if setup is None:
        common.start_log("launcher: play (no window)")
        common.log("error: no working setup found; open Roundtable Souls once and pick one on the Play page")
        return 1
    try:
        job_play(setup)
    except SystemExit as e:
        return int(e.code or 1) if isinstance(e.code, int) else 1
    return 0


def check():
    """`roundtable-souls --check`: what the launcher detects, printed and written to logs/last_run.log (so the windowed
    exe, which has no console, can be checked too). The co-op password is never included."""
    from roundtable_souls.mods.item_names import item_names

    lines = [f"{TITLE} {VERSION}"]
    settings = load_settings()
    setups = discover(settings.get("setup"))
    lines.append(f"setups found: {len(setups)}")
    for s in setups:
        sc = read_scaling(s.ini) if s.ini else None
        password = "set" if s.ini and read_password(s.ini) else "not set"
        lines += [
            f"  [{s.kind}] {s.label}",
            f"      {s.summary()}",
            f"      ini: {s.ini}  password: {password}",
            f"      scaling: {preset_of(sc) if sc else None} {sc}",
        ]
        if s.problems():
            lines.append("      PROBLEMS: " + "; ".join(s.problems()))
    lines.append(f"remembered: {settings.get('setup')}")
    lines.append(f"steam: {common.steam_exe()}")
    lines.append(f"game: {common.game_dir()}")
    game_ids = save_analyze.game_item_ids()
    lines.append(f"game items from regulation.bin: {len(game_ids) if game_ids else 'not readable'}")
    names = item_names(refresh=True).names
    sources = sorted({source for _name, source in names.values()})
    lines.append(f"mod item names: {len(names)} from {', '.join(sources) or 'no mods'}")
    lines.append(f"data folder: {DATA_DIR} ({'next to the program' if DATA_DIR == HERE else 'per-user app data'})")
    for p in common.save_files():
        i = save_info(p)
        lines.append(
            f"  save {i['name']}: {i['kind']}, block {i['block']}, modified {i['modified']}"
            + (f", error {i['error']}" if i["error"] else "")
        )
        for c in i["characters"]:
            lines.append(
                f"      slot {c['slot']}: {c['name']} lvl {c['level']} {c['body']} hp {c['hp']} runes {c['runes']}"
            )
    common.start_log("launcher: check")
    for line in lines:
        print(line)
        common.log(line)
