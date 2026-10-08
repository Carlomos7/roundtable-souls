"""The one profile writer (mods.profile_writer): every change planned under the rules and written once; a refused
plan writes nothing; a profile changed outside the launcher since it was read is never overwritten, standalone or
inside an operation. Temporary folders only."""

import os

import pytest
from test_mod_merge import World

from roundtable_souls.merging import build as B
from roundtable_souls.mods import history, operations
from roundtable_souls.mods import profile_writer as W
from support import er

PROFILE = (
    'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n\n'
    "# co-op\n[[natives]]\npath = 'natives/SeamlessCoop/ersc.dll'\nload_early = true\n\n"
    "# a DLL mod\n[[natives]]\npath = 'natives/cam/cam.dll'\n\n"
    "# flowers\n[[packages]]\nid = \"flora\"\npath = 'mod/flora'\n\n"
    "[[packages]]\nid = \"rocks\"\npath = 'mod/rocks'\n"
)


@pytest.fixture
def profile(tmp_path):
    root = tmp_path / "profiles"
    for folder in ("mod/flora", "mod/rocks"):
        (root / folder).mkdir(parents=True)
    for dll in ("natives/SeamlessCoop/ersc.dll", "natives/cam/cam.dll", "natives/other/ersc.dll"):
        (root / dll).parent.mkdir(parents=True, exist_ok=True)
        (root / dll).write_bytes(b"d")
    p = root / "my.me3"
    p.write_text(PROFILE, encoding="utf-8", newline="")
    return p


def names(w_or_text) -> list[str]:
    text = w_or_text if isinstance(w_or_text, str) else w_or_text.text
    from roundtable_souls.formats import me3_profile

    return [e["name"] for e in me3_profile.entries(text)]


# ----------------------------------------------------------------------------- planning and writing
def test_edits_change_only_the_text_in_memory_until_commit(profile):
    w = W.ProfileWriter(profile, er())
    w.add_package("grass", profile.parent / "mod" / "grass")
    w.set_options(1, {"enabled": False})
    plan = w.plan("before installing grass")
    assert plan.ok and plan.changes[0].action == "add" and plan.changes[1].action == "options"
    assert profile.read_text(encoding="utf-8") == PROFILE  # nothing written yet
    assert "path = 'mod/grass'" in plan.text and names(plan.text)[-1] == "grass"
    bak = w.commit(plan)
    text = profile.read_text(encoding="utf-8")
    assert "# flowers\n" in text and "# co-op\n" in text  # comments survived: text surgery
    assert "path = 'mod/grass'" in text and "enabled = false" in text
    assert bak == profile.with_name("my.me3.bak") and bak.read_text(encoding="utf-8") == PROFILE
    assert [v["why"] for v in history.versions(profile)] == ["before installing grass"]
    assert plan.snapshot is not None and plan.snapshot.read_text(encoding="utf-8") == PROFILE


def test_nothing_to_change_writes_nothing(profile):
    w = W.ProfileWriter(profile)
    assert w.commit(w.plan("nothing")) is None
    assert not profile.with_name("my.me3.bak").exists() and history.versions(profile) == []


def test_an_inline_array_profile_is_converted_to_blocks_when_written(tmp_path):
    p = tmp_path / "r.me3"
    p.write_text('profileVersion = "v1"\npackages = [ { id = "a", path = "mod/a" } ]\n', encoding="utf-8")
    w = W.ProfileWriter(p)
    w.set_options(0, {"enabled": False})
    w.write("before turning a off")
    assert p.read_text(encoding="utf-8").startswith('profileVersion = "v1"\n\n[[packages]]\nid = "a"')


def test_a_new_profile_is_created_and_refused_when_one_appeared_meanwhile(tmp_path):
    p = tmp_path / "new.me3"
    w = W.ProfileWriter.create(p, 'profileVersion = "v1"\n')
    plan = w.plan("new profile")
    assert plan.ok
    p.write_text("someone else's\n", encoding="utf-8")
    with pytest.raises(W.Refused, match="new.me3 already exists"):
        w.commit(plan)
    assert p.read_text(encoding="utf-8") == "someone else's\n"
    p.unlink()
    w.commit(plan)
    assert p.read_text(encoding="utf-8") == 'profileVersion = "v1"\n' and not p.with_name("new.me3.bak").exists()


# ----------------------------------------------------------------------------- unchanged since read
def test_a_profile_changed_outside_the_launcher_is_not_overwritten(profile):
    w = W.ProfileWriter(profile, er())
    w.set_options(1, {"enabled": False})
    plan = w.plan("before turning cam.dll off")
    assert plan.ok
    edited = PROFILE + "\n# edited in a text editor meanwhile\n"
    profile.write_text(edited, encoding="utf-8", newline="")
    with pytest.raises(W.Refused) as e:
        w.commit(plan)
    assert str(e.value) == "the profile changed outside the launcher; reload and try again"
    assert e.value.refusals[0].rule == "unchanged-since-read"
    assert profile.read_text(encoding="utf-8") == edited
    assert not profile.with_name("my.me3.bak").exists() and history.versions(profile) == []
    # planning again on the stale writer says so too, before anything is attempted
    assert [r.message for r in w.plan("again").refusals] == [W.CHANGED_OUTSIDE]
    # a fresh read goes through
    fresh = W.ProfileWriter(profile, er())
    fresh.set_options(1, {"enabled": False})
    fresh.write("before turning cam.dll off")
    assert "# edited in a text editor meanwhile" in profile.read_text(encoding="utf-8")


def test_a_write_waits_for_another_windows_operation_and_then_refuses(profile, monkeypatch):
    """A standalone write takes the folder's lock, as operations do: while another launcher window holds it (here
    another thread), the write waits briefly, then refuses with the reason and leaves the file alone."""
    import threading

    monkeypatch.setattr(W, "STANDALONE_LOCK_WAIT", 0.3)
    held, release = threading.Event(), threading.Event()

    def other_window():
        with operations.lock(profile):
            held.set()
            release.wait(10)

    t = threading.Thread(target=other_window)
    t.start()
    try:
        assert held.wait(10)
        w = W.ProfileWriter(profile, er())
        w.set_options(1, {"enabled": False})
        with pytest.raises(B.BuildError, match="another launcher window"):
            w.write("before turning cam.dll off")
        assert profile.read_text(encoding="utf-8") == PROFILE
    finally:
        release.set()
        t.join(10)
    w.write("before turning cam.dll off")  # once the other window is done, the same change goes through
    assert profile.read_text(encoding="utf-8") != PROFILE


def test_inside_an_operation_the_journal_checks_again_before_its_file_step(profile):
    root = profile.parent
    w = W.ProfileWriter(profile, er())
    w.remove_entry(3)  # rocks
    plan = w.plan("before removing rocks")
    with operations.lock(profile):
        op = operations.start(profile, "removal of rocks")
        w.commit(plan, operation=op)
        assert profile.read_text(encoding="utf-8") == PROFILE  # staged in the journal, not applied
        assert op.steps[0]["expect"] and len(op.steps[0]["expect"]) == 64
        profile.write_text(PROFILE + "# meanwhile\n", encoding="utf-8", newline="")
        with pytest.raises(B.BuildError, match="my.me3 changed outside the launcher; reload and try again"):
            op.commit()
    assert profile.read_text(encoding="utf-8") == PROFILE + "# meanwhile\n"
    assert B.pending(root) == [] and B.active(root) == []


def test_an_operation_interrupted_at_the_profile_step_is_undone_on_the_next_start(profile, monkeypatch):
    w = W.ProfileWriter(profile, er())
    w.remove_entry(3)
    plan = w.plan("before removing rocks")
    op = operations.start(profile, "removal of rocks")
    w.commit(plan, operation=op)
    real = B.os.replace

    class Crash(BaseException):
        pass

    def dying(src, dst):
        real(src, dst)
        if str(dst).endswith("my.me3"):  # the new bytes landed, and the process died before the journal said so
            raise Crash()

    with monkeypatch.context() as m:
        m.setattr(B.os, "replace", dying)
        m.setattr(B, "_undo", lambda op: None)
        with pytest.raises(Crash):
            op.commit()
    assert "rocks" not in profile.read_text(encoding="utf-8")
    assert operations.pending(profile) == ["removal of rocks"]
    said = operations.recover(profile)
    assert said == ["an interrupted removal of rocks was undone: the previous state is back"]
    assert profile.read_text(encoding="utf-8") == PROFILE
    assert operations.pending(profile) == []


# ----------------------------------------------------------------------------- the rules refuse, and write nothing
def test_a_refused_plan_writes_nothing(profile):
    w = W.ProfileWriter(profile, er())
    w.add_native(profile.parent / "natives" / "other" / "ersc.dll")  # a second ersc.dll switched on
    plan = w.plan("before installing other")
    assert not plan.ok and plan.refusals[0].rule == "valid-for-me3"
    with pytest.raises(W.Refused) as e:
        w.commit(plan)
    assert str(e.value) == (
        "Two switched-on DLLs are named ersc.dll (natives/SeamlessCoop/ersc.dll and natives/other/ersc.dll); "
        "me3 refers to DLLs by file name, so only one can be on"
    )
    assert profile.read_text(encoding="utf-8") == PROFILE
    assert not profile.with_name("my.me3.bak").exists() and history.versions(profile) == []


def test_a_second_dll_with_the_same_name_may_be_added_switched_off(profile):
    w = W.ProfileWriter(profile, er())
    w.add_native("natives/other/ersc.dll", enabled=False)
    assert w.plan("x").ok


def test_me3_refusals_a_duplicate_id_and_a_loop(profile):
    w = W.ProfileWriter(profile, er())
    w.set_options(3, {"id": "flora"})
    assert [r.message for r in w.plan("x").refusals] == ["Id 'flora' is used twice; me3 needs each id once"]
    w = W.ProfileWriter(profile, er())
    w.set_options(2, {"load_after": [{"id": "rocks", "optional": False}]})
    w.set_options(3, {"load_after": [{"id": "flora", "optional": False}]})
    assert [r.message for r in w.plan("x").refusals] == ["Load order loops: flora → rocks → flora; me3 would not start"]
    w = W.ProfileWriter(profile, er())
    w.set_options(3, {"load_after": [{"id": "trees", "optional": False}]})
    assert [r.message for r in w.plan("x").refusals] == [
        "Must load after 'trees', which is not in this profile: me3 stops"
    ]


def test_a_problem_the_profile_already_had_is_noted_not_refused(profile):
    text = PROFILE.replace('id = "rocks"', 'id = "flora"')
    profile.write_text(text, encoding="utf-8", newline="")
    w = W.ProfileWriter(profile, er())
    w.set_options(1, {"enabled": False})  # switching a DLL off while the ids clash: still allowed
    plan = w.plan("before turning cam.dll off")
    assert plan.ok and plan.notes["problems"] == ["Id 'flora' is used twice; me3 needs each id once"]
    w.commit(plan)
    assert "enabled = false" in profile.read_text(encoding="utf-8")


def test_a_shared_dependency_is_only_removed_or_switched_off_on_purpose(profile):
    w = W.ProfileWriter(profile, er())
    w.set_options(0, {"enabled": False})  # aimed at Seamless itself: the player's call
    assert w.plan("before turning ersc.dll off").ok
    w = W.ProfileWriter(profile, er())
    w.remove_entry(0)
    assert w.plan("before removing ersc.dll").ok
    # a whole-block rewrite aimed elsewhere that loses it as a side effect
    w = W.ProfileWriter(profile, er())
    w.replace_block(1, ["[[natives]]\n", "path = 'natives/cam/cam.dll'\n"])
    w.text = w.text.replace(
        "path = 'natives/SeamlessCoop/ersc.dll'\n", "path = 'natives/SeamlessCoop/ersc.dll'\nenabled = false\n"
    )
    assert [r.message for r in w.plan("x").refusals] == [
        "ersc.dll is a shared dependency and stays switched on; this change would switch it off as a side effect"
    ]


def test_declared_dependencies_stay_present_and_switched_on(profile):
    needs = W.StaticRequirements({"flora": [W.Requirement("native", "ersc.dll"), W.Requirement("package", "rocks")]})
    w = W.ProfileWriter(profile, er(), requirements=needs)
    w.set_options(0, {"enabled": False})
    assert [r.message for r in w.plan("x").refusals] == [
        "flora needs ersc.dll, which this change would leave switched off"
    ]
    w = W.ProfileWriter(profile, er(), requirements=needs)
    w.remove_entry(3)
    assert [r.message for r in w.plan("x").refusals] == [
        "flora needs rocks, which this change would leave out of the profile"
    ]
    w = W.ProfileWriter(profile, er(), requirements=needs)
    w.set_options(2, {"enabled": False})  # flora itself off: it needs nothing then
    w.remove_entry(3)
    assert w.plan("x").ok
    # a new mod whose needs the profile does not meet
    needs = W.StaticRequirements({"grass": [W.Requirement("package", "trees")]})
    w = W.ProfileWriter(profile, er(), requirements=needs)
    w.add_package("grass", "mod/grass")
    assert [r.message for r in w.plan("x").refusals] == [
        "grass needs trees, which this change would leave out of the profile"
    ]


GROVE = """overhaul = 1
id = "grove"
label = "Grove"
short_label = "Grove"
game = "eldenring"

[recognise]
folder = "Grove"
manifest = "grove.json"

[[builds]]
id = "grove"
match = { files = ["grove.json"] }
output = { mod = "mod" }
steps = []
requires = [{ native = "cam.dll" }]

[builds.install]
owned_package_ids = ["grove"]
"""


def test_the_overhaul_configs_requirements_are_the_default_source(profile):
    """An entry an overhaul owns needs what its author's config declares (here a made-up overhaul's local config):
    switching that off is refused while the overhaul is on; the player's own entries need nothing, and an overhaul
    that declares nothing (Revive) needs nothing."""
    from roundtable_souls import overhauls

    local = overhauls.local_dir()
    assert local is not None
    local.mkdir(parents=True, exist_ok=True)
    (local / "grove.toml").write_text(GROVE, encoding="utf-8")
    profile.write_text(PROFILE + "\n[[packages]]\nid = \"grove\"\npath = 'Grove/mod'\n")
    w = W.ProfileWriter(profile, rules=[W.Requires()])
    w.set_options(1, {"enabled": False})
    assert [r.message for r in w.plan("x").refusals] == [
        "grove needs cam.dll, which this change would leave switched off"
    ]
    w = W.ProfileWriter(profile, rules=[W.Requires()])
    w.set_options(4, {"enabled": False})  # the overhaul itself off: then nothing needs cam.dll
    w.set_options(1, {"enabled": False})
    assert w.plan("x").ok
    assert W.OverhaulRequirements().of({"kind": "package", "id": "flora", "path": "mod/flora"}) == []
    assert W.OverhaulRequirements().of({"kind": "package", "id": "nightreign-revive", "path": "x"}) == []


def test_added_entries_get_relative_paths_and_a_length_check(profile):
    w = W.ProfileWriter(profile, er())
    row = w.add_package("grass", profile.parent / "mod" / "grass")
    assert row["path"] == "mod/grass"
    assert w.add_native(str(profile.parent / "natives" / "x" / "x.dll"))["path"] == "natives/x/x.dll"
    assert w.add_native("natives\\y\\y.dll")["path"] == "natives/y/y.dll"
    assert w.plan("x").ok
    w = W.ProfileWriter(profile, er())
    w.add_package("long", "mod/" + "x" * 180)
    [r] = w.plan("x").refusals
    assert r.rule == "paths" and "is too long a path for Windows" in r.message and "220 are safe" in r.message
    w = W.ProfileWriter(profile, er())
    w.add_entry("package", {"id": "deep", "path": "mod/deep"}, deepest=200)
    assert w.plan("x").refusals[0].rule == "paths"
    # the player's own long entry is left alone: only what the launcher adds is checked
    profile.write_text(PROFILE + f"\n[[packages]]\nid = \"old\"\npath = 'mod/{'y' * 180}'\n", encoding="utf-8")
    w = W.ProfileWriter(profile, er())
    w.set_options(1, {"enabled": False})
    assert w.plan("x").ok


def test_a_verbatim_text_goes_through_safety_and_the_unchanged_check_only(profile):
    w = W.ProfileWriter(profile, er())
    w.replace_text(PROFILE.replace('id = "rocks"', 'id = "flora"'))  # the editor's text, ids clashing and all
    plan = w.plan("before saving the editor")
    assert plan.ok and plan.verbatim
    w.commit(plan)
    assert "id = \"flora\"\npath = 'mod/rocks'" in profile.read_text(encoding="utf-8")
    assert profile.with_name("my.me3.bak").read_text(encoding="utf-8") == PROFILE
    w = W.ProfileWriter(profile)
    w.restore_bytes(PROFILE.encode())
    profile.write_text("changed\n", encoding="utf-8")
    with pytest.raises(W.Refused, match="changed outside the launcher"):
        w.write("before restoring an earlier version")
    assert profile.read_text(encoding="utf-8") == "changed\n"


def test_rules_are_plug_ins_run_in_order(profile):
    seen = []

    class Noting(W.ProfileRule):
        name = "noting"

        def adjust(self, plan):
            seen.append("adjust")
            plan.notes["seen"] = True

        def check(self, plan):
            seen.append("check")
            return []

        def before_write(self, plan):
            seen.append("write")
            return None

    class Never(W.ProfileRule):
        name = "never"

        def check(self, plan):
            return [W.Refusal(self.name, "not today")]

    w = W.ProfileWriter(profile, rules=[Noting(), W.UnchangedSinceRead(), W.Safety()])
    w.set_setting("start_online", True)
    plan = w.write("x")
    assert seen == ["adjust", "check", "write"] and plan.notes["seen"] and plan.written
    assert "start_online = true" in profile.read_text(encoding="utf-8")
    w = W.ProfileWriter(profile, rules=[Never()])
    w.set_setting("start_online", False)
    with pytest.raises(W.Refused, match="not today"):
        w.write("x")
    assert "start_online = true" in profile.read_text(encoding="utf-8")


# ----------------------------------------------------------------------------- the mod that must stay last
@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def test_new_entries_go_before_the_mod_that_must_stay_last_and_its_lists_follow(world):
    w = W.ProfileWriter(world.profile, er())
    assert w.target is not None and w.target["name"] == "last"
    (world.base / "mod" / "grass").mkdir()
    w.add_package("grass", "mod/grass")
    plan = w.plan("before installing grass")
    assert plan.ok and names(plan.text).index("grass") < names(plan.text).index("last")
    assert '{ id = "grass", optional = true }' in plan.text
    w.commit(plan)
    assert "order_problem" not in plan.notes


def test_kept_after_it_on_purpose_names_it_in_its_own_list(world):
    w = W.ProfileWriter(world.profile, er())
    (world.base / "mod" / "late").mkdir()
    row = w.add_package("late", "mod/late", after_last=True)
    assert row["load_after"] == [{"id": "last", "optional": True}]
    plan = w.plan("x")
    assert plan.ok and names(plan.text)[-1] == "late"


def test_without_locations_the_stay_last_rule_does_nothing(world):
    w = W.ProfileWriter(world.profile)
    (world.base / "mod" / "grass").mkdir()
    w.add_package("grass", "mod/grass")
    plan = w.plan("x")
    assert plan.ok and names(plan.text)[-1] == "grass" and '{ id = "grass"' not in plan.text


def test_the_profile_folder_is_never_left_with_a_temp_file(profile):
    w = W.ProfileWriter(profile)
    w.set_setting("start_online", True)
    w.write("x")
    # the folder's lock file (shared with operations) is expected; nothing else is left beside the profile
    assert sorted(p.name for p in profile.parent.iterdir() if p.is_file()) == [
        ".roundtable-ops.lock",
        "my.me3",
        "my.me3.bak",
    ]
    assert not any(p.name.endswith(".tmp") for p in os.scandir(profile.parent))
