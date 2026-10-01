# 0004 Velopack installs and applies updates; the launcher decides what to trust and undoes failed starts

**Status:** in use from the release after 3.13.2. Supersedes the Inno Setup installer and the launcher's own exe swap.

## Decision

Releases are packed with Velopack (`vpk` 1.2.161, the same version as the `velopack` Python package in `uv.lock`):
a per-user setup and a portable zip on Windows, an AppImage on Linux, full and delta packages, and a feed per system.
The program is a PyInstaller folder (Velopack does not take a one-file program).

The launcher keeps what Velopack does not provide:

- **Trust.** Only signed feeds are used, and every package is checked against them before Velopack sees it
  ([0003](0003-signed-releases.md)).
- **Startup rollback.**
  - Before an update, the current version is kept: Velopack's full package on Windows (downloaded from that version's
    release and checked, for a portable copy that has none), the AppImage on Linux.
  - A watchdog script outside the program folder (`data/update-watchdog.ps1` / `.sh`) gives the new version 90
    seconds to report ready: its window is up, or a Play from a Steam shortcut is under way.
  - If it does not, the watchdog stops it and deletes its packages, puts the kept version back and starts it. That
    version records the failed one, which is never offered or installed again.
- **No automatic apply.** `App().set_auto_apply_on_startup(False)`: Velopack otherwise applies any newer package it
  finds at the next start, which would re-install a version the watchdog just undid.
- **Data outside the program folder.**
  - Installed copies and the AppImage: `%LOCALAPPDATA%\RoundtableSouls` / `~/.local/share/RoundtableSouls`.
  - Portable copies: `RoundtableSouls-data` beside `Update.exe`.
  - `ROUNDTABLE_SOULS_DATA` overrides both.
  - The app ID, `Carlomos7.RoundtableSouls`, is not the data folder's name: Velopack installs to
    `%LOCALAPPDATA%\<app ID>` and deletes that whole folder on uninstall. `settings.data_dir` refuses to run if the
    two ever coincide.
- **Moving from Inno Setup** (`migration.py`), at the first start of an installed copy:
  - remove the old install with its own uninstaller (it never touched the data folder);
  - recreate the Start menu and desktop shortcuts;
  - point Steam shortcuts that started the old program at the new stub, only while Steam is closed and with a
    backup of `shortcuts.vdf`.
  - Versions up to 3.13.2 reach the new setup through their own Update now: it is published under their asset name,
    `RoundtableSouls-Setup.exe`, listed in `SHA256SUMS.txt`, and Velopack's setup ignores the Inno flags they pass.

## Why

Velopack replaces three pieces we maintained ourselves:
- the Inno script with its downgrade guard and relaunch code;
- the one-file exe swap with its parked copies;
- the setup-log reporting.

In their place it gives a maintained, MIT-licensed installer and updater for Windows and Linux, with delta packages.
Its own trust model (hashes in an unsigned feed) and its lack of rollback were measured in an evaluation on packaged
builds:
- an altered package plus a rewritten feed was installed;
- a release that failed to start stayed installed, and Velopack re-applied it at the next start.

Both gaps are closed by the launcher code above, which the same evaluation and the end-to-end runs exercised.

## Reopen if

Velopack gains signed feeds or a health-check rollback of its own, or its packaging stops supporting PyInstaller
folders or AppImages.
