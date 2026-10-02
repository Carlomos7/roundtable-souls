"""What counts as a game item, the Tarnished Edition rule, labels for foreign items, and the report gate."""

from roundtable_souls.services import play as g
from roundtable_souls.services import saves as saves_service

A = g.save_analyze
WEAPON, ARMOUR, TALISMAN, GOODS, ASH = 0x0, 0x10000000, 0x20000000, 0x40000000, 0x80000000


def catalog(known=(), pack=False):
    return A.Catalog(frozenset(known), pack)


def test_placeholders_and_weapon_affinity_are_game_items():
    c = catalog({9000000, 9000001, 9000025, 1020000, 67700000, GOODS | 100})
    assert c.is_game_item(0) and c.is_game_item(0xFFFFFFFF)
    assert c.is_game_item(A.UNARMED_WEAPON)  # the fist row in every empty weapon slot
    assert all(c.is_game_item(ARMOUR | n) for n in A.NAKED_ARMOR)  # empty armour slots
    assert c.is_game_item(ASH | 0)  # the row a weapon keeps for its built-in skill
    assert c.is_game_item(9000914)  # base 9000000, affinity 9, +14
    assert c.is_game_item(9001225)  # affinity 12 +25 -> base +25 is listed
    assert not c.is_game_item(34910004)
    assert not c.is_game_item(ARMOUR | 742000)
    assert not c.is_game_item(GOODS | 101)


def test_tarnished_pack_covers_unlisted_equipment_only():
    plain, pack = catalog(), catalog(pack=True)
    for item in (WEAPON | 3560000, ARMOUR | 5350000, TALISMAN | 9999):
        assert not plain.is_game_item(item) and pack.is_game_item(item)
    assert not pack.is_game_item(GOODS | 8380001)  # consumables still count as foreign
    assert not pack.is_game_item(ASH | 12345)


def test_tarnished_flag_is_read_from_active_characters_only():
    def save(flags, active):
        slots = [{"dlc": bytes([0, 0, 0, f]) + bytes(46)} for f in flags]
        return {"ud10": {"active": active}, "slots": slots}

    assert A.tarnished_flag(save([0, 1], [True, True]))
    assert not A.tarnished_flag(save([0, 1], [True, False]))
    assert not A.tarnished_flag({})
    assert A.Catalog.for_save(save([1], [True])).pack


def test_labels_name_the_kind_and_id():
    assert A.item_label(ARMOUR | 5350000) == ("Armour 5350000", A.UNLISTED)
    assert A.item_label(3560008) == ("Weapon 3560000 +8", A.UNLISTED)
    assert A.item_label(GOODS | 8380002)[0] == "Item 8380002"
    assert A.item_label(TALISMAN | 7)[0] == "Talisman 7"


def test_bundled_list_is_game_items_only():
    known = A.known_item_ids()
    assert len(known) > 90000
    assert GOODS | 2010000 in known  # Scadutree Fragment: Shadow of the Erdtree is part of the game list
    assert 2010000 in known and 2010025 in known  # Short Sword and its +25
    assert GOODS | 8380001 not in known  # a Seamless Co-op item


def test_scan_finds_foreign_goods_and_gear_and_respects_worn():
    slot = {
        "ga_items": [
            {"gaitem_handle": 0x80800001, "item_id": 2010000},  # Short Sword
            {"gaitem_handle": 0x90800002, "item_id": ARMOUR | 742000},  # foreign armour, worn
            {"gaitem_handle": 0x90800003, "item_id": ARMOUR | 743000},  # foreign armour nothing holds
        ],
        "inventory": {"common": [(0x80800001, 1, 0), (0x90800002, 1, 1), (0xB07FDE61, 2, 2)], "key": []},
        "storage": {"common": [], "key": []},
        "chr_asm": [742000],
        "equipped_items": [],
        "quick": [(0xB07FDE61, 0)],
        "pouch": [],
    }
    scan = A.scan_mod_items(slot, catalog({2010000}))
    held = {e["name"]: e for e in scan["held"]}
    assert set(held) == {"Armour 742000", "Item 8380001"}
    assert held["Armour 742000"]["worn"] and not held["Item 8380001"]["worn"]
    assert held["Item 8380001"]["quick"] == [0] and held["Item 8380001"]["qty"] == 2
    assert [o["name"] for o in scan["orphans"]] == ["Armour 743000"]
    packed = A.scan_mod_items(slot, catalog({2010000}, pack=True))
    assert [e["name"] for e in packed["held"]] == ["Item 8380001"] and not packed["orphans"]


def test_info_findings_do_not_block_the_standard_copy():
    info = [
        {"level": "info", "code": "orphan_item", "title": "t", "detail": ""},
        {"level": "ok", "code": "regulation", "title": "t", "detail": ""},
        {"level": "ok", "code": "layout", "title": "t", "detail": ""},
    ]
    assert A.findings_are_clean(info)
    assert not A.findings_are_clean(info + [{"level": "warn", "code": "unknown_item", "title": "t", "detail": ""}])
    text = A.format_health_report({"findings": info})
    assert "[INFO]" in text and "Copy to standard save: ready" in text


def test_repair_available_predicate():
    assert not saves_service.repair_available({"needs_repair": False, "checksum_fixes": {"slots": [], "ud10": False}})
    assert saves_service.repair_available({"needs_repair": True})
    assert saves_service.repair_available({"checksum_fixes": {"slots": [0], "ud10": False}})
    assert saves_service.repair_available({"checksum_fixes": {"slots": [], "ud10": True}})
    assert saves_service.repair_available({"loading_plan": [{"slot": 0}]})
