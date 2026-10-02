"""After play: repair the regulation section in every save of the active game that the session touched.

me3's "oversized regulation fix" stops the game from copying its regulation into the save. Elden Ring: the repair
writes regulation.bin back into USER_DATA_11. Nightreign: it re-signs every encrypted section and, when entry 12 is no
longer RSLT, copies that section from a healthy sibling save. (Moved from system/session.py, which launches the game.)
"""

import time

from roundtable_souls.platform import paths as common
from roundtable_souls.platform.paths import fail, log
from roundtable_souls.saves import nightreign as repair_nightreign
from roundtable_souls.saves import regulation as repair


def wait_for_save_flush(saves, timeout=30):
    """The game writes its save on the way out. Wait until every save file can
    be opened for writing, which fails while the game still holds it."""
    deadline = time.time() + timeout
    busy = []
    while time.time() < deadline:
        busy = []
        for save in saves:
            try:
                with open(save, "r+b"):
                    pass
            except OSError:
                busy.append(save)
        if not busy:
            return True
        time.sleep(1)
    log(f"warning: still locked after {timeout}s: {', '.join(str(b) for b in busy)}")
    return False


def repair_all():
    if not common.GAME.regulation_repair:
        log(f"{common.GAME.name}: no save repair after play")
        return
    saves = common.save_files()
    if not saves:
        log(f"no {common.GAME.name} saves found on this PC")
        return
    if common.game_running():
        fail("the game is still running, not touching the saves", code=2)
    wait_for_save_flush(saves)
    if common.GAME.save_reader == "nightreign":
        fixed = 0
        for save in saves:
            log(str(save))
            fixed += repair_nightreign.repair(save, log=log)
        log(f"done: {fixed} repaired")
        return
    source = common.regulation_bin()
    if not source:
        fail("could not find the game's regulation.bin through Steam")
    reg, header = repair.load_regulation(source)
    if not repair.plausible_regulation(reg):
        fail(f"{source}: regulation length {len(reg):#x} does not look right")
    log(f"regulation: {source}")
    fixed = 0
    for save in saves:
        log(str(save))
        fixed += repair.repair(save, reg, header)
    log(f"done: {fixed} repaired")
