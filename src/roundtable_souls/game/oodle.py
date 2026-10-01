"""The game's own Oodle library (oo2core_*_win64.dll): finding it, loading it, and the native calls. Windows only;
elsewhere every function says there is none. The library is the game's: it is never shipped with the launcher."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from roundtable_souls.formats import FormatError


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


def decompress(fn, payload: bytes, usize: int) -> bytes:
    """Kraken-decompress payload to usize bytes with find_oodle()'s function."""
    out = ctypes.create_string_buffer(usize)
    got = fn(payload, len(payload), out, usize, 1, 0, 0, None, 0, None, None, None, 0, 3)
    if got != usize:
        raise FormatError("Oodle could not decompress the file")
    return out.raw


_compressor = None


def oodle_compressor(game_dir: Path | None):
    """The game's Oodle DLL's compressor, loaded once, or None (not Windows, or not found)."""
    global _compressor
    if _compressor is not None:
        return _compressor
    if sys.platform != "win32" or not game_dir:
        return None
    for dll in sorted(Path(game_dir).glob("oo2core_*_win64.dll"), reverse=True):
        try:
            lib = ctypes.WinDLL(str(dll))
        except OSError:
            continue
        _compressor = lib
        lib.OodleLZ_Compress.restype = ctypes.c_ssize_t
        lib.OodleLZ_Compress.argtypes = [
            ctypes.c_int, ctypes.c_char_p, ctypes.c_ssize_t, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ssize_t,
        ]  # fmt: skip
        lib.OodleLZ_CompressOptions_GetDefault.restype = ctypes.c_void_p
        lib.OodleLZ_CompressOptions_GetDefault.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.OodleLZ_GetCompressedBufferSizeNeeded.restype = ctypes.c_ssize_t
        lib.OodleLZ_GetCompressedBufferSizeNeeded.argtypes = [ctypes.c_ssize_t]
        return lib
    return None


class _Options(ctypes.Structure):
    _fields_ = [
        ("verbosity", ctypes.c_uint),
        ("minMatchLen", ctypes.c_int),
        ("seekChunkReset", ctypes.c_int),
        ("seekChunkLen", ctypes.c_int),
        ("profile", ctypes.c_int),
        ("dictionarySize", ctypes.c_int),
        ("spaceSpeedTradeoffBytes", ctypes.c_int),
        ("maxHuffmansPerChunk", ctypes.c_int),
        ("sendQuantumCRCs", ctypes.c_int),
        ("maxLocalDictionarySize", ctypes.c_int),
        ("makeLongRangeMatcher", ctypes.c_int),
        ("matchTableSizeLog2", ctypes.c_int),
    ]


KRAKEN = 8


def compress_kraken(body: bytes, level: int, lib) -> bytes:
    opts = _Options.from_address(lib.OodleLZ_CompressOptions_GetDefault(KRAKEN, level))
    mine = _Options()
    ctypes.memmove(ctypes.addressof(mine), ctypes.addressof(opts), ctypes.sizeof(_Options))
    mine.seekChunkReset = 1  # the game needs it
    mine.seekChunkLen = 0x40000
    size = lib.OodleLZ_GetCompressedBufferSizeNeeded(len(body))
    out = ctypes.create_string_buffer(size)
    got = lib.OodleLZ_Compress(KRAKEN, body, len(body), out, level, ctypes.byref(mine), None, None, None, 0)
    if got <= 0:
        raise FormatError("Oodle could not compress the file")
    return out.raw[:got]
