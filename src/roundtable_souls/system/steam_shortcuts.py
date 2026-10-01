"""Steam's non-Steam game shortcuts (userdata/<account>/config/shortcuts.vdf): find the ones that start this launcher
and point them at where it is now.

shortcuts.vdf is binary VDF: a tree of named nodes, each a map (type 0, closed by 8), a string (1, NUL-terminated
UTF-8) or a 32-bit int (2); 7 is a 64-bit int. Files are read and written back node for node, so anything not
touched stays byte-identical (round trip checked in tests). Steam keeps its own copy in memory and writes it on exit,
so a file is only changed while Steam is closed; a backup of each changed file is kept first.
"""

from __future__ import annotations

import os
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath

MAP, STRING, INT32, UINT64, END = 0, 1, 2, 7, 8


@dataclass
class Node:
    kind: int
    name: str
    value: object = None  # str, int, or list[Node] for a map
    children: list[Node] = field(default_factory=list)

    def get(self, name: str) -> Node | None:
        low = name.lower()
        return next((c for c in self.children if c.name.lower() == low), None)


class VdfError(ValueError):
    pass


def _cstring(data: bytes, pos: int) -> tuple[str, int]:
    end = data.find(b"\x00", pos)
    if end < 0:
        raise VdfError("unterminated string")
    return data[pos:end].decode("utf-8", "surrogateescape"), end + 1


def _parse_map(data: bytes, pos: int) -> tuple[list[Node], int]:
    out: list[Node] = []
    while True:
        if pos >= len(data):
            raise VdfError("unexpected end of file")
        kind = data[pos]
        pos += 1
        if kind == END:
            return out, pos
        name, pos = _cstring(data, pos)
        if kind == MAP:
            children, pos = _parse_map(data, pos)
            out.append(Node(MAP, name, children=children))
        elif kind == STRING:
            value, pos = _cstring(data, pos)
            out.append(Node(STRING, name, value))
        elif kind == INT32:
            out.append(Node(INT32, name, struct.unpack_from("<i", data, pos)[0]))
            pos += 4
        elif kind == UINT64:
            out.append(Node(UINT64, name, struct.unpack_from("<Q", data, pos)[0]))
            pos += 8
        else:
            raise VdfError(f"unknown node type {kind} at {pos - 1}")


def parse(data: bytes) -> list[Node]:
    """The top-level nodes of a binary VDF file (the file ends with the root's END byte)."""
    nodes, pos = _parse_map(data, 0)
    if pos != len(data):
        raise VdfError("trailing bytes after the root")
    return nodes


def _dump_map(nodes: list[Node], out: bytearray) -> None:
    for n in nodes:
        out.append(n.kind)
        out += n.name.encode("utf-8", "surrogateescape") + b"\x00"
        if n.kind == MAP:
            _dump_map(n.children, out)
        elif n.kind == STRING:
            out += str(n.value).encode("utf-8", "surrogateescape") + b"\x00"
        elif n.kind == INT32:
            out += struct.pack("<i", int(n.value))  # type: ignore[arg-type]
        elif n.kind == UINT64:
            out += struct.pack("<Q", int(n.value))  # type: ignore[arg-type]
    out.append(END)


def dump(nodes: list[Node]) -> bytes:
    out = bytearray()
    _dump_map(nodes, out)
    return bytes(out)


@dataclass
class Shortcut:
    file: Path
    index: str
    name: str
    exe: str  # as Steam stores it, usually in quotes
    start_dir: str
    options: str

    @property
    def exe_path(self) -> str:
        return self.exe.strip().strip('"')


def files(steam_root: Path | None) -> list[Path]:
    if steam_root is None:
        return []
    return sorted((Path(steam_root) / "userdata").glob("*/config/shortcuts.vdf"))


def _entries(nodes: list[Node]) -> list[Node]:
    root = next((n for n in nodes if n.kind == MAP and n.name.lower() == "shortcuts"), None)
    return [c for c in root.children if c.kind == MAP] if root else []


def _text(entry: Node, name: str) -> str:
    n = entry.get(name)
    return str(n.value) if n is not None and n.kind == STRING else ""


def read(path: Path) -> list[Shortcut]:
    nodes = parse(path.read_bytes())
    return [
        Shortcut(path, e.name, _text(e, "AppName") or _text(e, "appname"), _text(e, "Exe") or _text(e, "exe"),
                 _text(e, "StartDir"), _text(e, "LaunchOptions"))
        for e in _entries(nodes)
    ]  # fmt: skip


def _same_path(a: str, b: str) -> bool:
    na, nb = os.path.normpath(a.strip().strip('"')), os.path.normpath(b.strip().strip('"'))
    return na.lower() == nb.lower() if os.name == "nt" else na == nb


def is_launcher(exe: str, exe_names: tuple[str, ...]) -> bool:
    """Whether a shortcut's program is a Roundtable Souls program: one of exe_names, or a Roundtable Souls AppImage."""
    path = exe.strip().strip('"')
    name = (PureWindowsPath(path) if "\\" in path else PurePosixPath(path)).name.lower()  # either system's paths
    if name in {n.lower() for n in exe_names}:
        return True
    return name.endswith(".appimage") and "roundtable" in name


def launcher_shortcuts(steam_root: Path | None, exe_names: tuple[str, ...]) -> list[Shortcut]:
    """Shortcuts that start a Roundtable Souls program, whatever folder it was in."""
    found = []
    for f in files(steam_root):
        try:
            found += [s for s in read(f) if is_launcher(s.exe, exe_names)]
        except OSError, VdfError:
            continue
    return found


def retarget(
    steam_root: Path | None,
    matches,
    new_exe: Path,
    backup_dir: Path,
    steam_running: bool,
    now=time.time,
) -> list[Shortcut]:
    """Point every shortcut for which matches(shortcut) is true at new_exe (and its folder). Refuses while Steam runs
    (it would write its own copy back on exit). Returns the shortcuts changed, as they were before."""
    if steam_running:
        raise RuntimeError("Steam is running; close it first so it does not write its old shortcuts back.")
    changed: list[Shortcut] = []
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now()))
    for f in files(steam_root):
        try:
            data = f.read_bytes()
            nodes = parse(data)
        except OSError, VdfError:
            continue
        before = {s.index: s for s in read(f)}
        touched = False
        for entry in _entries(nodes):
            s = before.get(entry.name)
            if s is None or not matches(s) or _same_path(s.exe, str(new_exe)):
                continue
            for name, value in (("Exe", f'"{new_exe}"'), ("StartDir", f'"{new_exe.parent}"')):
                node = entry.get(name)
                if node is not None and node.kind == STRING:
                    node.value = value
            changed.append(s)
            touched = True
        if touched:
            backup_dir.mkdir(parents=True, exist_ok=True)
            (backup_dir / f"{stamp}-{f.parent.parent.name}-shortcuts.vdf").write_bytes(data)
            tmp = f.with_name(f.name + ".roundtable.tmp")
            tmp.write_bytes(dump(nodes))
            tmp.replace(f)
    return changed
