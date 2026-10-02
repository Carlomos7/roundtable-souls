"""Profile settings, load order, the conflict scan, and me3 facts."""

import pytest

from roundtable_souls.services import play as g

P = g.profile_tools
M = g.me3_info

PROFILE = (
    '# my profile\r\nprofileVersion = "v1"\r\n\r\n# start_online = true\r\n\r\n[[packages]]\r\nid = "a"\r\npath = \'mods/a\'\r\n\r\n'
    '[[packages]]\r\nid = "b"\r\npath = \'mods/b\'\r\nload_after = [{ id = "c", optional = true }]\r\n\r\n'
    "[[packages]]\r\nid = \"c\"\r\npath = 'mods/c'\r\n\r\n[[packages]]\r\nid = \"off\"\r\npath = 'mods/off'\r\nenabled = false\r\n\r\n"
    "[[natives]]\r\npath = 'natives/x.dll'\r\n"
)


def test_settings_roundtrip_keeps_comments_and_crlf():
    assert P.read_settings(PROFILE) == {}
    t = P.set_setting(PROFILE, "start_online", True)
    assert P.read_settings(t) == {"start_online": True}
    assert (
        t.splitlines()[2] == "start_online = true" and "\r\n" in t and "# start_online = true" in t
    )  # commented line untouched
    t = P.set_setting(t, "mem_patch_heap_size", 8192)
    t = P.set_setting(t, "savefile", 'Modded "one".sl2')
    t = P.set_setting(t, "disable_arxan", False)
    s = P.read_settings(t)
    assert s["mem_patch_heap_size"] == 8192 and s["savefile"] == 'Modded "one".sl2' and s["disable_arxan"] is False
    t = P.set_setting(t, "start_online", None)
    t = P.set_setting(t, "mem_patch_heap_size", 0)
    assert "start_online" not in P.read_settings(t) and "mem_patch_heap_size" not in P.read_settings(t)
    assert t.count("[[packages]]") == 4 and t.startswith("# my profile")
    # the array form Revive writes: settings go before packages = [...]
    arr = 'profileVersion = "v1"\nnatives = [{ path = "x.dll" }]\npackages = [{ id = "p", path = "mod" }]\n'
    t = P.set_setting(arr, "mem_patch", True)
    assert t.splitlines()[1] == "mem_patch = true" and P.read_settings(t) == {"mem_patch": True}
    with pytest.raises(KeyError):
        P.set_setting(arr, "nope", 1)
    # edge cases: no final newline, no profileVersion, duplicated key, empty file, savefile must be a name
    import tomllib

    t = P.set_setting('profileVersion = "v1"', "mem_patch", False)
    assert t == 'profileVersion = "v1"\nmem_patch = false\n' and tomllib.loads(t)["mem_patch"] is False
    t = P.set_setting("[[packages]]\npath = 'a'", "start_online", True)
    assert t.startswith("start_online = true\n[[packages]]") and tomllib.loads(t)["start_online"] is True
    t = P.set_setting('profileVersion = "v1"\nsavefile = "a"\nsavefile = "b"\n', "savefile", "c")
    assert tomllib.loads(t)["savefile"] == "c" and t.count("savefile") == 1
    t = P.set_setting('profileVersion = "v1"\nsavefile = "a"\nsavefile = "b"\n', "savefile", None)
    assert "savefile" not in t
    assert tomllib.loads(P.set_setting("", "savefile", "x.sl2"))["savefile"] == "x.sl2"
    for bad in ("C:\\saves\\x.sl2", "sub/x.sl2"):
        with pytest.raises(ValueError):
            P.set_setting(arr, "savefile", bad)
    loop = "[[packages]]\nid = 'a'\npath = 'a'\nload_after = [{ id = 'b', optional = false }]\n\n"
    loop += "[[packages]]\nid = 'b'\npath = 'b'\nload_after = [{ id = 'a', optional = false }]\n"
    looped = P.me3_order(None, loop)
    assert [r["id"] for r in looped.rows] == ["a", "b"] and "cycles" in looped.problem  # me3 would not start
    assert P.read_settings("this is = = not toml") == {} and P.package_rows("[[[") == []


def _profile(*blocks: str) -> str:
    return "\n".join(f"[[packages]]\n{b}\n" for b in blocks)


def test_me3_order_follows_load_after_and_before():
    assert [r["id"] for r in P.package_rows(PROFILE)] == ["a", "b", "c"]  # switched off: left out
    assert [r["id"] for r in P.package_rows(PROFILE, include_disabled=True)] == ["a", "b", "c", "off"]
    assert [r["id"] for r in P.me3_order(None, PROFILE).rows] == ["a", "c", "b"]
    x_first = _profile("id = 'x'\npath = 'x'\nload_before = [{ id = 'a', optional = false }]", "id = 'a'\npath = 'a'")
    assert [r["id"] for r in P.me3_order(None, x_first).rows] == ["x", "a"]
    x_last = _profile("id = 'a'\npath = 'a'", "id = 'x'\npath = 'x'\nload_before = [{ id = 'a', optional = false }]")
    assert [r["id"] for r in P.me3_order(None, x_last).rows] == ["x", "a"]


def test_me3_moves_a_dependency_run_where_the_old_launcher_order_did_not():
    # The case that showed the old order wrong: D loads after A. me3 loads D right after A (A D B C); the launcher
    # used to leave it last (A B C D), so a file D and B or C both ship had the wrong winner.
    text = _profile(
        "id = 'A'\npath = 'A'",
        "id = 'B'\npath = 'B'",
        "id = 'C'\npath = 'C'",
        "id = 'D'\npath = 'D'\nload_after = [{ id = 'A', optional = false }]",
    )
    assert [r["id"] for r in P.me3_order(None, text).rows] == ["A", "D", "B", "C"]


def test_me3_orders_switched_off_packages_and_drops_missing_folders(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "c").mkdir()
    prof = tmp_path / "p.me3"
    text = _profile(
        "id = 'a'\npath = 'a'",
        "id = 'gone'\npath = 'nowhere'",  # no folder: me3 leaves it out before ordering
        "id = 'c'\npath = 'c'\nload_after = [{ id = 'gone', optional = true }]",
        "id = 'off'\npath = 'a'\nenabled = false",
    )
    ordered = P.me3_order(prof, text)
    assert [r["id"] for r in ordered.rows] == ["a", "c"] and [r["id"] for r in ordered.dropped] == ["gone"]
    required = text.replace("optional = true", "optional = false")
    refused = P.me3_order(prof, required)
    assert refused.problem == "Required dependency is unavailable: gone"  # me3 would not start


def test_what_a_load_after_list_names_loads_in_the_lists_order():
    # me3 links the listed ids in the list's order and takes the first one ready: the list, not the file, decides
    # the order of what it names (and so which of them wins a file they both ship).
    text = _profile(
        "id = 'a'\npath = 'a'",
        "id = 'b'\npath = 'b'",
        "id = 'last'\npath = 'last'\nload_after = [{ id = 'b', optional = true }, { id = 'a', optional = true }]",
    )
    assert [r["id"] for r in P.me3_order(None, text).rows] == ["b", "a", "last"]


def test_a_dependency_without_optional_counts_as_required():
    text = _profile("id = 'a'\npath = 'a'\nload_after = ['b']")
    assert P.me3_order(None, text).problem == "Required dependency is unavailable: b"


def test_conflict_scan_finds_shared_paths_and_winner(tmp_path):
    prof = tmp_path / "p.me3"
    prof.write_text(PROFILE, encoding="utf-8")
    for pkg, files in (
        ("a", ["parts/am_m_1000.partsbnd.dcx", "regulation.bin", "only_a.txt", "me3.toml"]),
        ("b", ["parts/AM_M_1000.partsbnd.dcx", "chr/c0000.chrbnd.dcx", "junk.bak"]),
        ("c", ["chr/c0000.chrbnd.dcx", "regulation.bin"]),
    ):
        for f in files:
            p = tmp_path / "mods" / pkg / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x" * (len(pkg) + len(f)))
    r = P.scan_conflicts(prof)
    assert [p["id"] for p in r["packages"]] == ["a", "c", "b"] and not any(p["missing"] for p in r["packages"])
    paths = {c["path"].lower(): c for c in r["conflicts"]}
    assert set(paths) == {"parts/am_m_1000.partsbnd.dcx", "regulation.bin", "chr/c0000.chrbnd.dcx"}
    assert paths["parts/am_m_1000.partsbnd.dcx"]["winner"] == "b"  # b loads last: it wins, case-insensitively
    assert paths["regulation.bin"]["winner"] == "c" and [l["id"] for l in paths["regulation.bin"]["losers"]] == ["a"]
    assert paths["chr/c0000.chrbnd.dcx"]["winner"] == "b" and paths["chr/c0000.chrbnd.dcx"]["category"] == "chr"
    assert (
        r["by_category"] == {"parts": 1, "regulation.bin": 1, "chr": 1} and r["files"] == 6 and not r["truncated"]
    )  # only_a.txt at the root is not a game path
    by = {p["id"]: p for p in r["packages"]}
    assert by["b"]["wins"] == 2 and by["a"]["loses"] == 2 and by["c"]["wins"] == 1 and by["c"]["loses"] == 1
    assert P.category_of("regulation.bin") == "regulation.bin" and P.category_of("readme.txt") == "other"
    (tmp_path / "mods" / "c").rename(tmp_path / "mods" / "gone")
    r2 = P.scan_conflicts(prof)
    assert next(p for p in r2["packages"] if p["id"] == "c")["missing"]


def test_me3_facts_parse_without_a_binary():
    assert (
        M.parse_version("me3 0.13.0") == "0.13.0"
        and M.parse_version("\x1b[32mv0.14.1\x1b[0m") == "0.14.1"
        and M.parse_version("junk") is None
    )
    info = M.parse_info(
        "Configuration\n  Boot boost: true\n  Profile directory: C:\\p\n  Logs directory: C:\\l\nInstallation\n  Status: Found\n  Installation prefix: C:\\me3\nSteam\n  Status: Found\n  Path: C:\\Steam\n"
    )
    assert (
        info["profile_dir"] == "C:\\p"
        and info["logs_dir"] == "C:\\l"
        and info["install_prefix"] == "C:\\me3"
        and info["steam_status"] == "Found"
        and info["steam_path"] == "C:\\Steam"
        and info["install_status"] == "Found"
    )
    assert (
        M.update_available("0.13.0", "0.14.0")
        and not M.update_available("0.13.0", "0.13.0")
        and not M.update_available(None, "1.0.0")
    )
    assert M.me3_version(None) is None and M.me3_info("C:/nope/me3.exe") == {}
    assert g.launch_extra_args({"play_boot_boost": True, "play_show_logos": False, "play_diagnostics": False}) == []
    assert g.launch_extra_args({"play_boot_boost": False, "play_show_logos": True, "play_diagnostics": True}) == [
        "--no-boot-boost",
        "--show-logos",
        "--diagnostics",
    ]
    assert g.launch_extra_args({"play_diagnostics": True}, "0.12.4") == []  # older me3 does not know the flag
    assert g.launch_extra_args({"play_diagnostics": True}, "0.13.0") == ["--diagnostics"]
    assert g.launch_extra_args({"play_diagnostics": True}, None) == ["--diagnostics"]
    assert M.parse_version("me3 0.14.0-rc.1") == "0.14.0" and M.parse_info("") == {}
    assert g.play_options({})["play_boot_boost"] is True and g.play_options({})["play_show_logos"] is False
