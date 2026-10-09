"""The game configuration (data/games/eldenring.json) and the DCX layouts the launcher writes, which must be the ones
it records as loaded in game."""

import json
import struct

import pytest

from roundtable_souls import formats
from roundtable_souls.formats import dcx
from roundtable_souls.game import archives, config

KRAK_HEADER = (
    b"DCX\0"
    + struct.pack(">IIIII", 0x11000, 0x18, 0x24, 0x44, 0x4C)
    + b"DCS\0"
    + struct.pack(">II", 0, 0)
    + b"DCP\0KRAK"
    + struct.pack(">I", 0x20)
    + bytes([6, 0, 0, 0])
    + struct.pack(">III", 0, 0, 0)
    + struct.pack(">I", 0x10100)
    + b"DCA\0"
    + struct.pack(">I", 8)
)


def test_elden_ring_config_loads_and_names_every_archive_key():
    er = config.load()
    assert er.game == "eldenring" and archives.ARCHIVES == tuple(er.archive_names)
    assert set(er.archives) == set(er.archive_names)
    assert all(k.startswith("-----BEGIN RSA PUBLIC KEY-----") for k in er.archives.values())


def test_the_published_schema_is_the_models():
    assert json.loads(config.schema_path().read_text(encoding="utf-8")) == config.schema()


def test_the_writer_writes_exactly_the_layouts_the_config_records():
    w = config.load().dcx_writer
    assert (w.krak.level, w.krak.header_level) == (dcx.KRAKEN_LEVEL, dcx.KRAKEN_LEVEL)
    assert (w.dflt.level, w.dflt.header_level) == (dcx.DFLT_FALLBACK_LEVEL, dcx.DFLT_FALLBACK_LEVEL)
    assert (w.zstd.level, w.zstd.window_log, w.zstd.content_size) == (dcx.ZSTD_LEVEL, dcx.ZSTD_WINDOW_LOG, False)


def test_dflt_fallback_only_for_file_types_the_game_loaded_so():
    er = config.load()
    assert er.dflt_fallback_for("msg/engus/menu_dlc02.msgbnd.dcx")
    assert er.dflt_fallback_for("chr\\c0000_a00_hi.anibnd.dcx")
    assert not er.dflt_fallback_for("chr/c0000.behbnd.dcx")


def test_the_file_category_map_loads_with_plain_labels():
    er = config.load()
    assert er.file_categories and all(c.pattern == c.pattern.lower() and c.label for c in er.file_categories)
    assert er.category_of("regulation.bin") == "parameters"
    assert er.category_of("action/script/c0000.hks") == "behaviour scripts"
    assert er.category_of("script/talk/m00_00_00_00.talkesdbnd.dcx") == "NPC and grace menus"
    assert er.category_of("script/c0000.luabnd.dcx") == "scripts"
    assert er.category_of("parts/am_m_1000.partsbnd.dcx") == "equipment models"


def test_the_player_is_told_apart_from_other_characters():
    er = config.load()
    assert er.category_of("chr/c0000_a00_hi.anibnd.dcx") == "the player character's animations"
    assert er.category_of("chr/c2010.chrbnd.dcx") == "characters"


def test_case_and_backslashes_do_not_matter_and_unknown_paths_have_none():
    er = config.load()
    assert er.category_of("CHR\\C0000_A00_HI.ANIBND.DCX") == "the player character's animations"
    assert er.category_of("Msg\\engUS\\item.msgbnd.dcx") == "text"
    assert er.category_of("readme.txt") is None and er.category_of("notmine/thing.bin") is None


def test_the_first_rule_that_matches_wins():
    rules = [config.FileCategory(pattern="chr/c1*", label="first"), config.FileCategory(pattern="chr/*", label="all")]
    er = config.load().model_copy(update={"file_categories": rules})
    assert er.category_of("chr/c1000.chrbnd.dcx") == "first" and er.category_of("chr/c2000.chrbnd.dcx") == "all"
    reversed_ = er.model_copy(update={"file_categories": rules[::-1]})
    assert reversed_.category_of("chr/c1000.chrbnd.dcx") == "all"


def test_a_category_rule_takes_only_a_pattern_and_a_label():
    with pytest.raises(ValueError):
        config.FileCategory.model_validate({"pattern": "chr/*", "label": "characters", "extra": 1})


def test_a_kraken_file_without_oodle_is_written_as_dflt_only_when_allowed():
    how = dcx.Dcx(KRAK_HEADER, b"KRAK")
    with pytest.raises(formats.FormatError):
        dcx.pack(b"body" * 100, how)  # no Oodle, no fallback: stop with the reason
    out = dcx.pack(b"body" * 100, how, dflt_fallback=True)
    assert out[0x28:0x2C] == b"DFLT" and out[0x30] == 9
    body, again = dcx.unpack(out)
    assert body == b"body" * 100 and again is not None and again.kind == b"DFLT"


def test_a_zstd_file_gets_the_frame_the_game_reads():
    header = bytearray(KRAK_HEADER)
    header[0x28:0x2C] = b"ZSTD"
    body = bytes(range(256)) * 600  # several 64 KB blocks
    out = dcx.pack(body, dcx.Dcx(bytes(header), b"ZSTD"))
    frame = out[dcx.DCX_DATA_OFFSET :]
    assert frame[:4] == bytes.fromhex("28b52ffd") and frame[4] == 0  # no content size, no checksum
    assert frame[5] <= (dcx.ZSTD_WINDOW_LOG - 10) << 3  # a window of at most 64 KB
    assert dcx.unpack(out)[0] == body
