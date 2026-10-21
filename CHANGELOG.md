# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.1.0](https://github.com/Carlomos7/roundtable-souls/compare/v4.0.3...v4.1.0) (2026-10-21)


### Added

* **storage:** mirror backup notes, library index and profile history ([c864b4f](https://github.com/Carlomos7/roundtable-souls/commit/c864b4f6561cc5813e1bf682881c2e49a8c58ec3))
* **storage:** rebuild runs in the database ([a47c135](https://github.com/Carlomos7/roundtable-souls/commit/a47c135df26b97cc41b9b0c7809522fbf7576724))


### Changed

* read game file names from the game catalog ([0f053c8](https://github.com/Carlomos7/roundtable-souls/commit/0f053c826d88a583d08a3037c8f6385b5ad6c30a))

## [4.0.3] - 2026-10-21

### Fixed

- **Overhauls:** "Set up as an overhaul" and the Settings switch were hidden when no overhaul config shipped. They now show whenever the switch is on.

## [4.0.2] - 2026-10-21

### Changed

- The first release after the repository history was cleaned. It is the same launcher as 4.0.1.

## [4.0.1] - 2026-10-20

### Changed

- **Mods:** Remove no longer asks when Undo brings everything back. The folder goes to the Recycle Bin and a toast offers Undo. Remove still asks when another entry or profile uses the folder.
- **Mods:** the pencil beside the profile name is always visible and works with the keyboard ("Rename profile").
- **Mod Configs:** the overhaul setup buttons now live in one More menu on the open mod (and its right-click menu). "Edit as text" shows only for files that have a form.
- **Wording:** a pass over the helper text so each fact appears once, tooltips only add what is not visible, and errors say what happened and what to do.
- **Launch:** the reasons it is blocked now follow the window language.
- **Overhauls:** no overhaul config ships with the launcher. Make one with "Set up as an overhaul" on the Mods page; the launcher then builds what it installs itself.
- **Overhauls:** new overhaul configs keep their manifest in `overhaul.json`.

### Fixed

- **Mods:** the notices at the top of the page (adopt into the library, Seamless in the game folder, online with parameters) show their text again.

### Removed

- The launcher no longer runs other installers or rebuild tools from a mod's download. A setup made by another installer is still listed and started, but you update it with that installer.
- **Settings:** the "Build ... in the launcher (preview)" switch is gone; the launcher builds only what it installed.

## [4.0.0] - 2026-10-20

A new interface. Roundtable Souls now opens in a single redesigned window with a top bar and a navigation rail (Mods, Mod Configs, Saves, Activity, Settings). Saves and mods can be dragged and dropped, profiles can be renamed, duplicated, exported and imported, and the old window is gone.

### Highlights

- **New window:** one window for everything, with a Launch pill in the top bar and a status line that says why Launch is blocked and how to fix it.
- **Drag and drop:** move characters, save copies and backups between saves, and drop mods onto the Mods page to install them.
- **Mod Configs:** mods' settings files open as forms, with a full code editor for the rest.
- **Saves:** a new page with live saves, a Library of save copies and Backups, all with Undo.
- **Profiles:** rename, duplicate, export and import them, and adopt an existing setup into the library.
- **Safer launching:** Launch checks for failed backups, out-of-date merged mods and risky online play before the game starts.

### Added

- **Launch:** the Launch pill picks Profile, Offline or Vanilla (remembered per game). It asks before starting when a backup failed, merged mods are out of date, or the profile would go online with changed game data, and warns about a missing mod folder.
- **Profiles:** rename and duplicate a profile, and rename a mod's folder, each with Undo in Activity. Export / Import shares a profile as a small list or a full zip, previews what an import changes, and lets you choose when mod names clash.
- **Mods:** the Install mod dialog shows what it will do first, Adopt into the library moves an existing setup into the launcher's folder, and a bar offers to move Seamless Co-op out of the game folder.
- **Mods:** warnings when a profile goes online with a mod's parameters, and clear reasons when a drag is refused.
- **Mod Configs:** `.ini`, `.cfg` and `.toml` files open as forms with the file's comments as help. Saving changes only the values you edit. Seamless Co-op has its own panel with Share with a friend.
- **Editor:** one code editor everywhere (profile text, mod configs, README, logs) with syntax colours, find and replace, line numbers and the first error marked on its line.
- **Saves:** drag characters, save copies and backups to copy, restore, save or back up. Every drop backs up first and offers Undo. Save a copy and Import work while the game runs.
- **Activity:** a page listing every job by day, with its log and Undo, and plain-words reasons when a job fails.
- **Settings:** Locations, Launch, Backups, Appearance, Updates, Logs and About, with a backup count per save, themes (Dark, Tarnished, Light, System) and a Check for updates that answers at once.
- **Overhauls:** the launcher can install and remove an overhaul in a profile itself, showing every change first, and Mod Configs can set up any mod as an overhaul.
- **Accessibility:** icon buttons have names for screen readers, tooltips show on Tab, and no text is smaller than 12 px.

### Changed

- **Wording:** "Play" is now "Launch", "setup" is now "profile", Tools is Settings, Co-op is Mod Configs, Maintenance is Saves, and the second mod list is "DLL mods".
- **Look:** Dark is a near-neutral charcoal with gold as its only colour, and Light keeps its Carian blue.
- **Import:** a mod you already have is reused instead of copied again, and Undo import removes everything the import created.
- **Combine:** merging is faster (the large effects archive takes about 5 seconds instead of nearly 2 minutes), and warnings in the report are plainer.
- **Files:** the launcher's own files beside a profile now live in one hidden `.roundtable` folder; older files are still read.
- The download is smaller now that the old window is gone.

### Fixed

- **Launch Offline** always turns online play off. Before, a profile set to go online went online during an offline launch.
- **Install mod:** a mod that ships game files and DLLs together now loads its DLLs, and unusable folder names are refused before anything is copied.
- A rebuild interrupted as the new build replaces the old one no longer leaves the mod folder missing.
- The game counts as running while it is still starting, so saves and mods are not touched while it comes up.

### Removed

- The old window and its `--widgets` switch.

## [3.22.0] - 2026-10-15

### Added

- **Overhauls (preview):** a switch in Settings lets the launcher install an overhaul into a profile itself, with a preview of every change and one Undo step. Remove overhaul puts back what the install changed.
- **Mods:** a first look at the redesigned Mods page, in its own window (Open new Mods window): load order, drag to reorder, Mod options, Profile settings, Versions and the Parameters card.
- **Mod Configs:** a first look at the redesigned page, opened from the Co-op page, with forms for settings files and a Seamless Co-op panel.
- **Activity:** a first look at the redesigned page, opened from the Activity page.
- **Co-op:** when Seamless Co-op sits in the game folder, the page offers to move it into your profile or clean up the old copy.
- **Play:** with no profile for a game yet, a Get started card creates one in one click.
- **Combine:** merged builds match inner files the way the game finds them, warn about inner files a mod's copy leaves out, and check parameters and talk scripts the way the game reads them.
- **Play:** going online with a mod's parameters is warned about before the game starts.

### Changed

- **Combine:** merged archives are compressed faster, with the large effects archive going from nearly 2 minutes to about 5 seconds.
- **Mods:** New profile puts each game's profiles in its own `<game>-mods` folder; a copy now sits beside the original so its mods keep working.
- **Play session:** Elden Ring's "Repair saves after quitting" is now off by default, since only save editors need it. Nightreign's repair stays on.

### Fixed

- **Mods:** removing an entry that only points at a folder of mods no longer fails when another mod must load after it.
- **Mods:** deleting a profile now waits until the running job finishes.
- **Linux and Steam Deck:** merged files can be written without the game's compression library.

## [3.20.0] - 2026-10-09

### Added

- **Overhauls (for mod authors):** what an overhaul needs is a `requires` list, and script fragments are added with `do = "hook"`. The launcher says which key moved where for older configs.

### Changed

- **Appearance:** new colours, the first step of the new look. Dark is a near-neutral charcoal with gold as its only colour, and Light keeps its Carian blue with softer lines.
- **Mods:** the conflict list names what each file is in plain words.
- **Overhauls (preview):** the build no longer refuses to start without Seamless Co-op. The character script is checked before use, and one the game could not load is refused with the line named.

## [3.19.0] - 2026-10-08

### Added

- **Mods:** a profile edited outside the launcher is never overwritten. Changes that would repeat a package id, loop the load order or switch on two DLLs with the same name are refused.

### Fixed

- **Mods:** two launcher windows can no longer write the same profile at the same moment.
- **Profile history:** two changes made in the same millisecond are listed in the order they were made.
- **Mods:** undoing a removal puts the restored mod back under the mod that must stay last.

## [3.18.0] - 2026-10-08

### Added

- **Mods:** installing, updating and removing a mod are each one step that cannot be left half-done. If the window or the PC closes in the middle, the next start finishes or undoes it.
- **Mods:** an update keeps the previous version. Activity offers Roll back, and a fresh install can be undone. Files you changed yourself are kept and the new copy is put beside them as `.new`.

### Changed

- **Mods:** when "rebuild after installing" is ticked, a failed rebuild undoes the whole install.
- **Combine:** archives the game lists in ID order keep that order when a mod adds files.
- **Overhauls (preview):** the launcher now merges the grace menu itself and runs nothing from the overhaul's download. Clashes go to a merge report.

### Fixed

- **Mods:** removing a mod never deletes a folder that holds Seamless Co-op's DLL.

## [3.17.0] - 2026-10-06

### Changed

- **Combine:** animation events several mods change are merged animation by animation, so a mod that changes some animations and one that adds others now both apply.

## [3.16.0] - 2026-10-05

This version also carries the changes from 3.15.0, which was never published.

### Added

- **Load order:** the launcher works the order out exactly as me3 does, so the file a mod wins or loses is shown correctly. A note appears when the installed me3 is older than 0.11.0.
- **Combine:** talk scripts such as grace menus that several mods change are merged, keeping each mod's options, states and menus.
- **Combine:** the record lists, file by file, the inner files a mod's copy leaves out.
- **Backups:** a backup with damaged notes is never removed by the automatic clean-up and shows as "Protected: metadata unreadable".
- **Saves:** the save library keeps a copy whose removal stopped halfway and lets you finish or undo it.
- **Activity:** the launcher keeps its activity log and file-hash cache in a small database; entries are kept for 90 days. If the database cannot be used, the launcher works as before without it.

### Changed

- **Play:** with "Back up saves before Play" on, a failed backup no longer starts the game without asking. The window offers Retry, Launch without backup or Cancel.
- **Combine:** a rebuild is checked before it replaces the previous result, and one cut short is undone next time.
- **Combine:** the combined-parameters package is added to the load-after list of the mod that must stay last.

### Fixed

- **Saves:** two launchers at once no longer race when a backup or library change is made.
- **Saves:** a library file that cannot be read is reported and left as it is instead of being replaced by an empty one.

## [3.14.0] - 2026-10-01

### Added

- **Updates:** installing and updating use a new installer. The program is a folder, so it starts faster. Windows installs per account with no administrator prompt; a portable zip and a Linux AppImage are also published.
- **Updates:** updates are signed and checked before they install, and undo themselves if the new version does not start within 90 seconds.
- **Updates:** Settings has an update channel, Stable or Beta, and the update notice shows the start of the release notes with a Notes button.
- **Updates:** `RoundtableSouls --update` updates without the window, for a terminal or a Steam shortcut in Gaming Mode.
- **Steam shortcut:** Point Steam shortcuts here makes every Steam shortcut that starts a Roundtable Souls program elsewhere start this copy (Steam must be closed; a backup is kept).
- **Mods:** a mod's rebuild tool that has not been allowed yet is offered on the Mods page, so a rebuild does not stop to ask.

### Changed

- **Play:** the game no longer starts with out-of-date merged mods without asking; Play anyway starts it this once. "Update merged mods before Play" is now "Rebuild merged mods automatically before Play".
- **Mods:** Remove and Restore have one button, and files of a removed mod still inside the merged mods are named.
- **Updates:** a check that could not reach GitHub now says so and why instead of reporting "up to date".
- Starting Roundtable Souls again brings the open window forward, and a Play from a Steam shortcut runs in that window.

### Fixed

- Settings written at the same moment as an update check or a Steam shortcut Play are no longer lost.
- Archives the launcher changes in place record the file's new size.

## [3.13.2] - 2026-10-01

### Fixed

- Combined parameters (`regulation.bin`) written by the launcher crashed the game at start. They are now written in the format regulation editors use, and each layout was checked in game.

## [3.13.1] - 2026-09-30

### Added

- **Look:** a new light theme, frost and Carian blue with snow-white cards; dark keeps its gold. Status pills now carry a mark.

### Changed

- **Mods:** a DLL's settings files are attached rather than tied (Attach a file and Detach).
- **Mods:** Install mod asks archive or folder first; cancelling a picker installs nothing.

### Fixed

- Compressed files the launcher writes (merged files and the overhaul preview build) now use the layout tested for Elden Ring.

## [3.13.0] - 2026-09-30

### Added

- **Mods:** files two mods both ship are merged, not just replaced. Combine or Rebuild reads the game's own copy, works out what each mod changed, added or removed, and applies all of it.
- **Overhauls (preview):** the build now merges animations, effects, menu text and parameters with the launcher's own merger.

## [3.12.0] - 2026-09-30

### Added

- **Overhauls (preview, off by default):** the launcher can build an overhaul itself from the download kept in its setup folder, instead of running its installer.

## [3.11.0] - 2026-09-29

### Added

- **Play:** when merged mods are out of date, Play rebuilds them first and then starts the game, with Cancel Play. A failed rebuild keeps the previous result.
- **Settings:** "Update merged mods before Play" (on by default).

### Changed

- **Play:** after an automatic rebuild, only a rebuild tool's newest 3 backups are kept; older ones go to the Recycle Bin.

## [3.10.0] - 2026-09-29

### Added

- **Load order:** a Stays last section says when a mod loads after the package that must stay last, with Fix order and Keep it after.
- **Profiles:** the parameter overlay choice is kept next to the profile, so a copied profile folder works the same on another PC.

### Changed

- **Mods:** the package that must stay last keeps its place however mods are added, removed or renamed.
- **Install:** with such a package, the dialog says a new mod is placed before it so its changes are included.

### Fixed

- **Load order** names missing setup files and how to restore them instead of giving a misleading message.

## [3.9.0] - 2026-09-29

### Added

- **Profiles:** a copy is kept before every change the launcher makes. Switches and options show Undo right after the change, and Edit profile > Versions restores any copy.
- **Mods:** Undo rebuild on Activity puts back what a rebuild replaced, instantly and without extra space. Load order shows the space a rebuild tool's backups take and can move older ones to the Recycle Bin.

### Changed

- **Mods:** removing a mod inside combined parameters offers Remove and rebuild. The folder goes to the Recycle Bin instead of being deleted.

### Fixed

- Removing a mod took the comment lines of the entry after it and left its own behind. It now takes exactly the entry and its own comments, and a removed entry can be put back byte for byte.

## [3.8.0] - 2026-09-29

### Added

- **Activity:** a new page listing every job (Play, repairs, installs, rebuilds) by day, with how it went and its log.
- **Mods:** parameters show as a green or red pill next to the profile name; clicking it opens Load order.

### Changed

- **Mods:** Load order replaces Conflicts and explains what the profile loads, with the parameters' status and every file two packages ship.
- **Logs:** a job's end line reads "failed in 3s, 1 error" instead of counting zeros.

## [3.7.0] - 2026-09-29

### Changed

- **Logs:** every job keeps its own log, with how it ended, instead of one file overwritten by the next job. me3's output is kept with each Play.
- **Logs:** lines carry real levels and sources with milliseconds, and a folder the launcher cannot write no longer stops logging.

## [3.6.0] - 2026-09-29

### Added

- **Mods:** Combine applies each parameter pack's changes to the game's own file, row by row in load order, so all of them apply instead of only the last.
- **Mods:** merge health for Elden Ring profiles says whether the combined result is up to date and why not.
- **Mods:** rebuild tools are described in one documented format, `rebuild.json`, so any overhaul can ship one.
- **Mods:** Parameter overlay in a package's Options marks it as the package that must stay last.

### Changed

- **Mods:** a rebuild saves the profile first and keeps your comments.

### Fixed

- **Mods:** a folder holding only a leftover `regulation.bin` no longer hides the real mod folder when installing.

## [3.5.0] - 2026-09-29

### Added

- **Mods:** drag archives, DLLs or mod folders onto the page to install them. The page shows what a drop would do and names files it would skip.
- **Mods:** installing asks for the folder name and id, finds the mod below wrapper folders, asks which version when an archive has several, and ticks what to install.
- **Mods:** each DLL mod has a settings button that opens its own settings file in the editor.
- **Mods:** each entry is checked the way me3 reads it (missing files, repeated ids, load orders that loop).
- **Saves:** a save library keeps named copies of whole saves. Swap in replaces a live save and files the replaced one first.
- **Saves:** Copy to... replaces a save with a whole file, and Copy a character... copies one character into a slot in the same or another save.
- **Backups:** named for what came next ("Before fixing checksums", "Before playing"). The newest 20 of each save and everything from the last 7 days are kept; Keep holds one for good.
- Closing the window or switching games with unsaved changes asks Save, Discard or Cancel.

### Changed

- **Files:** everything Roundtable Souls keeps now lives in its own data folder (`%LOCALAPPDATA%\RoundtableSouls`, or beside a portable copy).
- **Saves:** the save file Play uses follows the profile, including a renamed save file.
- **Mods:** a profile changed outside the launcher is noticed when you come back to the window.
- **Buttons:** one size and shape everywhere, and a save bar shared by the Co-op page, the editors and Review & fix.

### Fixed

- Expandable cards could keep empty space under their content or cut off their last row.
- After a job, the message and the Mods page refresh looked at how the job ended instead of what it was.

## [3.4.0] - 2026-09-28

### Added

- **Games:** a game button at the top picks the game every page works on (Elden Ring or Nightreign). Ctrl+Tab steps through them.
- **Nightreign:** Play through me3, its profiles and mods, its Seamless Co-op settings, and saves with a structure check and backups.
- `--game <name>` picks the game for `--play` and `--check`. Settings > Steam shortcut shows the launch options per game.

### Changed

- me3 profiles are listed under the game they name; picking one made for another game says so instead of launching it.

### Fixed

- Deleting a profile on the Nightreign page cleared Elden Ring's remembered profile instead of Nightreign's.
- A remembered profile written with different letter case or slashes was not found again.

## [3.3.0] - 2026-09-27

### Changed

- **Saves:** items the installed game defines always count as game items, so the Tarnished Edition pack's gear is recognised exactly.
- **Saves:** mod items are named again, from the mod's own language file or text files.
- `--check` also writes its report to a log and no longer shows the co-op password.

## [3.2.0] - 2026-09-27

### Added

- **Installer:** releases include `RoundtableSouls-Setup.exe`, a per-user install with no administrator prompt, a Start menu entry and an uninstaller.
- **Updates:** Update now follows the install type: an installed copy downloads the setup, checks it and runs it silently; a portable copy swaps its exe.
- **Linux and Steam Deck:** a Linux build finds Steam (including Flatpak), the game and its saves.
- `--play` runs the Play session without the window, for a Steam shortcut or Gaming Mode. Settings > Steam shortcut shows what to paste.
- **Saves:** Tarnished Edition and Shadow of the Erdtree are detected automatically, and Fix loading is a table of checks, each with its own repair.
- **Keyboard:** Ctrl+1 to 5 open the pages, Esc leaves Review & fix, and focused buttons show a ring. Nothing has focus when the window opens.

### Changed

- **Licensing:** the project is now GPL-3.0-or-later.
- **Names:** Tools is now Settings; To .sl2 and To .co2 are Copy to standard save and Copy to co-op save.
- **Layout:** pages never scroll sideways; buttons and chips wrap.

### Fixed

- Copies made with Copy to co-op save appear in the Backups list.
- The weather check no longer runs; it flagged healthy characters.

## [3.1.4] - 2026-09-27

### Fixed

- Update now: the relaunch after an update no longer crashes on its first start.

## [3.1.3] - 2026-09-27

### Changed

- **Tools:** the update button is labelled Check for updates.

## [3.1.2] - 2026-09-27

### Fixed

- Check for updates now asks GitHub right away and says Up to date when there is nothing newer. The automatic check waits an hour between calls instead of a day.

## [3.1.1] - 2026-09-27

### Fixed

- **Editors:** Enter and Esc in the find bar no longer reach the document, and the bar keeps its colours after a theme switch.

## [3.1.0] - 2026-09-27

### Added

- **Updates:** Update now downloads the release, checks it against published checksums, swaps the exe and restarts, still one click and never silent.
- **Saves:** To .co2 on a standard save makes the Seamless Co-op copy, backing up any existing one first.
- **Editors:** Ctrl+F find and Ctrl+H replace with match case, regular expressions and Replace all.

## [3.0.1] - 2026-09-27

### Added

- **Tools:** Check for launcher updates looks at this project's GitHub releases once a day and shows a notice with a Download link. Nothing is installed automatically.

## [3.0.0] - 2026-09-26

### Changed

- Renamed to Roundtable Souls and rebuilt. Your settings folder is carried over, and what the launcher does is unchanged.

## [2.0 to 2.54] - Before 3.0.0

The 2.x versions were published before this changelog kept dates, so they are grouped here.

### Added

- **Mods:** install a mod from a `.zip`, `.7z`, `.rar` or folder with package and DLL detection and per-mod options. A package conflict scan, on and off switches for every entry, and profile settings as menus.
- **Window:** a Windows 11 look with pages (Play, Co-op, Saves, Tools), your character on the Play page, light and dark themes, and a Roundtable icon.
- **Co-op:** every Seamless Co-op setting editable in groups, a Share settings box, and difficulty presets by party size.
- **Saves:** Review & fix, a page per save with characters and every fix as a tick box, with one Apply and Undo. Restore vanilla and Fix quest flags open a checklist.
- **Saves:** findings for duplicate inventory, unknown item IDs, quest soft-locks and stale checksums, with a backups list and Restore.
- **Tarnished Edition:** its gear counts as official content when the pack flag is on the save.
- **Play:** offline play when Steam's login is down, with options to skip Steam or the overhaul, and a warning when dead game processes are left behind.
- **Locations:** Tools > Locations for a custom me3, game exe and profile folder, and folder buttons that say why when a folder is unknown.

### Changed

- Confirmations read top to bottom: what will happen, the safety line, then the button named for the action. With the game running, Apply, Restore and Undo stay off with the reason in their tooltip.

### Fixed

- Characters last saved on an early game patch now read; one that still cannot be read is named and left alone.
- The window opened on an empty Review & fix page instead of Play.

## [1.0 to 1.7] - Before 3.0.0

The 1.x versions were published before this changelog kept dates, so they are grouped here.

### Added

- The first window version, with a Saves panel, a dark theme, difficulty scaling presets, export and import of settings as a `.json` file, and Share settings.
- Finds an overhaul install inside the game folder by itself.

### Changed

- Safer file writes (`.bak` kept), error reporting, and a prompt before closing while a session runs.

[4.0.3]: https://github.com/Carlomos7/roundtable-souls/compare/v4.0.2...v4.0.3
[4.0.2]: https://github.com/Carlomos7/roundtable-souls/releases/tag/v4.0.2
