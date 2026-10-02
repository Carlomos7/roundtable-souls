"""The move from the Inno Setup install: uninstall the old program (never the data), recreate shortcuts, point
Steam shortcuts at the new copy; continued at a later start when something had to wait."""

from pathlib import Path

import pytest

from roundtable_souls import migration
from roundtable_souls.config import settings
from roundtable_souls.platform import steam_shortcuts


@pytest.fixture
def installed(monkeypatch):
    monkeypatch.setattr(migration, "is_installed", lambda: True)
    monkeypatch.setattr(migration, "_windows", lambda: True)
    monkeypatch.setattr(migration, "identity_matches", lambda: True)


class _Inno:
    """A fake old install: its uninstaller removes the program and the registry entry, nothing else."""

    def __init__(self, tmp_path: Path):
        self.folder = tmp_path / "Programs" / "Roundtable Souls"
        self.folder.mkdir(parents=True)
        (self.folder / "RoundtableSouls.exe").write_bytes(b"old")
        self.data = tmp_path / "LocalAppData" / "RoundtableSouls"
        self.data.mkdir(parents=True)
        (self.data / "launcher_settings.json").write_text("{}")
        self.registered = True
        self.ran = []

    def find(self):
        if not self.registered:
            return None
        return migration.InnoInstall(self.folder, "3.13.2", self.folder / "unins000.exe")

    def run(self, args, check=False):
        self.ran.append(args)
        (self.folder / "RoundtableSouls.exe").unlink()
        self.registered = False
        return type("R", (), {"returncode": 0})()


def _links(tmp_path):
    links = {
        "start_menu": tmp_path / "Start" / "Roundtable Souls.lnk",
        "desktop": tmp_path / "Desktop" / "Roundtable Souls.lnk",
    }
    return lambda: links


def test_migration_uninstalls_the_old_program_keeps_data_and_fixes_shortcuts(tmp_path, installed):
    inno = _Inno(tmp_path)
    shortcuts = _links(tmp_path)
    shortcuts()["desktop"].parent.mkdir()
    shortcuts()["desktop"].write_text("old desktop shortcut")
    made, steam_calls = [], []
    target = tmp_path / "Carlomos7.RoundtableSouls" / "Roundtable Souls.exe"

    def steam(olds, new):
        steam_calls.append((olds, new))
        return [steam_shortcuts.Shortcut(Path("f"), "0", "Elden Ring", "", "", "--game er --play")]

    record = migration.migrate_from_inno(
        find=inno.find, run=inno.run, running=lambda exe: False, shortcuts=shortcuts,
        make_shortcut=lambda lnk, t: made.append((lnk.name, lnk.parent.name, t)), steam=steam, target=target,
        wait=lambda s: None,
    )  # fmt: skip
    assert inno.ran == [[str(inno.folder / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]]
    assert (inno.data / "launcher_settings.json").is_file()  # the data folder is never touched
    assert made == [("Roundtable Souls.lnk", "Start", target), ("Roundtable Souls.lnk", "Desktop", target)]
    assert steam_calls == [([inno.folder / "RoundtableSouls.exe"], target)]
    assert (
        record["status"] == "done" and record["steam_changed"] == ["Elden Ring"] and record["old_version"] == "3.13.2"
    )
    assert migration.migrate_from_inno(find=inno.find) is None  # done once


def test_migration_waits_while_the_old_program_runs(tmp_path, installed):
    inno = _Inno(tmp_path)
    record = migration.migrate_from_inno(
        find=inno.find, run=inno.run, running=lambda exe: True, target=tmp_path / "Roundtable Souls.exe"
    )
    assert record["status"] == "waiting" and inno.ran == [] and inno.registered


def test_steam_step_waits_for_steam_to_close_then_finishes(tmp_path, installed, monkeypatch):
    inno = _Inno(tmp_path)

    def steam_open(olds, new):
        raise RuntimeError("Steam is running; close it first")

    record = migration.migrate_from_inno(
        find=inno.find, run=inno.run, running=lambda exe: False, shortcuts=_links(tmp_path),
        make_shortcut=lambda *a: None, steam=steam_open, target=tmp_path / "Roundtable Souls.exe", wait=lambda s: None,
    )  # fmt: skip
    assert record["status"] == "steam_pending" and not record["done"] and not inno.registered
    monkeypatch.setattr(migration, "retarget_steam", lambda olds, new: [])
    migration.finish_steam_step(target=tmp_path / "Roundtable Souls.exe")
    assert settings.load_settings()["inno_migration"]["done"]


def test_no_migration_outside_an_installed_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(migration, "is_installed", lambda: False)
    inno = _Inno(tmp_path)
    assert migration.migrate_from_inno(find=inno.find, run=inno.run) is None and inno.registered


def test_no_migration_from_a_build_of_another_app_id(tmp_path, installed, monkeypatch):
    """A build carrying another identity (a test build, say) never acts on an install that is not its own."""
    monkeypatch.setattr(migration, "identity_matches", lambda: False)
    inno = _Inno(tmp_path)
    assert migration.migrate_from_inno(find=inno.find, run=inno.run, running=lambda exe: False) is None
    assert inno.ran == [] and inno.registered


def test_shortcuts_only_ever_go_to_this_installs_stub(tmp_path, installed):
    inno = _Inno(tmp_path)
    record = migration.migrate_from_inno(
        find=inno.find, run=inno.run, running=lambda exe: False, target=tmp_path / "current" / "RoundtableSouls.exe"
    )
    assert record is None and inno.ran == [] and inno.registered
