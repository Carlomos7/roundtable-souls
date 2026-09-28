"""Read-only parser for Elden Ring PC saves.

A Python port of the ER-Save-Editor parser (src/save/**, Apache-2.0; see THIRD_PARTY_NOTICES.md), changed to read
only, to record byte positions for the repairs, and to tolerate slots saved by older game versions. It keeps the
original's checks, so a file the editor would reject fails here with a readable reason and offset.

Usage: python -m roundtable_souls.saves.layout <save> [<save> ...]"""

import hashlib
import struct
import sys

SLOT_SIZE = 0x280000
HEADER = 0x300


class BR:
    def __init__(self, data, pos=0):
        self.d = data
        self.pos = pos

    def bytes(self, n):
        if self.pos + n > len(self.d):
            raise EOFError(f"read {n} at 0x{self.pos:X} past end")
        b = self.d[self.pos : self.pos + n]
        self.pos += n
        return b

    def u8(self):
        return self.bytes(1)[0]

    def u16(self):
        return struct.unpack("<H", self.bytes(2))[0]

    def u32(self):
        return struct.unpack("<I", self.bytes(4))[0]

    def i32(self):
        return struct.unpack("<i", self.bytes(4))[0]

    def u64(self):
        return struct.unpack("<Q", self.bytes(8))[0]

    def f32(self):
        return struct.unpack("<f", self.bytes(4))[0]


class ParseError(Exception):
    pass


def check(cond, msg, br):
    if not cond:
        raise ParseError(f"{msg} (at 0x{br.pos:X})")


def read_ga_item(br):
    pos = br.pos
    handle = br.u32()
    item_id = br.u32()
    g = dict(gaitem_handle=handle, item_id=item_id, unk2=-1, unk3=-1, aow=0xFFFFFFFF, unk5=0, pos=pos)
    if item_id != 0 and (item_id & 0xF0000000) == 0:
        g["unk2"] = br.i32()
        g["unk3"] = br.i32()
        g["aow"] = br.u32()
        g["unk5"] = br.u8()
    elif item_id != 0 and (item_id & 0xF0000000) == 0x10000000:
        g["unk2"] = br.i32()
        g["unk3"] = br.i32()
    return g


def read_player_game_data(br):
    p = {}
    p["start"] = br.pos
    br.i32()
    br.i32()
    p["health"], p["max_health"], p["base_max_health"] = br.u32(), br.u32(), br.u32()
    p["fp"], p["max_fp"], p["base_max_fp"] = br.u32(), br.u32(), br.u32()
    br.i32()
    p["sp"], p["max_sp"], p["base_max_sp"] = br.u32(), br.u32(), br.u32()
    br.i32()
    p["vig"], p["mind"], p["end"], p["str"], p["dex"], p["int"], p["fai"], p["arc"] = [br.u32() for _ in range(8)]
    br.i32()
    br.i32()
    br.i32()
    p["level"], p["souls"], p["soulsmemory"] = br.u32(), br.u32(), br.u32()
    br.bytes(0x28)
    name = [br.u16() for _ in range(0x10)]
    p["name"] = "".join(chr(c) for c in name).split("\0")[0]
    br.bytes(2)
    p["gender_pos"] = br.pos
    p["gender"] = br.u8()
    check(p["gender"] in (0, 1), f"gender byte is {p['gender']}, expected 0/1", br)
    p["arche_type"] = br.u8()
    br.bytes(3)
    p["gift"] = br.u8()
    br.bytes(0x1E)
    p["mm_wpn_lvl"] = br.u8()
    br.bytes(0x35)
    for _ in range(6):
        br.bytes(0x12)
    br.bytes(0x34)
    return p


def read_u32s(br, n):
    return [br.u32() for _ in range(n)]


def read_equip_inventory(br, l1, l2):
    d = {}
    d["common_count"] = br.u32()
    d["common"] = [(br.u32(), br.u32(), br.u32()) for _ in range(l1)]
    d["key_count"] = br.u32()
    d["key"] = [(br.u32(), br.u32(), br.u32()) for _ in range(l2)]
    d["next_equip_index"] = br.u32()
    d["next_sort_id"] = br.u32()
    return d


def read_slot(br):
    s = {}
    start = br.pos
    end = start + SLOT_SIZE
    s["ver"] = br.u32()
    s["map_id"] = br.bytes(4)
    br.bytes(0x18)
    s["ga_items_pos"] = br.pos
    # Characters last saved on an early patch (slot version <= 81) carry two gaItem rows fewer.
    # Empty slots are version 0 and parse with the current layout.
    n_rows = 0x13FE if 0 < s["ver"] <= 81 else 0x1400
    s["ga_items"] = [read_ga_item(br) for _ in range(n_rows)]
    s["pgd"] = read_player_game_data(br)
    br.bytes(0xD0)
    s["equip_data"] = read_u32s(br, 22)
    s["chr_asm"] = read_u32s(br, 29)
    s["chr_asm2"] = read_u32s(br, 22)
    s["inv_pos"] = br.pos
    s["inventory"] = read_equip_inventory(br, 0xA80, 0x180)
    read_u32s(br, 24)
    br.bytes(0x10)
    br.i32()  # equip magic
    s["quick_pos"] = br.pos
    s["quick"] = [(br.u32(), br.u32()) for _ in range(10)]
    br.i32()
    s["pouch_pos"] = br.pos
    s["pouch"] = [(br.u32(), br.u32()) for _ in range(6)]
    br.bytes(8)
    read_u32s(br, 6)  # gestures
    s["proj_pos"] = br.pos
    n = br.i32()
    check(0 <= n <= 0x1000, f"projectile_count {n} looks bogus", br)
    s["projectiles"] = [(br.u32(), br.i32()) for _ in range(n)]
    s["equipped_items_pos"] = br.pos
    s["equipped_items"] = read_u32s(br, 39)
    s["physics"] = (br.u32(), br.u32())
    br.u32()
    br.bytes(0x12F)  # face data
    s["storage_pos"] = br.pos
    s["storage"] = read_equip_inventory(br, 0x780, 0x80)
    read_u32s(br, 0x40)
    s["regions_pos"] = br.pos
    rc = br.u32()
    check(rc <= 0x1000, f"unlocked_regions_count {rc} looks bogus", br)
    s["regions"] = read_u32s(br, rc)
    s["horse_pos"] = br.pos  # RideGameData: xyz(12) map(4) angle(16) hp(4) state(4)
    br.bytes(12)
    br.i32()
    br.bytes(0x10)
    s["horse"] = (br.i32(), br.u32())
    br.u8()
    br.bytes(0x40)
    br.i32()
    br.i32()
    br.i32()
    br.bytes(0x1008)
    br.bytes(0x34)
    s["gaitemdata_pos"] = br.pos
    br.i32()
    br.i32()
    s["ga_item_data"] = [(br.u32(), br.u32(), br.u32(), br.u32()) for _ in range(0x1B58)]
    br.bytes(0x408)
    br.bytes(0x1D)
    s["event_flags_pos"] = br.pos
    s["event_flags"] = br.bytes(0x1BF99F)
    br.u8()
    s["unk_lists_pos"] = br.pos
    for i in range(5):
        ln = br.i32()
        check(0 <= ln <= 0x100000, f"unk_list[{i}] length {ln} looks bogus", br)
        br.bytes(ln)
    s["coords_pos"] = br.pos
    s["coords"] = (br.f32(), br.f32(), br.f32())
    br.bytes(4)
    br.bytes(0x11)
    s["coords2_pos"] = br.pos
    s["coords2"] = (br.f32(), br.f32(), br.f32())
    br.bytes(0x10)
    # 2 pad + spawn point + game_man, then a temp spawn point from version 65 and one more byte from version 66
    tail = 0xA + (4 if s["ver"] == 0 or s["ver"] >= 65 else 0) + (1 if s["ver"] == 0 or s["ver"] >= 66 else 0)
    br.bytes(tail)
    s["_0x1_2_pos"] = br.pos
    v = br.u32()
    check(v in (0, 2), f"_0x1_2 is {v}, expected 0 or 2", br)
    br.bytes(0x20000)  # CSNetData chunks
    s["weather_pos"] = br.pos
    s["weather"] = (br.u16(), br.u16(), br.u32(), br.u32())  # area, type, timer, pad
    s["time_pos"] = br.pos
    s["time"] = (br.u32(), br.u32(), br.u32())
    s["base_version_pos"] = br.pos
    s["base_version"] = (br.u32(), br.u32(), br.u32(), br.u32())
    s["steam_id_pos"] = br.pos
    s["steam_id"] = br.u64()
    br.bytes(0x20)
    s["dlc_pos"] = br.pos
    s["dlc"] = br.bytes(0x32)  # [0] pre-order ring, [1] DLC entered, [2] pre-order, [3] Tarnished pack, rest unused
    br.bytes(0x80)
    check(br.pos <= end, f"slot parse overran slot end by {br.pos - end}", br)
    s["rest_len"] = end - br.pos
    br.pos = end
    return s


def read_user_data_10(br):
    u = {}
    start = br.pos
    end = start + 0x60010
    u["checksum"] = br.bytes(0x10)
    br.i32()
    u["steam_id"] = br.u64()
    br.bytes(0x140)
    br.u32()
    ln = br.u32()
    check(ln < 0x60000, f"CSMenuSystemSaveLoad length {ln} bogus", br)
    br.bytes(ln)
    u["active_pos"] = br.pos
    u["active"] = []
    for i in range(10):
        b = br.u8()
        check(b in (0, 1), f"active_slot[{i}] byte is {b}", br)
        u["active"].append(b == 1)
    u["profiles"] = []
    for _i in range(10):
        name = [br.u16() for _ in range(0x11)]
        level = br.u32()
        br.u32()
        br.u32()
        br.u32()
        br.u32()
        br.u32()
        br.bytes(0x120)
        read_u32s(br, 30)  # ProfileSummaryEquipmentGaitem
        read_u32s(br, 11)
        br.u64()
        read_u32s(br, 15)  # ProfileSummaryEquipmentItem
        u["profiles"].append(("".join(chr(c) for c in name).split("\0")[0], level))
        br.bytes(6)
        br.i32()
    br.i32()
    br.u8()
    br.bytes(18 + 0xA0)
    ln = br.i32()
    check(0 <= ln < 0x60000, f"CSKeyConfigSaveLoad length {ln} bogus", br)
    br.bytes(ln)
    br.u64()
    check(br.pos <= end, "UserData10 overran", br)
    br.pos = end
    return u


def parse(path):
    data = open(path, "rb").read()
    br = BR(data)
    check(data[:4] == b"BND4", "not BND4", br)
    br.pos = HEADER
    out = {"slots": [], "slot_md5_ok": [], "unreadable": {}}
    for i in range(10):
        chk = br.bytes(0x10)
        start = br.pos
        body = data[start : start + SLOT_SIZE]
        out["slot_md5_ok"].append(hashlib.md5(body).digest() == chk)
        try:
            out["slots"].append(read_slot(br))
        except (ParseError, EOFError) as e:
            # one slot in a layout this parser does not know must not hide the others: keep a stub and move on
            ver = struct.unpack_from("<I", data, start)[0]
            out["unreadable"][i] = {"error": str(e), "ver": ver}
            out["slots"].append(
                {
                    "unreadable": True,
                    "ver": ver,
                    "map_id": data[start + 4 : start + 8],
                    "pgd": {"name": "", "level": 0},
                    "ga_items": [],
                    "inventory": {},
                    "storage": {},
                    "event_flags": b"",
                    "steam_id": None,
                    "dlc": b"",
                    "horse": None,
                    "coords": (),
                    "coords2": (),
                    "weather": None,
                    "rest_len": 0,
                }
            )
            br.pos = start + SLOT_SIZE
    out["ud10_pos"] = br.pos
    out["ud10_md5_ok"] = hashlib.md5(data[br.pos + 0x10 : br.pos + 0x60010]).digest() == data[br.pos : br.pos + 0x10]
    out["ud10"] = read_user_data_10(br)
    out["ud10"]["active_raw"] = list(out["ud10"]["active"])
    for i in out["unreadable"]:  # consumers only look at active slots; an unreadable one is left alone
        out["ud10"]["active"][i] = False
    out["ud11_pos"] = br.pos
    out["ud11_md5_ok"] = hashlib.md5(data[br.pos + 0x10 : br.pos + 0x240020]).digest() == data[br.pos : br.pos + 0x10]
    br.bytes(0x10)
    br.bytes(0x10)
    block = br.bytes(0x240000)
    data_len = len(block.rstrip(b"\0"))
    reg_len = min(((data_len + 15) // 16) * 16, 0x240000)
    out["regulation"] = block[:reg_len]
    out["file_len"] = len(data)
    out["parsed_to"] = br.pos
    return out


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print("=====", p)
        try:
            r = parse(p)
        except ParseError as e:
            print("PARSE FAIL:", e)
            continue
        print("file_len", hex(r["file_len"]), "parsed_to", hex(r["parsed_to"]))
        print("slot md5 ok:", r["slot_md5_ok"])
        print("ud10 md5 ok:", r["ud10_md5_ok"], " ud11 md5 ok:", r["ud11_md5_ok"])
        print("steam_id", r["ud10"]["steam_id"], "active", r["ud10"]["active"])
        for i, s in enumerate(r["slots"]):
            if r["ud10"]["active"][i]:
                pgd = s["pgd"]
                print(
                    f" slot {i}: '{pgd['name']}' lvl {pgd['level']} gender {pgd['gender']} steam {s['steam_id']} "
                    f"inv_count {s['inventory']['common_count']} store_count {s['storage']['common_count']} "
                    f"proj {len(s['projectiles'])} regions {len(s['regions'])} rest {s['rest_len']}"
                )
        print("regulation len", hex(len(r["regulation"])), "md5", hashlib.md5(r["regulation"]).hexdigest())
