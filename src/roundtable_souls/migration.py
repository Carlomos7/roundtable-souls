"""Moving from the Inno Setup install (releases up to 3.13.2) to this Velopack install, on the first start of an
installed copy.

What it does, in order, each step recorded in the settings (inno_migration) so a later start finishes what is left:
  1. find the old install (its uninstall entry, by the old app ID) and remember which shortcuts it had;
  2. if the old program is running, wait for a later start;
  3. run its uninstaller silently. It removes the old program, its Start menu and desktop shortcuts and its
     uninstall entry; it never touches %LOCALAPPDATA%\\RoundtableSouls, where settings, logs and backups live
     (that folder is also this install's data folder, so nothing needs copying);
  4. recreate the Start menu shortcut (the old uninstaller deletes one with the same name) and, if there was one,
     the desktop shortcut, both pointing at this install's stub;
  5. point Steam shortcuts that started the old program at this one. Steam must be closed for that; while it runs,
     the step stays pending and Settings offers it.
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from roundtable_souls import folders, identity
from roundtable_souls.platform import steam_shortcuts
from roundtable_souls.settings import identity_matches, is_installed, launch_target, load_settings, save_settings


def _windows() -> bool:
    return sys.platform == "win32"


UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"


@dataclass
class InnoInstall:
    folder: Path
    version: str
    uninstaller: Path

    @property
    def exe(self) -> Path:
        return self.folder / f"{identity.get().exe_name}.exe"


def _registry_values(app_id: str) -> dict | None:
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{UNINSTALL_KEY}\{app_id}_is1") as key:
            out = {}
            for name in ("InstallLocation", "DisplayVersion", "UninstallString"):
                try:
                    out[name] = str(winreg.QueryValueEx(key, name)[0])
                except OSError:
                    out[name] = ""
            return out
    except OSError:
        return None


def find_inno_install(read=_registry_values) -> InnoInstall | None:
    values = read(identity.get().inno_app_id)
    if not values:
        return None
    folder = Path(values.get("InstallLocation") or "")
    uninstaller = (
        Path((values.get("UninstallString") or "").strip().strip('"'))
        if values.get("UninstallString")
        else folder / "unins000.exe"
    )
    if not str(folder) or not uninstaller.name:
        return None
    return InnoInstall(folder=folder, version=values.get("DisplayVersion") or "", uninstaller=uninstaller)


def _known_folder(name: str) -> Path:
    """Desktop / Programs (Start menu) of this account, as the shell reports them."""
    ps = f"[Environment]::GetFolderPath('{name}')"
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )  # fmt: skip
    return Path(out.stdout.strip())


def shortcut_paths() -> dict[str, Path]:
    title = identity.get().inno_title
    return {
        "start_menu": _known_folder("Programs") / f"{title}.lnk",
        "desktop": _known_folder("Desktop") / f"{title}.lnk",
    }


def create_shortcut(lnk: Path, target: Path) -> None:
    def q(p) -> str:
        return "'" + str(p).replace("'", "''") + "'"

    script = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({q(lnk)}); $s.TargetPath = {q(target)}; "
        f"$s.WorkingDirectory = {q(target.parent)}; $s.IconLocation = {q(target)}; $s.Save()"
    )
    lnk.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script], check=True, capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )  # fmt: skip


def _running(exe: Path) -> bool:
    ps = (
        "Get-Process | Where-Object { $_.Path -and $_.Path -ieq '" + str(exe).replace("'", "''") + "' } | "
        "Measure-Object | Select-Object -ExpandProperty Count"
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )  # fmt: skip
    return out.stdout.strip() not in ("", "0")


def steam_root() -> Path | None:
    override = identity.get().steam_root
    if override:
        return Path(override)
    from roundtable_souls.platform import paths as common

    return common.steam_root()


def steam_running() -> bool:
    from roundtable_souls.platform import paths as common

    if identity.get().steam_root:  # a test build's fake Steam is never running
        return False
    try:
        return bool(common.steam_running())
    except Exception:
        return True  # unsure: treat as running, so the file is not changed under Steam


def retarget_steam(old_exes: list[Path], new_exe: Path, running: bool | None = None) -> list[steam_shortcuts.Shortcut]:
    """Point Steam shortcuts that start one of old_exes at new_exe; a backup of each changed file goes to the
    launcher's backups folder."""
    olds = [str(p) for p in old_exes]
    return steam_shortcuts.retarget(
        steam_root(),
        lambda s: any(steam_shortcuts._same_path(s.exe, o) for o in olds),
        new_exe,
        folders.data_root() / "backups" / "steam-shortcuts",
        steam_running() if running is None else running,
    )


def migrate_from_inno(
    find=find_inno_install,
    run=subprocess.run,
    running=_running,
    shortcuts=shortcut_paths,
    make_shortcut=create_shortcut,
    steam=retarget_steam,
    target: Path | None = None,
    wait=time.sleep,
    now=time.time,
) -> dict | None:
    """Carry out (or continue) the move from the Inno install; returns the record for a notice, or None when there
    is nothing to do. Only an installed Velopack copy does this (never a portable copy or a build run from source)."""
    if not _windows() or not is_installed() or not identity_matches():
        return None
    record = dict(load_settings().get("inno_migration") or {})
    if record.get("done"):
        return None
    target = target or launch_target()
    if target.name != identity.get().stub_name:  # shortcuts only ever go to this install's own stub
        return None
    inno = find()
    if inno is None and not record:
        return None
    if inno is not None:
        if running(inno.exe):
            record.update(status="waiting", reason="The old Roundtable Souls is still open; close it.")
            save_settings(inno_migration=record)
            return record
        links = shortcuts()
        record.update(
            old_folder=str(inno.folder), old_exe=str(inno.exe), old_version=inno.version,
            had_desktop=links["desktop"].is_file(), started=now(),
        )  # fmt: skip
        result = run([str(inno.uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=False)
        for _ in range(120):  # the uninstaller hands over to a copy of itself in %TEMP% and returns at once
            if find() is None and not inno.exe.exists():
                break
            wait(0.5)
        if find() is not None:
            record.update(status="failed", reason=f"The old uninstaller did not finish (exit {result.returncode}).")
            save_settings(inno_migration=record)
            return record
        record["uninstalled"] = True
    links = shortcuts()
    if not record.get("shortcuts_done"):
        make_shortcut(links["start_menu"], target)
        if record.get("had_desktop"):
            make_shortcut(links["desktop"], target)
        record["shortcuts_done"] = True
    if not record.get("steam_done"):
        try:
            changed = steam([Path(record["old_exe"])], target)
            record.update(steam_done=True, steam_changed=[s.name for s in changed])
        except RuntimeError as e:
            record.update(steam_pending=str(e))
        except (KeyError, OSError) as e:
            record.update(steam_done=True, steam_error=str(e))
    record["status"] = "done" if record.get("steam_done") else "steam_pending"
    record["done"] = bool(record.get("steam_done"))
    save_settings(inno_migration=record)
    return record


def finish_steam_step(target: Path | None = None) -> list[steam_shortcuts.Shortcut]:
    """The pending Steam step (Settings, once Steam is closed)."""
    record = dict(load_settings().get("inno_migration") or {})
    changed = retarget_steam([Path(record["old_exe"])], target or launch_target()) if record.get("old_exe") else []
    if record:
        record.update(steam_done=True, done=True, status="done", steam_changed=[s.name for s in changed])
        record.pop("steam_pending", None)
        save_settings(inno_migration=record)
    return changed


def point_play_shortcuts_here(
    target: Path | None = None, running: bool | None = None
) -> list[steam_shortcuts.Shortcut]:
    """Settings > Steam shortcut: every Steam shortcut that runs a Roundtable Souls program with --play, wherever
    that program was, now starts this copy."""
    target = target or launch_target()
    name = identity.get().exe_name
    names = (f"{name}.exe", name, identity.get().stub_name, target.name)
    return steam_shortcuts.retarget(
        steam_root(),
        lambda s: "--play" in s.options and steam_shortcuts.is_launcher(s.exe, names),
        target,
        folders.data_root() / "backups" / "steam-shortcuts",
        steam_running() if running is None else running,
    )


def play_shortcuts_elsewhere(target: Path | None = None) -> list[steam_shortcuts.Shortcut]:
    """Steam shortcuts with --play that start a Roundtable Souls program other than this copy."""
    target = target or launch_target()
    name = identity.get().exe_name
    names = (f"{name}.exe", name, identity.get().stub_name, target.name)
    return [
        s for s in steam_shortcuts.launcher_shortcuts(steam_root(), names)
        if "--play" in s.options and not steam_shortcuts._same_path(s.exe, str(target))
    ]  # fmt: skip
