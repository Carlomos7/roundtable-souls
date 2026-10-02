"""Helpers for the tests: Elden Ring's locations on this PC (er()), and for the integration tests, which need a real
Seamless Co-op save, a copy of one.

The save comes from ROUNDTABLE_TEST_SAVE when set, otherwise from the first ER0000.co2 under %APPDATA%\\EldenRing.
Tests copy it into a temp folder and never write the original. Without a save the tests skip.
"""

import os
import shutil
from pathlib import Path

import pytest

from roundtable_souls.game import catalog
from roundtable_souls.game.locate import Locations
from roundtable_souls.saves.analyze import GameItems


def er() -> Locations:
    """Elden Ring with nothing set under Settings > Locations: what code that is handed a game's locations gets."""
    return Locations(catalog.ELDEN_RING)


def er_items() -> GameItems:
    """What a save is checked against with er(): the installed game's items (none when it is not installed)."""
    return GameItems.for_locations(er())


def live_save() -> Path | None:
    override = os.environ.get("ROUNDTABLE_TEST_SAVE")
    if override:
        p = Path(override)
        return p if p.is_file() else None
    return next((p for p in er().save_files() if p.suffix.lower() == ".co2"), None)


def copy_live_save(tmp_path: Path) -> Path:
    src = live_save()
    if src is None:
        pytest.skip("no Seamless Co-op save on this PC (set ROUNDTABLE_TEST_SAVE to use one)")
    tmp_path.mkdir(parents=True, exist_ok=True)
    copy = tmp_path / "ER0000.co2"
    shutil.copy2(src, copy)
    return copy
