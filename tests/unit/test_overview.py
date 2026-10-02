"""The Load order overview: what happens to each file two packages ship, the combine's overlapping rows, and the
entries me3 would refuse. Uses the small regulation files and profiles of the combine tests."""

from test_mod_merge import TALK, World
from test_param_merge import pack, set_word, vanilla

from roundtable_souls.mods import merge, overview
from roundtable_souls.platform import paths as common


def outcomes(ov, path):
    c = next(x for x in ov["overlaps"]["conflicts"] if x["path"].lower() == path.lower())
    return {loser["id"]: loser["outcome"] for loser in c["losers"]}, c["winner"]


def test_plain_overlaps_are_replaced(tmp_path, monkeypatch):
    base = tmp_path / "p"
    for name in ("a", "b"):
        (base / "mod" / name / "parts").mkdir(parents=True)
        (base / "mod" / name / "parts" / "am_m_1000.partsbnd.dcx").write_bytes(name.encode())
    prof = base / "p.me3"
    prof.write_text("[[packages]]\nid = \"a\"\npath = 'mod/a'\n\n[[packages]]\nid = \"b\"\npath = 'mod/b'\n")
    ov = overview.overview(prof)
    got, winner = outcomes(ov, "parts/am_m_1000.partsbnd.dcx")
    assert winner == "b" and got == {"a": "replaced"}
    assert ov["overlaps"]["counts"]["replaced"] == 1 and ov["overlaps"]["packages"]["a"]["replaced"] == 1
    assert ov["overlaps"]["packages"]["b"]["wins"] == 1 and ov["health"]["state"] == "single"


def test_what_a_rebuild_tool_merged_reads_as_combined_until_it_changes(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.pack("far", (TALK,))
    w.pack("near", (TALK,))
    merge.rebuild(w.profile, lambda s: None, combine=False)
    ov = overview.overview(w.profile)
    got, winner = outcomes(ov, TALK)
    assert winner == "last" and got == {"far": "unreached", "near": "combined"}  # only the nearest reaches the tool
    (w.base / "mod" / "near" / TALK).write_bytes(b"near v2")
    got, _ = outcomes(overview.overview(w.profile), TALK)
    assert got["near"] == "stale"


def test_regulation_packs_inside_the_combine_are_combined_through_the_chain(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    (w.game / "regulation.bin").write_bytes(vanilla())
    for name, edit in (("a", set_word(1000, 0, 1)), ("b", set_word(2000, 1, 2))):
        (w.pack(name) / "regulation.bin").write_bytes(pack({"EquipParamWeapon": edit}))
    merge.rebuild(w.profile, lambda s: None)  # combine, then the tool takes the combined file
    ov = overview.overview(w.profile)
    got, winner = outcomes(ov, "regulation.bin")
    assert winner == "last"
    assert got == {"a": "combined", "b": "combined", "combined-parameters": "combined"}
    (w.base / "mod" / "a" / "regulation.bin").write_bytes(pack({"EquipParamWeapon": set_word(1000, 0, 9)}))
    got, _ = outcomes(overview.overview(w.profile), "regulation.bin")
    assert got["a"] == "stale" and got["b"] == "combined"


def test_the_combines_overlapping_rows_are_listed(tmp_path, monkeypatch):
    game = tmp_path / "Game"
    game.mkdir()
    (game / "regulation.bin").write_bytes(vanilla())
    monkeypatch.setattr(common, "game_dir", lambda: game)
    monkeypatch.setattr(common, "game_running", lambda: False)
    base = tmp_path / "p"
    text = ""
    for name, value in (("a", 11), ("b", 22)):  # both differ from the game's value (1)
        (base / "mod" / name).mkdir(parents=True)
        (base / "mod" / name / "regulation.bin").write_bytes(pack({"EquipParamWeapon": set_word(1000, 0, value)}))
        text += f"[[packages]]\nid = \"{name}\"\npath = 'mod/{name}'\n\n"
    prof = base / "p.me3"
    prof.write_text(text)
    merge.rebuild(prof, lambda s: None, combine=True)
    ov = overview.overview(prof)
    assert (
        ov["rows"][0].startswith("1 rows changed by more than one pack")
        and "EquipParamWeapon 1000: a then b" in ov["rows"][1]
    )
    got, winner = outcomes(ov, "regulation.bin")
    assert winner == "combined-parameters" and got == {"a": "combined", "b": "combined"}


def test_a_pack_after_the_combined_one_replaces_it(tmp_path, monkeypatch):
    game = tmp_path / "Game"
    game.mkdir()
    (game / "regulation.bin").write_bytes(vanilla())
    monkeypatch.setattr(common, "game_dir", lambda: game)
    monkeypatch.setattr(common, "game_running", lambda: False)
    base = tmp_path / "p"
    for name in ("a", "b"):
        (base / "mod" / name).mkdir(parents=True)
        (base / "mod" / name / "regulation.bin").write_bytes(pack({"EquipParamWeapon": set_word(1000, 1, 5)}))
    prof = base / "p.me3"
    prof.write_text("[[packages]]\nid = \"a\"\npath = 'mod/a'\n\n[[packages]]\nid = \"b\"\npath = 'mod/b'\n")
    merge.rebuild(prof, lambda s: None, combine=True)
    (base / "mod" / "late").mkdir()
    (base / "mod" / "late" / "regulation.bin").write_bytes(vanilla())
    prof.write_text(prof.read_text() + "\n[[packages]]\nid = \"late\"\npath = 'mod/late'\n")
    got, winner = outcomes(overview.overview(prof), "regulation.bin")
    assert winner == "late" and got["combined-parameters"] == "replaced"


def test_problems_list_what_me3_would_refuse(tmp_path):
    base = tmp_path / "p"
    (base / "mod" / "here").mkdir(parents=True)
    prof = base / "p.me3"
    prof.write_text(
        '[[packages]]\nid = "here"\npath = \'mod/here\'\nload_after = [{ id = "nothere", optional = false }]\n\n'
        "[[packages]]\nid = \"gone\"\npath = 'mod/gone'\n"
    )
    probs = {p["name"]: p["problems"] for p in overview.problems(prof)}
    assert set(probs) == {"here", "gone"} and all(probs.values())


def test_a_broken_profile_gives_an_empty_overview_not_an_error(tmp_path):
    prof = tmp_path / "p.me3"
    prof.write_text("[[packages]\nthis is not toml")
    ov = overview.overview(prof)
    assert ov["overlaps"]["conflicts"] == [] and ov["rows"] == [] and isinstance(ov["problems"], list)
