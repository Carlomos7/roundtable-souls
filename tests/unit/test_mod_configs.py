"""A DLL mod's own settings files: which files count, ties, and writing them back exactly as they were stored."""

import pytest

from roundtable_souls.mods import configs as C


def _files(folder, *names):
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        (folder / n).write_bytes(b"x = 1\n")
    return folder


def test_a_mods_own_folder_offers_its_settings_but_never_readmes_logs_or_backups(tmp_path):
    d = _files(
        tmp_path / "UnlockTheFps",
        "UnlockTheFps.dll",
        "UnlockTheFps.ini",
        "UnlockTheFps.zh-CN.ini",  # a translation of the same file
        "config.json",
        "README.txt",
        "LICENSE.md",
        "THIRD_PARTY_NOTICES.md",
        "UnlockTheFps.ini.bak",
        "UnlockTheFps.ini.20260921",
        "mod.log",
    )
    assert [p.name for p in C.found(d / "UnlockTheFps.dll")] == ["UnlockTheFps.ini", "config.json"]


def test_in_a_shared_folder_only_files_named_after_the_dll_count(tmp_path):
    d = _files(tmp_path / "natives", "a.dll", "b.dll", "a.ini", "a_extra.txt", "b.ini", "skeleton_mods.txt")
    assert [p.name for p in C.found(d / "a.dll")] == ["a.ini", "a_extra.txt"]
    assert [p.name for p in C.found(d / "b.dll")] == ["b.ini"]


def test_ties_are_remembered_by_dll_and_the_coop_ini_is_left_to_its_page(tmp_path):
    d = _files(tmp_path / "natives", "SkeletonMan.dll", "other.dll", "skeleton_mods.txt")
    dll, txt = d / "SkeletonMan.dll", d / "skeleton_mods.txt"
    settings = {}
    assert C.files_for(settings, dll) == []
    settings["native_configs"] = C.with_tie(settings, dll, txt)
    settings["native_configs"] = C.with_tie(settings, dll, txt)  # tying twice keeps one
    rows = C.files_for(settings, dll)
    assert [(r["path"].name, r["how"], r["exists"]) for r in rows] == [("skeleton_mods.txt", "tied", True)]
    assert C.files_for(settings, dll, skip={C.key_for(txt)}) == []
    settings["native_configs"] = C.without_tie(settings, dll, txt)
    assert settings["native_configs"] == {} and C.files_for(settings, dll) == []


@pytest.mark.parametrize(
    "raw, encoding",
    [
        (b"a = 1\r\nb = \xe9\r\n", "cp1252"),  # an old mod's ini in the Windows code page, CRLF
        ("a = 1\nname = Émile\n".encode("utf-16"), "utf-16"),
        (b"\xef\xbb\xbfa = 1\n", "utf-8-sig"),
        (b"a = 1\n", "utf-8"),
    ],
)
def test_settings_are_written_back_in_their_own_encoding_and_line_endings(tmp_path, raw, encoding):
    p = tmp_path / "mod.ini"
    p.write_bytes(raw)
    got = C.read(p)
    assert got["encoding"] == encoding and "\r" not in got["text"]
    C.write(p, got["text"], got["encoding"], got["crlf"])
    assert p.read_bytes() == raw  # untouched text round-trips byte for byte
    C.write(p, got["text"].replace("a = 1", "a = 2"), got["encoding"], got["crlf"])
    assert C.read(p)["text"].startswith("a = 2") and (tmp_path / "mod.ini.bak").read_bytes() == raw


def test_binary_and_huge_files_are_not_settings(tmp_path):
    (tmp_path / "x.ini").write_bytes(b"MZ\x00\x00binary")
    with pytest.raises(C.ConfigError):
        C.read(tmp_path / "x.ini")
    (tmp_path / "big.txt").write_bytes(b"a" * (C.MAX_BYTES + 1))
    with pytest.raises(C.ConfigError):
        C.read(tmp_path / "big.txt")
    p = tmp_path / "y.ini"
    p.write_bytes(b"a = \xe9\n")
    with pytest.raises(C.ConfigError):  # a character the file's code page cannot hold
        C.write(p, "a = 中\n", "cp1252", False)
    assert p.read_bytes() == b"a = \xe9\n"
