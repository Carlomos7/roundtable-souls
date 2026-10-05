"""Mod install / remove / options and profile create / delete, all on temp folders."""

import tomllib
import zipfile
from pathlib import Path

import pytest

from roundtable_souls.mods import checks, extract, install, remove
from roundtable_souls.services import play as g

M = g.mod_manage

PROFILE = (
    '# my profile\r\nprofileVersion = "v1"\r\n\r\n[[supports]]\r\ngame = "eldenring"\r\n\r\n'
    "[[packages]]\r\nid = \"flora\"\r\n# keep this\r\npath = 'mod/flora'\r\n\r\n"
    "[[natives]]\r\npath = 'natives/SeamlessCoop/ersc.dll'\r\nload_early = true\r\nload_after = [\r\n  { id = \"x\", optional = true },\r\n]\r\n\r\n"
    "[[natives]]\r\npath = 'natives/other/other.dll'\r\nenabled = false\r\n"
)


def _read(p):
    return Path(p).read_bytes().decode("utf-8")


def _profile(tmp_path, text=PROFILE):
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "my.me3"
    p.write_text(text, encoding="utf-8", newline="")
    (tmp_path / "mod" / "flora" / "parts").mkdir(parents=True)
    (tmp_path / "mod" / "flora" / "parts" / "a.partsbnd.dcx").write_bytes(b"a")
    (tmp_path / "natives" / "SeamlessCoop").mkdir(parents=True)
    (tmp_path / "natives" / "SeamlessCoop" / "ersc.dll").write_bytes(b"d")
    (tmp_path / "natives" / "SeamlessCoop" / "ersc_settings.ini").write_text("x")
    (tmp_path / "natives" / "other").mkdir()
    (tmp_path / "natives" / "other" / "other.dll").write_bytes(b"o")
    return p


def test_detection_rules(tmp_path):
    pk = tmp_path / "pk" / "Wrapper" / "MyMod"
    (pk / "parts").mkdir(parents=True)
    (pk / "readme.txt").write_text("r")
    d = install.detect(tmp_path / "pk")
    assert d["kind"] == "package" and d["root"] == pk and d["assets"] == ["parts"]
    nt = tmp_path / "nt"
    nt.mkdir()
    (nt / "cool.dll").write_bytes(b"x")
    (nt / "dinput8.dll").write_bytes(b"x")
    d = install.detect(nt)
    assert d["kind"] == "native" and [p.name for p in d["dlls"]] == ["cool.dll"]
    mixed = tmp_path / "mx"
    (mixed / "msg").mkdir(parents=True)
    (mixed / "tool.dll").write_bytes(b"x")
    assert install.detect_kind(mixed) == "package"  # assets win
    nested = tmp_path / "nd" / "SeamlessCoop"
    nested.mkdir(parents=True)
    (nested / "ersc.dll").write_bytes(b"x")
    assert install.detect_kind(tmp_path / "nd") == "native"  # DLL one level down
    reg = tmp_path / "reg"
    reg.mkdir()
    (reg / "regulation.bin").write_bytes(b"x")
    assert install.detect_kind(reg) == "package"
    me3 = tmp_path / "prof"
    me3.mkdir()
    (me3 / "x.me3").write_text('profileVersion = "v1"')
    assert install.detect_kind(me3) == "me3"
    empty = tmp_path / "e"
    empty.mkdir()
    assert install.detect_kind(empty) == "unknown"
    assert M.slug("My Mod!! v2.0 (final)") == "My-Mod-v2.0-final" and M.slug("   ") == "mod"
    assert M.slug("Hair 13 - Ranni's Hairstyle V1.1-561-1-1-1648994275") == "Hair-13-Ranni-s-Hairstyle-V1.1"
    assert M.slug("Dark Souls ReShaded 2.2-127-2-2-1736209179") == "Dark-Souls-ReShaded-2.2"


def test_loose_game_files_are_sorted_into_folders(tmp_path):
    src = tmp_path / "hair"
    src.mkdir()
    (src / "hr_a_0007.partsbnd.dcx").write_bytes(b"h")
    (src / "readme.txt").write_text("r")
    d = install.detect(src)
    assert (
        d["kind"] == "package"
        and d["assets"] == ["parts"]
        and [(f.name, s) for f, s in d["loose"]] == [("hr_a_0007.partsbnd.dcx", "parts")]
    )
    p = tmp_path / "prof" / "p.me3"
    p.parent.mkdir()
    p.write_text('profileVersion = "v1"\n', encoding="utf-8")
    out = install.install(p, install.plan_install(p, src, name="Ranni Hair"))
    assert (out["dest"] / "parts" / "hr_a_0007.partsbnd.dcx").read_bytes() == b"h" and (
        out["dest"] / "readme.txt"
    ).is_file()
    assert not (out["dest"] / "hr_a_0007.partsbnd.dcx").exists()
    mixed = tmp_path / "mixed"
    mixed.mkdir()
    (mixed / "c0000.anibnd.dcx").write_bytes(b"a")
    (mixed / "regulation.bin").write_bytes(b"r")
    (mixed / "menu_x.gfx").write_bytes(b"g")
    d = install.detect(mixed)
    assert d["kind"] == "package" and set(d["assets"]) == {"chr", "regulation.bin", "menu"}
    out = install.install(p, install.plan_install(p, mixed))
    assert (
        (out["dest"] / "chr" / "c0000.anibnd.dcx").is_file()
        and (out["dest"] / "regulation.bin").is_file()
        and (out["dest"] / "menu" / "menu_x.gfx").is_file()
    )
    save = tmp_path / "save"
    save.mkdir()
    (save / "ER0000.sl2").write_bytes(b"s")
    assert "No game folders" in install.plan_install(p, save)["error"]  # a save is not a mod
    junk = tmp_path / "junk2"
    junk.mkdir()
    (junk / "notes.txt").write_text("x")
    assert "No game folders" in install.plan_install(p, junk)["error"]
    rs = tmp_path / "reshade" / "Dark Souls ReShaded"
    rs.mkdir(parents=True)
    (rs / "dxgi.dll").write_bytes(b"x")
    assert install.plan_install(p, tmp_path / "reshade")["kind"] == "native"  # a DLL is a native


def test_zip_safety(tmp_path):
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("../evil.txt", "x")
    with pytest.raises(M.ModError):
        extract.extract_zip(z, tmp_path / "out")
    with pytest.raises(M.ModError):
        extract.stage(tmp_path / "x.txt", tmp_path)
    with pytest.raises(M.ModError):
        extract.extract_archive(tmp_path / "x.tar.gz", tmp_path / "o")
    assert extract.ARCHIVE_EXTENSIONS == (".zip", ".7z", ".rar")


def test_7z_install_and_safety(tmp_path):
    py7zr = pytest.importorskip("py7zr")
    src = tmp_path / "src" / "Wrap" / "Nice Mod"
    (src / "msg").mkdir(parents=True)
    (src / "msg" / "x.msgbnd.dcx").write_bytes(b"m")
    a = tmp_path / "Nice Mod.7z"
    with py7zr.SevenZipFile(a, "w") as z:
        z.writeall(tmp_path / "src" / "Wrap", "Wrap")
    p = tmp_path / "prof" / "p.me3"
    p.parent.mkdir()
    p.write_text('profileVersion = "v1"\n', encoding="utf-8")
    plan = install.plan_install(p, a)
    assert plan["kind"] == "package" and plan["name"] == "nice-mod" and plan["assets"] == ["msg"] and plan["staging"]
    out = install.install(p, plan)
    assert (out["dest"] / "msg" / "x.msgbnd.dcx").read_bytes() == b"m" and not plan["staging"].exists()
    assert (
        extract._unsafe("../evil.txt")
        and extract._unsafe("C:/x")
        and extract._unsafe("/abs")
        and not extract._unsafe("Wrap/ok.txt")
    )  # py7zr refuses to write such names itself
    with pytest.raises(M.ModError):
        extract.extract_7z(tmp_path / "missing.7z", tmp_path / "o7")


def test_rar_dispatch(tmp_path, monkeypatch):
    fake = tmp_path / "x.rar"
    fake.write_bytes(b"not really")
    monkeypatch.setattr(extract, "rar_tools", lambda: [])
    with pytest.raises(M.ModError) as e:
        extract.extract_rar(fake, tmp_path / "o")
    assert "extractor" in str(e.value)
    tools = extract.rar_tools()  # on this Windows PC bsdtar is always there
    if tools:
        with pytest.raises(M.ModError) as e:
            extract.extract_rar(fake, tmp_path / "o2")  # garbage input fails cleanly
        assert "could not unpack" in str(e.value) and not any((tmp_path / "o2").iterdir())


def test_install_package_from_zip_and_native_from_folder(tmp_path):
    p = _profile(tmp_path)
    z = tmp_path / "Cool Armor.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Cool Armor/parts/am_m_1000.partsbnd.dcx", "p")
        f.writestr("Cool Armor/readme.txt", "r")
    plan = install.plan_install(p, z)
    assert (
        plan["kind"] == "package"
        and plan["name"] == "cool-armor"
        and plan["dest"] == tmp_path / "mod" / "cool-armor"
        and plan["staging"]
    )
    out = install.install(p, plan)
    assert (
        (out["dest"] / "parts" / "am_m_1000.partsbnd.dcx").read_text() == "p"
        and not plan["staging"].exists()
        and out["backup"].is_file()
    )
    text = _read(p)
    data = tomllib.loads(text)
    assert (
        data["packages"][-1] == {"id": "cool-armor", "path": "mod/cool-armor"}
        and "# keep this" in text
        and "\r\n" in text
    )
    assert [e["name"] for e in M.entries(p)] == ["flora", "ersc.dll", "other.dll", "cool-armor"]
    with pytest.raises(M.ModError):
        install.install(p, install.plan_install(p, z))  # exists
    plan = install.plan_install(p, z)
    assert plan["already_listed"] == ["mod/cool-armor"]
    out = install.install(p, plan, overwrite=True)
    assert (
        out["entries"] == [] and sum(1 for e in M.entries(p) if e["id"] == "cool-armor") == 1
    )  # files replaced, no second entry
    # a folder already inside mod/ installs in place: nothing copied, nothing deleted, one entry added
    here = tmp_path / "mod" / "Solo"
    (here / "parts").mkdir(parents=True)
    (here / "parts" / "x.partsbnd.dcx").write_bytes(b"x")
    plan = install.plan_install(p, here)
    assert plan["in_place"] and plan["exists"]
    out = install.install(p, plan, overwrite=True)
    assert (
        (here / "parts" / "x.partsbnd.dcx").read_bytes() == b"x"
        and out["in_place"]
        and [e["path"] for e in out["entries"]] == ["mod/Solo"]
    )
    plan = install.plan_install(p, here)
    assert plan["already_listed"] == ["mod/Solo"]
    assert install.install(p, plan, overwrite=True)["entries"] == []
    src = tmp_path / "dl" / "NoGlow"
    src.mkdir(parents=True)
    (src / "NoGlow.dll").write_bytes(b"g")
    (src / "NoGlow.ini").write_text("i")
    plan = install.plan_install(p, src, name="No Glow")
    assert plan["kind"] == "native" and plan["entries"] == [{"kind": "native", "path": "natives/No-Glow/NoGlow.dll"}]
    out = install.install(p, plan)
    assert (out["dest"] / "NoGlow.ini").is_file() and tomllib.loads(p.read_text(encoding="utf-8"))["natives"][-1][
        "path"
    ] == "natives/No-Glow/NoGlow.dll"
    bad = tmp_path / "junk"
    bad.mkdir()
    (bad / "notes.txt").write_text("x")
    assert "error" in install.plan_install(p, bad)


def test_install_into_array_form_profile_converts_it(tmp_path):
    text = 'profileVersion = "v1"\nstart_online = false\nnatives = [{ path = "SeamlessCoop/ersc.dll", load_early = true }]\npackages = [{ id = "nightreign-revive", path = "NightreignRevive/mod", load_after = [] }]\n'
    p = tmp_path / "revive.me3"
    p.write_text(text, encoding="utf-8")
    (tmp_path / "SeamlessCoop").mkdir()
    (tmp_path / "SeamlessCoop" / "ersc.dll").write_bytes(b"x")
    src = tmp_path / "src" / "Tex"
    (src / "menu").mkdir(parents=True)
    install.install(p, install.plan_install(p, src))
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert (
        data["start_online"] is False
        and data["natives"][0]["load_early"] is True
        and data["natives"][0]["path"] == "SeamlessCoop/ersc.dll"
    )
    assert [x["id"] for x in data["packages"]] == ["nightreign-revive", "tex"] and data["packages"][1][
        "path"
    ] == "mod/tex"  # never inside Revive's own folder
    assert "[[packages]]" in p.read_text(encoding="utf-8")


def test_options_roundtrip_keeps_comments_and_multiline_arrays(tmp_path):
    p = _profile(tmp_path)
    o = M.block_options(_read(p), 1)
    assert (
        o["kind"] == "native"
        and o["load_early"]
        and o["load_after"] == [{"id": "x", "optional": True}]
        and o["enabled"]
    )
    M.set_options(
        p,
        1,
        {
            "load_early": False,
            "optional": True,
            "initializer": {"function": "Init"},
            "finalizer": "Fini",
            "load_after": [{"id": "flora", "optional": False}],
            "load_before": ["other.dll"],
            "enabled": False,
        },
    )
    text = _read(p)
    n = tomllib.loads(text)["natives"][0]
    assert (
        n["path"] == "natives/SeamlessCoop/ersc.dll"
        and "load_early" not in n
        and n["optional"] is True
        and n["enabled"] is False
    )
    assert n["initializer"] == {"function": "Init"} and n["finalizer"] == "Fini"
    assert n["load_after"] == [{"id": "flora", "optional": False}] and n["load_before"] == [
        {"id": "other.dll", "optional": True}
    ]
    assert "# keep this" in text and text.count("load_after") == 1 and "\r\n" in text
    M.set_options(p, 1, {"initializer": {"delay": {"ms": 250}}, "enabled": True, "finalizer": ""})
    n = tomllib.loads(p.read_text(encoding="utf-8"))["natives"][0]
    assert n["initializer"] == {"delay": {"ms": 250}} and "enabled" not in n and "finalizer" not in n
    M.set_options(p, 0, {"id": "flora2", "load_after": ["ersc.dll"]})
    pk = tomllib.loads(p.read_text(encoding="utf-8"))["packages"][0]
    assert (
        pk["id"] == "flora2"
        and pk["load_after"] == [{"id": "ersc.dll", "optional": True}]
        and pk["path"] == "mod/flora"
    )
    M.set_options(p, 0, {"id": ""})
    assert tomllib.loads(p.read_text(encoding="utf-8"))["packages"][0]["id"] == "flora2"  # blank keeps the old id
    assert [e["enabled"] for e in M.entries(p)] == [True, True, False]


def test_uninstall_rules(tmp_path):
    p = _profile(tmp_path)
    (tmp_path / "natives" / "SeamlessCoop" / "second.dll").write_bytes(b"s")
    text = _read(p)
    p.write_text(
        M.append_entry(text, "native", {"path": "natives/SeamlessCoop/second.dll"}), encoding="utf-8", newline=""
    )
    out = remove.uninstall(p, 1, delete_folder=True)  # ersc.dll: folder still used by second.dll
    assert out["removed_folder"] is False and (tmp_path / "natives" / "SeamlessCoop").is_dir()
    assert [e["name"] for e in M.entries(p)] == ["flora", "other.dll", "second.dll"]
    out = remove.uninstall(p, 1, delete_folder=True)  # other.dll: its folder is only its own
    assert out["removed_folder"] is True and not (tmp_path / "natives" / "other").exists()
    out = remove.uninstall(p, 0, delete_folder=False)
    assert (
        out["removed_folder"] is False
        and (tmp_path / "mod" / "flora").is_dir()
        and [e["name"] for e in M.entries(p)] == ["second.dll"]
    )
    out = remove.uninstall(p, 0, delete_folder=True)
    assert out["removed_folder"] is True and not (tmp_path / "natives" / "SeamlessCoop").exists()
    assert M.entries(p) == [] and tomllib.loads(p.read_text(encoding="utf-8"))["profileVersion"] == "v1"
    # a package outside the profile folder is never deleted
    p2 = tmp_path / "p2.me3"
    outside = tmp_path.parent / f"outside-{tmp_path.name}"
    outside.mkdir()
    (outside / "parts").mkdir()
    p2.write_text(
        M.append_entry('profileVersion = "v1"\n', "package", {"id": "ext", "path": str(outside)}), encoding="utf-8"
    )
    out = remove.uninstall(p2, 0, delete_folder=True)
    assert out["removed_folder"] is False and outside.is_dir()


def test_create_and_delete_profile(tmp_path):
    p = M.create_profile(tmp_path / "profiles", "My Setup")
    assert p.name == "My-Setup.me3" and tomllib.loads(p.read_text(encoding="utf-8"))["supports"] == [
        {"game": "eldenring"}
    ]
    assert (tmp_path / "profiles" / "mod").is_dir() and (tmp_path / "profiles" / "natives").is_dir()
    with pytest.raises(M.ModError):
        M.create_profile(tmp_path / "profiles", "My Setup")
    src = _profile(tmp_path / "src")
    c = M.create_profile(tmp_path / "profiles", "copy.me3", copy_from=src)
    assert c.name == "copy.me3" and "flora" in c.read_text(encoding="utf-8")
    gone = M.delete_profile(c)
    from roundtable_souls.platform import data_folder

    assert not c.exists() and gone.parent == data_folder.deleted_profiles(c.parent) and gone.suffix == ".me3"
    assert '"from"' in Path(str(gone) + ".json").read_text(encoding="utf-8")  # a note of where it lived
    with pytest.raises(M.ModError):
        M.delete_profile(c)


FOLDER_OF_MODS = (
    'profileVersion = "v1"\n\n[[packages]]\nid = "all"\npath = \'mod\'\n\n'
    "[[packages]]\nid = \"flora\"\npath = 'mod/pack/flora'\n\n[[packages]]\nid = \"hud\"\npath = 'mod/hud'\n"
)


def _tree_layout(tmp_path):
    p = tmp_path / "my.me3"
    p.write_text(FOLDER_OF_MODS, encoding="utf-8")
    for rel in ("mod/hud/menu", "mod/pack/flora/parts", "mod/pack/sky/parts", "mod/skin/parts", "mod/_backup/parts"):
        (tmp_path / rel).mkdir(parents=True)
    (tmp_path / "mod" / "notes").mkdir()
    return p


def test_package_tree_finds_a_folder_of_mods_and_what_it_leaves_unloaded(tmp_path):
    p = _tree_layout(tmp_path)
    tree = checks.package_tree(p, M.entries(p))
    root, flora, hud = tree[0], tree[1], tree[2]
    assert not root["own_files"] and sorted(root["children"]) == [1, 2]  # 'mod' only holds other mods
    assert flora["own_files"] and flora["parent"] == 0 and hud["parent"] == 0
    unlisted = sorted(f.relative_to(tmp_path / "mod").as_posix() for f in root["unlisted"])
    assert unlisted == ["pack/sky", "skin"]  # _backup and a folder with no game files are not mods
    assert flora["unlisted"] == [] and hud["unlisted"] == []  # ordinary packages are not walked


def test_add_existing_lists_folders_in_place_without_copying(tmp_path):
    p = _tree_layout(tmp_path)
    before = sorted(x.as_posix() for x in (tmp_path / "mod").rglob("*"))
    out = install.add_existing(p, [tmp_path / "mod" / "pack" / "sky", tmp_path / "mod" / "skin"])
    assert [r["id"] for r in out["entries"]] == ["pack-sky", "skin"]
    assert sorted(x.as_posix() for x in (tmp_path / "mod").rglob("*")) == before  # nothing copied or moved
    rows = tomllib.loads(p.read_text(encoding="utf-8"))["packages"]
    assert [r["path"] for r in rows[-2:]] == ["mod/pack/sky", "mod/skin"] and out["backup"].is_file()
    again = install.add_existing(p, [tmp_path / "mod" / "skin"])  # a clash gets a numbered id, never a duplicate
    assert again["entries"][0]["id"] == "skin-2"


CHECKS = (
    'profileVersion = "v1"\n\n'
    '[[packages]]\nid = "a"\npath = \'mod/a\'\nload_after = [{ id = "b", optional = false }]\n\n'
    '[[packages]]\nid = "b"\npath = \'mod/b\'\nload_after = [{ id = "a", optional = false }]\n\n'
    "[[packages]]\nid = \"a\"\npath = 'mod/gone'\n\n"
    '[[packages]]\nid = "c"\npath = \'mod/c\'\nload_after = [{ id = "nowhere", optional = false }, { id = "fine", optional = true }]\n\n'
    '[[natives]]\npath = \'natives/x.dll\'\nload_after = [{ id = "off.dll", optional = false }, { id = "a", optional = false }]\n\n'
    "[[natives]]\npath = 'natives/off.dll'\nenabled = false\n\n"
    "[[natives]]\npath = 'natives/readme.txt'\n"
)


def test_entry_problems_follow_me3_rules(tmp_path):
    p = tmp_path / "my.me3"
    p.write_text(CHECKS, encoding="utf-8")
    for d in ("mod/a/parts", "mod/b/parts", "mod/c/parts"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "natives").mkdir()
    for f in ("x.dll", "off.dll", "readme.txt"):
        (tmp_path / "natives" / f).write_bytes(b"x")
    items = M.entries(p)
    got = checks.entry_problems(p, items)
    by = {i: " | ".join(v) for i, v in got.items()}
    assert "Load order loops: a" in by[0] and "Load order loops" in by[1]
    assert "used twice" in by[0] and "Folder missing" in by[2]
    assert "'nowhere', which is not in this profile" in by[3] and "fine" not in by[3]  # optional is fine
    assert not any("'off.dll'" in x for x in by[4])  # switched off: me3 orders it anyway, nothing stops
    assert "'a', which is not in this profile" in by[4]  # a native cannot wait for a package
    assert by[5] == "" and "Not a .dll" in by[6]


def test_conflicts_count_only_what_the_game_can_ask_for(tmp_path):
    from roundtable_souls.mods import profile as P

    p = tmp_path / "my.me3"
    p.write_text(
        'profileVersion = "v1"\n[[packages]]\nid = "all"\npath = \'mod\'\n[[packages]]\nid = "x"\npath = \'mod/x\'\n'
        "[[packages]]\nid = \"y\"\npath = 'mod/y'\n",
        encoding="utf-8",
    )
    for d in ("x", "y"):
        (tmp_path / "mod" / d / "parts").mkdir(parents=True)
        (tmp_path / "mod" / d / "parts" / "am_m_1000.partsbnd.dcx").write_bytes(b"p")
        (tmp_path / "mod" / d / "_backup").mkdir()
        (tmp_path / "mod" / d / "_backup" / "old.partsbnd.dcx").write_bytes(b"o")
    r = P.scan_conflicts(p)
    assert [(c["path"], c["winner"]) for c in r["conflicts"]] == [("parts/am_m_1000.partsbnd.dcx", "y")]
    assert r["files"] == 2 and r["packages"][0]["files"] == 0  # the folder of mods adds nothing


def _layout(tmp_path, profile_text, folders=(), files=()):
    p = tmp_path / "my.me3"
    p.write_text(profile_text, encoding="utf-8")
    for d in folders:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    for f in files:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_bytes(b"x")
    return p


def test_an_entry_for_the_folder_of_mods_is_a_folder_not_a_mod(tmp_path):
    p = _layout(
        tmp_path,
        'profileVersion = "v1"\n[[packages]]\nid = "all"\npath = \'mod\'\n[[packages]]\nid = "hud"\npath = \'mod/hud\'\n',
        ("mod/hud/menu", "mod/skin/parts"),
    )
    items = M.entries(p)
    o = checks.folder_overview(p, items)
    pk = o["packages"]
    assert pk["root"].name == "mod" and pk["holders"] == [0] and pk["listed"] == 1
    assert [u.name for u in pk["unlisted"]] == ["skin"]


def test_one_package_for_everything_as_in_the_me3_guide_is_just_a_mod(tmp_path):
    p = _layout(tmp_path, 'profileVersion = "v1"\n[[packages]]\nid = "nightmods"\npath = \'mod\'\n', ("mod/parts",))
    items = M.entries(p)
    o = checks.folder_overview(p, items)
    assert o["packages"] is None  # mod/ serves game files itself: no folder row, no holder
    assert not checks.package_tree(p, items)[0]["holder"]


def test_unloaded_mod_folders_show_without_an_entry_for_the_folder(tmp_path):
    p = _layout(
        tmp_path,
        'profileVersion = "v1"\n[[packages]]\nid = "hud"\npath = \'mod/hud\'\n',
        ("mod/hud/menu", "mod/skin/parts", "mod/_backup/parts", "mod/notes"),
    )
    pk = checks.folder_overview(p, M.entries(p))["packages"]
    assert pk["holders"] == [] and [u.name for u in pk["unlisted"]] == ["skin"]


def test_listed_folders_match_whatever_the_letter_case(tmp_path):
    import os

    if os.name != "nt":
        pytest.skip("case-insensitive paths are a Windows thing")
    p = _layout(tmp_path, 'profileVersion = "v1"\n[[packages]]\nid = "hud"\npath = \'MOD\\\\HUD\'\n', ("mod/hud/menu",))
    pk = checks.folder_overview(p, M.entries(p))["packages"]
    assert pk is None or pk["unlisted"] == []


def test_unloaded_dlls_leave_out_helpers_runtimes_and_reshade_addons(tmp_path):
    p = _layout(
        tmp_path,
        "profileVersion = \"v1\"\n[[natives]]\npath = 'natives/SeamlessCoop/ersc.dll'\n[[natives]]\npath = 'natives/a.dll'\n",
        (),
        (
            "natives/a.dll",
            "natives/b.dll",
            "natives/SeamlessCoop/ersc.dll",
            "natives/SeamlessCoop/helper.dll",
            "natives/Fps/UnlockTheFps.dll",
            "natives/RenoDX/nvngx_dlssnr.dll",
            "natives/RenoDX/renodx.addon64",
            "natives/Other/extra.dll",
            "natives/sl.dlss.dll",
        ),
    )
    nt = checks.folder_overview(p, M.entries(p))["natives"]
    assert sorted(x.name for x in nt["unlisted"]) == ["UnlockTheFps.dll", "b.dll", "extra.dll"] and nt["listed"] == 2
    out = install.add_existing(p, [tmp_path / "natives" / "b.dll"], kind="native")
    assert out["entries"] == [{"kind": "native", "path": "natives/b.dll"}]
    assert "b.dll" not in [x.name for x in checks.folder_overview(p, M.entries(p))["natives"]["unlisted"]]


def _goblins(root, langs=("English", "Italian")):
    """An archive laid out like Map for Goblins Expanded: a mod/ folder per language, a readme and an example .me3."""
    for lang in langs:
        m = root / lang / "mod"
        (m / "menu").mkdir(parents=True)
        (m / "menu" / "02_120_worldmap.gfx").write_bytes(b"g")
        for code in ("engus", "itait"):
            (m / "msg" / code).mkdir(parents=True)
            (m / "msg" / code / "item_dlc02.msgbnd.dcx").write_bytes(lang.encode())
        (m / "script" / "talk").mkdir(parents=True)
        (m / "script" / "talk" / "m00_00_00_00.talkesdbnd.dcx").write_bytes(b"t")
        (m / "regulation.bin").write_bytes(b"R")
        (m / "readme.txt").write_text("r")
    (root / "example.me3").write_text('profileVersion = "v1"\n')
    (root / "Readme.txt").write_text("r")


REVIVE_LAST = (
    'profileVersion = "v1"\n\n[[packages]]\nid = "solo"\npath = \'mod/solo\'\n\n'
    "# Revive: must stay last\n# (its regulation.bin)\n[[packages]]\nid = \"nightreign-revive\"\npath = 'revive/mod'\n"
)


def _revive_profile(tmp_path):
    base = tmp_path / "prof"
    (base / "mod" / "solo" / "parts").mkdir(parents=True)
    (base / "revive" / "mod").mkdir(parents=True)
    (base / "revive" / "mod" / "regulation.bin").write_bytes(b"V")
    p = base / "p.me3"
    p.write_text(REVIVE_LAST, encoding="utf-8")
    return p


def test_find_roots_picks_mod_folders_below_wrappers_and_offers_each_language(tmp_path):
    _goblins(tmp_path / "Map for Goblins Expanded")
    roots = install.find_roots(tmp_path)
    assert [r.relative_to(tmp_path).as_posix() for r in roots] == [
        "Map for Goblins Expanded/English/mod",
        "Map for Goblins Expanded/Italian/mod",
    ]
    one = tmp_path / "one"
    _goblins(one / "Wrap", langs=("x",))
    assert [r.relative_to(one).as_posix() for r in install.find_roots(one)] == ["Wrap/x/mod"]


def test_contents_tick_what_the_game_reads_and_leave_docs_and_profiles_out(tmp_path):
    _goblins(tmp_path, langs=("x",))
    got = {c["name"]: (c["group"], c["on"]) for c in install.contents(tmp_path / "x" / "mod", "package")}
    assert got == {
        "menu": ("game", True),
        "msg": ("game", True),
        "script": ("game", True),
        "regulation.bin": ("regulation", True),
        "readme.txt": ("doc", False),
    }
    n = tmp_path / "dll"
    (n / "locale").mkdir(parents=True)
    for f in ("Fps.dll", "Fps.ini", "skeleton_mods.txt", "README.md", "sample.me3"):
        (n / f).write_text("x")
    got = {c["name"]: (c["group"], c["on"]) for c in install.contents(n, "native")}
    assert got == {
        "locale": ("files", True),
        "Fps.dll": ("dll", True),
        "Fps.ini": ("settings", True),
        "skeleton_mods.txt": ("settings", True),
        "README.md": ("doc", False),
        "sample.me3": ("profile", False),
    }


def test_plan_offers_variants_and_replans_without_unpacking_again(tmp_path):
    py7zr = pytest.importorskip("py7zr")
    src = tmp_path / "src" / "Map for Goblins Expanded"
    _goblins(src)
    a = tmp_path / "Map for Goblins Expanded-1234-1-0.7z"
    with py7zr.SevenZipFile(a, "w") as z:
        z.writeall(src, arcname=src.name)
    p = _revive_profile(tmp_path)
    plan = install.plan_install(p, a)
    assert (
        plan["kind"] == "package"
        and plan["variants"] == ["Map for Goblins Expanded/English/mod", "Map for Goblins Expanded/Italian/mod"]
        and plan["languages"] == ["engus", "itait"]
        and plan["profiles_inside"]  # the example .me3 is noted, not what makes it a mod
        and plan["regulation_winner"] == "nightreign-revive"
    )
    again = install.replan(p, plan, name="Goblin Maps", pkg_id="goblins", variant=plan["variants"][1])
    assert (
        again["unpacked"] == plan["unpacked"]
        and again["name"] == "Goblin-Maps"
        and again["id"] == "goblins"
        and again["root"].parent.name == "Italian"
    )
    assert install.replan(p, plan, pkg_id="solo")["id_taken"]
    again["exclude"] = [c["name"] for c in again["contents"] if not c["on"]]
    again["insert_before"] = again["regulation_packages"][-1]["index"]
    out = install.install(p, again)
    got = sorted(x.relative_to(out["dest"]).as_posix() for x in out["dest"].rglob("*") if x.is_file())
    assert "readme.txt" not in got and "regulation.bin" in got
    assert (out["dest"] / "msg" / "engus" / "item_dlc02.msgbnd.dcx").read_bytes() == b"Italian"
    text = p.read_text(encoding="utf-8")
    assert [x["id"] for x in tomllib.loads(text)["packages"]] == ["solo", "goblins", "nightreign-revive"]
    assert text.index("goblins") < text.index("# Revive: must stay last")  # the note stays with its entry
    assert not Path(plan["unpacked"]).exists()


def test_regulation_order_follows_load_order_and_skips_disabled(tmp_path):
    p = _revive_profile(tmp_path)
    (p.parent / "mod" / "solo" / "regulation.bin").write_bytes(b"S")
    assert [x["name"] for x in install.regulation_order(p)["regulation_packages"]] == ["solo", "nightreign-revive"]
    p.write_text(
        p.read_text(encoding="utf-8").replace(
            "path = 'mod/solo'", "path = 'mod/solo'\nload_after = [{ id = \"nightreign-revive\" }]"
        ),
        encoding="utf-8",
    )
    assert install.regulation_order(p)["regulation_winner"] == "solo"
    p.write_text(
        p.read_text(encoding="utf-8").replace("path = 'revive/mod'", "path = 'revive/mod'\nenabled = false"),
        encoding="utf-8",
    )
    assert [x["name"] for x in install.regulation_order(p)["regulation_packages"]] == ["solo"]


def test_insert_entry_goes_above_the_note_but_not_above_commented_out_entries():
    text = REVIVE_LAST
    blk = next(b for b in M.blocks(text) if "nightreign-revive" in text.splitlines()[b["start"] + 1])
    out = M.insert_entry(text, "package", {"id": "new", "path": "mod/new"}, blk["index"])
    assert out.index('id = "new"') < out.index("# Revive: must stay last") and tomllib.loads(out)
    commented = text.replace("# (its regulation.bin)", '# [[packages]]\n# id = "old"')
    out = M.insert_entry(commented, "package", {"id": "new", "path": "mod/new"}, blk["index"])
    assert out.index('# id = "old"') < out.index('id = "new"') < out.index('id = "nightreign-revive"')


def test_excluded_dll_folders_get_no_entry(tmp_path):
    p = _profile(tmp_path / "p")
    src = tmp_path / "dl" / "Pack"
    (src / "extra").mkdir(parents=True)
    (src / "Main.dll").write_bytes(b"m")
    (src / "extra" / "Helper.dll").write_bytes(b"h")
    plan = install.plan_install(p, src)
    plan["exclude"] = ["extra"]
    out = install.install(p, plan)
    assert [e["path"] for e in out["entries"]] == ["natives/pack/Main.dll"] and not (out["dest"] / "extra").exists()


def test_unrecognised_files_install_and_loader_dlls_and_extras_do_not(tmp_path):
    p = _profile(tmp_path / "p")
    src = tmp_path / "dl" / "Wrap"
    (src / "Thing" / "parts").mkdir(parents=True)
    (src / "Thing" / "parts" / "a.partsbnd.dcx").write_bytes(b"a")
    (src / "Thing" / "mystery.bin").write_bytes(b"m")
    (src / "Thing" / "dinput8.dll").write_bytes(b"d")
    (src / "example.me3").write_text('profileVersion = "v1"\n')
    (src / "Notes.txt").write_text("n")
    plan = install.plan_install(p, src)
    got = {c["name"]: (c["group"], c["on"], c.get("extra")) for c in plan["contents"]}
    assert got == {
        "parts": ("game", True, None),
        "dinput8.dll": ("loader", False, None),
        "mystery.bin": ("other", True, None),
        "example.me3": ("profile", False, "example.me3"),
        "Notes.txt": ("doc", False, "Notes.txt"),
    }
    plan["exclude"] = [c["name"] for c in plan["contents"] if not c["on"] and c["name"] != "example.me3"]
    out = install.install(p, plan)  # the .me3 ticked: kept as a copy with the mod
    names = sorted(x.name for x in out["dest"].iterdir())
    assert names == ["example.me3", "mystery.bin", "parts"]


def test_a_lone_dll_installs_as_a_dll_mod(tmp_path):
    p = _profile(tmp_path / "p")
    dll = tmp_path / "dl" / "UnlockTheFps.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"u")
    plan = install.plan_install(p, dll)
    assert plan["kind"] == "native" and plan["name"] == "unlockthefps"
    out = install.install(p, plan)
    assert [e["path"] for e in out["entries"]] == ["natives/unlockthefps/UnlockTheFps.dll"] and dll.is_file()


def test_regulation_placement_follows_the_package_if_the_profile_changed_meanwhile(tmp_path):
    p = _revive_profile(tmp_path)
    src = tmp_path / "dl" / "Params"
    src.mkdir(parents=True)
    (src / "regulation.bin").write_bytes(b"R")
    plan = install.plan_install(p, src)
    assert [x["name"] for x in plan["regulation_packages"]] == ["nightreign-revive"]
    plan["insert_before"] = "nightreign-revive"
    # edited outside the launcher before Install: a new entry above Revive moves it down one block
    p.write_text(
        p.read_text(encoding="utf-8").replace("# Revive", "[[packages]]\nid = \"late\"\npath = 'mod/late'\n\n# Revive"),
        encoding="utf-8",
    )
    install.install(p, plan)
    ids = [x["id"] for x in tomllib.loads(p.read_text(encoding="utf-8"))["packages"]]
    assert ids == ["solo", "late", "params", "nightreign-revive"]
    again = install.plan_install(p, src)  # a reinstall: its own entry is not the one to place before
    assert again["already_listed"] and [x["name"] for x in again["regulation_packages"]] == ["nightreign-revive"]
    plan = install.plan_install(p, src, name="other")
    plan["insert_before"] = "gone"  # the package was removed meanwhile: goes last
    install.install(p, plan)
    assert [x["id"] for x in tomllib.loads(p.read_text(encoding="utf-8"))["packages"]][-1] == "other"


def test_me3_stops_for_a_required_dependency_whose_folder_is_missing_or_whose_id_differs_in_case(tmp_path):
    p = tmp_path / "my.me3"
    p.write_text(
        'profileVersion = "v1"\n\n'
        "[[packages]]\nid = \"Base\"\npath = 'mod/base'\n\n"
        "[[packages]]\nid = \"gone\"\npath = 'mod/gone'\n\n"
        '[[packages]]\nid = "x"\npath = \'mod/x\'\nload_after = [{ id = "base", optional = false }, '
        '{ id = "gone", optional = false }]\n',
        encoding="utf-8",
    )
    for d in ("mod/base/parts", "mod/x/parts"):
        (tmp_path / d).mkdir(parents=True)
    by = {i: " | ".join(v) for i, v in checks.entry_problems(p, M.entries(p)).items()}
    assert "'base', but the profile calls it 'Base'" in by[2]
    assert "'gone', whose folder is missing: me3 stops" in by[2]


def test_a_loop_is_only_one_me3_sees(tmp_path):
    p = tmp_path / "my.me3"
    p.write_text(
        'profileVersion = "v1"\n\n'
        '[[packages]]\nid = "a"\npath = \'mod/a\'\nload_after = [{ id = "gone", optional = true }]\n\n'
        '[[packages]]\nid = "gone"\npath = \'mod/gone\'\nload_after = [{ id = "a", optional = true }]\n\n'
        '[[packages]]\nid = "b"\npath = \'mod/b\'\nload_after = [{ id = "C", optional = true }]\n\n'
        '[[packages]]\nid = "c"\npath = \'mod/c\'\nload_after = [{ id = "b", optional = true }]\n',
        encoding="utf-8",
    )
    for d in ("mod/a/parts", "mod/b/parts", "mod/c/parts"):
        (tmp_path / d).mkdir(parents=True)
    found = checks.entry_problems(p, M.entries(p))
    # gone's folder is missing (me3 leaves it out) and 'C' is not 'c' (me3 matches ids exactly): no loop either way
    assert not any("loops" in x for v in found.values() for x in v)
