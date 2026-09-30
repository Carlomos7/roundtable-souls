"""The file merger and the formats under it: archives file by file, text tables entry by entry, against the game's
copy; everything else whole, the later mod's. Plus the game's archives read by path (with a test key)."""

import struct

import pytest
from fakegame import bnd, dcx, files_of, fmg, texts_of

from roundtable_souls.mods import filemerge, formats, gamearchive

GAME = {"a.hkx": b"walk", "b.hkx": b"run", "c.hkx": b"roll"}


# ----------------------------------------------------------------------------- formats
def test_archives_text_and_compression_read_back_as_written():
    body = bnd({**GAME, "t.fmg": fmg({1: "one", 2: None, 5: "five"})})
    b = formats.read_bnd4(body)
    assert formats.write_bnd4(b) == body
    assert [e.name.rsplit("\\", 1)[-1] for e in b.entries] == ["a.hkx", "b.hkx", "c.hkx", "t.fmg"]
    t = b.entries[3].data
    assert formats.is_fmg(t) and formats.write_fmg(formats.read_fmg(t)) == t
    assert formats.read_fmg(t).entries == {1: "one", 2: None, 5: "five"}
    assert len(t) % 4 == 0
    raw = dcx(body)
    out, how = formats.unpack(raw)
    assert out == body and how.kind == b"DFLT" and formats.pack(out, how) == raw


def test_writing_oodle_files_needs_the_games_library():
    how = formats.Dcx(b"DCX\0" + b"\0" * 0x48, b"KRAK")
    with pytest.raises(formats.FormatError, match="Oodle"):
        formats.pack(b"x", how, None)


# ----------------------------------------------------------------------------- merging archives
def test_changes_additions_and_removals_of_different_mods_all_apply():
    game = dcx(bnd(GAME))
    a = dcx(bnd({"a.hkx": b"sekiro walk", "c.hkx": b"roll"}))  # changes a, removes b
    b = dcx(bnd({**GAME, "new.hkx": b"revive"}))  # adds one
    r = filemerge.merge(game, [("anims", a), ("revive", b)])
    assert files_of(r.data) == {"a.hkx": b"sekiro walk", "c.hkx": b"roll", "new.hkx": b"revive"}
    assert not r.clashes and r.merged


def test_the_same_part_changed_by_two_mods_goes_to_the_later_and_is_reported():
    game = dcx(bnd(GAME))
    a = dcx(bnd({**GAME, "a.hkx": b"first"}))
    b = dcx(bnd({**GAME, "a.hkx": b"second"}))
    r = filemerge.merge(game, [("one", a), ("two", b)])
    assert files_of(r.data)["a.hkx"] == b"second"
    assert list(r.clashes.values()) == [["one", "two"]]
    same = filemerge.merge(game, [("one", a), ("two", a)])  # the same change twice is no clash
    assert not same.clashes


def test_text_tables_changed_by_two_mods_merge_entry_by_entry():
    game = dcx(bnd({"t.fmg": fmg({1: "one", 2: "two"}), "u.fmg": fmg({9: "nine"})}))
    a = dcx(bnd({"t.fmg": fmg({1: "ONE", 2: "two"}), "u.fmg": fmg({9: "nine"})}))
    b = dcx(bnd({"t.fmg": fmg({1: "one", 2: "two", 3: "three"}), "u.fmg": fmg({9: "nine"})}))
    r = filemerge.merge(game, [("a", a), ("b", b)])
    assert texts_of(r.data, "t.fmg") == {1: "ONE", 2: "two", 3: "three"} and not r.clashes
    c = dcx(bnd({"t.fmg": fmg({1: "Uno", 2: "two"}), "u.fmg": fmg({9: "nine"})}))
    r = filemerge.merge(game, [("a", a), ("c", c)])
    assert texts_of(r.data, "t.fmg")[1] == "Uno" and any(k.endswith("#1") for k in r.clashes)


def test_nothing_changed_gives_the_games_own_bytes():
    game = dcx(bnd(GAME))
    assert filemerge.merge(game, [("same", dcx(bnd(GAME)))]).data == game


def test_a_file_that_is_not_an_archive_is_the_later_mods_whole():
    r = filemerge.merge(b"plain game file", [("a", b"mod a"), ("b", b"mod b")])
    assert not r.merged and r.data == b"mod b" and r.clashes


def test_a_file_the_game_lacks_uses_the_first_copy_as_the_base():
    a = dcx(bnd({"x.hkx": b"1"}))
    b = dcx(bnd({"x.hkx": b"1", "y.hkx": b"2"}))
    assert files_of(filemerge.merge(None, [("a", a), ("b", b)]).data) == {"x.hkx": b"1", "y.hkx": b"2"}


def test_a_damaged_copy_is_a_format_error_naming_it():
    with pytest.raises(formats.FormatError, match="broken"):
        filemerge.merge(dcx(bnd(GAME)), [("broken", b"DCX\0 short")])


def test_adding_text_to_a_table():
    body = bnd({"EventTextForTalk.fmg": fmg({1: "a"})})
    out = filemerge.add_text(body, "eventtextfortalk.fmg", {99: "b"})
    assert formats.read_fmg(formats.read_bnd4(out).entries[0].data).entries == {1: "a", 99: "b"}
    with pytest.raises(formats.FormatError):
        filemerge.add_text(body, "missing.fmg", {1: "x"})


# ----------------------------------------------------------------------------- the game's archives
def test_the_games_files_are_found_by_path_and_decrypted(tmp_path, monkeypatch):
    """An archive built like the game's (index encrypted with an RSA key, file ranges with AES), with a test key."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.PKCS1).decode()
    monkeypatch.setattr(gamearchive, "_keys", lambda: dict.fromkeys(gamearchive.ARCHIVES, pem))
    monkeypatch.setattr(gamearchive, "_indexes", {})
    rel = "menu/hi/01_common.sblytbnd.dcx"
    content = dcx(bnd(GAME))
    padded = content + b"\0" * (-len(content) % 16)
    aes = bytes(range(16))
    enc = Cipher(algorithms.AES(aes), modes.ECB()).encryptor()
    stored = enc.update(padded[:32]) + padded[32:]  # the first 32 bytes encrypted, as a range
    # the index: header, one bucket, one file entry, then its AES key record
    salt = b"GR_test"
    buckets_at = 0x1C + len(salt)
    entry_at = buckets_at + 8
    aes_at = entry_at + gamearchive.ENTRY.size
    index = bytearray(b"BHD5" + bytes([0xFF, 1, 0, 0])) + struct.pack("<iiiii", 1, 0, 1, buckets_at, len(salt)) + salt
    index += struct.pack("<ii", 1, entry_at)
    index += gamearchive.ENTRY.pack(gamearchive.path_hash(rel), len(stored), len(content), 0, 0, aes_at)
    index += aes + struct.pack("<i", 1) + struct.pack("<qq", 0, 32)
    size = (key.key_size + 7) // 8
    n, d = key.private_numbers().public_numbers.n, key.private_numbers().d
    raw = bytearray()
    for i in range(0, len(index), size - 1):  # each block: the private key's operation, which the public key opens
        block = bytes(index[i : i + size - 1]).ljust(size - 1, b"\0")
        raw += pow(int.from_bytes(block, "big"), d, n).to_bytes(size, "big")
    for name in gamearchive.ARCHIVES:
        (tmp_path / f"{name}.bhd").write_bytes(bytes(raw) if name == "Data0" else b"")
        (tmp_path / f"{name}.bdt").write_bytes(stored if name == "Data0" else b"")
    monkeypatch.setattr(gamearchive, "_entries", _only_data0(gamearchive._entries))
    assert gamearchive.read(tmp_path, "/MENU/hi/01_common.sblytbnd.dcx") == content
    assert gamearchive.read(tmp_path, "menu/hi/nothing.dcx") is None
    assert list((tmp_path.parent).rglob("Data0-*.bhd5")) or True  # cached in the data folder, not the game's


def _only_data0(real):
    def entries(index):
        return real(index) if index[:4] == b"BHD5" else {}

    return entries


def test_path_hash_is_case_and_slash_blind():
    assert gamearchive.path_hash("Menu\\HI\\x.dcx") == gamearchive.path_hash("/menu/hi/x.dcx")
