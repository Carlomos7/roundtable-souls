"""The game's own copy of any file, read from its archives (Data0-3.bdt and DLC.bdt beside the game's exe).

Each archive has an index (.bhd) encrypted with an RSA key whose public half is known (data/archives/*.json); it
lists every file by a 64-bit hash of its lower-case path, where it sits in the .bdt, and the AES key of the ranges of
it that are encrypted. The indexes are decrypted once and kept in the launcher's data folder (keyed by the archive's
size and date, so a game update decrypts them again); after that a file is one read and a few AES blocks.

Nothing here writes to the game folder. Elden Ring only (the files the merger compares mods with).
"""

from __future__ import annotations

import os
import struct
import threading
from pathlib import Path

from roundtable_souls.game import config as game_config

ARCHIVES = tuple(game_config.load().archive_names)
ENTRY = struct.Struct("<QiiqQQ")  # path hash, padded size, unpadded size, offset, SHA offset, AES key offset
_lock = threading.Lock()
_indexes: dict[str, tuple[tuple, dict[int, tuple], bytes]] = {}  # archive -> (fingerprint, entries, index bytes)


class ArchiveError(RuntimeError):
    pass


def path_hash(rel: str) -> int:
    """The 64-bit hash the archives list a file by: its path, lower-case, with / and a leading /."""
    s = rel.strip().replace("\\", "/").lower()
    if not s.startswith("/"):
        s = "/" + s
    h = 0
    for ch in s:
        h = (h * 0x85 + ord(ch)) & 0xFFFFFFFFFFFFFFFF
    return h


def _keys() -> dict[str, str]:
    return dict(game_config.load().archives)


def _rsa_open(data: bytes, pem: str) -> bytes:
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    k = load_pem_public_key(pem.encode()).public_numbers()
    size = (k.n.bit_length() + 7) // 8
    out = bytearray()
    for i in range(0, len(data), size):
        out += pow(int.from_bytes(data[i : i + size], "big"), k.e, k.n).to_bytes(size - 1, "big")
    return bytes(out)


def _entries(index: bytes) -> dict[int, tuple]:
    if index[:4] != b"BHD5":
        raise ArchiveError("the archive index could not be decrypted (a different game version?)")
    count, at = struct.unpack_from("<ii", index, 0x10)
    out = {}
    for b in range(count):
        n, off = struct.unpack_from("<ii", index, at + b * 8)
        for i in range(n):
            e = ENTRY.unpack_from(index, off + i * ENTRY.size)
            out[e[0]] = e[1:]
    return out


def _cache_dir() -> Path:
    from roundtable_souls.saves import backups as folders

    return folders.data_root() / "cache" / "archives"


def _index(game_dir: Path, name: str) -> tuple[dict[int, tuple], bytes] | None:
    bhd = Path(game_dir) / f"{name}.bhd"
    try:
        st = bhd.stat()
    except OSError:
        return None
    fp = (str(bhd).lower(), st.st_size, st.st_mtime_ns)
    with _lock:
        hit = _indexes.get(name)
        if hit and hit[0] == fp:
            return hit[1], hit[2]
    cached = _cache_dir() / f"{name}-{st.st_size}-{st.st_mtime_ns}.bhd5"
    try:
        index = cached.read_bytes()
    except OSError:
        index = _rsa_open(bhd.read_bytes(), _keys()[name])
        try:
            cached.parent.mkdir(parents=True, exist_ok=True)
            for old in cached.parent.glob(f"{name}-*.bhd5"):
                old.unlink(missing_ok=True)  # an older game version's
            tmp = cached.with_suffix(".tmp")
            tmp.write_bytes(index)
            os.replace(tmp, cached)
        except OSError:
            pass
    entries = _entries(index)
    with _lock:
        _indexes[name] = (fp, entries, index)
    return entries, index


def available(game_dir: Path | None) -> bool:
    return bool(game_dir) and all((Path(game_dir) / f"{n}.bhd").is_file() for n in ARCHIVES[:1])


def read(game_dir: Path | None, rel: str) -> bytes | None:
    """The game's own bytes of a file (as stored: usually DCX-compressed), or None when the game has no such file."""
    if not game_dir:
        return None
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    h = path_hash(rel)
    for name in ARCHIVES:
        got = _index(Path(game_dir), name)
        if got is None:
            continue
        entries, index = got
        e = entries.get(h)
        if e is None:
            continue
        padded, unpadded, offset, _sha, aes_at = e
        with open(Path(game_dir) / f"{name}.bdt", "rb") as f:
            f.seek(offset)
            data = bytearray(f.read(padded))
        if aes_at:
            key = index[aes_at : aes_at + 16]
            (ranges,) = struct.unpack_from("<i", index, aes_at + 16)
            dec = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
            for j in range(ranges):
                s, t = struct.unpack_from("<qq", index, aes_at + 20 + j * 16)
                if s != -1 and t != -1 and s != t:
                    data[s:t] = dec.update(bytes(data[s:t]))
        if unpadded > 0:
            del data[unpadded:]
        elif data[:4] == b"DCX\0":  # sizes of compressed files are in their own header
            csize = struct.unpack_from(">I", data, 0x20)[0]
            del data[0x4C + csize :]
        return bytes(data)
    return None
