"""Steam's shortcuts.vdf: read and written back byte for byte, and shortcuts that start an old copy of the launcher
pointed at the new one (only while Steam is closed, with a backup)."""

import struct
from pathlib import Path

import pytest

from roundtable_souls.system import steam_shortcuts as vdf


def _s(name, value):
    return b"\x01" + name.encode() + b"\x00" + value.encode() + b"\x00"


def _i(name, value):
    return b"\x02" + name.encode() + b"\x00" + struct.pack("<i", value)


def _entry(index, name, exe, opts):
    return (
        b"\x00" + index.encode() + b"\x00"
        + _i("appid", -123456789)
        + _s("AppName", name)
        + _s("Exe", f'"{exe}"')
        + _s("StartDir", f'"{Path(exe).parent}"')
        + _s("icon", "")
        + _s("LaunchOptions", opts)
        + _i("IsHidden", 0)
        + b"\x07LastPlayTime\x00" + struct.pack("<Q", 1700000000)
        + b"\x00tags\x00" + _s("0", "Favorites") + b"\x08"
        + b"\x08"
    )  # fmt: skip


OLD = r"C:\Users\me\AppData\Local\Programs\Roundtable Souls\RoundtableSouls.exe"


def _file(tmp_path: Path, account="12345") -> Path:
    raw = (
        b"\x00shortcuts\x00"
        + _entry("0", "Elden Ring (Roundtable)", OLD, "--game er --play")
        + _entry("1", "Nightreign (Roundtable)", OLD, "--game nr --play")
        + _entry("2", "Some other game", r"C:\Games\other.exe", "")
        + b"\x08\x08"
    )
    f = tmp_path / "Steam" / "userdata" / account / "config" / "shortcuts.vdf"
    f.parent.mkdir(parents=True)
    f.write_bytes(raw)
    return f


def test_files_round_trip_byte_for_byte(tmp_path):
    f = _file(tmp_path)
    raw = f.read_bytes()
    assert vdf.dump(vdf.parse(raw)) == raw
    shortcuts = vdf.read(f)
    assert [s.name for s in shortcuts] == ["Elden Ring (Roundtable)", "Nightreign (Roundtable)", "Some other game"]
    assert shortcuts[0].exe_path == OLD and shortcuts[0].options == "--game er --play"
    with pytest.raises(vdf.VdfError):
        vdf.parse(raw[:-3])


def test_retarget_points_matching_shortcuts_at_the_new_copy(tmp_path):
    f = _file(tmp_path)
    before = f.read_bytes()
    new = tmp_path / "Carlomos7.RoundtableSouls" / "Roundtable Souls.exe"
    backups = tmp_path / "backups"
    with pytest.raises(RuntimeError, match="Steam is running"):
        vdf.retarget(tmp_path / "Steam", lambda s: True, new, backups, steam_running=True)
    assert f.read_bytes() == before
    changed = vdf.retarget(tmp_path / "Steam", lambda s: vdf._same_path(s.exe, OLD), new, backups, steam_running=False)
    assert [s.name for s in changed] == ["Elden Ring (Roundtable)", "Nightreign (Roundtable)"]
    after = vdf.read(f)
    assert all(s.exe == f'"{new}"' and s.start_dir == f'"{new.parent}"' for s in after[:2])
    assert after[2].exe_path == r"C:\Games\other.exe"  # untouched
    assert [s.options for s in after] == ["--game er --play", "--game nr --play", ""]
    (backup,) = list(backups.iterdir())
    assert backup.read_bytes() == before and "12345" in backup.name
    # everything but the two paths is unchanged: same nodes, same order, same ints (appid keeps Steam's artwork)
    nodes_before, nodes_after = vdf.parse(before), vdf.parse(f.read_bytes())
    flat = lambda ns: [(n.kind, n.name, n.value) for n in ns for _ in [0]]  # noqa: E731
    assert [(c.name, c.kind) for c in nodes_before[0].children] == [(c.name, c.kind) for c in nodes_after[0].children]
    assert nodes_after[0].children[0].get("appid").value == -123456789
    assert flat(nodes_after[0].children[2].children) == flat(nodes_before[0].children[2].children)
    # a second run changes nothing
    assert vdf.retarget(tmp_path / "Steam", lambda s: vdf._same_path(s.exe, OLD), new, backups, False) == []


def test_launcher_shortcuts_are_found_by_program_name(tmp_path):
    _file(tmp_path)
    found = vdf.launcher_shortcuts(tmp_path / "Steam", ("RoundtableSouls.exe", "RoundtableSouls"))
    assert len(found) == 2
    assert vdf.is_launcher("/home/deck/Apps/RoundtableSouls-linux-x86_64.AppImage", ())
    assert not vdf.is_launcher(r"C:\Games\other.exe", ("RoundtableSouls.exe",))
