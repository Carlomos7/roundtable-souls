"""The games Roundtable Souls knows: where each one installs, where it saves, and what the launcher can do for it.

Everything that differs between games lives here, so the rest of the code asks the active game instead of assuming
Elden Ring. `ready` games get the full launcher; the others show a placeholder tab until their support lands.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Game:
    key: str  # me3's name for the game (`me3 launch --game <key>`), also the settings key
    name: str  # shown in the window
    short: str  # tab label when the window is narrow
    aliases: tuple[str, ...]  # what `--game` accepts besides the key and the Steam app id
    app_id: str  # Steam app id (Proton prefix folder on Linux)
    install_dir: str  # folder under steamapps/common that holds `exe`
    exe: str
    save_dir: str  # folder under %APPDATA% (or the Proton prefix's Roaming) with one folder per Steam account
    save_stem: str  # save file name without extension
    coop_dll: str | None = None  # Seamless Co-op dll for this game, if one exists
    coop_ini: str | None = None
    save_reader: str | None = None  # "eldenring": full character reading; "container": file structure only
    save_sections: int | None = None  # sections the game writes into a save, for the structure check
    regulation_repair: bool = False  # me3 leaves the save's regulation block dirty; repaired after play
    ready: bool = False

    @property
    def save_names(self) -> tuple[str, str]:
        return f"{self.save_stem}.sl2", f"{self.save_stem}.co2"


ELDEN_RING = Game(
    key="eldenring",
    name="Elden Ring",
    short="ER",
    aliases=("er", "elden", "elden-ring"),
    app_id="1245620",
    install_dir="ELDEN RING/Game",
    exe="eldenring.exe",
    save_dir="EldenRing",
    save_stem="ER0000",
    coop_dll="ersc.dll",
    coop_ini="ersc_settings.ini",
    save_reader="eldenring",
    regulation_repair=True,
    ready=True,
)
NIGHTREIGN = Game(
    key="nightreign",
    name="Nightreign",
    short="NR",
    aliases=("nr", "elden-ring-nightreign"),
    app_id="2622380",
    install_dir="ELDEN RING NIGHTREIGN/Game",
    exe="nightreign.exe",
    save_dir="Nightreign",
    save_stem="NR0000",
    coop_dll="nrsc.dll",
    coop_ini="nrsc_settings.ini",
    save_reader="container",
    save_sections=14,
    ready=True,
)
DARK_SOULS_3 = Game(
    key="darksouls3",
    name="Dark Souls III",
    short="DS3",
    aliases=("ds3", "dark-souls-3", "darksoulsiii"),
    app_id="374320",
    install_dir="DARK SOULS III/Game",
    exe="DarkSoulsIII.exe",
    save_dir="DarkSoulsIII",
    save_stem="DS30000",
)
SEKIRO = Game(
    key="sekiro",
    name="Sekiro",
    short="Sekiro",
    aliases=("sdt", "sekiro-shadows-die-twice"),
    app_id="814380",
    install_dir="Sekiro",
    exe="sekiro.exe",
    save_dir="Sekiro",
    save_stem="S0000",
)

GAMES: tuple[Game, ...] = (ELDEN_RING, NIGHTREIGN, DARK_SOULS_3, SEKIRO)
BY_KEY = {g.key: g for g in GAMES}
DEFAULT = ELDEN_RING


def resolve(name: str | None) -> Game | None:
    """The game for a `--game` value: its key, an alias, or its Steam app id, in any case. None when unknown."""
    wanted = str(name or "").strip().lower()
    if not wanted:
        return None
    for g in GAMES:
        if wanted in (g.key, g.app_id, g.short.lower(), *g.aliases):
            return g
    return None


def get(key: str | None) -> Game:
    """The game for a stored key, falling back to Elden Ring for anything unknown."""
    return BY_KEY.get(str(key or ""), DEFAULT)


def names_help() -> str:
    """The accepted `--game` values, for error messages."""
    return ", ".join(f"{g.short.lower() if g.short.lower() != g.key else g.key} ({g.name})" for g in GAMES)


def for_save(path) -> Game | None:
    """The game a save file belongs to, from its name (ER0000.co2 is Elden Ring's). None for other files."""
    stem = Path(str(path)).name.split(".")[0].upper()
    return next((g for g in GAMES if g.save_stem.upper() == stem), None)
