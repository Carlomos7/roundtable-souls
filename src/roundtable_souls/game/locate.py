"""Where one game is on this machine: its install folder and exe, its saves, whether it runs, and the me3 that
launches it, with the Settings > Locations overrides applied.

A Locations value answers for one game. The app context (app.py) holds the one for the game the window shows and
makes a new one when the game, the settings or the setup in use change; code that needs a location is handed one
instead of reading a global. On Linux (desktop or Steam Deck) the game runs through Proton, so its saves live inside
the game's Proton prefix and the game process is a Wine process whose command line names the game's exe.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from roundtable_souls.config.settings import LauncherSettings, game_setting
from roundtable_souls.game import catalog
from roundtable_souls.platform import paths

PATH_SETTINGS = ("me3_path", "game_exe", "me3_profile_dir")  # Settings > Locations; blank = detect


@dataclass(frozen=True)
class Overrides:
    """The Settings > Locations values for one game (blank = detect): a custom me3, a custom game exe (me3 launches
    it with --exe) and a custom me3 profile folder, which falls back to what `me3 info` last reported."""

    me3_exe: str = ""
    game_exe: str = ""
    profiles_dir: str = ""

    @classmethod
    def from_settings(cls, settings: LauncherSettings, game: catalog.Game) -> Overrides:
        return cls(
            me3_exe=settings.me3_path.strip(),
            game_exe=str(game_setting(settings, game.key, "game_exe") or "").strip(),
            profiles_dir=settings.me3_profile_dir.strip()
            or str(settings.me3_info_cache.get("profile_dir") or "").strip(),
        )

    def in_effect(self) -> dict:
        """What Settings > Locations shows as set (the same keys apply_overrides returned)."""
        return {"me3": self.me3_exe, "game_exe": self.game_exe, "profile_dir": self.profiles_dir}


@dataclass(frozen=True, eq=False)
class Locations:
    game: catalog.Game
    overrides: Overrides = field(default_factory=Overrides)
    # Save names the setup in use configures beyond the defaults (me3's savefile, Seamless Co-op's
    # save_file_extension): role -> file name, so those files are listed and repaired too.
    setup_save_names: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, settings: LauncherSettings, game: catalog.Game) -> Locations:
        return cls(game, Overrides.from_settings(settings, game))

    def with_setup_save_names(self, names: Mapping[str, str]) -> Locations:
        """names: role -> file name, e.g. {"standard": "ER0000.sl2", "coop": "ER0000.co3"}."""
        return replace(self, setup_save_names={k: v for k, v in names.items() if v})

    def for_game(self, game: catalog.Game, settings: LauncherSettings) -> Locations:
        """The same machine's answers for another game (its own exe override; no setup save names yet)."""
        return Locations.from_settings(settings, game)

    # ------------------------------------------------------------------ the game
    def game_exe_name(self) -> str:
        return Path(self.overrides.game_exe).name if self.overrides.game_exe else self.game.exe

    def game_running(self) -> bool:
        return paths.exe_running(self.game_exe_name())

    def dead_game_shells(self) -> list[int]:
        """Leftover zero-memory copies of the game. A Windows problem; Proton cleans up after itself."""
        return paths.dead_exe_shells(self.game_exe_name())

    def game_dir(self) -> Path | None:
        if self.overrides.game_exe and Path(self.overrides.game_exe).is_file():
            return Path(self.overrides.game_exe).parent
        return installed_dir(self.game)

    def regulation_bin(self) -> Path | None:
        game = self.game_dir()
        if game and (game / "regulation.bin").exists():
            return game / "regulation.bin"
        return None

    # ------------------------------------------------------------------ saves
    def save_roots(self, game: catalog.Game | None = None) -> list[Path]:
        """Folders that hold the per-account save folders: %APPDATA%\\<game> on Windows, the same folder inside the
        game's Proton prefix on Linux (in whichever Steam library the prefix lives)."""
        game = game or self.game
        return paths.save_roots_for(game.save_dir, game.app_id)

    def save_names(self) -> list[str]:
        """The default names (ER0000.sl2, ER0000.co2) and any the setup in use configures, without repeats."""
        out: list[str] = []
        for n in (*self.game.save_names, *self.setup_save_names.values()):
            if n.lower() not in (x.lower() for x in out):
                out.append(n)
        return out

    def save_files(self) -> list[Path]:
        """Every save the game or the setup in use uses in the game's save folders, one folder per Steam account."""
        names = self.save_names()
        found: list[Path] = []
        for root in self.save_roots():
            for profile in sorted(root.glob("*")):
                if profile.is_dir():
                    found.extend(p for p in (profile / n for n in names) if p.exists())
        return found

    # ------------------------------------------------------------------ me3
    def me3_exe(self) -> Path | None:
        return paths.me3_exe(self.overrides.me3_exe)

    def me3_profiles_dir(self) -> Path | None:
        return paths.me3_profiles_dir(self.overrides.profiles_dir)

    def me3_profiles(self, game: catalog.Game | None = None) -> list[Path]:
        """User-made .me3 profiles for the game (the *-default.me3 ones me3 generates are skipped). A profile that
        names no game in [[supports]] counts for Elden Ring, the only game older profiles were written for."""
        game = game or self.game
        return paths.find_profiles(self.me3_profiles_dir(), game.key, catalog.ELDEN_RING.key)


def installed_dir(game: catalog.Game) -> Path | None:
    """The folder with this game's exe in any Steam library, or None (cached per game for the session)."""
    return paths.find_installed(game.key, game.install_dir, game.exe)
