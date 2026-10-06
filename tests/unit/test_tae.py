"""formats.tae and merging.rules.tae: Elden Ring animation events read and written structurally, and merged animation
by animation against the game's file. Built files only (the game's and the mods' own: scripts/verify/tae_*.py)."""

import copy
import struct

import pytest
from fakegame import bnd, dcx, files_of

from roundtable_souls import formats
from roundtable_souls.formats.tae import (
    IMPORT,
    STANDARD,
    TAE,
    Animation,
    Event,
    EventGroup,
    animation_key,
    header_key,
    is_tae,
    read_tae,
    write_tae,
    written_as,
)
from roundtable_souls.merging import merger
from roundtable_souls.merging.rules import tae as rule

FOREVER = 3.4028234663852886e38  # float.MaxValue: an event that lasts to the animation's end
FLAGS = b"\x01\x00\x01\x02\x02\x01\x01\x01"


def params(*values: int, size: int = 16) -> bytes:
    raw = b"".join(struct.pack("<i", v) for v in values)
    return raw + bytes(-len(raw) % size)


def standard(source: int | None = None) -> bytes:
    """A standard header: loop off, motion data from `source` when given."""
    return bytes([0, 1 if source is not None else 0, 0, 0]) + struct.pack("<i", source or 0)


def anim(anim_id: int, *events: Event, name: str | None = "a000.hkt", groups=(), header=None) -> Animation:
    return Animation(anim_id, STANDARD, header or standard(), name, list(events), list(groups))


def stored(t: TAE) -> TAE:
    """t as a file stores it: written once and read back. Parameters then carry the padding their place gives them, so
    models built here compare exactly with what comes back from a file."""
    return read_tae(write_tae(t))


def built_game_tae() -> TAE:
    return TAE(
        2000,
        37,
        FLAGS,
        "skeleton.hkt",
        "c9990.SIB",
        [
            anim(0, Event(0.0, FOREVER, 16, 0, params(1)), name="a000_000000.hkt"),
            anim(
                1,
                Event(0.0, 0.5, 129, 0, params(7, 8, 9)),
                Event(0.1, 0.4, 700, 2, params(3)),
                Event(0.1, 0.2, 16, 0, b""),
                groups=[EventGroup(129, [1, 0]), EventGroup(700, [2])],
            ),
            anim(2, Event(0.3, 0.6, 16, 102, params(5)), name=None),
            Animation(3, IMPORT, struct.pack("<ii", 23031900, -1), "a023_031900.hkt"),
            anim(10, Event(0.0, 1.0, 1, 0, params(2)), header=standard(1)),
            Animation(11, STANDARD, None, None),
        ],
    )


def game_tae() -> TAE:
    return stored(built_game_tae())


def tae_bytes(t: TAE) -> bytes:
    return write_tae(t)


def with_anims(t: TAE, *changes: Animation, drop: tuple[int, ...] = (), **header) -> TAE:
    """A copy of t with these animations replaced or added (by ID), those in drop left out, header fields set."""
    t = copy.deepcopy(t)
    by_id = {a.id: a for a in t.animations}
    for a in changes:
        by_id[a.id] = a
    t.animations = [by_id[i] for i in sorted(by_id) if i not in drop]
    for k, v in header.items():
        setattr(t, k, v)
    return stored(t)


def keys(t: TAE) -> list:
    return [animation_key(a) for a in t.animations]


# ----------------------------------------------------------------------------- the format
def test_a_written_file_reads_back_to_the_same_model_and_the_same_bytes():
    built = built_game_tae()
    data = write_tae(built)
    assert is_tae(data) and len(data) == struct.unpack_from("<i", data, 12)[0]
    back = read_tae(data)
    differences, padded = written_as(built, back)
    assert differences == []
    # params(1) is 16 bytes; animation 0 has one event, whose data starts 8 bytes past a 16-byte boundary
    assert padded == ["animation 0 event 0: 8 zero bytes of padding added", *padded[1:]]
    assert back == read_tae(write_tae(back)) and write_tae(back) == data  # once stored, every field exactly
    assert back.animations[3].source_id == 23031900 and back.animations[4].source_id == 1
    assert back.animations[1].source_id is None


def test_the_header_names_and_animation_groups_are_where_the_game_keeps_them():
    data = write_tae(game_tae())
    skel, sib = struct.unpack_from("<qq", data, 0xB0)
    assert (skel, sib) == (0xD0, 0xF0)  # the skeleton name right after the header; the sib name 16-aligned after it
    assert data[0xD0:0xEA].decode("utf-16-le") == "skeleton.hkt\0"
    assert struct.unpack_from("<q", data, 0x30)[0] == 37
    groups_off = struct.unpack_from("<q", data, 0x60)[0]
    count, at = struct.unpack_from("<qq", data, groups_off)
    runs = [struct.unpack_from("<ii", data, at + 16 * k) for k in range(count)]
    assert runs == [(0, 3), (10, 11)]  # runs of consecutive animation IDs


def test_no_file_name_and_an_empty_one_are_kept_apart_but_compare_equal():
    t = game_tae()
    rewritten = copy.deepcopy(t)
    rewritten.animations[2].file_name = ""  # how a tool that rewrites the file stores "no name"
    data = write_tae(rewritten)
    assert read_tae(data).animations[2].file_name == ""
    assert read_tae(write_tae(t)).animations[2].file_name is None
    assert data != write_tae(t)
    assert keys(read_tae(data)) == keys(t)


def test_an_edited_file_reads_back_as_edited():
    t = game_tae()
    e = copy.deepcopy(t)
    e.event_bank = -1
    e.animations[1].events.pop(0)  # 3 events become 2: the new first event's data moves onto a 16-byte boundary
    e.animations[1].groups = [EventGroup(129, [0]), EventGroup(700, [1])]
    e.animations[2].events[0].params = b"\x05" + bytes(23)  # same length, a changed value
    back = read_tae(write_tae(e))
    assert written_as(e, back) == ([], [])  # exactly as edited: no event's padding changed here
    assert header_key(back) == header_key(e) and keys(back) == keys(e)


def test_padding_that_grows_on_rewriting_is_reported_not_hidden():
    t = game_tae()
    e = copy.deepcopy(t)
    e.animations[1].events.pop()  # 3 events become 2: the first event's data now starts on a 16-byte boundary
    e.animations[1].groups = [EventGroup(129, [1, 0])]
    e.animations[1].events.pop()  # and 1: it starts 8 bytes past one again, so its stored bytes get 8 more
    e.animations[1].groups = [EventGroup(129, [0])]
    e.animations[1].events[0].params = params(7, 8, 9)  # 16 bytes written where 8 bytes of padding follow
    back = read_tae(write_tae(e))
    assert written_as(e, back) == ([], ["animation 1 event 0: 8 zero bytes of padding added"])
    assert keys(back) != keys(e)  # an exact comparison sees the difference; only written_as names it padding
    changed = copy.deepcopy(back)
    changed.animations[1].events[0].params = back.animations[1].events[0].params[:-1] + b"\x01"
    assert written_as(e, changed)[0] == ["animation 1 event 0: parameters"]  # a non-zero byte is never padding
    shorter = copy.deepcopy(back)
    shorter.animations[1].events[0].params = e.animations[1].events[0].params[:-4]
    assert written_as(e, shorter)[0] == ["animation 1 event 0: parameters"]  # neither is a missing zero field


def test_layouts_this_code_does_not_know_are_refused():
    data = bytearray(write_tae(game_tae()))
    older = bytearray(data)
    struct.pack_into("<i", older, 8, 0x1000C)  # Dark Souls III / Bloodborne
    assert not is_tae(bytes(older))
    with pytest.raises(formats.FormatError):
        read_tae(bytes(older))
    count2 = bytearray(data)
    struct.pack_into("<q", count2, 0x70, 99)
    with pytest.raises(formats.FormatError, match="counts"):
        read_tae(bytes(count2))
    groups = bytearray(data)
    at = struct.unpack_from("<q", data, struct.unpack_from("<q", data, 0x60)[0] + 8)[0]
    struct.pack_into("<i", groups, at + 4, 2)  # a group that is not a run of consecutive IDs
    with pytest.raises(formats.FormatError, match="runs"):
        read_tae(bytes(groups))


def test_event_groups_must_hold_the_animations_own_events_once():
    t = game_tae()
    twice = copy.deepcopy(t)
    twice.animations[1].groups = [EventGroup(129, [0]), EventGroup(700, [0])]
    with pytest.raises(ValueError, match="more than one group"):
        write_tae(twice)
    outside = copy.deepcopy(t)
    outside.animations[1].groups = [EventGroup(129, [5])]
    with pytest.raises(ValueError, match="not one of its events"):
        write_tae(outside)


# ----------------------------------------------------------------------------- the rule
def test_parameters_differing_only_in_trailing_zero_bytes_are_a_change():
    """Without the event type's parameter size, zero padding cannot be told from parameters that are zero, so such a
    copy counts as changed: taken when it is the only change, a clash when another mod changed the animation too."""
    game = game_tae()
    base = game.animations[4].events[0].params  # animation 10's single event: 24 bytes as stored
    longer = with_anims(game, anim(10, Event(0.0, 1.0, 1, 0, base + bytes(16)), header=standard(1)))
    assert longer.animations[4].events[0].params == base + bytes(16)
    assert animation_key(longer.animations[4]) != animation_key(game.animations[4])
    r = rule.merge(tae_bytes(game), [("zeros", tae_bytes(longer))], "a00.tae")
    assert r.changed == {"a00.tae": ["zeros"]} and r.notes["a00.tae"] == ["zeros: changed 1 (10)"]
    assert read_tae(r.data).animations[4].events[0].params == base + bytes(16)
    other = with_anims(game, anim(10, Event(0.0, 1.0, 1, 0, params(3)), header=standard(1)))
    r = rule.merge(tae_bytes(game), [("zeros", tae_bytes(longer)), ("other", tae_bytes(other))], "a00.tae")
    assert r.clashes == {"a00.tae#10": ["zeros", "other"]}


def test_merged_animations_keep_their_parameter_bytes_exactly():
    """Every animation starts on a 16-byte boundary and moves by multiples of 16 when others are added, so its
    events' padding, and so their stored bytes, stay as in the copy it came from."""
    game = game_tae()
    added = [anim(i, *(Event(0.0, 0.1 * k, 16, 0, params(k)) for k in range(1, i % 4 + 2))) for i in range(4, 9)]
    many = with_anims(game, *added)
    dash = with_anims(game, anim(1, Event(0.0, 0.3, 129, 0, params(1, 2, 3))))
    r = rule.merge(tae_bytes(game), [("many", tae_bytes(many)), ("dash", tae_bytes(dash))], "a00.tae")
    out = {a.id: a for a in read_tae(r.data).animations}
    sources = {a.id: a for a in [*game.animations, *many.animations]} | {1: dash.animations[1]}
    assert all([e.params for e in out[i].events] == [e.params for e in a.events] for i, a in sources.items())


def test_independent_changes_of_two_mods_all_apply():
    game = game_tae()
    dash = with_anims(game, anim(1, Event(0.0, 0.3, 129, 0, params(1))), event_bank=-1)
    revive = with_anims(game, anim(975000, Event(0.0, 2.0, 16, 0, params(9))), anim(2, name="a000_000002.hkt"))
    r = rule.merge(tae_bytes(game), [("dash", tae_bytes(dash)), ("revive", tae_bytes(revive))], "a00.tae")
    assert r.merged and not r.clashes and not r.removed
    out = read_tae(r.data)
    assert out.event_bank == -1
    assert [a.id for a in out.animations] == [0, 1, 2, 3, 10, 11, 975000]
    want = {a.id: animation_key(a) for a in game.animations}
    want[1] = animation_key(dash.animations[1])
    want[2] = animation_key(revive.animations[2])
    want[975000] = animation_key(revive.animations[-1])
    assert {a.id: animation_key(a) for a in out.animations} == want
    assert r.changed == {"a00.tae": ["dash", "revive"]}
    assert r.notes["a00.tae"] == [
        "dash: changed 1 (1); file header (event bank 37 -> -1)",
        "revive: changed 1 (2); added 1 (975000)",
    ]


def test_one_animation_changed_differently_by_two_mods_is_a_clash_the_later_wins():
    game = game_tae()
    a = with_anims(game, anim(1, Event(0.0, 0.3, 129, 0, params(1))))
    b = with_anims(game, anim(1, Event(0.0, 0.9, 129, 0, params(2))), anim(10, name="other.hkt"))
    r = rule.merge(tae_bytes(game), [("a", tae_bytes(a)), ("b", tae_bytes(b))], "a00.tae")
    assert r.clashes == {"a00.tae#1": ["a", "b"]}
    out = {x.id: x for x in read_tae(r.data).animations}
    assert animation_key(out[1]) == animation_key(b.animations[1])
    assert out[10].file_name == "other.hkt"  # b's other change still applies
    same = rule.merge(tae_bytes(game), [("a", tae_bytes(a)), ("a2", tae_bytes(a))], "a00.tae")
    assert not same.clashes  # the same change twice is no clash


def test_file_headers_changed_differently_are_a_clash():
    game = game_tae()
    a, b = with_anims(game, event_bank=-1), with_anims(game, event_bank=40)
    r = rule.merge(tae_bytes(game), [("a", tae_bytes(a)), ("b", tae_bytes(b))], "a00.tae")
    assert r.clashes == {"a00.tae#header": ["a", "b"]} and read_tae(r.data).event_bank == 40


def test_an_animation_a_mod_leaves_out_is_removed_and_listed():
    game = game_tae()
    a = with_anims(game, drop=(2,))
    b = with_anims(game, anim(975000))
    r = rule.merge(tae_bytes(game), [("a", tae_bytes(a)), ("b", tae_bytes(b))], "a00.tae")
    assert r.removed == {"a00.tae#2": ["a"]}
    assert [x.id for x in read_tae(r.data).animations] == [0, 1, 3, 10, 11, 975000]


def test_a_rewritten_copy_without_changes_gives_the_games_own_bytes():
    game = game_tae()
    rewritten = copy.deepcopy(game)
    for a in rewritten.animations:
        if a.header is not None and a.file_name is None:
            a.file_name = ""
    data = tae_bytes(game)
    assert tae_bytes(rewritten) != data
    r = rule.merge(data, [("a", tae_bytes(rewritten)), ("b", tae_bytes(rewritten))], "a00.tae")
    assert r.data == data and not r.changed and not r.clashes


def test_a_copy_the_code_cannot_read_is_the_later_mods_whole_with_the_reason():
    game = tae_bytes(game_tae())
    broken = bytearray(tae_bytes(with_anims(game_tae(), event_bank=-1)))
    struct.pack_into("<q", broken, 0x70, 99)
    a = tae_bytes(with_anims(game_tae(), anim(975000)))
    r = rule.merge(game, [("a", a), ("broken", bytes(broken))], "a00.tae")
    assert not r.merged and r.data == bytes(broken) and r.clashes == {"a00.tae": ["a", "broken"]}
    assert "not merged" in r.notes["a00.tae"][0] and "broken's copy is used whole" in r.notes["a00.tae"][0]


def test_animation_archives_merge_their_tae_through_the_archive_rule(monkeypatch):
    game = game_tae()
    dash = with_anims(game, anim(1, Event(0.0, 0.3, 129, 0, params(1))), event_bank=-1)
    revive = with_anims(game, anim(975000, Event(0.0, 2.0, 16, 0, params(9))))
    other = {"a000_000000.hkx": b"motion"}

    def anibnd(t: TAE, **files: bytes) -> bytes:
        return dcx(bnd({**other, **files, "a00.tae": tae_bytes(t)}))

    layers = [("dash", anibnd(dash)), ("revive", anibnd(revive, **{"a975_000000.hkx": b"downed"}))]
    r = merger.merge(anibnd(game), layers)
    assert r.merged and not r.clashes
    files = files_of(r.data)
    assert files["a975_000000.hkx"] == b"downed"
    out = read_tae(files["a00.tae"])
    assert out.event_bank == -1 and [a.id for a in out.animations][-1] == 975000
    assert any(k.endswith("a00.tae") for k in r.notes)
    monkeypatch.setattr(merger, "TAE_MERGING", False)  # switched off: the later mod's copy, a clash
    off = merger.merge(anibnd(game), layers)
    assert read_tae(files_of(off.data)["a00.tae"]).event_bank == 37
    assert any(k.endswith("a00.tae") for k in off.clashes)


def test_two_animations_with_one_id_are_refused():
    t = game_tae()
    data = bytearray(write_tae(t))
    anims_off = struct.unpack_from("<q", data, 0x58)[0]
    struct.pack_into("<q", data, anims_off + 16, 0)  # the second animation's ID made the first's
    with pytest.raises(formats.FormatError, match="same ID"):
        read_tae(bytes(data))
