"""Repair Elden Ring PC saves (.sl2/.co2) whose USER_DATA_11 regulation block
was overwritten with garbage.

Seen with me3: its "oversized regulation fix" hooks the game's save routine
so the regulation is no longer copied into the block. The game still signs
the block and loads the save fine, but save editors that decode the
regulation fail on it.

Layout of the last BND4 entry (offset 0x19603B0, size 0x240020):
  0x00  MD5 of everything after it
  0x10  16-byte header (" GER", version 2, ...)
  0x20  encrypted regulation (same bytes as the game's regulation.bin),
        zero padded to 0x240000

Usage:
  repair_regulation.py [<save> ...] [--regulation <regulation.bin or healthy save>]
                       [--force] [--dry-run] [-o OUT]

With no saves given, every ER0000.sl2 / ER0000.co2 under %APPDATA%/EldenRing
is repaired. With no --regulation the game's regulation.bin is located through
the Steam install. Saves whose block already looks healthy are skipped unless
--force. Each repaired save is backed up first, into the launcher's backups
folder next to it.

Exit codes: 0 done (repaired or nothing to do), 1 error, 2 game is running.
"""

import argparse
import hashlib
from pathlib import Path

from roundtable_souls.system import common
from roundtable_souls.system.common import fail, log

UD11_OFF = 0x19603B0
UD11_SIZE = 0x240020
BLOCK = 0x240000
FILE_SIZE = 0x1BA03D0
HEALTHY_HEADER = bytes.fromhex("20 47 45 52 02 00 00 00 18 b2 b2 00 00 00 24 00")


def is_pc_save(data):
    return len(data) == FILE_SIZE and data[:4] == b"BND4"


def plausible_regulation(reg):
    return 0x100000 < len(reg) < BLOCK


def load_regulation(src):
    """The encrypted regulation and block header from a regulation.bin, or
    from the block of a healthy save."""
    data = Path(src).read_bytes()
    if is_pc_save(data):
        body = data[UD11_OFF + 0x20 : UD11_OFF + UD11_SIZE]
        reg = body[: len(body.rstrip(b"\0"))]
        reg = reg[: min((len(reg) + 15) // 16 * 16, BLOCK)]
        return reg, data[UD11_OFF + 0x10 : UD11_OFF + 0x20]
    return data, HEALTHY_HEADER


def block_status(data):
    """(healthy, used_bytes, header) for a save's regulation block."""
    entry = data[UD11_OFF : UD11_OFF + UD11_SIZE]
    header = bytes(entry[0x10:0x20])
    used = len(entry[0x20:].rstrip(b"\0"))
    signed = hashlib.md5(entry[0x10:]).digest() == entry[:0x10]
    healthy = header == HEALTHY_HEADER and 0x100000 < used < BLOCK and signed
    return healthy, used, header


def rebuild_block(reg, header):
    payload = header + reg + b"\0" * (BLOCK - len(reg))
    return hashlib.md5(payload).digest() + payload


def backup(save):
    from roundtable_souls.saves import fix as save_fix

    return save_fix.backup(
        Path(save),
        {"action": "Before repairing for save editors", "changes": ["regulation block rebuilt from regulation.bin"]},
    )


def repair(save, reg, header, force=False, out_path=None, dry_run=False):
    """Returns True when the save was (or would be) rewritten."""
    save = Path(save)
    data = bytearray(save.read_bytes())
    if not is_pc_save(data):
        log("  skip: not a PC Elden Ring save (magic/size mismatch)")
        return False

    healthy, used, hdr = block_status(data)
    log(f"  block: {used:#x} non-zero bytes, header {hdr.hex(' ')}, {'healthy' if healthy else 'BROKEN'}")
    if healthy and not force:
        log("  nothing to do")
        return False
    if dry_run:
        log("  would repair (dry run)")
        return True

    data[UD11_OFF : UD11_OFF + UD11_SIZE] = rebuild_block(reg, header)
    out = Path(out_path) if out_path else save
    if out == save:
        log(f"  backup: {backup(save)}")
    out.write_bytes(data)
    log(f"  wrote:  {out}")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("saves", nargs="*", help="save files to repair (default: every save under %%APPDATA%%/EldenRing)")
    ap.add_argument(
        "--regulation", help="regulation.bin, or a healthy save to copy the block from (default: the game's)"
    )
    ap.add_argument("--force", action="store_true", help="rewrite the block even if it looks healthy")
    ap.add_argument("--dry-run", action="store_true", help="report what would change without writing")
    ap.add_argument("-o", "--out", help="output path (single save only; default: repair in place)")
    a = ap.parse_args()
    common.start_log("repair_regulation")

    saves = [Path(p) for p in a.saves] or common.save_files()
    if not saves:
        fail("no saves given and none found under %APPDATA%/EldenRing")
    if a.out and len(saves) > 1:
        fail("-o only works with a single save")

    source = Path(a.regulation) if a.regulation else common.regulation_bin()
    if not source or not source.exists():
        fail("could not find the game's regulation.bin through Steam; pass it with --regulation")
    reg, header = load_regulation(source)
    if not plausible_regulation(reg):
        fail(f"{source}: regulation length {len(reg):#x} does not look right")
    log(f"regulation: {source} ({len(reg):#x} bytes, md5 {hashlib.md5(reg).hexdigest()})")

    if common.game_running() and not a.dry_run:
        fail("Elden Ring is running: close it first so the game does not overwrite the repaired save", code=2)

    fixed = 0
    for save in saves:
        log(str(save))
        if not save.exists():
            log("  skip: not found")
            continue
        fixed += repair(save, reg, header, a.force, a.out, a.dry_run)
    log(f"done: {fixed} {'would be ' if a.dry_run else ''}repaired")


if __name__ == "__main__":
    main()
