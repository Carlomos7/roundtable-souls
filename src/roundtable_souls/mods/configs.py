"""A DLL mod's own settings files (UnlockTheFps.ini, SkeletonMan's skeleton_mods.txt, ...), found beside it or tied
to it by the user, and read / written without changing their encoding or line endings.

Found: text files of a config kind in the DLL's folder. When the folder holds other DLLs too (the top of natives/,
where one file per mod is the usual layout), only files named after the DLL count, so a neighbour's settings are
never claimed. Readmes, licences, logs and backups are never settings.

Tied: any other file the user points at, remembered in the launcher's settings (native_configs) under the DLL's
path, so the tie holds across profiles and never needs a key me3 does not know in the .me3 itself.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

CONFIG_SUFFIXES = {".ini", ".txt", ".toml", ".json", ".cfg", ".conf", ".yaml", ".yml", ".xml"}
NOT_SETTINGS = re.compile(
    r"^(readme|read_me|license|licence|copying|notice|third[_-]?party|changelog|changes|credits|install|"
    r"instructions|faq|version)([ ._-].*)?$",
    re.I,
)
MAX_BYTES = 2 * 1024 * 1024  # a settings file, not data
LANG = {".ini": "ini", ".cfg": "ini", ".conf": "ini", ".toml": "toml", ".json": "json"}


class ConfigError(Exception):
    pass


def key_for(dll: Path) -> str:
    """How a DLL is remembered in the settings: its full path, compared without case on Windows."""
    return os.path.normcase(os.path.abspath(str(dll)))


def looks_like_settings(p: Path) -> bool:
    name = p.name.lower()
    return (
        p.is_file()
        and p.suffix.lower() in CONFIG_SUFFIXES
        and not NOT_SETTINGS.match(p.stem)
        and not re.search(r"\.(bak|old|orig|tmp)(\.|$)|\d{8}", name)  # dated / backup copies
    )


def found(dll: Path) -> list[Path]:
    """Settings files beside a DLL (see the module notes for which count)."""
    dll = Path(dll)
    folder = dll.parent
    if not folder.is_dir():
        return []
    try:
        kids = list(folder.iterdir())
    except OSError:
        return []
    shared = sum(1 for k in kids if k.suffix.lower() == ".dll") > 1
    stem = dll.stem.lower()
    out = [
        k
        for k in kids
        if looks_like_settings(k) and (not shared or k.stem.lower() == stem or k.stem.lower().startswith(stem + "_"))
    ]
    # a translated copy (UnlockTheFps.zh-CN.ini) is documentation when the plain file is there too
    plain = {(k.stem.lower(), k.suffix.lower()) for k in out}
    out = [
        k
        for k in out
        if not (
            (m := re.match(r"^(.*)\.[a-z]{2}(-[a-z]{2,4})?$", k.stem, re.I))
            and (m.group(1).lower(), k.suffix.lower()) in plain
        )
    ]
    return sorted(out, key=lambda k: (k.stem.lower() != stem, k.name.lower()))


def tied(settings: dict, dll: Path) -> list[Path]:
    return [Path(p) for p in (settings.get("native_configs") or {}).get(key_for(dll), [])]


def files_for(settings: dict, dll: Path, skip: set[str] = frozenset()) -> list[dict]:
    """Everything to offer for a DLL: {path, how ('found' / 'tied'), exists}. skip: paths another page owns (the
    Seamless Co-op ini is edited on the Co-op page)."""
    seen, out = set(), []
    for how, paths in (("tied", tied(settings, dll)), ("found", found(dll))):
        for p in paths:
            k = key_for(p)
            if k in seen or k in skip:
                continue
            seen.add(k)
            out.append({"path": p, "how": how, "exists": p.is_file()})
    return out


def with_tie(settings: dict, dll: Path, file: Path) -> dict:
    """The native_configs value with file tied to dll (returned for save_settings)."""
    ties = {k: list(v) for k, v in (settings.get("native_configs") or {}).items()}
    lst = ties.setdefault(key_for(dll), [])
    if str(Path(file)) not in lst and key_for(file) not in {key_for(Path(x)) for x in lst}:
        lst.append(str(Path(file)))
    return ties


def without_tie(settings: dict, dll: Path, file: Path) -> dict:
    ties = {k: list(v) for k, v in (settings.get("native_configs") or {}).items()}
    k = key_for(dll)
    ties[k] = [x for x in ties.get(k, []) if key_for(Path(x)) != key_for(file)]
    if not ties[k]:
        ties.pop(k)
    return ties


def lang_for(p: Path) -> str:
    return LANG.get(Path(p).suffix.lower(), "text")


# ----------------------------------------------------------------------------- reading and writing
def read(p: Path) -> dict:
    """{text, encoding, crlf} with the text's line breaks as \\n. Refuses binary files and anything over 2 MB."""
    p = Path(p)
    raw = p.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ConfigError(f"{p.name} is {len(raw) // 1024} KB: too big for a settings file.")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    elif raw.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    elif b"\0" in raw[:4096]:
        raise ConfigError(f"{p.name} is not a text file.")
    else:
        try:
            raw.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            encoding = "cp1252"  # older mods write their ini in the Windows code page
    text = raw.decode(encoding, errors="replace")
    return {"text": text.replace("\r\n", "\n").replace("\r", "\n"), "encoding": encoding, "crlf": b"\r\n" in raw}


def write(p: Path, text: str, encoding: str, crlf: bool) -> Path:
    """Write text back the way the file was stored (encoding, line endings), keeping one .bak of the old version."""
    from roundtable_souls.platform.files import atomic_write

    p = Path(p)
    body = text.replace("\n", "\r\n") if crlf else text
    try:
        data = body.encode(encoding)
    except UnicodeEncodeError as e:
        raise ConfigError(
            f"A character cannot be stored in {p.name}'s encoding ({encoding}): {e.object[e.start]!r}"
        ) from e
    atomic_write(p, data, backup=True)
    return p.with_name(p.name + ".bak")
