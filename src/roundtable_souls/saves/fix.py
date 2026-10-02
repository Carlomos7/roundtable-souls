"""Backed-up writes for Elden Ring PC saves: checksum repair, and the commit step every repair uses.

Every write:
  1. builds the new bytes in memory,
  2. re-parses them and checks the MD5 of every touched slot,
  3. copies the original into the launcher's backups (folders.backups, with a JSON note saying why), then
     replaces it.

Nothing is written when there is nothing to do. Callers refuse while the game runs.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

from roundtable_souls.saves import backups as folders
from roundtable_souls.saves import layout as L

SLOT_STRIDE = 0x10 + L.SLOT_SIZE


class FixError(Exception):
    pass


def plan_checksum_fixes(parsed: dict) -> dict:
    """Which MD5s are stale: {'slots': [active slot indexes], 'ud10': bool}."""
    active = (parsed.get("ud10") or {}).get("active") or []
    bad = [i for i, ok in enumerate(parsed.get("slot_md5_ok") or []) if not ok and i < len(active) and active[i]]
    return {"slots": bad, "ud10": not parsed.get("ud10_md5_ok", True)}


def backup(save: Path, manifest: dict | None = None) -> Path:
    """Copy the save into its account's backups folder (folders.backups). A note (what it was taken before, when,
    which save, what changed) is written beside it as <backup>.json, then older backups of that save are pruned."""
    save = Path(save)
    folder = folders.backups(save.parent)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = folder / f"{save.name}.{stamp}.bak"
    n = 1
    while dest.exists():
        n += 1
        dest = folder / f"{save.name}.{stamp}-{n}.bak"
    shutil.copy2(save, dest)
    write_manifest(dest, manifest or {"action": "Before a change"}, save)
    folders.prune(folder, save.name)
    return dest


def write_manifest(bak: Path, manifest: dict, save: Path | None = None) -> None:
    doc = {
        "action": manifest.get("action", "Before a change"),
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "save": str(save) if save else "",
        "changes": list(manifest.get("changes") or []),
    }
    try:
        Path(str(bak) + ".json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    except OSError:
        pass


def read_manifest(bak: Path) -> dict | None:
    p = Path(str(bak) + ".json")
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None


def _sign_slot(data: bytearray, i: int) -> None:
    off = L.HEADER + i * SLOT_STRIDE
    data[off : off + 0x10] = hashlib.md5(data[off + 0x10 : off + SLOT_STRIDE]).digest()


def _sign_ud10(data: bytearray, ud10_pos: int) -> None:
    data[ud10_pos : ud10_pos + 0x10] = hashlib.md5(data[ud10_pos + 0x10 : ud10_pos + 0x60010]).digest()


def _commit(
    save: Path, data: bytes, touched_slots: list[int], expect_ud10_ok: bool, manifest: dict | None = None
) -> Path:
    """Verify the new bytes parse with matching MD5s, back the original up, then replace it."""
    tmp = save.with_name(save.name + ".roundtable.tmp")
    tmp.write_bytes(data)
    try:
        r = L.parse(str(tmp))
        for i in touched_slots:
            if not r["slot_md5_ok"][i]:
                raise FixError(f"slot {i + 1} checksum did not verify after the write")
        if expect_ud10_ok and not r["ud10_md5_ok"]:
            raise FixError("profile summary checksum did not verify after the write")
        bak = backup(save, manifest)
        tmp.replace(save)
        return bak
    finally:
        if tmp.exists():
            tmp.unlink()


def repair_checksums(save: Path, log=None) -> dict:
    """Recompute stale slot and profile-summary MD5s. Returns {'slots': [...], 'ud10': bool, 'backup': Path | None}."""
    save = Path(save)
    say = log or (lambda *_: None)
    data = bytearray(save.read_bytes())
    r = L.parse(str(save))
    plan = plan_checksum_fixes(r)
    if not plan["slots"] and not plan["ud10"]:
        say("  checksums already match")
        return {"slots": [], "ud10": False, "backup": None}
    for i in plan["slots"]:
        _sign_slot(data, i)
        say(f"  slot {i + 1}: checksum recomputed")
    if plan["ud10"]:
        _sign_ud10(data, r["ud10_pos"])
        say("  profile summary: checksum recomputed")
    changes = [f"slot {i + 1}: checksum recomputed" for i in plan["slots"]] + (
        ["profile summary: checksum recomputed"] if plan["ud10"] else []
    )
    bak = _commit(save, bytes(data), plan["slots"], True, {"action": "Before fixing checksums", "changes": changes})
    say(f"  backup: {bak}")
    return {"slots": plan["slots"], "ud10": plan["ud10"], "backup": bak}
