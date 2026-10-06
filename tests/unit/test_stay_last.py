"""The mod that must stay last stays last: only its own load order lists change, every other entry is listed (on or
off) as optional, exceptions are respected, a change that would loop writes nothing, and a missing setup is named."""

import difflib
import random
import shutil
import tomllib
from pathlib import Path

import pytest
from test_mod_merge import World, _pack_source

from roundtable_souls.game import locate
from roundtable_souls.mods import install, profile_settings, remove, stay_last
from roundtable_souls.mods import profile as profile_tools
from roundtable_souls.mods import profile_edit as M
from roundtable_souls.mods import rebuild as merge
from support import er

PROFILE = """profileVersion = "v1"

# base mods
[[packages]]
id = "parts"
path = 'mod/parts'

# off for now
[[packages]]
id = "off"
path = 'mod/off'
enabled = false

# the merger's package must stay last
[[packages]]
id = "last"
path = 'Merger/mod'
load_after = [
  { id = "parts", optional = true },
]

# a DLL mod
[[natives]]
path = 'natives/a/a.dll'

[[natives]]
path = 'natives/b/b.dll'
enabled = false

[[natives]]
path = 'natives/early/early.dll'
load_early = true

[[natives]]
path = 'Merger/Boot.dll'
load_early = true

[[natives]]
path = 'Merger/Last.dll'
initializer = { function = "Init" }
load_after = [
  { id = "a.dll", optional = true },
]
"""


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    (w.base / "mod" / "off").mkdir(parents=True)
    for dll in ("natives/a/a.dll", "natives/b/b.dll", "natives/early/early.dll", "Merger/Boot.dll", "Merger/Last.dll"):
        (w.base / dll).parent.mkdir(parents=True, exist_ok=True)
        (w.base / dll).write_bytes(b"d")
    w.profile.write_text(PROFILE, encoding="utf-8")
    return w


def _doc(text: str) -> dict:
    return tomllib.loads(text)


def _after(text: str, kind: str, match: str) -> list[tuple[str, bool]]:
    rows = _doc(text)["packages" if kind == "package" else "natives"]
    row = next(r for r in rows if match in (r.get("id") or r["path"]))
    return [(d["id"], d.get("optional", False)) for d in row.get("load_after") or []]


def _blocks_except(text: str, skip: set[str]) -> list[str]:
    out = []
    for b in M.blocks(text):
        body = "".join(b["lines"])
        if not any(s in body for s in skip):
            out.append(body)
    return out


def test_every_other_entry_is_listed_and_only_its_own_lists_change(world):
    text = world.profile.read_text(encoding="utf-8")
    new, problem = stay_last.reconcile(world.profile, text)
    assert problem is None
    assert _after(new, "package", "last") == [("parts", True), ("off", True)]  # off ones too: toggles need no rewrite
    assert _after(new, "native", "Last.dll") == [("a.dll", True), ("b.dll", True)]  # load_early ones are not added
    assert _after(new, "native", "Boot.dll") == []  # its own load_early DLL is left alone
    owners = {'id = "last"', "Merger/Last.dll"}
    assert _blocks_except(new, owners) == _blocks_except(text, owners)  # every other entry byte for byte
    assert "# the merger's package must stay last" in new and "# a DLL mod" in new
    assert stay_last.reconcile(world.profile, new) == (new, None)  # twice changes nothing


def test_switching_a_mod_on_or_off_changes_only_that_line(world):
    assert stay_last.fix(world.profile, loc=er()) is None
    before = world.profile.read_text(encoding="utf-8")
    off = next(e for e in M.entries(world.profile) if e.get("id") == "off")
    M.set_options(world.profile, off["index"], {"enabled": True})
    after = world.profile.read_text(encoding="utf-8")
    changed = [l for l in difflib.ndiff(before.splitlines(), after.splitlines()) if l[:2] in ("- ", "+ ")]
    assert changed == ["- enabled = false"]


def test_a_new_package_goes_before_it_and_is_listed(world, tmp_path):
    plan = install.plan_install(world.profile, _pack_source(tmp_path / "dl"))
    assert plan["stay_last"] == "last"
    install.install(world.profile, {**plan, "insert_before": None})
    text = world.profile.read_text(encoding="utf-8")
    assert text.index(f'id = "{plan["id"]}"') < text.index('id = "last"')
    assert (plan["id"], True) in _after(text, "package", "last")
    ids = [r["id"] for r in profile_tools.me3_order(None, text).rows]
    assert ids[-1] == "last"


def test_a_new_dll_goes_before_its_dlls_and_is_listed(world, tmp_path):
    src = tmp_path / "dl" / "Cool"
    src.mkdir(parents=True)
    (src / "cool.dll").write_bytes(b"x")
    plan = install.plan_install(world.profile, src)
    install.install(world.profile, plan)
    text = world.profile.read_text(encoding="utf-8")
    assert text.index("cool.dll") < text.index("Merger/Boot.dll")
    assert ("cool.dll", True) in _after(text, "native", "Last.dll")


def test_kept_after_on_purpose_when_installed_that_way(world, tmp_path):
    plan = install.plan_install(world.profile, _pack_source(tmp_path / "dl"))
    install.install(world.profile, {**plan, "after_overlay": True, "insert_before": None})
    text = world.profile.read_text(encoding="utf-8")
    assert text.index(f'id = "{plan["id"]}"') > text.index('id = "last"')
    assert plan["id"] not in [i for i, _ in _after(text, "package", "last")]
    assert _after(text, "package", plan["id"]) == [("last", True)]
    st = stay_last.status(world.profile, loc=er())
    assert st["late"] == [] and plan["id"] in st["kept"]


def test_removing_a_mod_drops_it_from_the_list(world):
    stay_last.fix(world.profile, loc=er())
    parts = next(e for e in M.entries(world.profile) if e.get("id") == "parts")
    remove.uninstall(world.profile, parts["index"], delete_folder=False)
    assert _after(world.profile.read_text(encoding="utf-8"), "package", "last") == [("off", True)]


def test_a_renamed_id_is_followed_where_it_was(world):
    stay_last.fix(world.profile, loc=er())
    parts = next(e for e in M.entries(world.profile) if e.get("id") == "parts")
    M.set_options(world.profile, parts["index"], {"id": "body"})
    assert _after(world.profile.read_text(encoding="utf-8"), "package", "last") == [("body", True), ("off", True)]


def test_adding_an_existing_folder_puts_it_before_it(world):
    extra = world.base / "mod" / "extra"
    extra.mkdir()
    install.add_existing(world.profile, [extra])
    text = world.profile.read_text(encoding="utf-8")
    assert text.index('id = "extra"') < text.index('id = "last"') and ("extra", True) in _after(text, "package", "last")


def test_a_hand_added_mod_after_it_is_reported_and_fixed(world):
    (world.base / "mod" / "hand").mkdir()
    world.profile.write_text(PROFILE + "\n[[packages]]\nid = \"hand\"\npath = 'mod/hand'\n", encoding="utf-8")
    st = stay_last.status(world.profile, loc=er())
    assert st["late"] == ["hand"] and st["can_fix"] and st["problem"] is None
    assert stay_last.fix(world.profile, loc=er()) is None
    text = world.profile.read_text(encoding="utf-8")
    assert stay_last.status(world.profile, loc=er())["late"] == []
    assert text.endswith("id = \"hand\"\npath = 'mod/hand'\n")  # the user's own entry is where they put it


def test_keep_it_after_is_kept_in_roundtable_json_and_can_be_undone(world):
    (world.base / "mod" / "hand").mkdir()
    world.profile.write_text(PROFILE + "\n[[packages]]\nid = \"hand\"\npath = 'mod/hand'\n", encoding="utf-8")
    stay_last.keep_after(world.profile, ["hand"])
    assert profile_settings.load(world.profile)["after_overlay"] == ["hand"]
    st = stay_last.status(world.profile, loc=er())
    assert st["late"] == [] and st["kept_setting"] == ["hand"]
    new, _ = stay_last.reconcile(world.profile, world.profile.read_text(encoding="utf-8"))
    assert "hand" not in [i for i, _ in _after(new, "package", "last")]
    stay_last.keep_after(world.profile, ["hand"], keep=False)
    assert "after_overlay" not in profile_settings.load(world.profile)
    assert stay_last.status(world.profile, loc=er())["late"] == ["hand"]


def test_a_change_that_would_loop_writes_nothing(world):
    for name in ("x", "y"):
        (world.base / "mod" / name).mkdir()
    loop = (
        PROFILE
        + '\n[[packages]]\nid = "x"\npath = \'mod/x\'\nload_after = [{ id = "last", optional = true }]\n'
        + '\n[[packages]]\nid = "y"\npath = \'mod/y\'\nload_after = [{ id = "x", optional = true }]\n'
    )
    world.profile.write_text(loop, encoding="utf-8")
    text = world.profile.read_text(encoding="utf-8")
    new, problem = stay_last.reconcile(world.profile, text)
    assert new == text and "loop" in problem
    before = world.profile.read_bytes()
    assert "loop" in stay_last.fix(world.profile, loc=er())
    assert world.profile.read_bytes() == before
    assert stay_last.status(world.profile, loc=er())["late"] == ["y"]


def test_without_a_mod_that_must_stay_last_nothing_is_touched(tmp_path):
    base = tmp_path / "p"
    for name in ("a", "b"):
        (base / "mod" / name).mkdir(parents=True)
    prof = base / "p.me3"
    text = "[[packages]]\nid = \"a\"\npath = 'mod/a'\n\n[[packages]]\nid = \"b\"\npath = 'mod/b'\n"
    prof.write_text(text, encoding="utf-8")
    assert stay_last.target(prof) is None and stay_last.status(prof, loc=er()) is None
    assert stay_last.reconcile(prof, text) == (text, None)
    (base / "mod" / "c").mkdir()
    install.add_existing(prof, [base / "mod" / "c"])
    assert prof.read_text(encoding="utf-8").startswith(text)  # appended, nothing else changed


def test_random_profiles_keep_it_last_and_leave_every_other_entry_alone(tmp_path):
    """Property check over generated profiles: after reconcile the package that must stay last loads after every
    entry not kept after it on purpose, no other block changes, and a second pass changes nothing."""
    base = tmp_path / "p"
    base.mkdir()
    prof = base / "p.me3"
    prof.write_text("", encoding="utf-8")
    tgt = {"folder": base / "Merger" / "mod", "own": [base / "Merger"], "name": "last"}
    rng = random.Random(1234)
    for _ in range(150):
        ids = [f"m{i}" for i in range(rng.randint(0, 7))]
        blocks = []
        after_it = set()
        for i in ids:
            body = f"[[packages]]\nid = \"{i}\"\npath = 'mod/{i}'\n"
            if rng.random() < 0.3:
                body += "enabled = false\n"
            if rng.random() < 0.15:
                body += 'load_after = [{ id = "last", optional = true }]\n'
                after_it.add(i)
            if rng.random() < 0.3:
                body = f"# notes on {i}\n" + body
            blocks.append(body)
        listed = rng.sample(ids, rng.randint(0, len(ids))) + (["gone"] if rng.random() < 0.3 else [])
        last = "[[packages]]\nid = \"last\"\npath = 'Merger/mod'\n"
        if listed:
            last += "load_after = [\n" + "".join(f'  {{ id = "{i}", optional = true }},\n' for i in listed) + "]\n"
        blocks.insert(rng.randint(0, len(blocks)), last)
        text = "\n".join(blocks)
        new, problem = stay_last.reconcile(prof, text, tgt)
        if problem:  # only a loop blocks it, and then nothing changes
            assert new == text and "loop" in problem
            continue
        assert _blocks_except(new, {'id = "last"'}) == _blocks_except(text, {'id = "last"'})
        order = [r["id"] for r in profile_tools.me3_order(None, new).rows]
        if "last" in order:
            before_it = {i for i in order[: order.index("last")]}
            enabled = {r["id"] for r in profile_tools.package_rows(new)} - {"last"}
            assert enabled - after_it <= before_it
        listed_now = [i for i, _ in _after(new, "package", "last")]
        assert "gone" not in listed_now and not (set(listed_now) & after_it)
        assert stay_last.reconcile(prof, new, tgt) == (new, None)


# ----------------------------------------------------------------------------- a missing setup is named
def test_missing_setup_files_are_named_and_a_rebuild_changes_nothing(world):
    shutil.rmtree(world.setup)
    h = merge.health(world.profile, loc=er())
    assert "setup files are missing: its setup folder" in h["reasons"][0]
    assert not any("loads after the combined parameters" in r for r in h["reasons"])
    before = world.profile.read_bytes()
    with pytest.raises(merge.MergeError, match="setup files are missing"):
        merge.rebuild(world.profile, lambda s: None, loc=er())
    assert world.profile.read_bytes() == before


def test_a_package_that_lists_the_others_is_known_to_stay_last_without_its_files(world):
    world.pack("params")
    text = world.profile.read_text(encoding="utf-8").replace(
        '{ id = "parts", optional = true },',
        '{ id = "parts", optional = true },\n  { id = "params", optional = true },',
    )
    world.profile.write_text(text, encoding="utf-8")
    (world.base / "Merger" / "installation.json").unlink()
    h = merge.health(world.profile, loc=er())
    assert h["overlay"] == "last" and "setup files are missing: installation.json" in h["reasons"][0]
    assert not any("combined parameters and replaces them" in r for r in h["reasons"])
    before = world.profile.read_bytes()
    with pytest.raises(merge.MergeError, match="installation.json"):
        merge.rebuild(world.profile, lambda s: None, combine=True, loc=er())
    assert world.profile.read_bytes() == before
    assert not (world.base / "mod" / "combined-parameters").exists()  # stopped before making anything


def test_a_profile_without_it_still_combines(tmp_path, monkeypatch):
    """Two packs and nothing that must stay last: a plain combine, no setup is asked for."""

    base = tmp_path / "p"
    for name in ("a", "b"):
        (base / "mod" / name).mkdir(parents=True)
        (base / "mod" / name / "regulation.bin").write_bytes(name.encode())
    prof = base / "p.me3"
    prof.write_text("[[packages]]\nid = \"a\"\npath = 'mod/a'\n\n[[packages]]\nid = \"b\"\npath = 'mod/b'\n")
    monkeypatch.setattr(locate, "installed_dir", lambda _game: None)
    assert merge.setup_problem(prof, loc=er()) is None
    assert Path(prof).is_file()
