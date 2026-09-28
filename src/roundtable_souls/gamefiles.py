"""Read FromSoftware's container formats from files on the player's own PC: the encrypted regulation (the game's
item database), DCX compression, BND4 archives, PARAM tables and FMG text tables. Read-only; nothing is bundled.

Oodle-compressed files are decompressed with the Oodle library that ships with the game, so that part works on
Windows only.
"""

from __future__ import annotations

import ctypes
import struct
import sys
import zlib
from compression import zstd
from pathlib import Path

REGULATION_KEY = bytes.fromhex("99BFFC366A6BC8C6F5827D093602D676C42892A01C207FB024D3AF4E493FEF99")
DCX_DATA_OFFSET = 0x4C


class FormatError(ValueError):
    """The file is not in the expected format (or needs a decompressor that is not available here)."""


def decrypt_regulation(raw: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    if len(raw) < 32 or (len(raw) - 16) % 16:
        raise FormatError("regulation size is not a whole number of AES blocks")
    decryptor = Cipher(algorithms.AES(REGULATION_KEY), modes.CBC(raw[:16])).decryptor()
    return decryptor.update(raw[16:]) + decryptor.finalize()


def find_oodle(game_dir: Path | None):
    """The game's own Oodle DLL, loaded, or None (not Windows, or not found)."""
    if sys.platform != "win32" or not game_dir:
        return None
    for dll in sorted(Path(game_dir).glob("oo2core_*_win64.dll"), reverse=True):
        try:
            lib = ctypes.WinDLL(str(dll))
        except OSError:
            continue
        fn = lib.OodleLZ_Decompress
        fn.restype = ctypes.c_ssize_t
        fn.argtypes = [
            ctypes.c_char_p, ctypes.c_ssize_t, ctypes.c_char_p, ctypes.c_ssize_t, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_void_p, ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_ssize_t, ctypes.c_int,
        ]  # fmt: skip
        return fn
    return None


def dcx_decompress(data: bytes, oodle=None) -> bytes:
    """Unpack a DCX file (ZSTD, DFLT or, with the game's Oodle, KRAK)."""
    if data[:4] != b"DCX\0":
        raise FormatError("not a DCX file")
    usize, csize = struct.unpack_from(">II", data, 0x1C)
    kind = data[0x28:0x2C]
    payload = data[DCX_DATA_OFFSET : DCX_DATA_OFFSET + csize]
    if kind == b"ZSTD":
        return zstd.decompress(payload)
    if kind == b"DFLT":
        return zlib.decompress(payload)
    if kind == b"KRAK":
        if oodle is None:
            raise FormatError("Oodle compression needs the game's oo2core DLL (Windows only)")
        out = ctypes.create_string_buffer(usize)
        got = oodle(payload, csize, out, usize, 1, 0, 0, None, 0, None, None, None, 0, 3)
        if got != usize:
            raise FormatError("Oodle could not decompress the file")
        return out.raw
    raise FormatError(f"unknown DCX compression {kind!r}")


def _utf16z(data: bytes, offset: int) -> str:
    end = offset
    while data[end : end + 2] != b"\0\0":
        end += 2
    return data[offset:end].decode("utf-16-le")


def bnd4_files(body: bytes) -> list[tuple[str, bytes]]:
    """(file name without folders, bytes) for every file in a BND4 archive of the kind the game uses (format 0x74)."""
    if body[:4] != b"BND4":
        raise FormatError("not a BND4 archive")
    count = struct.unpack_from("<i", body, 0x0C)[0]
    header_size = struct.unpack_from("<q", body, 0x20)[0]
    if not body[0x30] or header_size < 36:
        raise FormatError("unsupported BND4 layout")
    files = []
    for i in range(count):
        o = 0x40 + i * header_size
        size = struct.unpack_from("<q", body, o + 8)[0]
        data_offset, _id, name_offset = struct.unpack_from("<III", body, o + 24)
        name = _utf16z(body, name_offset).replace("\\", "/").rsplit("/", 1)[-1]
        files.append((name, body[data_offset : data_offset + size]))
    return files


def param_row_ids(blob: bytes) -> list[int]:
    """Row IDs of a PARAM table (the 64-bit layout the game uses)."""
    count = struct.unpack_from("<H", blob, 0x0A)[0]
    return [struct.unpack_from("<I", blob, 0x40 + i * 24)[0] for i in range(count)]


def fmg_entries(blob: bytes) -> dict[int, str]:
    """Text ID -> text for an FMG table (version 2). Empty entries are skipped."""
    groups = struct.unpack_from("<i", blob, 0x0C)[0]
    offsets_at = struct.unpack_from("<q", blob, 0x18)[0]
    out = {}
    for g in range(groups):
        index, first, last, _pad = struct.unpack_from("<iiii", blob, 0x28 + g * 16)
        for k, text_id in enumerate(range(first, last + 1)):
            at = struct.unpack_from("<q", blob, offsets_at + (index + k) * 8)[0]
            if at > 0:
                text = _utf16z(blob, at).strip()
                if text:
                    out[text_id] = text
    return out


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
