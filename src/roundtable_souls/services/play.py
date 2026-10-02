"""Play: the setups a game can launch (me3 profiles, launchers' installation.json), the play session jobs (online,
offline, repair, cleanup), play without the window (--play, --check), and error reporting. Co-op, saves, mods,
settings and updates have services modules of their own."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from roundtable_souls import __version__
from roundtable_souls.config.settings import (
    FROZEN,
    data_dir,
    exe_dir,
    game_setting,
    launch_target,
    load_settings,
    save_game_settings,
)
from roundtable_souls.coop.ini import (
    coop_ini_for,
    has_password,
    read_keys,
    read_password,
)
from roundtable_souls.coop.scaling import (
    preset_of,
    read_scaling,
    scaling_spec,
)
from roundtable_souls.files import (
    atomic_write,
)
from roundtable_souls.game import catalog as games
from roundtable_souls.mods import profile as profile_tools
from roundtable_souls.mods import profile_edit as mod_manage
from roundtable_souls.mods import rebuild as mod_merge
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.platform import me3_info, steam
from roundtable_souls.platform import paths as common
from roundtable_souls.platform import session as me3_session
from roundtable_souls.platform.paths import apply_overrides
from roundtable_souls.resources import ASSETS_DIR
from roundtable_souls.saves import analyze as save_analyze
from roundtable_souls.saves import fix as save_fix
from roundtable_souls.saves import repair as save_repair
from roundtable_souls.services.saves import (
    save_info,
)

HERE = exe_dir()
DATA_DIR = data_dir()
SETTINGS = DATA_DIR / "launcher_settings.json"
LOGS = DATA_DIR / "logs"


def report_exception(exc_type, exc, tb, where="launcher"):
    """Every uncaught error, in the UI thread or a worker: to logs/launcher.log with its traceback (and the running
    job's log), then a message box."""
    run_logging.log_crash(exc_type, exc, tb, where)
    if NOTIFY is not None:
        try:
            NOTIFY(TITLE, "Something went wrong:\n" + str(exc) + "\n\nDetails are in logs\\launcher.log")
        except Exception:
            pass


TITLE = "Roundtable Souls"
VERSION = __version__
EXE_NAME = "RoundtableSouls"
STARTUP_GAME = None  # `--game` without --play/--check: the tab the window opens on, this run only
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
    """What to launch and how. kind: 'me3' (installed me3, --game) or 'revive' (installation.json, --exe).
    game: the game it launches (the active game when not given)."""

    def __init__(self, kind, profile, me3=None, exe=None, source=None, ini=None, game=None):
        self.kind, self.profile, self.me3, self.exe, self.source = kind, str(profile), me3, exe, str(source or profile)
        self.game = game or common.GAME
        self._ini = ini

    @property
    def ini(self):
        """The Seamless Co-op ini this profile loads. Found on first use: discover() builds a Setup for every
        profile on disk, and reading each one there made every game-tab switch pay for inis nobody asked about."""
        if self._ini is None:
            self._ini = coop_ini_for(self.profile, self.game) or False  # False: looked, this profile has none
        return self._ini or None

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
        game = Path(self.exe).name if self.exe else f"{self.game.name} (Steam)"
        return f"me3: {me3 if me3 else 'not found'}    game: {game}"

    def problems(self):
        out = []
        if not Path(self.profile).is_file():
            out.append(f"profile missing: {self.profile}")
        elif self.kind == "me3":
            named = common.profile_games(Path(self.profile))
            if named and self.game.key not in named:
                other = ", ".join(games.get(k).name if k in games.BY_KEY else k for k in named)
                out.append(f"this profile is for {other}, not {self.game.name}")
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


def same_source(a, b) -> bool:
    """Whether two setup sources name the same file. Sources travel as strings (the combo list, the remembered
    setup in settings), so every comparison ignores case and slash direction the same way, here."""
    return bool(a) and bool(b) and os.path.normcase(str(a)) == os.path.normcase(str(b))


def setup_from_path(p: str | Path, game: games.Game | None = None) -> Setup | None:
    """A setup for a picked file: a .me3 profile, or (Elden Ring only) a launcher's installation.json."""
    p = Path(p)
    game = game or common.GAME
    if p.name.lower() == "installation.json":
        return setup_from_installation(p) if game is games.ELDEN_RING else None
    if p.suffix.lower() == ".me3" and p.is_file():
        return Setup("me3", p, game=game)
    return None


def discover(remembered: str | None, game: games.Game | None = None):
    """The active game's me3 profiles (+ the remembered one). For Elden Ring, also every Nightreign Revive
    installation next to them; Revive is an Elden Ring mod despite its name."""
    game = game or common.GAME
    found, seen = [], set()

    def add(s):
        key = os.path.normcase(s.source) if s else None
        if s and key not in seen:
            seen.add(key)
            found.append(s)

    if remembered:
        add(setup_from_path(remembered, game))
    for prof in common.me3_profiles(game):
        if prof.name.lower().endswith(".offline.me3"):
            continue  # our own generated copies
        add(Setup("me3", prof, game=game))
        inst = prof.parent / "NightreignRevive" / "installation.json"
        if game is games.ELDEN_RING and inst.is_file():
            add(setup_from_installation(inst))
    if game is not games.ELDEN_RING:
        return found
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


def remembered_setup(settings: dict | None = None, game: games.Game | None = None) -> str | None:
    """The setup Play last used for the game."""
    s = load_settings() if settings is None else settings
    return game_setting(s, (game or common.GAME).key, "setup")


def remember_setup(source: str, game: games.Game | None = None) -> None:
    save_game_settings((game or common.GAME).key, setup=source)


def forget_setup(game: games.Game | None = None) -> None:
    """Drop the setup Play remembered for the game (its profile was deleted, say)."""
    save_game_settings((game or common.GAME).key, setup=None)


def setup_saves(setup: Setup | None) -> dict:
    """The save files a setup plays on, by name in the account's save folder:

    standard  what the game writes: me3's per-profile savefile, else ER0000.sl2 (NR0000.sl2, ...).
    coop      what Seamless Co-op writes instead, when the setup loads it: the standard name with Seamless's
              save_file_extension (co2 unless changed in its ini). None without Seamless.
    active    the one Play uses (co-op when Seamless is loaded; Play offline always uses the standard one).
    why       role -> where the name comes from, for the Saves page."""
    game = setup.game if setup else common.GAME
    standard = f"{game.save_stem}.sl2"
    why = {"standard": "the game's default"}
    if setup and Path(setup.profile).is_file():
        try:
            named = profile_tools.read_settings(Path(setup.profile).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            named = {}
        if named.get("savefile"):
            standard = str(named["savefile"])
            why["standard"] = f"savefile in {Path(setup.profile).name}"
    coop_name = None
    if setup and setup.ini and Path(setup.ini).is_file():
        ext = (read_keys(setup.ini, ["save_file_extension"]).get("save_file_extension") or "co2").strip().lstrip(".")
        coop_name = f"{Path(standard).stem}.{ext or 'co2'}"
        why["coop"] = f"save_file_extension in {Path(setup.ini).name}" if ext != "co2" else "Seamless Co-op's default"
    return {"standard": standard, "coop": coop_name, "active": coop_name or standard, "why": why}


def note_setup_saves(setup: Setup | None) -> dict:
    """Make save discovery (the Saves page, repairs after play) include the files this setup uses."""
    names = setup_saves(setup)
    common.set_setup_save_names(setup.game if setup else common.GAME, {k: names[k] for k in ("standard", "coop")})
    return names


def use_game(key: str | games.Game, settings: dict | None = None) -> games.Game:
    """Switch every lookup (Steam folder, saves, me3 profiles, running-game checks) to this game."""
    return common.set_game(key, settings)


PLAY_DEFAULTS = {
    "play_update_merge": True,
    "build_merges": False,
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
        run_logging.log(
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
    """One dated copy of every save of the active game, tagged 'Backup before Play'."""
    made = []
    for p in common.save_files():
        try:
            made.append(save_fix.backup(p, {"action": "Before playing", "changes": []}))
            run_logging.log(f"backup: {made[-1]}")
        except OSError as e:
            run_logging.log(f"backup failed for {p.name}: {e}")
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
            roots = [r for r in common.save_roots() if r.is_dir()]
            if roots:
                out["saves"] = roots[0]
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
    if not common.GAME.regulation_repair:
        pass  # this game has no regulation block me3 leaves dirty
    elif opts["play_repair_after"]:
        save_repair.repair_all()
    else:
        run_logging.log("repair after quitting is off (Tools > Play session)")
    if opts["play_clear_after"]:
        me3_session.clear_dead_shells("after exit")
    else:
        run_logging.log("clearing leftover processes after quitting is off (Tools > Play session)")


def job_play(setup: Setup):
    common.start_log("launcher: play")
    note_setup_saves(setup)
    opts = play_options()
    if opts["play_backup_before"]:
        backup_saves_before_play()
    me3_session.ensure_steam(120)
    if opts["play_clear_before"]:
        me3_session.clear_dead_shells("before launch")
    me3_session.launch(
        setup.game.key,
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


def offline_profile_text(text: str, strip_revive: bool = False, coop_dll: str | None = "ersc.dll") -> str:
    """A throwaway copy of the me3 profile with Seamless (and optionally Revive) turned off.
    Seamless refuses to run without a signed-in, online Steam; without it the game uses the standard save.
    coop_dll: the game's Seamless Co-op dll (ersc.dll for Elden Ring, nrsc.dll for Nightreign)."""
    dll = (coop_dll or "").lower()

    def strip_coop(m):
        block = m.group(1)
        if not dll or dll not in block.lower():
            return block
        return _comment_block(block)

    out = NATIVE_BLOCK_RE.sub(strip_coop, text)
    if dll:
        out = re.sub(
            r"\{[^{}]*path\s*=\s*['\"][^'\"]*" + re.escape(dll) + r"['\"][^{}]*\}",
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


def offline_profile_for(profile: str, strip_revive: bool = False, coop_dll: str | None = "ersc.dll") -> Path:
    """Write <profile>.offline.me3 next to the profile (relative paths keep working) and return it."""
    src = Path(profile)
    dst = src.with_name(src.stem + ".offline.me3")
    atomic_write(
        dst,
        offline_profile_text(
            src.read_text(encoding="utf-8", errors="replace"), strip_revive=strip_revive, coop_dll=coop_dll
        ),
    )
    return dst


def steam_state():
    """(running, signed_in) from the process list and Steam's own registry flag."""
    try:
        running = steam.steam_running()
    except Exception:
        running = False
    try:
        signed = bool(steam.steam_logged_in())
    except Exception:
        signed = False
    return running, signed


def job_play_offline(setup, strip_revive=False, start_steam=True):
    common.start_log("launcher: play offline")
    note_setup_saves(setup)
    opts = play_options()
    if opts["play_backup_before"]:
        backup_saves_before_play()
    if start_steam:
        me3_session.ensure_steam_running(60)
    if opts["play_clear_before"]:
        me3_session.clear_dead_shells("before launch")
    me3_session.launch(
        setup.game.key,
        str(offline_profile_for(setup.profile, strip_revive=strip_revive, coop_dll=setup.game.coop_dll)),
        me3=setup.me3,
        exe=setup.launch_exe(),
        extra_args=("--skip-steam-init", "true", *launch_extra_args(opts, me3_info.me3_version(setup.me3_path()))),
    )
    time.sleep(3)
    _after_play(opts)


def job_repair(setup):
    common.start_log("launcher: repair")
    save_repair.repair_all()


def job_clear(setup):
    common.start_log("launcher: clear dead shells")
    me3_session.clear_dead_shells("manual")


def run_job(job, setup, sink, done, title="Job"):
    """Run one job on this (worker) thread as a logged job of its own: its lines go to its log file and the window,
    and the jobs index records how it ended."""
    game = getattr(getattr(setup, "game", None), "key", "") or common.GAME.key
    profile = str(getattr(setup, "profile", "") or "")
    record = run_logging.begin_job(title.rstrip(". "), game=game, profile=profile)
    log = run_logging.get_logger("job")
    try:
        job(setup)
    except SystemExit as e:
        stopped = e.code == 130
        run_logging.end_job(record, "stopped" if stopped else "failed" if e.code not in (0, None) else None)
        done(e.code in (0, None), "Finished" if e.code in (0, None) else "Stopped (see details)")
    except Exception:
        log.exception("the job failed with an unexpected error")
        run_logging.end_job(record, "failed")
        done(False, "Error (see details)")
    else:
        run_logging.end_job(record)
        done(True, "Finished")


apply_overrides()


def play_command(game: games.Game | None = None) -> tuple[str, str]:
    """(target, launch options) for a Steam shortcut that runs Play for one game without the window."""
    game = game or common.GAME
    opts = f"--game {game.key} --play"
    if FROZEN:
        return str(launch_target()), opts  # the stub or AppImage: its path stays the same across updates
    return sys.executable, f"-m roundtable_souls {opts}"


def game_from_args(argv: list[str], settings: dict | None = None) -> games.Game | None:
    """The game `--game <name>` (or `--game=<name>`) asks for; without the flag, the tab the window last showed.
    None when the name is unknown."""
    value = None
    for i, arg in enumerate(argv):
        if arg == "--game":
            value = argv[i + 1] if i + 1 < len(argv) else ""
        elif arg.startswith("--game="):
            value = arg.split("=", 1)[1]
    if value is None:
        s = load_settings() if settings is None else settings
        return games.get(s.get("game"))
    return games.resolve(value)


def play_headless(game: games.Game | None = None, notice: Callable[[games.Game, str], None] | None = None) -> int:
    """`roundtable-souls --game <name> --play`: the Play button without the window, for one game. Uses the setup
    Play last used for that game (or the only one), runs the same session (Steam, me3, wait, save repair, cleanup)
    and exits. For Steam shortcuts and Gaming Mode. notice(game, why) tells the player when the game was not
    started (the command line passes one that shows a small window)."""
    settings = load_settings()
    game = use_game(game or games.get(settings.get("game")), settings)
    if not game.ready:
        common.start_log("launcher: play (no window)")
        run_logging.log(f"error: Roundtable Souls cannot launch {game.name} yet")
        return 1
    remembered = remembered_setup(settings, game)
    setups = [s for s in discover(remembered, game) if not s.problems()]
    setup = next((s for s in setups if same_source(s.source, remembered)), setups[0] if setups else None)
    if setup is None:
        common.start_log("launcher: play (no window)")
        run_logging.log(
            f"error: no working {game.name} setup found; open Roundtable Souls once, pick the {game.name} tab, "
            "and choose one on the Play page"
        )
        return 1
    why = update_merge_headless(setup, automatic=play_options(settings)["play_update_merge"])
    if why:
        run_logging.log(f"error: the game was not started: {why}")
        if notice is not None:
            notice(game, why)
        return 1
    try:
        job_play(setup)
    except SystemExit as e:
        return int(e.code or 1) if isinstance(e.code, int) else 1
    return 0


def update_merge_headless(setup, automatic: bool = True) -> str | None:
    """--play without the window: bring the merged mods up to date first. None when the game may start (nothing to
    do, or updated); otherwise why it must not start: the game never runs with merged mods that no longer match the
    profile (a removed mod still inside them, say). Nothing can ask here, so a rebuild tool runs only when it was
    already allowed. automatic False (the setting "rebuild ... automatically" off): nothing is rebuilt
    without being asked, so the game is not started either."""
    prof = Path(setup.profile) if getattr(setup, "profile", None) else None
    if prof is None:
        return None
    h = mod_merge.play_check(prof)
    if h is None:
        return None
    common.start_log("launcher: update merged mods before Play (no window)")
    reason = (h.get("reasons") or [h.get("text") or "the merged mods are out of date"])[0]
    if h["blocked"]:
        run_logging.log(f"error: the merged mods are out of date ({reason}) and cannot be rebuilt: {h['blocked']}")
        return f"The merged mods are out of date and cannot be rebuilt: {h['blocked']}"
    if not automatic:
        run_logging.log(f"error: the merged mods are out of date ({reason}); automatic rebuilds are off")
        return (
            f"The merged mods are out of date ({reason}), and rebuilding them automatically before Play is "
            "turned off. Open Roundtable Souls to rebuild them."
        )
    tool: Any = mod_merge.find_backend(prof)  # a rebuild tool (mods.backends), or None
    if tool is not None and tool.problem():
        run_logging.log(f"error: {tool.label} cannot run: {tool.problem()}")
        return f"The merged mods are out of date and {tool.label} cannot run: {tool.problem()}"
    if tool is not None and not mod_merge.approved(tool):
        run_logging.log(f"error: {tool.label} has not been allowed to run yet; open Roundtable Souls and allow it")
        return (
            f"The merged mods are out of date ({reason}), and {tool.label} has not been allowed to run yet. "
            "Open Roundtable Souls to allow it."
        )
    try:
        mod_merge.update_before_play(prof, run_logging.log)
        run_logging.log("done: merged mods updated")
        return None
    except mod_merge.MergeError as e:
        run_logging.log(f"error: the merged mods could not be updated: {e}")
        return f"The merged mods could not be updated: {e}"


def check(game: games.Game | None = None):
    """`roundtable-souls [--game <name>] --check`: what the launcher detects for one game, printed and written to
    logs/last_run.log (so the windowed exe, which has no console, can be checked too). The co-op password is never
    included."""
    from roundtable_souls.saves.item_names import item_names

    lines = [f"{TITLE} {VERSION}"]
    settings = load_settings()
    game = use_game(game or games.get(settings.get("game")), settings)
    installed = [g.name for g in games.GAMES if common.installed_dir(g)]
    lines.append(f"game: {game.name}{'' if game.ready else ' (not supported yet)'}")
    lines.append(f"installed games: {', '.join(installed) or 'none found'}")
    remembered = remembered_setup(settings, game)
    setups = discover(remembered, game) if game.ready else []
    lines.append(f"setups found: {len(setups)}")
    for s in setups:
        spec = scaling_spec(s.ini) if s.ini else None
        sc = read_scaling(s.ini, spec) if s.ini else None
        if not s.ini or not has_password(s.ini):
            password = "none in this mod" if s.ini else "not set"
        else:
            password = "set" if read_password(s.ini) else "not set"
        lines += [
            f"  [{s.kind}] {s.label}",
            f"      {s.summary()}",
            f"      ini: {s.ini}  password: {password}",
            f"      scaling: {preset_of(sc, spec) if sc else None} {sc}",
        ]
        probs = s.problems()
        if probs:
            lines.append("      PROBLEMS: " + "; ".join(probs))
    lines.append(f"remembered: {remembered}")
    lines.append(f"steam: {steam.steam_exe()}")
    lines.append(f"game folder: {common.game_dir()}")
    if game is games.ELDEN_RING:
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
        if not i["characters"]:
            for f in i["findings"]:
                lines.append(f"      {f['title']}: {f.get('detail', '')}")
    common.start_log("launcher: check")
    for line in lines:
        print(line)
        run_logging.log(line)
