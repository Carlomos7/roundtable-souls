"""Readers for the checks: the launcher's own, and independent ones when installed.

Soulstruct (GPL-3.0; not a dependency of the launcher) has its own DCX, BND4 and FMG readers. Run a check with it:

    uv run --with soulstruct python scripts/verify/verify_output.py ...

Soulstruct decompresses Oodle with Oodle too (its own copy of the DLL), so it is an independent archive and text
reader, not an independent decompressor. pyooz, when installed, is a separate Oodle decoder; it has failed on files
that work in game, so calibrate.py runs it on the game's own files before its results are used.
"""

from __future__ import annotations

import struct
from collections.abc import Callable

Parts = dict[str, tuple[int, int, bytes]]  # inner path (lower case, /) -> (ID, flags, contents)


class CannotRead(Exception):
    """This reader cannot open the file (reported apart from validation failures)."""


def soulstruct_version() -> str | None:
    try:
        from importlib.metadata import version

        return version("soulstruct")
    except Exception:
        return None


def _key(path: str) -> str:
    return path.replace("\\", "/").lower()


def ours(dec) -> Callable[[bytes], Parts]:
    from roundtable_souls.mods import formats

    def read(raw: bytes) -> Parts:
        try:
            b = formats.read_bnd4(formats.unpack(raw, dec)[0])
        except Exception as e:  # noqa: BLE001
            raise CannotRead(f"{type(e).__name__}: {e}") from e
        return {_key(e.name or f"#{e.id}"): (e.id, e.flags, bytes(e.data)) for e in b.entries}

    return read


def soulstruct() -> Callable[[bytes], Parts] | None:
    try:
        from soulstruct.containers import Binder  # pyright: ignore[reportMissingImports]
    except Exception:
        return None

    def read(raw: bytes) -> Parts:
        try:
            b = Binder.from_bytes(raw)
        except Exception as e:  # noqa: BLE001
            raise CannotRead(f"{type(e).__name__}: {str(e)[:160]}") from e
        out: Parts = {}
        for e in b.entries:
            key = _key(e.path or e.name)
            if key in out:
                raise CannotRead(f"two inner files share the path {key}")
            out[key] = (e.entry_id, int(e.flags), bytes(e.data))
        return out

    return read


def fmg_ours(data: bytes) -> dict[int, str]:
    from roundtable_souls.mods import formats

    return {k: v for k, v in formats.read_fmg(data).entries.items() if v}


def fmg_soulstruct() -> Callable[[bytes], dict[int, str]] | None:
    try:
        from soulstruct.base.text.fmg import FMG  # pyright: ignore[reportMissingImports]
    except Exception:
        return None

    def read(data: bytes) -> dict[int, str]:
        try:
            return {k: v for k, v in dict(FMG.from_bytes(data).entries).items() if v}
        except Exception as e:  # noqa: BLE001
            raise CannotRead(f"{type(e).__name__}: {str(e)[:160]}") from e

    return read


def pyooz() -> Callable[[bytes], bytes] | None:
    """Decompress a KRAK DCX file with pyooz, or None when it is not installed."""
    try:
        import ooz  # pyright: ignore[reportMissingImports]
    except Exception:
        return None

    def read(raw: bytes) -> bytes:
        if raw[:4] != b"DCX\0" or raw[0x28:0x2C] != b"KRAK":
            raise CannotRead("not an Oodle (KRAK) DCX file")
        usize, csize = struct.unpack_from(">II", raw, 0x1C)
        try:
            return bytes(ooz.decompress(raw[0x4C : 0x4C + csize], usize))
        except Exception as e:  # noqa: BLE001
            raise CannotRead(f"{type(e).__name__}: {e}") from e

    return read
