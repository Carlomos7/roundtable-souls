"""The game-file readers on synthetic files: an encrypted regulation and a mod's item text archive."""

import json
import struct
import zlib
from compression import zstd

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from roundtable_souls import formats
from roundtable_souls.mods import item_names as N
from roundtable_souls.saves import analyze as A


def param(ids):
    rows = b"".join(struct.pack("<IiqQ", i, 0, 0, 0) for i in ids)
    head = bytearray(0x40)
    struct.pack_into("<H", head, 0x0A, len(ids))
    return bytes(head) + rows


def fmg(entries):
    ids = sorted(entries)
    groups = [(k, i, i) for k, i in enumerate(ids)]
    head = bytearray(0x28)
    struct.pack_into("<ii", head, 0x0C, len(groups), len(ids))
    group_bytes = b"".join(struct.pack("<iiii", k, lo, hi, 0) for k, lo, hi in groups)
    offsets_at = 0x28 + len(group_bytes)
    strings_at = offsets_at + 8 * len(ids)
    strings, offsets = b"", []
    for i in ids:
        offsets.append(strings_at + len(strings))
        strings += entries[i].encode("utf-16-le") + b"\0\0"
    struct.pack_into("<q", head, 0x18, offsets_at)
    return bytes(head) + group_bytes + b"".join(struct.pack("<q", o) for o in offsets) + strings


def bnd4(files):
    n = len(files)
    header = bytearray(0x40)
    header[:4] = b"BND4"
    struct.pack_into("<i", header, 0x0C, n)
    struct.pack_into("<q", header, 0x10, 0x40)
    struct.pack_into("<q", header, 0x20, 36)
    header[0x30], header[0x31] = 1, 0x74
    names_at = 0x40 + 36 * n
    names = b""
    name_offsets = []
    for name, _ in files:
        name_offsets.append(names_at + len(names))
        names += name.encode("utf-16-le") + b"\0\0"
    data_at = names_at + len(names)
    entries, blobs = b"", b""
    for (_name, blob), name_off in zip(files, name_offsets, strict=True):
        # flags(1) pad(3), -1, compressed size, uncompressed size, data offset, id, name offset
        entries += bytes([0x40, 0, 0, 0]) + struct.pack(
            "<iqqIII", -1, len(blob), len(blob), data_at + len(blobs), 0, name_off
        )
        blobs += blob
    return bytes(header) + entries + names + blobs


def dcx(body, kind=b"ZSTD"):
    payload = zstd.compress(body) if kind == b"ZSTD" else zlib.compress(body)
    head = bytearray(0x4C)
    head[:4] = b"DCX\0"
    struct.pack_into(">iiiii", head, 4, 0x11000, 0x18, 0x24, 0x44, 0x4C)
    head[0x18:0x1C] = b"DCS\0"
    struct.pack_into(">II", head, 0x1C, len(body), len(payload))
    head[0x24:0x28] = b"DCP\0"
    head[0x28:0x2C] = kind
    return bytes(head) + payload


def encrypt(plain):
    padded = plain + bytes(-len(plain) % 16)
    iv = bytes(range(16))
    enc = Cipher(algorithms.AES(formats.regulation.REGULATION_KEY), modes.CBC(iv)).encryptor()
    return iv + enc.update(padded) + enc.finalize()


def test_regulation_items_are_read_from_every_item_table():
    body = bnd4(
        [
            ("N:\\GR\\param\\EquipParamWeapon.param", param([0, 3560000, 3560001])),
            ("N:\\GR\\param\\EquipParamProtector.param", param([5350000])),
            ("N:\\GR\\param\\EquipParamGoods.param", param([2004330])),
            ("N:\\GR\\param\\SpEffectParam.param", param([1, 2, 3])),
        ]
    )
    ids = formats.regulation.regulation_item_ids(encrypt(dcx(body)))
    assert ids == {3560000, 3560001, 0x10000000 | 5350000, 0x40000000 | 2004330}
    with pytest.raises(formats.FormatError):
        formats.regulation.regulation_item_ids(encrypt(dcx(bnd4([("x.param", param([1]))]))))
    with pytest.raises(formats.FormatError):
        formats.regulation.regulation_item_ids(b"not a regulation")


def test_game_items_count_as_game_items_even_when_unlisted():
    game = frozenset({0x10000000 | 5350000, 3560000})
    catalog = A.Catalog(frozenset(), pack=False, game=game)
    assert catalog.is_game_item(0x10000000 | 5350000) and catalog.is_game_item(3560008)  # +8 of a game weapon
    assert not catalog.is_game_item(0x10000000 | 742000)
    # with the game's tables available, the pack flag no longer excuses unlisted equipment
    assert not A.Catalog(frozenset(), pack=True, game=game).is_game_item(0x10000000 | 742000)
    assert A.Catalog(frozenset(), pack=True).is_game_item(0x10000000 | 742000)  # fallback without the tables


def test_dcx_needs_oodle_for_krak():
    with pytest.raises(formats.FormatError):
        formats.dcx.dcx_decompress(dcx(b"x")[:0x28] + b"KRAK" + dcx(b"x")[0x2C:], oodle=None)


def fake_mods(tmp_path, monkeypatch, seamless=True):
    game = tmp_path / "Game"
    game.mkdir()
    profiles = tmp_path / "profiles"
    msg = profiles / "CoolArmour" / "msg" / "engus"
    msg.mkdir(parents=True)
    text = bnd4(
        [
            ("ProtectorName.fmg", fmg({742000: "Cool Helm", 742100: "Cool Armour"})),
            ("GoodsName_dlc01.fmg", fmg({900: "Cool Potion"})),
        ]
    )
    (msg / "item_dlc01.msgbnd.dcx").write_bytes(dcx(text, b"DFLT"))
    if seamless:
        locale = game / "SeamlessCoop" / "locale"
        locale.mkdir(parents=True)
        (locale / "english.json").write_text(
            json.dumps({"MODGOODSNAME_HOSTINGITEM": "Tiny Great Pot", "MODGOODSNAME_DRIEDFINGERITEM": "Dried Fingers"}),
            encoding="utf-8",
        )
    monkeypatch.setattr(N.common, "game_dir", lambda: game)
    monkeypatch.setattr(N.common, "me3_profiles_dir", lambda: profiles)
    monkeypatch.setattr(N, "_CACHE", None)


def test_names_come_from_the_installed_mods(tmp_path, monkeypatch):
    fake_mods(tmp_path, monkeypatch)
    names = N.item_names(refresh=True)
    assert names.get(0x40000000 | 8380001) == ("Tiny Great Pot", "Seamless Co-op")
    assert names.get(0x40000000 | 8380012) == ("Dried Fingers", "Seamless Co-op")
    assert names.get(0x10000000 | 742000) == ("Cool Helm", "CoolArmour")
    assert names.get(0x40000000 | 900) == ("Cool Potion", "CoolArmour")
    assert names.get(0x10000000 | 5) is None


def test_seamless_ids_are_named_even_without_the_mod(tmp_path, monkeypatch):
    fake_mods(tmp_path, monkeypatch, seamless=False)
    names = N.item_names(refresh=True)
    assert names.get(0x40000000 | 8380003) == ("Seamless Co-op item 8380003", "Seamless Co-op")
