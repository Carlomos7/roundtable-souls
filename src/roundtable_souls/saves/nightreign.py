"""Nightreign PC saves (.sl2/.co2): decrypt, verify, re-sign, and restore the regulation section.

Each BND4 section is AES-128-CBC with a 16-byte IV in front (the well-known FromSoft SL2 key, same as
DS2 / Elden Ring). After decrypt:

  [0:4]       size field (payload length + 16)
  [4:n-28]    payload  (MD5 of this range is the integrity check)
  [n-28:n-12] 16-byte MD5
  [n-12:n]    12 bytes of 0x0C

Entry 12 is the in-save regulation / param blob. It starts with ``RSLT``, not a copy of Game\\regulation.bin
(that file is a different encoding). me3's oversized-regulation hook still applies to Nightreign, so a
session can leave entry 12 unsigned or unreadable. Repair re-signs every section with its original IV, and
when entry 12 no longer looks like RSLT it copies the section from a healthy sibling (.bak / .sl2 / .co2)
if one exists. It never writes Game\\regulation.bin into the save.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from roundtable_souls.saves import container
from roundtable_souls.saves import fix as save_fix

# Well-known FromSoft SL2 AES-128 key (DS2 / Elden Ring / Nightreign saves).
KEY = bytes.fromhex("18F6326605BD178A5524523AC0A0C609")
IV_SIZE = 16
CHECKSUM_TAIL = 28  # MD5 (16) + 0x0C padding (12)
PAD12 = b"\x0c" * 12
REGULATION_INDEX = 12
RSLT = b"RSLT"
EXPECTED_SECTIONS = 14


class NightreignSaveError(ValueError):
    """The file is not a Nightreign save we can decrypt or rewrite."""


def decrypt_entry(blob: bytes) -> tuple[bytes, bytes]:
    """(iv, decrypted) for one encrypted BND4 section."""
    if len(blob) < IV_SIZE + 32 or (len(blob) - IV_SIZE) % 16:
        raise NightreignSaveError("section is not a whole AES block")
    iv, payload = bytes(blob[:IV_SIZE]), blob[IV_SIZE:]
    dec = Cipher(algorithms.AES(KEY), modes.CBC(iv)).decryptor()
    return iv, dec.update(payload) + dec.finalize()


def encrypt_entry(iv: bytes, decrypted: bytes | bytearray) -> bytes:
    """Re-encrypt with the original IV so the BND4 section stays the same size."""
    if len(iv) != IV_SIZE:
        raise NightreignSaveError("IV must be 16 bytes")
    if len(decrypted) % 16:
        raise NightreignSaveError("plaintext is not a whole AES block")
    enc = Cipher(algorithms.AES(KEY), modes.CBC(bytes(iv))).encryptor()
    return bytes(iv) + enc.update(bytes(decrypted)) + enc.finalize()


def checksum_offset(dec: bytes | bytearray) -> int:
    if len(dec) < CHECKSUM_TAIL + 4:
        raise NightreignSaveError("section plaintext is too short")
    return len(dec) - CHECKSUM_TAIL


def payload_of(dec: bytes | bytearray) -> bytes:
    return bytes(dec[4 : checksum_offset(dec)])


def checksum_of(dec: bytes | bytearray) -> bytes:
    off = checksum_offset(dec)
    return hashlib.md5(bytes(dec[4:off])).digest()


def checksum_ok(dec: bytes | bytearray) -> bool:
    off = checksum_offset(dec)
    return bytes(dec[off : off + 16]) == checksum_of(dec)


def padding_ok(dec: bytes | bytearray) -> bool:
    return bytes(dec[len(dec) - 12 :]) == PAD12


def patch_checksum(dec: bytearray) -> None:
    """Write MD5(dec[4:n-28]) at n-28. Leaves the 0x0C padding alone."""
    off = checksum_offset(dec)
    dec[off : off + 16] = checksum_of(dec)
    if len(dec) - off >= CHECKSUM_TAIL:
        dec[off + 16 : off + CHECKSUM_TAIL] = PAD12


def wrap_plaintext(payload: bytes) -> bytes:
    """One decrypted section: size field + payload + MD5 + 0x0C padding, 16-byte aligned."""
    body = struct.pack("<I", len(payload) + 16) + payload
    pad = (-(len(body) + CHECKSUM_TAIL)) % 16
    body = body + (b"\0" * pad)
    dec = bytearray(body + bytes(CHECKSUM_TAIL))
    patch_checksum(dec)
    return bytes(dec)


def rslt_payload(dec: bytes | bytearray) -> bool:
    """True when entry 12 still looks like the in-save regulation blob (RSLT), checksum aside."""
    return padding_ok(dec) and payload_of(dec).startswith(RSLT)


def regulation_ok(dec: bytes | bytearray) -> bool:
    return checksum_ok(dec) and rslt_payload(dec)


def inspect(data: bytes, expected_sections: int | None = EXPECTED_SECTIONS) -> dict:
    """Checksum / padding / regulation status for every section. Does not write."""
    found = container.check(data, expected_sections)
    checksums, pads, errors = [], [], []
    decrypted: list[bytes | None] = []
    for i, sec in enumerate(found):
        blob = data[sec.offset : sec.offset + sec.size]
        try:
            _iv, dec = decrypt_entry(blob)
        except NightreignSaveError as e:
            checksums.append(False)
            pads.append(False)
            decrypted.append(None)
            errors.append(f"section {i}: {e}")
            continue
        checksums.append(checksum_ok(dec))
        pads.append(padding_ok(dec))
        decrypted.append(dec)
        if not checksums[-1] or not pads[-1]:
            errors.append(f"section {i}: checksum or padding mismatch")
    rslt = False
    if len(decrypted) > REGULATION_INDEX and decrypted[REGULATION_INDEX] is not None:
        rslt = rslt_payload(decrypted[REGULATION_INDEX])
    cs_ok = bool(checksums) and all(checksums) and all(pads)
    return {
        "sections": found,
        "checksum_ok": checksums,
        "padding_ok": pads,
        "rslt": rslt,
        "regulation_ok": rslt and (checksums[REGULATION_INDEX] if len(checksums) > REGULATION_INDEX else False),
        "healthy": cs_ok and rslt,
        "checksum_all_ok": cs_ok,
        "errors": errors,
    }


def rewrite(data: bytes, *, restore_regulation: bytes | None = None) -> bytes:
    """Re-sign every section (original IVs). Optionally replace entry 12 from another encrypted section."""
    found = container.check(data, EXPECTED_SECTIONS)
    src_dec = None
    if restore_regulation is not None:
        _iv, src_dec = decrypt_entry(restore_regulation)
        if not regulation_ok(src_dec):
            raise NightreignSaveError("regulation source is not a signed RSLT section")
    out = bytearray(data)
    for i, sec in enumerate(found):
        blob = bytes(data[sec.offset : sec.offset + sec.size])
        iv, dec = decrypt_entry(blob)
        dec = bytearray(dec)
        if i == REGULATION_INDEX and src_dec is not None:
            if len(src_dec) != len(dec):
                raise NightreignSaveError(f"regulation section size mismatch ({len(src_dec)} vs {len(dec)})")
            dec[:] = src_dec
        patch_checksum(dec)
        new_blob = encrypt_entry(iv, dec)
        if len(new_blob) != sec.size:
            raise NightreignSaveError(f"section {i} changed size while re-encrypting")
        out[sec.offset : sec.offset + sec.size] = new_blob
    return bytes(out)


def pack_save(payloads: list[bytes], *, ivs: list[bytes] | None = None) -> bytes:
    """A whole Nightreign-shaped BND4 of encrypted sections (for tests)."""
    if len(payloads) != EXPECTED_SECTIONS:
        raise NightreignSaveError(f"Nightreign writes {EXPECTED_SECTIONS} sections, not {len(payloads)}")
    names = [f"USER_DATA{i:03d}" for i in range(EXPECTED_SECTIONS)]
    blobs = []
    for i, payload in enumerate(payloads):
        iv = ivs[i] if ivs else bytes([i, *range(1, 16)])
        blobs.append(encrypt_entry(iv, wrap_plaintext(payload)))
    table_end = 0x40 + 0x20 * EXPECTED_SECTIONS
    name_blob, name_offsets = b"", []
    for n in names:
        name_offsets.append(table_end + len(name_blob))
        name_blob += n.encode("utf-16-le") + b"\0\0"
    data_at = table_end + len(name_blob)
    head = bytearray(0x40)
    head[:4] = b"BND4"
    struct.pack_into("<i", head, 0x0C, EXPECTED_SECTIONS)
    struct.pack_into("<q", head, 0x20, 0x20)
    entries, data = b"", b""
    for blob, name_off in zip(blobs, name_offsets, strict=True):
        entries += struct.pack("<iiqII8x", 0x40, -1, len(blob), data_at + len(data), name_off)
        data += blob
    return bytes(head) + entries + name_blob + data


def _encrypted_section(data: bytes, index: int) -> bytes:
    found = container.check(data, EXPECTED_SECTIONS)
    if index >= len(found):
        raise NightreignSaveError(f"save has no section {index}")
    sec = found[index]
    return data[sec.offset : sec.offset + sec.size]


def sibling_regulation_source(save: Path) -> Path | None:
    """A healthy Nightreign save next to this one whose entry 12 still looks like RSLT."""
    save = Path(save)
    cands = [
        save.with_name(save.name + ".bak"),
        save.with_suffix(".bak"),
        save.with_suffix(".sl2" if save.suffix.lower() == ".co2" else ".co2"),
    ]
    for cand in cands:
        if not cand.is_file() or cand.resolve() == save.resolve():
            continue
        try:
            if inspect(cand.read_bytes())["regulation_ok"]:
                return cand
        except OSError, NightreignSaveError, container.ContainerError:
            continue
    return None


def repair(
    save: Path, *, force: bool = False, dry_run: bool = False, log=None, regulation_source: Path | None = None
) -> bool:
    """Re-sign the save and restore entry 12 from a healthy sibling when needed. True if rewritten."""
    say = log or (lambda *_a, **_k: None)
    save = Path(save)
    data = save.read_bytes()
    try:
        status = inspect(data)
    except container.ContainerError as e:
        say(f"  skip: not a whole Nightreign save ({e})")
        return False

    restore_blob = None
    if not status["rslt"]:
        src = Path(regulation_source) if regulation_source else sibling_regulation_source(save)
        if src is not None:
            try:
                restore_blob = _encrypted_section(src.read_bytes(), REGULATION_INDEX)
                if not regulation_ok(decrypt_entry(restore_blob)[1]):
                    restore_blob = None
                else:
                    say(f"  regulation source: {src}")
            except (OSError, NightreignSaveError, container.ContainerError) as e:
                say(f"  regulation source unusable ({e})")
                restore_blob = None
        else:
            say("  regulation section unreadable; no healthy copy next to this file to restore from")

    if status["healthy"] and restore_blob is None and not force:
        say("  nothing to do")
        return False
    if not status["checksum_all_ok"]:
        bad = [str(i) for i, ok in enumerate(status["checksum_ok"]) if not ok]
        say(f"  checksum mismatch in section(s) {', '.join(bad)}")
    if dry_run:
        say("  would repair (dry run)")
        return True

    new = rewrite(data, restore_regulation=restore_blob)
    if new == data:
        say("  nothing to do")
        return False
    bak = save_fix.backup(
        save,
        {
            "action": "Repair Nightreign save",
            "changes": (
                (["regulation section restored from a healthy copy"] if restore_blob is not None else [])
                + (["section checksums recomputed"] if not status["checksum_all_ok"] or restore_blob else [])
            )
            or ["sections re-signed"],
        },
    )
    tmp = save.with_name(save.name + ".roundtable.tmp")
    tmp.write_bytes(new)
    try:
        check = inspect(tmp.read_bytes())
        if not check["checksum_all_ok"]:
            raise NightreignSaveError("checksums did not verify after the write")
        if restore_blob is not None and not check["regulation_ok"]:
            raise NightreignSaveError("regulation section did not verify after the write")
        tmp.replace(save)
    finally:
        if tmp.exists():
            tmp.unlink()
    say(f"  backup: {bak}")
    say(f"  wrote:  {save}")
    return True
