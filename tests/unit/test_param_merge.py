"""Regulation files and the launcher's own parameter combine, on small regulation files built here (encrypted, DCX,
BND4, PARAM, like the game's), so no game file is needed."""

import json
import struct

import pytest

from roundtable_souls import formats
from roundtable_souls.merging.rules import param as pm
from roundtable_souls.mods import manage as M
from roundtable_souls.mods import rebuild as merge
from roundtable_souls.mods.backends import builtin
from roundtable_souls.platform import paths as common

DCX = (  # the 0x4C header of the game's regulation (sizes are filled in on write)
    b"DCX\0"
    + struct.pack(">IIIII", 0x11000, 0x18, 0x24, 0x44, 0x4C)
    + b"DCS\0"
    + struct.pack(">II", 0, 0)
    + b"DCP\0ZSTD"
    + struct.pack(">IIIIII", 0x20, 0x15000000, 0, 0, 0, 0x10100)
    + b"DCA\0"
    + struct.pack(">I", 8)
)
assert len(DCX) == 0x4C
STRIDE = 16


def table(type_name: str, rows, stride: int = STRIDE, names=None) -> formats.param.Param:
    header = bytearray(0x40)
    struct.pack_into("<H", header, 0x06, 1)
    header[0x2D], header[0x2E] = 0x85, 7
    struct.pack_into("<q", header, 0x10, 0x40)
    tail = type_name.encode() + b"\0" + b"\0\0\0\0"
    p = formats.param.Param(bytes(header), [], stride, tail, len(type_name) + 1, True, data_end=0x40)
    p.rows = [formats.param.Row(i, bytes(d), (names or {}).get(i, "")) for i, d in rows]
    return p


def row(*words: int, stride: int = STRIDE) -> bytes:
    data = b"".join(struct.pack("<I", w) for w in words)
    return data + bytes(stride - len(data))


def regulation(tables: dict, version: str = "11711000") -> bytes:
    hdr = bytearray(0x40)
    hdr[0:4] = b"BND4"
    hdr[0x08:0x0C] = bytes.fromhex("00000100")
    struct.pack_into("<q", hdr, 0x10, 0x40)
    hdr[0x18:0x20] = version.encode()
    struct.pack_into("<q", hdr, 0x20, 36)
    hdr[0x30:0x34] = bytes([1, 0x74, 4, 0])
    entries = [
        formats.bnd4.Entry(f"N:\\GR\\data\\Param\\param\\GameParam\\{n}.param", i, formats.param.write_param(p))
        for i, (n, p) in enumerate(tables.items())
    ]
    binder = formats.bnd4.Bnd4(bytes(hdr), formats.regulation.REGULATION_FORMAT, 0x74, True, 4, entries)
    return formats.regulation.write_regulation(formats.regulation.Regulation(DCX, binder))


def vanilla(version="11711000") -> bytes:
    return regulation(
        {
            "EquipParamWeapon": table("EQUIP_PARAM_WEAPON_ST", [(1000, row(1, 2, 3, 4)), (2000, row(5, 6, 7, 8))]),
            "SpEffectParam": table("SP_EFFECT_PARAM_ST", [(10, row(9, 9, 9, 9))]),
        },
        version,
    )


def rows_of(raw: bytes, name: str) -> dict:
    reg = formats.regulation.read_regulation(raw)
    return {r.id: r for r in formats.param.read_param(reg.bnd.get(name + ".param").data).rows}


def pack(edits: dict, version="11711000", base=None) -> bytes:
    """A pack: the vanilla regulation with edits {table: fn(param)} applied."""
    reg = formats.regulation.read_regulation(base or vanilla(version))
    for name, fn in edits.items():
        f = reg.bnd.get(name + ".param")
        p = formats.param.read_param(f.data)
        fn(p)
        f.data = formats.param.write_param(p)
    return formats.regulation.write_regulation(reg)


def set_word(rid, i, value):
    def fn(p):
        r = next(x for x in p.rows if x.id == rid)
        d = bytearray(r.data)
        struct.pack_into("<I", d, i * 4, value)
        r.data = bytes(d)

    return fn


# ----------------------------------------------------------------------------- the file format
def test_a_regulation_reads_back_as_written_and_decrypts_like_the_games():
    raw = vanilla()
    body = formats.dcx.dcx_decompress(formats.regulation.decrypt_regulation(raw))
    assert formats.bnd4.bnd4_files(body)[0][0] == "EquipParamWeapon.param"
    reg = formats.regulation.read_regulation(raw)
    assert (
        reg.version == "11711000"
        and formats.regulation.binder_bytes(reg.bnd) == formats.bnd4.write_bnd4(reg.bnd) == body
    )
    for f in reg.bnd.entries:
        assert formats.param.write_param(formats.param.read_param(f.data)) == f.data
    assert formats.param.param_row_ids(reg.bnd.get("EquipParamWeapon.param").data) == [1000, 2000]


def zstd_blocks(frame: bytes) -> list[int]:
    """The compressed size of each block of a zstd frame that has no content size and no checksum."""
    assert frame[:4] == bytes.fromhex("28b52ffd")
    descriptor, window = frame[4], frame[5]
    assert (
        descriptor == 0 and window <= (formats.regulation.ZSTD_WINDOW_LOG - 10) << 3
    )  # no content size or checksum; window <= 64 KB
    pos, sizes = 6, []
    while True:
        header = int.from_bytes(frame[pos : pos + 3], "little")
        last, kind, size = header & 1, (header >> 1) & 3, header >> 3
        sizes.append(size)
        pos += 3 + (1 if kind == 1 else size)  # an RLE block stores one byte
        if last:
            return sizes


def test_the_zstd_frame_is_shaped_as_the_game_requires():
    # 64 KB blocks, no content size: the game crashes at start on zstd's default 128 KB blocks (in-game finding,
    # 2026-09-30, Elden Ring 1.17.1); its own regulation and every editor keep to this shape.
    body = bytes(range(256)) * 1000 + bytes(50_000)  # 306 000 bytes: five blocks of 64 KB (the last one shorter)
    frame = formats.regulation.compress_regulation_body(body)
    assert len(zstd_blocks(frame)) == -(-len(body) // 65536) == 5 and frame[5] == 0x30  # a 64 KB window exactly
    from compression import zstd

    assert zstd.decompress(frame) == body and zstd.get_frame_info(frame).decompressed_size is None
    raw = vanilla()
    plain = formats.regulation.decrypt_regulation(raw)
    compressed_size = struct.unpack_from(">I", plain, 0x20)[0]
    assert zstd_blocks(plain[0x4C : 0x4C + compressed_size])  # the written file carries that same shape


def test_names_order_and_repeated_ids_survive():
    p = table("T", [(5, row(1)), (3, row(2)), (5, row(3))], names={3: "Three"})
    back = formats.param.read_param(formats.param.write_param(p))
    assert [(r.id, r.name) for r in back.rows] == [(5, ""), (3, "Three"), (5, "")]
    assert formats.param.write_param(back) == formats.param.write_param(p)


# ----------------------------------------------------------------------------- combining
def test_each_packs_changes_apply_and_overlaps_go_to_the_later_pack():
    a = pack({"EquipParamWeapon": set_word(1000, 0, 111)})
    b = pack({"EquipParamWeapon": lambda p: (set_word(1000, 0, 222)(p), set_word(1000, 2, 333)(p))})
    c = pack({"SpEffectParam": lambda p: p.rows.append(formats.param.Row(11, row(7, 7, 7, 7), "New effect"))})
    out, rep = pm.combine(vanilla(), [("a", a), ("b", b), ("c", c)])
    w = rows_of(out, "EquipParamWeapon")
    assert struct.unpack("<4I", w[1000].data) == (222, 2, 333, 4)  # b won word 0, b's word 2, the rest vanilla
    assert w[2000].data == row(5, 6, 7, 8)
    e = rows_of(out, "SpEffectParam")
    assert e[11].name == "New effect" and e[10].data == row(9, 9, 9, 9)
    assert rep.conflicts == [("EquipParamWeapon", 1000, ["a", "b"])]
    assert [(p.name, p.changed, p.added) for p in rep.packs] == [("a", 1, 0), ("b", 1, 0), ("c", 0, 1)]


def test_different_parts_of_one_row_both_apply():
    a = pack({"EquipParamWeapon": set_word(2000, 1, 60)})
    b = pack({"EquipParamWeapon": set_word(2000, 3, 80)})
    out, rep = pm.combine(vanilla(), [("a", a), ("b", b)])
    assert struct.unpack("<4I", rows_of(out, "EquipParamWeapon")[2000].data) == (5, 60, 7, 80) and not rep.conflicts


def test_rows_a_pack_lacks_are_kept_and_other_versions_are_skipped_and_said():
    drops = pack({"EquipParamWeapon": lambda p: p.rows.pop()})  # made from older data without row 2000
    wide = regulation(
        {"EquipParamWeapon": table("EQUIP_PARAM_WEAPON_ST", [(1000, row(9, stride=20))], stride=20)}, "11600000"
    )
    out, rep = pm.combine(vanilla(), [("drops", drops), ("wide", wide)])
    assert set(rows_of(out, "EquipParamWeapon")) == {1000, 2000}
    wide_rep = rep.packs[1]
    assert wide_rep.skipped and "another game version" in wide_rep.skipped[0]
    assert any("made for regulation 11600000" in line for line in rep.lines())


def test_a_table_the_game_lacks_comes_from_the_last_pack():
    extra = regulation(
        {
            "EquipParamWeapon": table("EQUIP_PARAM_WEAPON_ST", [(1000, row(1, 2, 3, 4)), (2000, row(5, 6, 7, 8))]),
            "SpEffectParam": table("SP_EFFECT_PARAM_ST", [(10, row(9, 9, 9, 9))]),
            "ModOnlyParam": table("MOD_ONLY_ST", [(1, row(1))]),
        }
    )
    out, _rep = pm.combine(vanilla(), [("x", extra)])
    assert set(rows_of(out, "ModOnlyParam")) == {1}


def test_unchanged_packs_leave_the_games_file_as_it_was():
    out, rep = pm.combine(vanilla(), [("same", vanilla())])
    base = formats.regulation.read_regulation(vanilla())
    assert (
        formats.regulation.binder_bytes(formats.regulation.read_regulation(out).bnd)
        == formats.regulation.binder_bytes(base.bnd)
        and rep.tables == 0
    )


# ----------------------------------------------------------------------------- in a profile
@pytest.fixture
def prof(tmp_path, monkeypatch):
    game = tmp_path / "Game"
    game.mkdir()
    (game / "regulation.bin").write_bytes(vanilla())
    monkeypatch.setattr(common, "game_dir", lambda: game)
    monkeypatch.setattr(common, "game_running", lambda: False)
    base = tmp_path / "profiles" / "er"
    text = "# mine\n"
    for name, raw in (
        ("balance", pack({"EquipParamWeapon": set_word(1000, 0, 111)})),
        ("effects", pack({"SpEffectParam": set_word(10, 1, 42)})),
    ):
        (base / "mod" / name).mkdir(parents=True)
        (base / "mod" / name / "regulation.bin").write_bytes(raw)
        text += f"[[packages]]\nid = \"{name}\"\npath = 'mod/{name}'\n\n"
    (base / "mod" / "textures" / "parts").mkdir(parents=True)
    text += "[[packages]]\nid = \"textures\"\npath = 'mod/textures'\n"
    p = base / "p.me3"
    p.write_text(text, encoding="utf-8")
    return p


def test_stacked_packs_can_be_combined_and_then_stay_checked(prof):
    h = merge.health(prof)
    assert h["state"] == "stacked" and h["can_combine"] and h["winner"] == "effects"
    out = merge.rebuild(prof, lambda s: None, combine=True)
    assert "combine" in out["backend"]
    ids = [e["id"] for e in M.entries(prof) if e["kind"] == "package"]
    assert ids == ["balance", "effects", "combined-parameters", "textures"]  # right after the last pack
    got = prof.parent / "mod" / "combined-parameters" / "regulation.bin"
    assert struct.unpack("<I", rows_of(got.read_bytes(), "EquipParamWeapon")[1000].data[:4])[0] == 111
    assert struct.unpack("<4I", rows_of(got.read_bytes(), "SpEffectParam")[10].data)[1] == 42
    h = merge.health(prof)
    assert h["state"] == "current" and h["combine"] and h["winner"] == "combined-parameters"
    assert "# mine" in prof.read_text(encoding="utf-8")
    (prof.parent / "mod" / "effects" / "regulation.bin").write_bytes(pack({"SpEffectParam": set_word(10, 1, 43)}))
    assert "effects's regulation.bin changed" in merge.health(prof)["reasons"][0]
    merge.rebuild(prof, lambda s: None)
    assert merge.health(prof)["state"] == "current"
    record = json.loads((prof.parent / "mod" / "combined-parameters" / builtin.RECORD).read_text())
    assert [p["name"] for p in record["packs"]] == ["balance", "effects"] and record["base_sha256"]


def test_a_pack_placed_after_the_combined_one_is_moved_behind_on_rebuild(prof):
    merge.rebuild(prof, lambda s: None, combine=True)
    late = prof.parent / "mod" / "late"
    late.mkdir()
    late.joinpath("regulation.bin").write_bytes(pack({"SpEffectParam": set_word(10, 3, 7)}))
    prof.write_text(
        prof.read_text(encoding="utf-8") + "\n[[packages]]\nid = \"late\"\npath = 'mod/late'\n", encoding="utf-8"
    )
    h = merge.health(prof)
    assert h["state"] == "stale" and any("late ships parameters now" in r for r in h["reasons"])
    merge.rebuild(prof, lambda s: None)
    ids = [e["id"] for e in M.entries(prof) if e["kind"] == "package"]
    assert ids.index("combined-parameters") > ids.index("late") and merge.health(prof)["state"] == "current"


def test_a_game_update_or_a_removed_pack_makes_the_combine_stale(prof):
    merge.rebuild(prof, lambda s: None, combine=True)
    game = common.game_dir() / "regulation.bin"
    game.write_bytes(pack({"EquipParamWeapon": set_word(2000, 0, 1)}))
    assert any("game update" in r for r in merge.health(prof)["reasons"])
    merge.rebuild(prof, lambda s: None)
    idx = next(e["index"] for e in M.entries(prof) if e["name"] == "balance")
    M.uninstall(prof, idx)
    assert any("balance was combined but is no longer loaded" in r for r in merge.health(prof)["reasons"])


def test_one_pack_alone_is_not_combined_unless_asked(prof):
    idx = next(e["index"] for e in M.entries(prof) if e["name"] == "balance")
    M.uninstall(prof, idx)
    assert merge.health(prof)["state"] == "single"
    with pytest.raises(merge.MergeError, match="nothing to combine"):
        merge.rebuild(prof, lambda s: None)


def test_with_an_overlay_tool_the_combine_sits_right_before_it_and_feeds_it(tmp_path, monkeypatch):
    from test_mod_merge import World

    w = World(tmp_path, monkeypatch)
    (w.game / "regulation.bin").write_bytes(vanilla())
    for name, edit in (("a", set_word(1000, 0, 111)), ("b", set_word(2000, 3, 222))):
        d = w.pack(name)
        (d / "regulation.bin").write_bytes(pack({"EquipParamWeapon": edit}))
    h = merge.health(w.profile)
    assert h["state"] == "stale" and h["can_combine"] and not h["combine"]
    merge.rebuild(w.profile, lambda s: None)  # two packs before the overlay: combined first, then its tool
    ids = [e["id"] for e in M.entries(w.profile) if e["kind"] == "package"]
    assert ids == ["parts", "a", "b", "combined-parameters", "last"]
    h = merge.health(w.profile)
    assert h["state"] == "current" and h["combine"] and h["backend"] == "the rebuild tool of last"
    sources = json.loads((w.base / "Merger" / "installation.json").read_text())["sources"]
    used = [s["path"].replace("\\", "/") for s in sources]
    assert any(p.endswith("combined-parameters/regulation.bin") for p in used), used  # the tool took the combined file
    combined = rows_of((w.base / "mod" / "combined-parameters" / "regulation.bin").read_bytes(), "EquipParamWeapon")
    assert struct.unpack("<4I", combined[1000].data)[0] == 111 and struct.unpack("<4I", combined[2000].data)[3] == 222


def test_the_combined_package_is_listed_for_the_overlay_so_me3_loads_it_before_it(tmp_path, monkeypatch):
    from test_mod_merge import World

    from roundtable_souls.mods import profile as P

    w = World(tmp_path, monkeypatch)
    (w.game / "regulation.bin").write_bytes(vanilla())
    for name in ("a", "b"):
        (w.pack(name) / "regulation.bin").write_bytes(pack({"EquipParamWeapon": set_word(1000, 1, 5)}))
    merge.ensure_combined(w.profile, merge.overlay(w.profile)[0])  # before the tool rewrites anything
    text = w.profile.read_text(encoding="utf-8")
    assert '{ id = "combined-parameters", optional = true }' in text.split('id = "last"')[1]
    order = [r["id"] for r in P.me3_order(w.profile, text).rows]
    assert order.index("combined-parameters") < order.index("last")


def test_two_packs_before_a_tool_without_a_combine_are_stacked(tmp_path, monkeypatch):
    from test_mod_merge import World

    w = World(tmp_path, monkeypatch)
    (w.game / "regulation.bin").write_bytes(vanilla())
    for name in ("a", "b"):
        (w.pack(name) / "regulation.bin").write_bytes(pack({"EquipParamWeapon": set_word(1000, 1, 5)}))
    merge.rebuild(w.profile, lambda s: None, combine=False)  # only the tool, as before
    h = merge.health(w.profile)
    assert h["state"] == "stacked" and "only b's reach it" in h["reasons"][0]
