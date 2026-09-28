"""Mod install / remove / options and profile create / delete, all on temp folders."""

import tomllib
import zipfile
from pathlib import Path

import pytest

from roundtable_souls import core as g

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
    d = M.detect(tmp_path / "pk")
    assert d["kind"] == "package" and d["root"] == pk and d["assets"] == ["parts"]
    nt = tmp_path / "nt"
    nt.mkdir()
    (nt / "cool.dll").write_bytes(b"x")
    (nt / "dinput8.dll").write_bytes(b"x")
    d = M.detect(nt)
    assert d["kind"] == "native" and [p.name for p in d["dlls"]] == ["cool.dll"]
    mixed = tmp_path / "mx"
    (mixed / "msg").mkdir(parents=True)
    (mixed / "tool.dll").write_bytes(b"x")
    assert M.detect_kind(mixed) == "package"  # assets win
    nested = tmp_path / "nd" / "SeamlessCoop"
    nested.mkdir(parents=True)
    (nested / "ersc.dll").write_bytes(b"x")
    assert M.detect_kind(tmp_path / "nd") == "native"  # DLL one level down
    reg = tmp_path / "reg"
    reg.mkdir()
    (reg / "regulation.bin").write_bytes(b"x")
    assert M.detect_kind(reg) == "package"
    me3 = tmp_path / "prof"
    me3.mkdir()
    (me3 / "x.me3").write_text('profileVersion = "v1"')
    assert M.detect_kind(me3) == "me3"
    empty = tmp_path / "e"
    empty.mkdir()
    assert M.detect_kind(empty) == "unknown"
    assert M.slug("My Mod!! v2.0 (final)") == "My-Mod-v2.0-final" and M.slug("   ") == "mod"
    assert M.slug("Hair 13 - Ranni's Hairstyle V1.1-561-1-1-1648994275") == "Hair-13-Ranni-s-Hairstyle-V1.1"
    assert M.slug("Dark Souls ReShaded 2.2-127-2-2-1736209179") == "Dark-Souls-ReShaded-2.2"


def test_loose_game_files_are_sorted_into_folders(tmp_path):
    src = tmp_path / "hair"
    src.mkdir()
    (src / "hr_a_0007.partsbnd.dcx").write_bytes(b"h")
    (src / "readme.txt").write_text("r")
    d = M.detect(src)
    assert (
        d["kind"] == "package"
        and d["assets"] == ["parts"]
        and [(f.name, s) for f, s in d["loose"]] == [("hr_a_0007.partsbnd.dcx", "parts")]
    )
    p = tmp_path / "prof" / "p.me3"
    p.parent.mkdir()
    p.write_text('profileVersion = "v1"\n', encoding="utf-8")
    out = M.install(p, M.plan_install(p, src, name="Ranni Hair"))
    assert (out["dest"] / "parts" / "hr_a_0007.partsbnd.dcx").read_bytes() == b"h" and (
        out["dest"] / "readme.txt"
    ).is_file()
    assert not (out["dest"] / "hr_a_0007.partsbnd.dcx").exists()
    mixed = tmp_path / "mixed"
    mixed.mkdir()
    (mixed / "c0000.anibnd.dcx").write_bytes(b"a")
    (mixed / "regulation.bin").write_bytes(b"r")
    (mixed / "menu_x.gfx").write_bytes(b"g")
    d = M.detect(mixed)
    assert d["kind"] == "package" and set(d["assets"]) == {"chr", "regulation.bin", "menu"}
    out = M.install(p, M.plan_install(p, mixed))
    assert (
        (out["dest"] / "chr" / "c0000.anibnd.dcx").is_file()
        and (out["dest"] / "regulation.bin").is_file()
        and (out["dest"] / "menu" / "menu_x.gfx").is_file()
    )
    save = tmp_path / "save"
    save.mkdir()
    (save / "ER0000.sl2").write_bytes(b"s")
    assert "No game folders" in M.plan_install(p, save)["error"]  # a save is not a mod
    junk = tmp_path / "junk2"
    junk.mkdir()
    (junk / "notes.txt").write_text("x")
    assert "No game folders" in M.plan_install(p, junk)["error"]
    rs = tmp_path / "reshade" / "Dark Souls ReShaded"
    rs.mkdir(parents=True)
    (rs / "dxgi.dll").write_bytes(b"x")
    assert M.plan_install(p, tmp_path / "reshade")["kind"] == "native"  # a DLL is a native


def test_zip_safety(tmp_path):
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("../evil.txt", "x")
    with pytest.raises(M.ModError):
        M.extract_zip(z, tmp_path / "out")
    with pytest.raises(M.ModError):
        M.stage(tmp_path / "x.txt", tmp_path)
    with pytest.raises(M.ModError):
        M.extract_archive(tmp_path / "x.tar.gz", tmp_path / "o")
    assert M.ARCHIVE_EXTENSIONS == (".zip", ".7z", ".rar")


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
    plan = M.plan_install(p, a)
    assert plan["kind"] == "package" and plan["name"] == "Nice-Mod" and plan["assets"] == ["msg"] and plan["staging"]
    out = M.install(p, plan)
    assert (out["dest"] / "msg" / "x.msgbnd.dcx").read_bytes() == b"m" and not plan["staging"].exists()
    assert (
        M._unsafe("../evil.txt") and M._unsafe("C:/x") and M._unsafe("/abs") and not M._unsafe("Wrap/ok.txt")
    )  # py7zr refuses to write such names itself
    with pytest.raises(M.ModError):
        M.extract_7z(tmp_path / "missing.7z", tmp_path / "o7")


def test_rar_dispatch(tmp_path, monkeypatch):
    fake = tmp_path / "x.rar"
    fake.write_bytes(b"not really")
    monkeypatch.setattr(M, "rar_tools", lambda: [])
    with pytest.raises(M.ModError) as e:
        M.extract_rar(fake, tmp_path / "o")
    assert "extractor" in str(e.value)
    tools = M.rar_tools()  # on this Windows PC bsdtar is always there
    if tools:
        with pytest.raises(M.ModError) as e:
            M.extract_rar(fake, tmp_path / "o2")  # garbage input fails cleanly
        assert "could not unpack" in str(e.value) and not any((tmp_path / "o2").iterdir())


def test_install_package_from_zip_and_native_from_folder(tmp_path):
    p = _profile(tmp_path)
    z = tmp_path / "Cool Armor.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Cool Armor/parts/am_m_1000.partsbnd.dcx", "p")
        f.writestr("Cool Armor/readme.txt", "r")
    plan = M.plan_install(p, z)
    assert (
        plan["kind"] == "package"
        and plan["name"] == "Cool-Armor"
        and plan["dest"] == tmp_path / "mod" / "Cool-Armor"
        and plan["staging"]
    )
    out = M.install(p, plan)
    assert (
        (out["dest"] / "parts" / "am_m_1000.partsbnd.dcx").read_text() == "p"
        and not plan["staging"].exists()
        and out["backup"].is_file()
    )
    text = _read(p)
    data = tomllib.loads(text)
    assert (
        data["packages"][-1] == {"id": "Cool-Armor", "path": "mod/Cool-Armor"}
        and "# keep this" in text
        and "\r\n" in text
    )
    assert [e["name"] for e in M.entries(p)] == ["flora", "ersc.dll", "other.dll", "Cool-Armor"]
    with pytest.raises(M.ModError):
        M.install(p, M.plan_install(p, z))  # exists
    plan = M.plan_install(p, z)
    assert plan["already_listed"] == ["mod/Cool-Armor"]
    out = M.install(p, plan, overwrite=True)
    assert (
        out["entries"] == [] and sum(1 for e in M.entries(p) if e["id"] == "Cool-Armor") == 1
    )  # files replaced, no second entry
    # a folder already inside mod/ installs in place: nothing copied, nothing deleted, one entry added
    here = tmp_path / "mod" / "Solo"
    (here / "parts").mkdir(parents=True)
    (here / "parts" / "x.partsbnd.dcx").write_bytes(b"x")
    plan = M.plan_install(p, here)
    assert plan["in_place"] and plan["exists"]
    out = M.install(p, plan, overwrite=True)
    assert (
        (here / "parts" / "x.partsbnd.dcx").read_bytes() == b"x"
        and out["in_place"]
        and [e["path"] for e in out["entries"]] == ["mod/Solo"]
    )
    plan = M.plan_install(p, here)
    assert plan["already_listed"] == ["mod/Solo"]
    assert M.install(p, plan, overwrite=True)["entries"] == []
    src = tmp_path / "dl" / "NoGlow"
    src.mkdir(parents=True)
    (src / "NoGlow.dll").write_bytes(b"g")
    (src / "NoGlow.ini").write_text("i")
    plan = M.plan_install(p, src, name="No Glow")
    assert plan["kind"] == "native" and plan["entries"] == [{"kind": "native", "path": "natives/No-Glow/NoGlow.dll"}]
    out = M.install(p, plan)
    assert (out["dest"] / "NoGlow.ini").is_file() and tomllib.loads(p.read_text(encoding="utf-8"))["natives"][-1][
        "path"
    ] == "natives/No-Glow/NoGlow.dll"
    bad = tmp_path / "junk"
    bad.mkdir()
    (bad / "notes.txt").write_text("x")
    assert "error" in M.plan_install(p, bad)


def test_install_into_array_form_profile_converts_it(tmp_path):
    text = 'profileVersion = "v1"\nstart_online = false\nnatives = [{ path = "SeamlessCoop/ersc.dll", load_early = true }]\npackages = [{ id = "nightreign-revive", path = "NightreignRevive/mod", load_after = [] }]\n'
    p = tmp_path / "revive.me3"
    p.write_text(text, encoding="utf-8")
    (tmp_path / "SeamlessCoop").mkdir()
    (tmp_path / "SeamlessCoop" / "ersc.dll").write_bytes(b"x")
    src = tmp_path / "src" / "Tex"
    (src / "menu").mkdir(parents=True)
    M.install(p, M.plan_install(p, src))
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert (
        data["start_online"] is False
        and data["natives"][0]["load_early"] is True
        and data["natives"][0]["path"] == "SeamlessCoop/ersc.dll"
    )
    assert [x["id"] for x in data["packages"]] == ["nightreign-revive", "Tex"] and data["packages"][1][
        "path"
    ] == "mod/Tex"  # never inside Revive's own folder
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
    out = M.uninstall(p, 1, delete_folder=True)  # ersc.dll: folder still used by second.dll
    assert out["removed_folder"] is False and (tmp_path / "natives" / "SeamlessCoop").is_dir()
    assert [e["name"] for e in M.entries(p)] == ["flora", "other.dll", "second.dll"]
    out = M.uninstall(p, 1, delete_folder=True)  # other.dll: its folder is only its own
    assert out["removed_folder"] is True and not (tmp_path / "natives" / "other").exists()
    out = M.uninstall(p, 0, delete_folder=False)
    assert (
        out["removed_folder"] is False
        and (tmp_path / "mod" / "flora").is_dir()
        and [e["name"] for e in M.entries(p)] == ["second.dll"]
    )
    out = M.uninstall(p, 0, delete_folder=True)
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
    out = M.uninstall(p2, 0, delete_folder=True)
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
    assert not c.exists() and gone.parent.name == "deleted-profiles" and gone.suffix == ".me3"
    with pytest.raises(M.ModError):
        M.delete_profile(c)
