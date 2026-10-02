"""Merge health: states, staleness, install offers and rebuilds, with a fake merger (no real merger runs in tests)."""

import hashlib
import json
import tomllib
import zipfile
from pathlib import Path

import pytest

from roundtable_souls.mods import backends, merge
from roundtable_souls.mods import manage as M
from roundtable_souls.platform import common

TALK = "script/talk/m00_00_00_00.talkesdbnd.dcx"
PROFILE = (
    'profileVersion = "v1"\n\n'
    "# base mods\n[[packages]]\nid = \"parts\"\npath = 'mod/parts'\n\n"
    "# the merger's package must stay last\n[[packages]]\nid = \"last\"\npath = 'Merger/mod'\n"
    'load_after = [\n  { id = "parts", optional = true },\n]\n'
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class World:
    """A profile folder with a package that must stay last, its merger's setup files and manifest, and a game."""

    def __init__(self, tmp_path, monkeypatch):
        self.base = tmp_path / "profiles" / "er"
        self.game = tmp_path / "Game"
        self.game.mkdir(parents=True)
        (self.game / "regulation.bin").write_bytes(b"GAME")
        (self.game / "eldenring.exe").write_bytes(b"x")
        monkeypatch.setattr(common, "game_dir", lambda: self.game)
        monkeypatch.setattr(common, "game_running", lambda: False)
        (self.base / "mod" / "parts" / "parts").mkdir(parents=True)
        self.winner = self.base / "Merger" / "mod"
        (self.winner / "script" / "talk").mkdir(parents=True)
        (self.winner / "regulation.bin").write_bytes(b"MERGED")
        (self.winner / TALK).write_bytes(b"MERGED-TALK")
        self.setup = self.base / ".merger-setup"
        for f in ("installer/installer.py", "tools/python/python.exe", "payload/mod/regulation.bin"):
            (self.setup / f).parent.mkdir(parents=True, exist_ok=True)
            (self.setup / f).write_bytes(b"s")
        (self.setup / "payload/settings/vanilla" / TALK).parent.mkdir(parents=True)
        (self.setup / "payload/settings/vanilla" / TALK).write_bytes(b"VANILLA-TALK")
        (self.setup / "merger-maintenance.json").write_text('{"protocol": 1}')
        self.profile = self.base / "p.me3"
        self.profile.write_text(PROFILE, encoding="utf-8")
        self.runs = 0
        monkeypatch.setattr(backends.Tool, "run", lambda b, log: self.fake_run(b))
        self.fake_run(None)  # a first merge, as the tool's own installer leaves it
        merge.approve(merge.find_backend(self.profile))

    def pack(self, name, files=("regulation.bin",), before="last", listed=True):
        """A package placed before the merger and (listed) in its load_after, as the launcher's install does: me3
        orders by load_after runs, so a package the merger does not list loads after it."""
        d = self.base / "mod" / name
        for f in files:
            (d / f).parent.mkdir(parents=True, exist_ok=True)
            (d / f).write_bytes(f"{name}:{f}".encode())
        text = self.profile.read_text(encoding="utf-8")
        at = text.index("# the merger's package")
        text = text[:at] + f"[[packages]]\nid = \"{name}\"\npath = 'mod/{name}'\n\n" + text[at:]
        marker = "load_after = [\n"
        if listed and marker in text[at:]:  # at the end of the list: me3 loads what it names in its order
            i = text.index("]\n", text.index(marker, at))
            text = text[:i] + f'  {{ id = "{name}", optional = true }},\n' + text[i:]
        self.profile.write_text(text)
        return d

    def fake_run(self, backend, rewrite=True, fail=False, sources_from_game=False):
        """What the merger does: each merged file from the last layer before it that has one (else the game's or its
        own vanilla copy), its sources listed with sha256; and the profile rewritten without comments."""
        self.runs += 1
        if fail:
            raise backends.BackendError("merge tool refused a file")
        layers = merge.layers(self.profile)
        before = [l for l in layers if l["name"] != "last"]
        sources = []
        for rel, base in (
            ("regulation.bin", self.game / "regulation.bin"),
            (TALK, self.setup / "payload/settings/vanilla" / TALK),
        ):
            src = next((l["folder"] / rel for l in reversed(before) if (l["folder"] / rel).is_file()), base)
            if sources_from_game and rel == "regulation.bin":
                src = base
            sources.append({"path": str(src), "sha256": _sha(src)})
        sources.append({"path": str(self.profile), "sha256": _sha(self.profile)})
        data = {
            "refreshProtocol": 1,
            "maintenance": str(self.setup),
            "game": str(self.game / "eldenring.exe"),
            "sources": sources,
        }
        (self.base / "Merger" / "installation.json").write_text(json.dumps(data), encoding="utf-8")
        if rewrite and backend is not None:  # comments gone, array form, its own load_after refreshed
            doc = tomllib.loads(self.profile.read_text(encoding="utf-8"))
            ids = [p["id"] for p in doc["packages"] if p["id"] != "last"]
            rows = []
            for p in doc["packages"]:
                row = f'{{ id = "{p["id"]}", path = "{(self.base / p["path"]).as_posix()}"'
                if p.get("enabled") is False:
                    row += ", enabled = false"
                if p["id"] == "last":
                    row += ", load_after = [" + ", ".join(f'{{ id = "{i}", optional = true }}' for i in ids) + "]"
                rows.append(row + " }")
            self.profile.write_text('profileVersion = "v1"\npackages = [' + ", ".join(rows) + "]\n", encoding="utf-8")


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


# ----------------------------------------------------------------------------- states
def test_no_merger_is_single_or_stacked(tmp_path, monkeypatch):
    base = tmp_path / "p"
    for name in ("a", "b"):
        (base / "mod" / name).mkdir(parents=True)
        (base / "mod" / name / "regulation.bin").write_bytes(name.encode())
    prof = base / "p.me3"
    prof.write_text("[[packages]]\nid = \"a\"\npath = 'mod/a'\n", encoding="utf-8")
    assert merge.health(prof)["state"] == "single"
    prof.write_text(prof.read_text() + "[[packages]]\nid = \"b\"\npath = 'mod/b'\n", encoding="utf-8")
    h = merge.health(prof)
    assert h["state"] == "stacked" and h["winner"] == "b" and h["backend"] is None


def test_a_fresh_merge_is_current_and_names_its_merger(world):
    h = merge.health(world.profile)
    assert h["state"] == "current" and h["backend"] == "the rebuild tool of last" and h["reasons"] == []


def test_a_new_pack_before_the_merger_makes_it_stale_until_rebuilt(world):
    world.pack("params", ("regulation.bin", TALK))
    h = merge.health(world.profile)
    assert h["state"] == "stale" and h["packs"] == ["params", "last"]
    assert any(r.startswith("regulation.bin: params ships it now") for r in h["reasons"])
    assert any(r.startswith(f"{TALK}: params ships it now") for r in h["reasons"])
    out = merge.rebuild(world.profile, lambda s: None)
    assert merge.health(world.profile)["state"] == "current"
    assert "comments were kept" in out["profile_note"]


def test_changed_bytes_disabling_and_uninstalling_a_source_make_it_stale(world):
    d = world.pack("params")
    merge.rebuild(world.profile, lambda s: None)
    (d / "regulation.bin").write_bytes(b"params v2, a bit longer")
    assert "copy changed" in merge.health(world.profile)["reasons"][0]
    merge.rebuild(world.profile, lambda s: None)
    idx = next(e["index"] for e in M.entries(world.profile) if e["name"] == "params")
    M.set_options(world.profile, idx, {"enabled": False})
    assert "params is no longer loaded" in merge.health(world.profile)["reasons"][0]
    M.set_options(world.profile, idx, {"enabled": True})
    assert merge.health(world.profile)["state"] == "current"
    M.uninstall(world.profile, idx)
    h = merge.health(world.profile)
    assert h["state"] == "stale" and "params is no longer loaded" in h["reasons"][0]
    assert "still in last's build" in h["reasons"][0]  # named by its folder, with what it means


def test_a_pack_after_the_merger_is_named(world):
    text = world.profile.read_text(encoding="utf-8")
    (world.base / "mod" / "late").mkdir()
    (world.base / "mod" / "late" / "regulation.bin").write_bytes(b"late")
    world.profile.write_text(text + "\n[[packages]]\nid = \"late\"\npath = 'mod/late'\n", encoding="utf-8")
    h = merge.health(world.profile)
    assert h["state"] == "stale" and h["reasons"] == ["late loads after last, the package that must stay last"]


def test_a_game_update_makes_it_stale(world):
    (world.game / "regulation.bin").write_bytes(b"GAME 1.17")
    assert "game's copy changed" in merge.health(world.profile)["reasons"][0]


def test_a_merger_without_a_source_list_is_never_current(world):
    m = world.base / "Merger" / "installation.json"
    data = json.loads(m.read_text())
    data["sources"] = []
    m.write_text(json.dumps(data))
    h = merge.health(world.profile)
    assert h["state"] == "stale" and "left no list" in h["reasons"][0]


def test_sources_written_on_another_pc_are_found_here(world):
    m = world.base / "Merger" / "installation.json"
    data = json.loads(m.read_text())
    for s in data["sources"]:
        s["path"] = s["path"].replace(
            str(world.base.parent), r"C:\Users\someone\AppData\Local\garyttierney\me3\config\profiles"
        )
        s["path"] = s["path"].replace(str(world.game), r"D:\SteamLibrary\steamapps\common\ELDEN RING\Game")
    m.write_text(json.dumps(data))
    assert merge.health(world.profile)["state"] == "current"
    assert (
        backends.local_path(r"D:\Steam\ELDEN RING\Game\regulation.bin", world.profile, world.game)
        == world.game / "regulation.bin"
    )


def test_not_for_other_games(world):
    world.profile.write_text('[[supports]]\ngame = "nightreign"\n\n' + world.profile.read_text(encoding="utf-8"))
    common._PROFILE_GAMES_CACHE.clear()
    assert merge.health(world.profile)["state"] is None


# ----------------------------------------------------------------------------- rebuilds
def test_a_rebuild_that_does_not_use_the_new_pack_fails_and_says_so(world, monkeypatch):
    world.pack("params")
    monkeypatch.setattr(backends.Tool, "run", lambda b, log: world.fake_run(b, sources_from_game=True))
    with pytest.raises(merge.MergeError, match="does not match the packages"):
        merge.rebuild(world.profile, lambda s: None)
    h = merge.health(world.profile)
    assert h["state"] == "failed" and "does not match" in h["reasons"][0]
    monkeypatch.setattr(backends.Tool, "run", lambda b, log: world.fake_run(b))
    merge.rebuild(world.profile, lambda s: None)
    assert merge.health(world.profile)["state"] == "current"  # a good run clears the failure


def test_a_merger_that_stops_leaves_the_profile_as_it_was(world, monkeypatch):
    world.pack("params")
    before = world.profile.read_text(encoding="utf-8")
    monkeypatch.setattr(backends.Tool, "run", lambda b, log: world.fake_run(b, fail=True))
    with pytest.raises(merge.MergeError, match="refused"):
        merge.rebuild(world.profile, lambda s: None)
    assert world.profile.read_text(encoding="utf-8") == before and merge.health(world.profile)["state"] == "failed"


def test_no_rebuild_while_the_game_runs(world, monkeypatch):
    monkeypatch.setattr(common, "game_running", lambda: True)
    with pytest.raises(merge.MergeError, match="Close the game"):
        merge.rebuild(world.profile, lambda s: None)
    assert world.runs == 1


def test_the_profile_text_comes_back_with_only_the_mergers_lists_updated(world):
    world.pack("params")
    merge.rebuild(world.profile, lambda s: None)
    text = world.profile.read_text(encoding="utf-8")
    assert "# the merger's package must stay last" in text and "# base mods" in text
    last = next(e for e in M.entries(world.profile) if e["name"] == "last")
    assert [d["id"] for d in last["load_after"]] == ["parts", "params"]
    assert text.index('{ id = "params", optional = true }') > text.index("load_after = [\n")  # one per line, in place


def test_a_merger_that_changes_what_loads_keeps_its_version(world, monkeypatch):
    world.pack("params")

    def drops_a_pack(b, log):
        world.fake_run(b)
        t = world.profile.read_text(encoding="utf-8")
        world.profile.write_text(t.replace('{ id = "parts"', '{ id = "parts", enabled = false', 1), encoding="utf-8")

    monkeypatch.setattr(backends.Tool, "run", drops_a_pack)
    out = merge.rebuild(world.profile, lambda s: None)  # still verified against what loads now
    assert "its version is kept" in out["profile_note"]
    assert "packages = [" in world.profile.read_text(encoding="utf-8")
    assert "# base mods" in (world.base / "p.me3.bak").read_text(encoding="utf-8")


def test_the_command_uses_refresh_here_and_install_for_a_foreign_manifest(world):
    b = merge.find_backend(world.profile)
    assert b.recipe.command[4] == "refresh"
    m = world.base / "Merger" / "installation.json"
    data = json.loads(m.read_text())
    data["maintenance"] = r"C:\Users\someone\profiles\er\.merger-setup"
    m.write_text(json.dumps(data))
    b = merge.find_backend(world.profile)
    cmd = b.recipe.command
    assert b.recipe.cwd == world.setup and cmd[4] == "install" and cmd[cmd.index("--package") + 1] == str(world.setup)
    assert cmd[cmd.index("--target") + 1] == str(world.base)


# ----------------------------------------------------------------------------- install offers
def _pack_source(root: Path, wrapper=True):
    top = root / "Big Params" if wrapper else root
    m = top / "mod"
    (m / "script" / "talk").mkdir(parents=True)
    (m / "regulation.bin").write_bytes(b"PARAMS")
    (m / TALK).write_bytes(b"TALK")
    (m / "menu").mkdir()
    (m / "menu" / "02_120_worldmap.gfx").write_bytes(b"map")
    return root


def test_install_offers_a_rebuild_before_the_merger(world):
    src = _pack_source(world.base.parent.parent / "dl")
    plan = M.plan_install(world.profile, src)
    assert plan["merge_offered"] and plan["merge_label"] == "the rebuild tool of last"
    assert plan["regulation_packages"][-1]["name"] == "last" and plan["merge_source_now"] is None
    assert any("talk file" in n for n in plan["merge_notes"])
    world.pack("older")
    plan = M.plan_install(world.profile, src)
    assert plan["merge_combine"] and plan["merge_tool"]  # combined with older first, so both apply
    assert any("combined with older" in n for n in plan["merge_notes"])


def test_without_a_tool_the_offer_is_to_combine(tmp_path, world):
    (world.base / "Merger" / "installation.json").unlink()
    world.pack("a")
    plan = M.plan_install(world.profile, _pack_source(tmp_path / "dl"))
    assert [x["name"] for x in plan["regulation_packages"]] == ["a", "last"]
    assert not plan["merge_tool"] and plan["merge_combine"]  # no tool: the launcher combines the packs itself


def test_a_zip_and_a_folder_with_the_same_layout_plan_alike(world, tmp_path):
    src = _pack_source(tmp_path / "dl")
    z = tmp_path / "Big Params.zip"
    with zipfile.ZipFile(z, "w") as f:
        for p in src.rglob("*"):
            if p.is_file():
                f.write(p, p.relative_to(src).as_posix())
    keys = ("kind", "merge_offered", "merge_notes", "merge_source_now", "regulation_winner")
    a, b = M.plan_install(world.profile, src), M.plan_install(world.profile, z)
    assert {k: a[k] for k in keys} == {k: b[k] for k in keys}


def test_a_leftover_regulation_bin_does_not_hide_the_real_mod_folder(tmp_path):
    top = tmp_path / "x"
    _pack_source(top, wrapper=False)
    (top / "regulation.bin").write_bytes(b"old")
    assert M.find_roots(top) == [top / "mod"]
    (top / "mod" / "menu").rename(top / "menu")  # a real mod at the top: kept
    assert M.find_roots(tmp_path / "x") == [top]


# ----------------------------------------------------------------------------- overlay set by hand
def _as_fork(world):
    """The merger's record under another name and without a refresh protocol: not found on its own."""
    m = world.base / "Merger" / "installation.json"
    data = json.loads(m.read_text())
    data.pop("refreshProtocol")
    (world.base / "Merger" / "merge-record.json").write_text(json.dumps(data))
    m.unlink()


def test_a_fork_is_found_only_once_set_as_the_overlay(world):
    _as_fork(world)
    world.pack("params")
    assert merge.health(world.profile)["state"] == "stacked"
    merge.set_overlay_override(world.profile, world.winner)
    h = merge.health(world.profile)
    assert h["overlay"] == "last" and h["overlay_set"] and h["state"] == "stale" and h["backend"]
    merge.rebuild(world.profile, lambda s: None)
    assert merge.health(world.profile)["state"] == "current"
    merge.set_overlay_override(world.profile, None)
    assert merge.health(world.profile)["overlay_set"] is False


def test_an_overlay_without_a_tool_still_says_what_must_stay_last(world, tmp_path):
    (world.base / "Merger" / "installation.json").unlink()
    merge.set_overlay_override(world.profile, world.winner)
    h = merge.health(world.profile)
    assert h["backend"] is None and "setup files are missing: installation.json" in h["reasons"][0]
    plan = M.plan_install(world.profile, _pack_source(tmp_path / "dl"))
    assert plan["merge_target"] == "last" and not plan["merge_offered"]
    late = world.base / "mod" / "late"
    late.mkdir()
    (late / "regulation.bin").write_bytes(b"late")
    world.profile.write_text(world.profile.read_text() + "\n[[packages]]\nid = \"late\"\npath = 'mod/late'\n")
    assert "late loads after last" in merge.health(world.profile)["reasons"][1]


def test_an_overlay_mark_for_a_package_that_is_gone_falls_back_to_finding_it(world):
    merge.set_overlay_override(world.profile, world.base / "mod" / "removed")
    h = merge.health(world.profile)
    assert h["overlay"] == "last" and h["overlay_set"] is False and h["state"] == "current"


# ----------------------------------------------------------------------------- rebuild.json (any tool)
TOOL = r"""
import hashlib, json, sys, tomllib
from pathlib import Path
profile, package, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
doc = tomllib.loads(profile.read_text(encoding="utf-8"))
before = [profile.parent / p["path"] for p in doc["packages"] if p.get("enabled", True) and (profile.parent / p["path"]) != package]
sources = []
for rel in ("regulation.bin",):
    src = next((d / rel for d in reversed(before) if (d / rel).is_file()), None)
    if src is None:
        continue
    (package / rel).write_bytes(b"COMBINED:" + src.read_bytes())
    sources.append({"path": str(src), "sha256": hashlib.sha256(src.read_bytes()).hexdigest()})
out.write_text(json.dumps({"sources": sources}))
print("combined", len(sources))
"""


def _declared(tmp_path, monkeypatch):
    """A profile whose last package ships a rebuild.json for a tool of its own (a Python script here)."""
    import sys

    base = tmp_path / "prof"
    monkeypatch.setattr(common, "game_running", lambda: False)
    monkeypatch.setattr(common, "game_dir", lambda: tmp_path / "Game")
    for name in ("params", "overhaul"):
        (base / "mod" / name).mkdir(parents=True)
        (base / "mod" / name / "regulation.bin").write_bytes(name.encode())
    tool = base / "mod" / "overhaul-tools"
    tool.mkdir()
    (tool / "combine.py").write_text(TOOL)
    rebuild = {
        "rebuild": 1,
        "name": "Overhaul's rebuild tool",
        "command": [sys.executable, "combine.py", "{profile}", "{package}", "{package}/sources.json"],
        "cwd": "{here}/../overhaul-tools",
        "merges": ["regulation.bin"],
        "sources": "{package}/sources.json",
    }
    (base / "mod" / "overhaul" / "rebuild.json").write_text(json.dumps(rebuild))
    prof = base / "p.me3"
    prof.write_text(
        "# mine\n[[packages]]\nid = \"params\"\npath = 'mod/params'\n\n[[packages]]\nid = \"overhaul\"\npath = 'mod/overhaul'\n",
        encoding="utf-8",
    )
    return prof


def test_any_tool_with_a_rebuild_json_is_found_asked_about_run_and_verified(tmp_path, monkeypatch):
    prof = _declared(tmp_path, monkeypatch)
    h = merge.health(prof)
    assert h["backend"] == "Overhaul's rebuild tool" and h["state"] == "stale" and "left no list" in h["reasons"][0]
    tool = merge.find_backend(prof)
    assert tool.recipe.command[1] == "combine.py" and tool.recipe.command[2] == str(prof)
    with pytest.raises(merge.MergeError, match="not been allowed"):
        merge.rebuild(prof, lambda s: None)
    merge.approve(tool)
    lines = []
    merge.rebuild(prof, lines.append)
    assert any("combined 1" in l for l in lines)
    assert (prof.parent / "mod" / "overhaul" / "regulation.bin").read_bytes() == b"COMBINED:params"
    assert merge.health(prof)["state"] == "current" and "# mine" in prof.read_text(encoding="utf-8")
    (prof.parent / "mod" / "params" / "regulation.bin").write_bytes(b"params v2")
    assert merge.health(prof)["state"] == "stale"


def test_a_changed_rebuild_json_is_asked_about_again(tmp_path, monkeypatch):
    prof = _declared(tmp_path, monkeypatch)
    merge.approve(merge.find_backend(prof))
    f = prof.parent / "mod" / "overhaul" / "rebuild.json"
    f.write_text(f.read_text().replace("combine.py", "other.py"))
    assert not merge.approved(merge.find_backend(prof))


def test_a_rebuild_json_picked_in_options_works_for_a_tool_that_ships_none(tmp_path, monkeypatch):
    prof = _declared(tmp_path, monkeypatch)
    shipped = prof.parent / "mod" / "overhaul" / "rebuild.json"
    mine = tmp_path / "my-rebuild.json"
    mine.write_text(
        shipped.read_text().replace("{here}/../overhaul-tools", (prof.parent / "mod" / "overhaul-tools").as_posix())
    )
    shipped.unlink()
    assert merge.health(prof)["backend"] is None
    merge.set_overlay_override(prof, prof.parent / "mod" / "overhaul", mine)
    tool = merge.find_backend(prof)
    assert tool is not None and tool.recipe.cwd == prof.parent / "mod" / "overhaul-tools"
    merge.approve(tool)
    merge.rebuild(prof, lambda s: None)
    assert merge.health(prof)["state"] == "current"


def test_a_rebuild_json_that_is_not_one_is_ignored(tmp_path, monkeypatch):
    prof = _declared(tmp_path, monkeypatch)
    (prof.parent / "mod" / "overhaul" / "rebuild.json").write_text('{"rebuild": 2, "command": "rm -rf /"}')
    assert merge.find_backend(prof) is None and merge.health(prof)["state"] == "stacked"


def test_a_missing_program_is_said_before_running(tmp_path, monkeypatch):
    prof = _declared(tmp_path, monkeypatch)
    f = prof.parent / "mod" / "overhaul" / "rebuild.json"
    data = json.loads(f.read_text())
    data["command"][0] = "{here}/tools/missing.exe"
    f.write_text(json.dumps(data))
    tool = merge.find_backend(prof)
    assert "was not found" in tool.problem()
    merge.approve(tool)
    with pytest.raises(merge.MergeError, match="was not found"):
        merge.rebuild(prof, lambda s: None)
