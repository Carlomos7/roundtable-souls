# Changelog

All notable changes to Roundtable Souls. The version is shown in the window title.

## [Unreleased]

- Updates: a check that could not reach GitHub (offline, GitHub's hourly limit, an error) now says so and why, on Settings and after Check for updates, instead of reporting "up to date". Settings shows when the last check succeeded. After failed checks the automatic one waits longer each time (up to a day); Check for updates always asks at once. Unchanged answers are asked for with the previous answer's tag, which GitHub does not count against its limit.
- Updates: releases are signed. Update now checks the release's checksum file against the project's key built into the launcher, and that the signature names the version being installed, before it trusts any checksum; an unsigned release (every earlier one) is offered as a download from the releases page instead. A release that is not newer than the running copy is refused.
- Updates: the download is written to the launcher's data folder as it arrives instead of being held in memory, continues where it stopped after an interruption, and is removed once the update is done. Download folders earlier versions left in the temp folder are cleared.
- Updates: an installed copy's update writes a setup log (in the logs folder), and the setup reopens the launcher whether or not it installed. When the update did not install, the launcher says so at the next start with the reason from the log, Try again and Open log. A portable copy waits for the new version's window to open; if the new version closes before that, the previous one is put back and says why.
- Updates: the update notice shows the start of the release notes and a Notes button. Settings has an update channel: Stable (as before) or Beta, which also offers pre-releases. The project can publish a notice asking versions with a known problem to update (it only warns).
- One window: starting Roundtable Souls again brings the open window forward. Play from a Steam shortcut while the window is open runs Play in that window; a second shortcut Play while one runs is refused. Update now waits while a shortcut Play runs, and the setup does not install while the launcher or a shortcut Play is open.
- Settings are written under a lock, so a change made at the same moment as the update check (or a Steam shortcut Play) writes is no longer lost.
- Installer: a silent setup refuses to replace a newer installed version with an older one (the setup wizard asks first). Program files left in the install folder by a portable-style update are removed.
- Fixed: when the launcher changes a file inside an archive in place (the menu text of the preview Nightreign Revive build), the archive now records that file's new size instead of the size it had before. Archives the launcher does not change are written exactly as before. Not yet checked in game.

## [3.13.2] - 2026-10-01

- Fixed: combined parameters (regulation.bin) written by the launcher crashed the game at start. The file is now compressed with a 64 KB window, the frame regulation editors write; checked in game on Windows with Elden Ring 1.17.1, together with each layout the launcher can write for merged archives and text.
- Versions 3.6.0 to 3.13.1 use the same compression settings for combined parameters as the writer that crashed. The crash was reproduced with that writer on Elden Ring 1.17.1; the older versions themselves were inspected, not run in game. Combining parameters only happens when two enabled mods both ship a regulation.bin, or in the preview Nightreign Revive build.

## [3.13.1] - 2026-09-30

- Fixed: Oodle-compressed files the launcher writes (merged files, and the preview build of Nightreign Revive) now use the tested Elden Ring layout: compression level 6, with the same level in the file header. Files over 16 MB were written at a faster level with that level in the header, a layout no game file uses. Merging the largest archives now takes longer (the 88 MB effects archive about two and a half minutes instead of seconds).
- Mods: a DLL's settings files are attached rather than tied: Attach a file and Detach.
- Mods: Rebuild is offered whenever a build exists, so turning on Build Nightreign Revive in the launcher can be put into effect at once.
- Look: a new light theme, frost and Carian blue with snow-white cards; dark keeps its gold. Status colours, pills (now with a mark: ✓, ✕, ⚠), logs, dialogs, menus and the sidebar follow the theme; a page's main action is solid, a destructive one is red; the sidebar can be reached with Tab.
- Mods: Install mod asks archive or folder first; cancelling a picker installs nothing.

## [3.13.0] - 2026-09-30

- Mods: files two mods both ship are merged, not just replaced. For archives (menu layouts, animations, effects and the like) and text, a Combine or Rebuild reads the game's own copy from its archives, works out what each mod changed, added or removed inside, and puts all of it into one file in the combined package, so both mods apply; where two mods change the same part, the later one's is used and the log says so. Load order shows those copies as combined, and a changed copy or a game update makes the merge out of date (Play updates it first). Undo rebuild covers the merged files too.
- Mods: building Nightreign Revive in the launcher (the preview on Settings) now merges its animations, effects, menu text and parameters with the launcher's own merger instead of the mod's tool; only the grace menu still uses the mod's tool. On a real profile the content matched the mod's installer's, file for file.
- The game's own files are read from its archives when a merge needs them; the decrypted archive indexes are kept in the launcher's data folder after the first time.

## [3.12.0] - 2026-09-30

- Mods: the launcher can build Nightreign Revive (LITE 0.1.33) itself from the download kept in its setup folder, instead of running its installer (Build Nightreign Revive in the launcher, on Settings; a preview, off by default). It follows a recipe (data, not code) and uses the mod's own merge tool for each merged file; on a real profile its output matched the installer's file for file. The profile is never rewritten, RevivePrototype.ini keeps the player's values (a newer version only adds its new settings), inputs are only read, a failed build leaves the old one in place, and the build it replaced is kept for Undo rebuild instead of a full backup on every run. Other versions still use the mod's installer.
- Docs: the recipe format, in Rebuild tools.

## [3.11.0] - 2026-09-29

- Play: when merged mods are out of date (a mod was added, removed, turned on or off, reordered or updated, or the game updated), Play rebuilds them first and then starts the game, with Cancel Play. A failed rebuild keeps the previous result and offers Play anyway or View details; it is not retried with the same mods in that session. Offline Play and Play from a Steam shortcut do the same (the shortcut only runs a rebuild tool that was already allowed, and starts anyway on failure).
- Play: after an automatic rebuild only the newest 3 of a rebuild tool's backups are kept (about 140 MB each for some tools); older ones go to the Recycle Bin.
- Settings: Update merged mods before Play (on by default). Off, Play only warns as before. Load order says an out-of-date merge will update at the next Play.

## [3.10.0] - 2026-09-29

- Mods: the package that must stay last (and its DLL) now stays last however mods are added. Installing, adding existing folders, removing, renaming an id or saving options keeps its own load_after lists naming every other package and DLL (on or off, each optional), so switching a mod on or off never rewrites them; your own entries are never changed. New mods go right before it in the file.
- Install: with such a package, the dialog says a new mod is placed before it so it includes the mod's changes, instead of offering a load order; an advanced option loads a mod after it on purpose.
- Load order: a Stays last section says when a mod loads after it (an edit by hand) and replaces its files, with Fix order and Keep it after (and Put them before to undo that). A change that would make the load order loop is not made, and the reason is shown.
- Profiles: the package set as the parameter overlay, and the mods kept after it on purpose, are kept in roundtable.json next to the profile (relative paths), so a copied profile folder works the same on another PC. A setting from an earlier version moves there on its own; a folder that cannot be written keeps using the launcher's own setting.
- Fixed: when the package that must stay last is there but its setup files are not, Load order names the missing files (installation.json, the setup folder) and how to put them back, instead of saying it loads after the combined parameters, and Rebuild stops before changing anything.

## [3.9.0] - 2026-09-29

- Fixed: removing a mod took the comment lines of the entry after it (a section heading, another mod's notes) and left its own behind. Removing now takes exactly the entry and its own comments, and a removed entry can be put back byte for byte where it was.
- Profiles: a copy is kept before every change the launcher makes (the newest 30, in the data folder, identical copies skipped). Switches, options and profile settings show Undo right after the change; Edit profile > Versions restores any copy, and a restore can itself be undone.
- Mods: removing a mod inside combined parameters offers Remove and rebuild, so the game does not keep a removed mod's changes; removal is a job on Activity. The folder goes to the Recycle Bin instead of being deleted (Windows still asks before deleting for good when the bin cannot take it), and Activity's Restore puts the folder and the entry back.
- Mods: Undo rebuild on Activity puts back what a rebuild replaced: the rebuild tool's output from its own backup and the launcher's combined parameters (the last 3 kept), swapped by renaming so it is instant and needs no space; Redo swaps them again. The profile comes back as it was before the rebuild.
- Mods: Load order shows how much space a rebuild tool's backups take (it never removes them) and can move all but the newest 3 to the Recycle Bin.

## [3.8.0] - 2026-09-29

- Activity: a new page in the sidebar listing every job (Play, repairs, installs, rebuilds...) by day, with how it went and a line on what it did or what went wrong. Open one for its log, with Show details for the fine detail and me3's output kept with each Play; filter by game, kind or failures. A red count on Activity shows jobs that failed since you last looked, and a failure message offers View in Activity. Copy for support and Save logs for support (a zip) mask your user name and Steam IDs. The Log on the Play page links to it.
- Mods: parameters are a green or red pill next to the profile name (Parameters OK, out of date, 1 of N apply, or rebuild failed). Clicking it opens Load order.
- Mods: Load order replaces Conflicts and explains what the profile loads from one scan: the parameters' status with reasons, Combine or Rebuild, and the rows two packs both changed; every file two packages ship with what happens to the earlier copy (replaced, combined, combined but out of date, or not reaching the rebuild), checked against the rebuild's or the combine's checksums; and the entries me3 would refuse. It opens by itself when the pill turns red.
- Logs: a job's end line reads "failed in 3s, 1 error" instead of counting zeros.

## [3.7.0] - 2026-09-29

- Logs: every job (Play, a repair, an install, a rebuild...) keeps its own log in logs\jobs, with how it ended, instead of one last_run.log overwritten by the next job. jobs.jsonl lists them. me3's output is kept with each Play instead of one file overwritten per launch. launcher.log (rotated) holds everything else and every crash with its details, replacing launcher-errors.log, which only grew. Jobs are kept for 14 days or the newest 50; older log files move to logs\old and go after 30 days.
- Logs: lines carry real levels (errors, warnings) and where they came from, with milliseconds. A job's log only has that job's lines; background checks no longer mix in. The Log on the Play page shows the running job and warnings from anywhere, wraps long lines under the message, and has a Logs folder button; its buttons wrap in a narrow window. Changes made in the window itself (profile options, co-op settings) are kept in launcher.log too.
- Logs: a folder the launcher cannot write no longer stops logging; the window still shows every line.

## [3.6.0] - 2026-09-29

- Mods: combine parameter packs. When several packages ship a regulation.bin, Combine on the Mods page (or the box in the install dialog) applies each pack's changes to the game's own file, row by row in load order, so all of them apply: packs changing different parts of a row both apply, overlapping values go to the later pack and are listed, rows a pack lacks are kept, and tables made for another game version are left out and named. The result is a launcher-managed package, combined-parameters, checked against what went in like any rebuild.
- Mods: with a package that must stay last and has its own rebuild tool, the combined package goes right before it, so that tool takes the combined file and every pack applies, not only the last one.
- Mods: merge health for Elden Ring profiles. When the package that must stay last comes with a rebuild tool that folds earlier packages' regulation.bin (and similar shared files) into its own, the Mods page says whether that merge is up to date, why not (a pack added, changed, turned off, reordered or removed, or a game update), and offers Rebuild. The tool is found from its files, never from a mod's name, and the launcher only runs and checks it.
- Mods: installing a pack with a regulation.bin before such a package offers to rebuild afterwards, notes which of the pack's files the rebuild will take, and warns when another pack stops being the source. Without a rebuild tool, placing a pack before the last one says its parameters will not apply; placing it last says the other one's will not.
- Mods: a rebuild saves the profile first, keeps your commented profile when the tool only rewrote it (updating just the tool's own load order lists), and is verified against the tool's list of sources; a run that did not use the right files is reported as failed. Play warns about out-of-date or failed combined parameters but never rebuilds by itself.
- Mods: rebuild tools are described in one documented format, rebuild.json (docs/Rebuild tools.md), so any overhaul can ship one: the command, what it combines and where it lists its sources. Tools that keep an installation.json with a refresh protocol are recognised as before. The launcher shows a tool's command and asks once before it first runs, and again when it changes.
- Mods: Parameter overlay in a package's Options marks it as the package that must stay last when the launcher does not recognise it by its files; its rebuild tool is then looked for with looser rules, or a rebuild.json can be picked for it. Nothing else asks for per-mod labels.
- Mods: a folder holding only a leftover regulation.bin no longer hides the real mod folder below it when installing.
- Mods: changed load order lists keep their place in the entry and their one-per-line layout.

## [3.5.0] - 2026-09-29

- Buttons: one size and shape everywhere; a primary action and the button beside it always match. Only Play stays larger.
- Save rows: the Co-op page, both text editors and Review & fix share one bar: a note on what is unsaved, Discard and the action. On a narrow window the note goes above the buttons.
- Editors: Edit profile and Share with a friend work the same way. The name of what the text came from, the tools, the editor, then Discard and Save (or Apply). Edit profile's Save moved from the top of the Mods page to under the editor.
- Closing the window or switching games with unsaved changes asks Save, Discard or Cancel. Before, closing could only save or stay open.
- Messages at the top of the window keep their buttons on a row under the text, so they fit a narrow window. Every dialog uses the launcher's own buttons.
- Mods: each package and DLL has a tag naming the folder it sits in, below the profile's natives and mod folders (the full path is on hover). Long names shorten on a narrow window instead of pushing buttons out of view.
- Mods: the packages folder (mod) and the natives folder show as folders at the top of their lists. An entry that points at a folder of mods instead of a mod (it loads nothing itself) is explained there instead of listed as a mod, with Remove entry; Not loaded lists the mod folders and DLLs in there that no entry points at, to add the ones you pick. Nothing is copied or moved. A profile with one package for everything, as in me3's guide, stays a normal package.
- Mods: removing an entry whose folder other entries still use no longer offers to delete that folder, and says why.
- Saves: the file Play uses follows the setup. A save file name set in the me3 profile and Seamless Co-op's save file setting are both honoured, so a renamed save is listed, and repaired after play, like the default one. The Saves page says which file Play and Play offline use.
- Saves: Copy to... replaces another save with a whole file (the save it replaces is kept in the library first, under a name you choose) or only adds a named library copy. Both show every character before and after.
- Saves: Copy a character... copies one character into a free slot, or over one, in the same or another save, checked and backed up; a character from another Steam account moves to this one.
- Saves: a save library keeps named copies of whole saves beside them. Swap in puts one in place of a live save and files the replaced one first, so nothing is lost. library.json records every copy, swap, rename and removal.
- Mods: each entry is checked the way me3 reads it: a missing file or folder, a native that is not a .dll, a package id used twice, a required load_after / load_before that is missing or switched off, and load orders that loop are named on the entry.
- Mods: Options offers only entries of the same kind for load order (me3 orders packages with packages and DLLs with DLLs), named the way me3 refers to them.
- Mods: Conflicts looks only at the game folders at the top of each package, which is what me3 serves; a folder of other mods no longer counts their files twice, and the scan is much faster.
- Mods: quieter rows: no On / Off text beside the switches, long load-order lists shortened (the full list is on hover), initializers named by their function. Heap size is only editable with the memory patch on; the save file field is a plain name.
- Mods: a profile changed outside the launcher (in a text editor, by me3 or an installer) is noticed. Coming back to the window reloads the Mods page, switches and Options act on the entry as it is in the file now rather than by its old position, and saving Edit profile over newer changes on disk asks first.
- Mods: an empty package folder says it is empty for now (game folders put there load), instead of reading as a problem.
- Mods: each DLL mod has a settings button that opens its own settings file (UnlockTheFps.ini, BetterCamera's ini, ...) in the editor, with Save and Discard and a .bak on save. Files beside the DLL are found on their own; one the mod reads under another name (SkeletonMan's skeleton_mods.txt) can be tied to it once and is remembered. Files keep their encoding and line endings. Seamless Co-op's settings stay on the Co-op page.
- Mods: the folder line's buttons sit on the right.
- Files: everything Roundtable Souls keeps now lives in its own data folder (%LOCALAPPDATA%\RoundtableSouls, or beside a portable copy): backups and the save library under saves\<game>\<Steam account>, deleted profiles under profiles\deleted, install unpacking under temp. Nothing of the launcher's is written into the game's save folder or me3's profile folders any more, apart from the offline .me3 copy and a single .bak beside an edited file. Folders earlier versions made there (save-fix-backups, regulation-fix-backups, co2-to-sl2-backups, sl2-to-co2-backups, roundtable-saves, deleted-profiles) are moved in automatically.
- Backups: named for what came next ("Before fixing checksums", "Before playing", "Before copying a character in"). The newest 20 of each save and everything from the last 7 days are kept; Keep holds on to one for good. The Backups card shows the total size. Copies between the co-op and standard save no longer keep a spare copy of the unchanged source.
- Fixed: expandable cards could keep empty space under their content, or cut off their last row after the list was refilled.
- Mods: drag one or more archives, DLLs or mod folders onto the Mods page to install them, one after another. The page shows what a drop would do while you drag, and names files it would skip.
- Mods: installing asks for the folder name and id, and shows what the mod holds with what to install: game files, the DLL and its settings are ticked; readmes, example .me3 profiles and other mod loaders' DLLs are not, each with the reason. Unrecognised files install as shipped. Files beside the mod's folder in the archive are listed too.
- Mods: the mod is found below wrapper folders and next to readmes, and an archive with several versions (an English and an Italian mod folder) asks which one. Text languages are named.
- Mods: a mod with a regulation.bin says that me3 uses only the last one in the load order and which package's is used now. It goes before that package by default (above the comment lines that describe its entry), or last, or without its regulation.bin.
- Mods: a lone .dll installs as a DLL mod. An archive that also ships an example .me3 installs as a mod instead of being refused as a profile.
- Fixed: after a job, the message and the Mods page refresh looked at how the job ended instead of what it was, so an install did not reload the page and every job reported "Saves repaired and cleanup done."

## [3.4.0] - 2026-09-28

- Games: a game button at the top of the window picks the game every page works on; its menu lists every game with whether it is installed, and Ctrl+Tab / Ctrl+Shift+Tab step through them. Elden Ring and Nightreign are supported; Dark Souls III and Sekiro have placeholder pages that only show what was found on the PC. Settings stays shared, and each game remembers its own setup and custom game exe.
- Nightreign: Play through me3 (online, or offline without Seamless Co-op), its me3 profiles and mods, and its Seamless Co-op settings (three difficulty values, no password in that mod). Saves are listed with a structure check, backups, restore, and copies between the co-op and standard save; Nightreign encrypts its saves, so characters are not shown.
- `--game <name>` picks the game for `--play` and `--check`, or the tab the window opens on for that run. Settings > Steam shortcut shows the launch options for the game on screen, one shortcut per game. An unknown name lists the valid ones.
- me3 profiles are listed under the game they name in `[[supports]]`; a profile that names none counts as Elden Ring's. Picking a profile made for another game says so instead of launching it.
- Setups: switching games no longer reads every profile's co-op settings up front, only the one in use. Two profiles with the same file name show their folder in the list, and the list is sorted by name.
- Fixed: deleting a profile on the Nightreign page cleared Elden Ring's remembered setup instead of Nightreign's.
- Fixed: a remembered setup written with different letter case or slashes was not found again, so Play could pick another one.

## [3.3.0] - 2026-09-27

- Saves: items the installed game defines always count as game items, read from the game's own regulation.bin. The Tarnished Edition pack's gear is recognised exactly, whether or not a character owns the pack; the guess based on the pack flag is only used when the game is not on this PC.
- Saves: mod items are named again. Seamless Co-op's items take their names from the mod's own language file, and other mods' items from the text files they ship (Windows, read with the game's own decompression library). Names are grouped by mod on the Saves page, and Review & fix can filter by mod when a save holds more than one.
- --check also writes its report to logs/last_run.log, adds the game data and mod names it found, and no longer shows the co-op password.
- Builds: tests run only when code, tests, build files or dependencies change, exactly as locked; a newer push cancels the older run. Releases must come from main, match the version, and are checked file by file before they go public. Changes to documentation alone skip the tests.

## [3.2.0] - 2026-09-27

- Licensing: the project is now GPL-3.0-or-later, matching the GPL-3.0 UI library the app is built on.
- Saves: items the game does not define are shown by kind and ID ("Armour 742000").
- Saves: Tarnished Edition and Shadow of the Erdtree are detected automatically, from the pack flag stored in the save and from DLC.bdt next to the game.
- Saves: Fix loading is a table of checks, each with its own repair.
- Saves: the weather check no longer runs; it flagged healthy characters during normal play.
- Layout: pages never scroll sideways. Page actions, status chips and button rows wrap; settings rows stack their control under the text; Review & fix turns its character list into a dropdown when the window is narrow. Checked at narrow widths and 150 % scaling.
- Names: Tools is now Settings; To .sl2 and To .co2 are Copy to standard save and Copy to co-op save; Worth knowing is Notes; one word, Refresh, for re-reading; folder buttons say which folder. The per-save Folder button is gone (the page has Saves folder).
- Buttons that are only an icon (delete, clear) are square with a tooltip; backups read as two lines per copy.
- Keyboard: nothing has focus when the window opens, so a stray Enter or Space cannot press Play. Ctrl+1 to Ctrl+5 open the pages, Esc leaves Review & fix, and focused buttons show a ring.
- Fixed: rebuilding the Saves page no longer trips a flood of internal layout errors.
- Fixed: copies made with Copy to co-op save appear in the Backups list.
- Installer: releases include RoundtableSouls-Setup.exe, a per-user install with no administrator prompt, a Start menu entry, an optional desktop shortcut and an uninstaller in Windows' app list. Installed copies keep settings in %LOCALAPPDATA%\RoundtableSouls, so updates and uninstalls never touch them. The portable zip stays available.
- Update now follows the install type: an installed copy downloads the new setup, checks it against SHA256SUMS.txt and runs it silently, which closes, updates and reopens the app; a portable copy swaps its exe as before. Settings shows which kind of copy is running.
- Linux and Steam Deck: a Linux build finds Steam (including Flatpak), the game, and the saves inside the game's Proton folder on any library or SD card; processes are read from /proc; me3's Linux paths are used; folders open with the desktop's handler.
- --play runs the Play session without the window, for a Steam shortcut, Big Picture or Steam Deck Gaming Mode. Settings > Steam shortcut shows the exact target and launch option to paste.
- The user guide and README were rewritten for this release.
- Tools: a Launcher card at the top holds the version, Check for updates, Releases and Logs, and the update toggle. The me3 card is back to me3 only, with one me3 folder button instead of two, me3 releases and Refresh.

## [3.1.4] - 2026-09-27

- Update now: the relaunch after an update crashed on its first start (the new exe inherited the old one's PyInstaller markers and looked for its files in a folder that was already gone; a manual start worked). The new exe is now started with a clean environment, detached from the old one.

## [3.1.3] - 2026-09-27

- Tools: the launcher update button is labelled Check for updates and sits before Launcher releases.

## [3.1.2] - 2026-09-27

- Tools > Check now asks GitHub for a newer launcher right away, ignoring the cache, and says Up to date when there is nothing. The automatic check now waits an hour between calls instead of a day.

## [3.1.1] - 2026-09-27

- Editors: Enter and Esc in the find bar no longer reach the document (Enter used to replace the found text with a line break). The bar keeps its colours after a theme switch and stays inside a narrow editor. Key-driven tests cover the bar.

## [3.1.0] - 2026-09-27

- Update now: the update notice can download the release, check it against the published SHA-256 checksums, swap the exe and restart. Still one click, never silent, and the manual Download link remains.
- Saves: To .co2 on a standard save makes the Seamless Co-op copy, backing up any existing .co2 first.
- Editors: Ctrl+F find and Ctrl+H replace with match case, regular expressions, Enter / Shift+Enter stepping and Replace all as one undo step.
- Releases now ship SHA256SUMS.txt next to the zip.

## [3.0.1] - 2026-09-27

- Tools > Check for launcher updates: once a day the launcher looks at this project's GitHub releases and shows a notice with a Download link when a newer version exists. Skip this version hides one release. Nothing is installed automatically.

## [3.0.0] - 2026-09-26

- Renamed to Roundtable Souls and rebuilt as a Python package (Python 3.14, uv). Settings are validated on load; the settings folder %LOCALAPPDATA%\Roundtable is carried over. No change to what the launcher does.

## [2.54]

- Characters last saved on an early game patch (slot version 81 or lower) now read. If a slot still cannot be read, the other characters show and that one is named and left alone.

## [2.53]

- Saves without Shadow of the Erdtree: DLC items are named as such and removable, with a Tools override for checking someone else's save.

## [2.52]

- Folder buttons: me3, Game and Saves under Tools > Folders, me3 folder on the me3 card, Saves folder on the Saves page, Profile folder on Mods, Game folder beside the setup picker. Each says why when a folder is unknown.

## [2.51]

- Less tied to one PC: Tools > Locations for a custom me3, game exe and profile folder; the profile folder follows me3 info; setups from an installation.json are labelled as such; the difficulty presets are named by party size; help texts name Seamless and Revive as examples, not assumptions.

## [2.50]

- Install mod accepts .7z and .rar as well as .zip.

## [2.49]

- Mods: install from a .zip or folder with package / DLL detection, per-mod options (loaded, optional, load early, initializer, finalizer, load order), remove with optional folder delete, on/off switches for every entry, new and delete profile.

## [2.48]

- Edge cases: profile settings keep a file without a final newline intact and never leave a duplicated key; a save file name must be a name, not a path; launch flags are skipped for a me3 older than 0.13; a setting change refuses to overwrite unsaved editor text; the me3 version follows the chosen setup.

## [2.47]

- Mods: package conflict scan, profile settings as menus, boot boost / logos / diagnostics launch flags, and the me3 version with an update notice and its logs.

## [2.46]

- Confirms read top to bottom: what will happen as bullets, then the safety line, then the button named for the action. Locks: with Elden Ring running, Apply, Restore and Undo stay off with the reason in their tooltip, and every write also waits for a save the game is still flushing.

## [2.45]

- Fix: the window opened on an empty Review & fix page instead of Play.

## [2.44]

- Altered versions of Tarnished Edition armour are recognised and named.

## [2.43]

- Tarnished Edition gear is official content: it counts as vanilla when the pack flag is on the save (Tools can override). Nothing worn is modded any more on such saves; the About card shows the pack pieces separately.

## [2.42]

- Review & fix: a page per save with characters on the left and every fix as a tick box on the right, search and filter for mod items, removals off by default, one Apply with Undo after. Backups list on the Saves page with Restore and Delete; every backup records what it was taken before. Tools > Play session toggles for backup before Play, process cleanup and repair. "Restore vanilla" is now "Remove mod items".

## [2.41]

- Restore vanilla, Fix quest flags and Fix loading open a checklist: pick characters, items and fixes one by one. Nothing is removed that you did not tick.

## [2.40]

- Fix loading: Torrent, position, DLC flags and weather repairs, with the usual confirm and backup. Torn writes are detected and named. Status chips on each save card; action buttons wrap on narrow windows.

## [2.39]

- Fix quest flags is always its own button when a soft-lock is found, next to Restore vanilla. Goods in a pouch slot no longer read as "worn".

## [2.38]

- Worth knowing shows one line per character with counts per mod; hover a line for the item names. The profile and share editors get Ctrl+/ comment toggle, Tab / Shift+Tab indent, Ctrl+D duplicate line.

## [2.37]

- Restore vanilla: strips Seamless and mod items by name, clears leftover rows and soft-locks, re-signs, backs up. The vanilla item list is rebuilt from the game's own item data, so vanilla goods, gestures and spirit-ash levels no longer read as unknown, and mod packs no longer pass as vanilla. Mod items are named on the Saves page.

## [2.36]

- Saves can fix quest soft-locks and stale checksums (asks first, backs up, re-signs). Item check understands weapon affinities and empty-slot placeholders; leftover entries from co-op partners' gear are informational only. The Saves icon shows a count only when a repair is available.

## [2.35]

- Saves panel spacing fits the content; notes are tighter and grouped.

## [2.34]

- Saves stay calm: characters first, optional "Worth knowing" notes only on that page. No Play banner for save checks.

## [2.33]

- Saves add duplicate-inventory, unknown item IDs, and known quest-flag soft-lock findings. Copy report and To .sl2 (only when clean). Play glances when a save needs attention.

## [2.32]

- Saves show regulation and layout findings, with Repair on a dirty block. Play warns when dead eldenring.exe shells are left behind and offers Clear.

## [2.31]

- The exe icon is a square plate with a size ladder (16–256). Windows 11 rounds it; 16 and 20 stay a ring and disc so they stay readable.

## [2.30]

- Everything is Roundtable. The mark is a circle with a transparent edge, like a current app icon.

## [2.29]

- The app is Roundtable. A grace mark replaces the old icon, and Tools can follow the theme or lock the logo to dark or light.

## [2.28]

- Gameplay settings are named menus and switches, not ini numbers. An info button explains each one. Offline play can skip Revive, skip starting Steam, and skip the confirm. The profile and share editors highlight TOML and JSON.

## [2.27]

- Launch log timestamps each line and colours errors. The profile and share boxes are code wells. Setup names the profile file, not this PC's folders.

## [2.26]

- Light is mid ice. Play is a deeper sea blue (#075C8B).

## [2.25]

- Light sits on a cooler frost ground. Play is a deeper sea blue.

## [2.24]

- Light is frost paper, a pale hero wash, and sea-blue Play.

## [2.23]

- Dark is the Lands Between gold strip. Light is Ranni frost and hatband dusk. Icon buttons keep a 36px slot so type does not sit under the glyph.

## [2.22]

- Ink canvas, antique gold only on Play and Save. The featured card holds the character, the Play action, and three facts. Pages paint their own ground so type stays readable.

## [2.21]

- The window shrinks to 720px. Play stacks the banner over the stats, difficulty goes to two columns, and padding tightens.

## [2.20]

- One glass palette: brighter violet, deeper background, 16px cards, 22px banner, pill Play and Save.

## [2.19]

- Design pass: quieter copy, Setup folded unless it is broken, Save profile on the Mods title when the file is dirty, Ctrl+S, and closing offers to save instead of only warning.

## [2.18]

- Co-op Save stays on a bar at the bottom of the page. It names what is unsaved and turns violet until you save or discard.

## [2.17]

- Windows 11 acrylic behind the window, and the featured card is translucent so the blur shows through. The setup line shows the program names; the full paths are on the tooltip.

## [2.16]

- Play is a featured card: the character and Play on the left, level, save, and body on the right.

## [2.14]

- Play leads with the character, then one Play button. Page titles are type only; the nav already carries the icon.

## [2.13]

- A profile that only has Seamless Co-op and Nightreign Revive is read too, including the packages = [ ] form Revive's installer writes.

## [2.12]

- Panels ease open and shut, and a closed panel keeps only its header height.

## [2.11]

- Clearer layout. Refresh sits on the page title. Co-op hides its form when the setup has no Seamless. Launch log, and each save, fold. Closing asks if the profile or co-op settings are unsaved.

## [2.10]

- Mods lists only entries me3 will load (enabled is not false), with Refresh. Share, profile text, folders, offline play, and each save fold open and shut.

## [2.9]

- Mods page lists what is on and off, and edits the loaded me3 profile

## [2.8]

- Mods page: list packages and natives, turn them on or off

## [2.7]

- one Save co-op settings button for the password, difficulty, and the other options, with the unsaved list written above it

## [2.6]

- a confirmation when a setting is saved or applied; save buttons light up only when something changed

## [2.5]

- Nightreign-like presets for parties of 4, 5 and 6

## [2.4]

- offline play when Steam's login is down (solo, standard save)

## [2.3]

- Nightreign-like preset now uses Nightreign's real scaling rule

## [2.2]

- every Seamless Co-op setting editable in groups, your character on the Play page, status pills, one calm accent in dark and light

## [2.0]

- new window: Windows 11 Fluent look, pages (Play / Co-op / Saves / Tools), your character on the Play page, one Play button

## [1.7]

- safer file writes (.bak kept), error reporting, asks before closing while a session runs, settings fall back to LOCALAPPDATA

## [1.6]

- Share settings... : copy / paste / apply the settings as text

## [1.5]

- export / import settings as a .json file

## [1.4]

- difficulty scaling presets (Seamless default / Nightreign-like / Custom)

## [1.3]

- finds a Nightreign Revive install inside the game folder by itself

## [1.2]

- saves panel, dark theme, no more terminal flashes

## [1.1]

- Nightreign Revive setups, tools menu

## [1.0]

- first window version
