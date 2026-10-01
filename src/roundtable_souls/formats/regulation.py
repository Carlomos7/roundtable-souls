"""regulation.bin: AES-256-CBC around a DCX (ZSTD) around a BND4 binder of PARAM tables.

Writing keeps every structure the game's own file has and only recomputes what changes (row counts, offsets, sizes,
the binder's hash table), so rebuilding an unchanged regulation gives back the same binder bytes (the encryption's IV
differs on every write)."""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass

from roundtable_souls.formats import FormatError
from roundtable_souls.formats.bnd4 import COMPRESSION, IDS, NAMES1, NAMES2, Bnd4, bnd4_files, read_bnd4, write_bnd4
from roundtable_souls.formats.dcx import (  # noqa: F401  (ZSTD_WINDOW_LOG: also read from here)
    DCX_DATA_OFFSET,
    ZSTD_WINDOW_LOG,
    dcx_decompress,
    zstd_frame,
)
from roundtable_souls.formats.param import param_row_ids

REGULATION_KEY = bytes.fromhex("99BFFC366A6BC8C6F5827D093602D676C42892A01C207FB024D3AF4E493FEF99")


def decrypt_regulation(raw: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    if len(raw) < 32 or (len(raw) - 16) % 16:
        raise FormatError("regulation size is not a whole number of AES blocks")
    decryptor = Cipher(algorithms.AES(REGULATION_KEY), modes.CBC(raw[:16])).decryptor()
    return decryptor.update(raw[16:]) + decryptor.finalize()


# ----------------------------------------------------------------------------- the binder
# The regulation's binder is a BND4 archive read and written by the shared code in formats.py. What is particular to
# it is checked here: its layout.
REGULATION_FORMAT = IDS | NAMES1 | NAMES2 | COMPRESSION  # 0x74 as stored: 36-byte entries with IDs and Unicode names
REGULATION_ENTRY = 36


def read_binder(body: bytes) -> Bnd4:
    """The regulation's binder. Refuses another layout rather than guess at it."""
    b = read_bnd4(body)
    if b.format != REGULATION_FORMAT or not b.unicode or struct.unpack_from("<q", body, 0x20)[0] != REGULATION_ENTRY:
        raise FormatError("unsupported BND4 layout")
    return b


def binder_bytes(b: Bnd4) -> bytes:
    """The binder as the game's regulation stores it. Tables are not compressed inside it, so each one's sizes are its
    length (the shared writer's rule for such entries)."""
    return write_bnd4(b)


# ----------------------------------------------------------------------------- DCX and encryption
@dataclass
class Regulation:
    dcx_header: bytes  # the 0x4C DCX header as read
    bnd: Bnd4

    @property
    def version(self) -> str:
        """The regulation version the archive names (e.g. 11711000)."""
        return self.bnd.header[0x18:0x20].decode("ascii", "replace").strip("\0")


def read_regulation(raw: bytes, oodle=None) -> Regulation:
    dec = decrypt_regulation(raw)
    if dec[:4] != b"DCX\0":
        raise FormatError("not a DCX file")
    return Regulation(bytes(dec[:DCX_DATA_OFFSET]), read_binder(dcx_decompress(dec, oodle)))


def compress_regulation_body(body: bytes, level: int = 9) -> bytes:
    """The zstd frame the game accepts.

    The game crashes at start (access violation) on a frame whose blocks hold more than 64 KB of data, which is what
    zstd writes by default (128 KB). Its own regulation and every editor's output (SoulsFormats, Soulstruct) keep
    blocks at 64 KB by capping the window at 64 KB, and leave the content size out of the frame header. Checked in
    game on Elden Ring 1.17.1 (2026-09-30): the game's own bytes re-encrypted load; the same content recompressed
    with default blocks crashes, whatever the IV, level or window.
    """
    return zstd_frame(body, level)


def write_regulation(reg: Regulation, level: int = 9) -> bytes:
    """The encrypted file. Always ZSTD (what the game's own regulation uses)."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    body = binder_bytes(reg.bnd)
    payload = compress_regulation_body(body, level)
    header = bytearray(reg.dcx_header)
    if header[0x28:0x2C] != b"ZSTD":
        raise FormatError("the base regulation is not ZSTD-compressed; rebuild from the game's own file")
    struct.pack_into(">II", header, 0x1C, len(body), len(payload))
    plain = bytes(header) + payload
    plain += b"\0" * (-len(plain) % 16)
    iv = os.urandom(16)
    enc = Cipher(algorithms.AES(REGULATION_KEY), modes.CBC(iv)).encryptor()
    return iv + enc.update(plain) + enc.finalize()


# Item tables in the regulation, with the category bits a full item ID carries.
ITEM_TABLES = {
    "EquipParamWeapon": 0x00000000,
    "EquipParamProtector": 0x10000000,
    "EquipParamAccessory": 0x20000000,
    "EquipParamGoods": 0x40000000,
    "EquipParamGem": 0x80000000,
}


def regulation_item_ids(raw: bytes) -> frozenset[int]:
    """Full item IDs of every weapon, armour piece, talisman, item and ash of war the regulation defines."""
    body = dcx_decompress(decrypt_regulation(raw))
    ids: set[int] = set()
    for name, blob in bnd4_files(body):
        bits = ITEM_TABLES.get(name.split(".", 1)[0])
        if bits is not None:
            ids.update(bits | row for row in param_row_ids(blob) if row)
    if not ids:
        raise FormatError("no item tables in the regulation")
    return frozenset(ids)
