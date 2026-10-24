# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [5.0.0-rc.3](https://github.com/Carlomos7/roundtable-souls/compare/v4.6.0-rc.3...v5.0.0-rc.3) (2026-10-22)


### ⚠ BREAKING CHANGES

* the import package roundtable_souls is now bayle.

### Added

* **api:** add the generated TypeScript client with a typed SSE reader and use it in the desktop app ([5d1a11f](https://github.com/Carlomos7/roundtable-souls/commit/5d1a11f94c4af6c9fff1aa65904d3af4bff7c2cc))
* **api:** FastAPI app factory, bearer auth, CORS, backend entry point and OpenAPI snapshot ([f250f0e](https://github.com/Carlomos7/roundtable-souls/commit/f250f0e40f44851eb7d88aa7668cb94817569758))
* **api:** job manager in the app, SSE event stream, job snapshot and cancel routes ([c1fa121](https://github.com/Carlomos7/roundtable-souls/commit/c1fa121fe74a989c508eaccb0d2da59ff2a21020))
* **desktop:** add Tailwind v4 theme tokens generated from the Qt theme ([cc461d3](https://github.com/Carlomos7/roundtable-souls/commit/cc461d3382e3f9e8dd3355e2c9f836cd454e42a1))
* **desktop:** add the app shell, backend plumbing and shared prompt and toast components ([dc99920](https://github.com/Carlomos7/roundtable-souls/commit/dc99920e5c59e9a1a988a0e7b402731bb698d975))
* **desktop:** add the Tauri v2 shell and React front-end skeleton ([9d64352](https://github.com/Carlomos7/roundtable-souls/commit/9d643522bd4b5094dc03990dc6d8e5e73f6f8579))
* **desktop:** use the generated @bayle/api client, set the window size and move the token generator ([59aa6ed](https://github.com/Carlomos7/roundtable-souls/commit/59aa6ede3478587563351805f48925ba96735248))
* **session,api:** Activity operations, plan tokens and generic page/op/plan routes ([90f7283](https://github.com/Carlomos7/roundtable-souls/commit/90f7283c0e14263559ec8e0b4694b14447f5e1c5))
* **session,ui:** Mods install drafts, overhauls and the Library behind the Session ([d84f433](https://github.com/Carlomos7/roundtable-souls/commit/d84f433c548a3ade035ab2fd1bb2c8467234bef0))
* **session,ui:** Mods page snapshot, notices and drag table behind the Session ([bad34e6](https://github.com/Carlomos7/roundtable-souls/commit/bad34e6714c684b44f9d4e4e943e1d7b5e677af5))
* **session,ui:** Mods profile operations behind the Session ([d5bae3b](https://github.com/Carlomos7/roundtable-souls/commit/d5bae3bcef7ed540f19cd563281290cf0832220a))
* **session,ui:** Settings operations and snapshot behind the Session ([4f6a353](https://github.com/Carlomos7/roundtable-souls/commit/4f6a35384184e6e65b1ba75e0062b57205b99915))
* **session:** job titles from params, destructive plans, follow_job on the shell host ([41fe18a](https://github.com/Carlomos7/roundtable-souls/commit/41fe18ad1de6f34453f09ecd7a15c9903d5a3220))
* **session:** JobManager and EventBus over services.jobs ([4c53ae0](https://github.com/Carlomos7/roundtable-souls/commit/4c53ae06fec751c70809b084123ac61d557ca62e))
* **session:** operation registry, Session.run/snapshot/answer/startup, settings service ([e1faefb](https://github.com/Carlomos7/roundtable-souls/commit/e1faefbaf11f7fb782412498404011e38930aaf7))
* **views,session:** one Confirm/Refusal/Pick/Choose schema, PlanStore and PromptBroker ([4908e02](https://github.com/Carlomos7/roundtable-souls/commit/4908e02be045c3a0ee43736996204cfe4dc55642))


### Fixed

* **api:** give the Mods merge-health pill its own name so the API's Health type keeps its name ([2fc0442](https://github.com/Carlomos7/roundtable-souls/commit/2fc04423de2bdf12eddbe72f166ccc235404a1e0))
* **api:** type check the event stream's yield ([0e77293](https://github.com/Carlomos7/roundtable-souls/commit/0e77293897ebabc435d93f32bcbf50d82c151af1))
* **desktop:** send the bearer token on page and plan calls ([17fef23](https://github.com/Carlomos7/roundtable-souls/commit/17fef234fde63bacd2b71753c3d7c856524b53d6))
* **desktop:** show the backend's message in the status line when the shell page is refused ([bee43af](https://github.com/Carlomos7/roundtable-souls/commit/bee43af7aaadcfadcf2284ae703009a0a333a7bd))
* **ui:** stop page adapters from outliving their window through reference cycles ([6281deb](https://github.com/Carlomos7/roundtable-souls/commit/6281debf75088edd47acb4e0142802cace65b65b))
* write worker requests from a writer thread, not under the pool lock ([b690709](https://github.com/Carlomos7/roundtable-souls/commit/b6907097d15ef47e58400346c4c5626e960e7e64))


### Changed

* move presenters, load order, install draft, top bar and menu models into bayle.views ([ce20ccd](https://github.com/Carlomos7/roundtable-souls/commit/ce20ccd2aacbd628e6a7fb0385f51dc5a7383603))
* move the CPU worker pool to platform/cpu_pool.py on subprocess ([11fa1fd](https://github.com/Carlomos7/roundtable-souls/commit/11fa1fd5a258377f5a549712b9a43bc34448a86f))
* move ui.text to platform.text ([fb36a62](https://github.com/Carlomos7/roundtable-souls/commit/fb36a62e8e9c531914407a92e2e54b1c8cb08963))
* rename the package to bayle ([69844fa](https://github.com/Carlomos7/roundtable-souls/commit/69844fad3dd007c1c9581ac4b32230b1aacb2f82))
* **saves:** Saves page reads and writes go through the Session (WP11, WP12) ([a00be35](https://github.com/Carlomos7/roundtable-souls/commit/a00be3591594dace561a6ce36127c74997b0796c))
* **services:** typed operation errors, JobResult and run_logged ([bc632d1](https://github.com/Carlomos7/roundtable-souls/commit/bc632d16bb278509e5459904852b1275e3354b64))
* **shell:** move the shell behind the Session ([14a8bf4](https://github.com/Carlomos7/roundtable-souls/commit/14a8bf4abd30855b84c480e825a9b8f8028cc3e7))
* **ui,session:** Mod Configs page goes through the Session ([fe2b5db](https://github.com/Carlomos7/roundtable-souls/commit/fe2b5dbf9daca67953bba7dcf627fcdab6480428))
* **ui:** Activity adapter and host go through the Session ([a513d5c](https://github.com/Carlomos7/roundtable-souls/commit/a513d5c01b8d1b38304b869929d26fe0f622308d))
* **ui:** Profile transfer export and import go through the Session ([b799298](https://github.com/Carlomos7/roundtable-souls/commit/b79929856c5ff270009f6709f94029f6b1dc83fd))


### Removed

* take the desktop app, the TypeScript client and their CI off main; they stay on local branches ([ae25905](https://github.com/Carlomos7/roundtable-souls/commit/ae2590597448bb3d98bf5b1826ea6daa3d13d71f))

## [4.6.0-rc.3] - 2026-10-22

### Added

- **Appearance:** a new Bayle icon and logo. Settings > Appearance > Logo picks Follows theme (crimson on dark, ice
  on light), Crimson, Ice or Tarnished (gold); the window and taskbar icon follow your choice.

## [4.6.0-rc.2] - 2026-10-21

### Fixed

- **Overhauls:** Install as overhaul uses your saved setup of the same overhaul again (each DLL's options, the text
  table, your Files choices), also when a new download keeps its game files in a folder such as `mod`.
- **Overhauls:** the review asks you to choose a text table once, and names the files as
  `msg/<language>/...` instead of showing a raw `{each}`.
- **Overhauls:** the game path of a file you place has its own line in the Files table, so it's no longer cut off.

## [4.6.0-rc.1] - 2026-10-21

Overhauls set up by Bayle now cover large overhauls like Nightreign Revive from start to finish: you see and choose
what happens to every file, the menu text gets built, and an overhaul its own installer set up can be taken over.

### Added

- **Overhauls:** a Files table in the overhaul setup and in Install mod shows what Bayle does with each file
  (combine, merge, copy, keep your copy, place at a game path, leave out), and lets you change it.
- **Overhauls:** Install as overhaul shows each DLL's options (start early, start function, load after the other
  DLLs) and the proposed menu texts before anything is installed.
- **Overhauls:** a file shipped outside the game folders, like a talk script, can be placed at its game path and
  merged with the other mods' copy there.
- **Overhauls:** menu text a mod ships as language files (JSON) is built into the game's message files, on top of
  the other mods' text. When Bayle can't tell which table the text belongs to, the setup asks you to pick one.
- **Overhauls:** Take over, for an overhaul its own installer set up: it shows what the installer changed, removes
  its entries and folders with an Undo, keeps your own mods, and offers to install the overhaul again with Bayle.
- **Overhauls:** Clean up installer leftovers finds an installer's folders, setup copy and backups even when Bayle
  has no setup for that overhaul.
- **Play:** Bayle tells you when the game updated since your last run, since DLL mods may need updates then.
- **Play:** an overhaul's setup can name a log file to check after each run; a failure line shows as a toast and in
  Activity, also after a run Bayle didn't see end.
- **Mods:** a notice with a Move in button when the profile is outside Bayle's folder.

### Changed

- **Overhauls:** saving an overhaul's setup applies it to every profile that uses it, with one Undo for all of them.
- **Overhauls:** a download whose game files sit in their own folder (such as `mod`) installs as it is.
- **Overhauls:** an overhaul's own folder counts as part of the profile: Move in, rename, duplicate, export and
  migration handle it, and duplicating a profile with a Bayle-installed overhaul now works.
- **Folders:** the folder names you give packages and natives in Settings > Locations are reserved and used
  everywhere; operation records and locks live in `.bayle`, and old `.roundtable-ops` ones are taken over safely.

### Fixed

- **Overhauls:** a setup's paths can't point outside the mod's folders.
- **Overhauls:** older saved setups keep their settings when saved again, a new download that dropped a file no
  longer breaks the setup, and a hand-edited setup file isn't rewritten.
- **Overhauls:** a switched-off overhaul stays off when its setup is applied; Undo restores each profile's exact
  bytes.
- **Overhauls:** the merge report no longer shows a blank version.

## [4.5.1] - 2026-10-21

### Fixed

- **Speed:** moving the mouse over the window no longer makes Bayle stutter. On Windows, the title bar searched the
  whole window for its buttons on every mouse move, which froze the window for up to several seconds on busy pages.

## [4.5.0] - 2026-10-21

Bayle keeps its window responsive: heavy work runs in separate worker processes, disk reads happen in the
background, and pages show at once while fresh data loads.

### Changed

- **Speed:** checking saves, combining parameters and hashing mods run in separate worker processes, so the window
  never freezes while they work (checking a large save went from a 57 ms freeze to 4 ms).
- **Speed:** pages show straight away and refresh in the background. Several refreshes at once become one, and a
  page that hasn't changed isn't rebuilt. Opening Settings and Export is about twice as fast, and start-up is
  about 0.5 s quicker.
- **Logs:** the launcher notes which graphics backend it uses at start, and logs any moment the window freezes for
  more than 0.2 s, so slowness can be traced.

### Fixed

- Closing Bayle while a long job runs no longer hangs: it waits up to 3 seconds, and the job is finished or undone
  at the next start.
- Mod Configs no longer loses a refresh asked for while it is loading.
- Save checks right after installing a mod see the new mod's item names.

## [4.4.0] - 2026-10-21

The launcher is now **Bayle**. Each game has its own tidy folder of profiles, you choose where it lives, and the
window is much faster.

### Highlights

- **New name:** Roundtable Souls is now Bayle. Shortcuts and the Windows app list say Bayle; updates, settings and
  your files carry over, and Steam shortcuts keep working.
- **Tidier folders:** profiles live in `b-eldenring\<profile>\` (and `b-nightreign\`), with Shared mods in
  `b-eldenring\.shared\`. Profiles from earlier versions move there once; undo it in Activity.
- **Your choice of location:** Settings → Locations sets where profiles live and what the folders are called.
- **Faster:** pages no longer rebuild when nothing changed, Activity opens about 10 times faster, and scrolling
  stays smooth.

### Added

- **Settings → Locations:** Profiles folder with Change…, which moves everything with progress, Cancel and Undo,
  and warns about cloud-synced folders and low space. Folder names for the game folder (`b-{game}`), game-file mods,
  DLL mods and Shared mods, with a live preview. Move all… moves every plain me3 profile into Bayle's folder in one
  step.

### Changed

- **Name:** the window, About, shortcuts and uninstall entry say Bayle, and About notes that Bayle is an
  unofficial fan project, not affiliated with FromSoftware or Bandai Namco.
- **Folders:** each profile's hidden launcher folder is `.bayle` (older `.roundtable` folders are still read).
- **Settings:** me3's own folder setting is now called "me3 profiles folder", next to Bayle's "Profiles folder".
- **Speed:** lists update only the rows that changed, Activity builds a job's log only when you open it, mod menus
  are built on first use, hidden pages refresh when you open them, and the unlisted-folder check is faster.

## [4.3.1] - 2026-10-21

### Fixed

- **Speed:** the launcher no longer slows down after every change on the Mods page. The check for mods kept twice
  now runs once when your profiles change, never re-reads a folder that hasn't changed, and no longer counts one
  folder that two profiles use as two copies.

## [4.3.0] - 2026-10-21

Mods can be shared between profiles to save space, DLL mods get folders of their own, and the window has a single
title row.

### Highlights

- **Shared mods:** share a game-file mod between profiles to store it once. Each profile stays on its own version
  until you choose Update here or Update everywhere.
- **DLL mods in their own folders:** a notice offers to move loose DLLs into folders of their own, with their
  settings files.
- **One window row:** the menus, the title and the window buttons share one row, with Windows snapping kept.

### Added

- **Shared mods:** Share, Use in other profiles… and Use a separate copy on a mod's menu, a Shared mods window
  listing versions and who uses them, Remove unused versions, and a hint when duplicated mods take over 1 GB.
- **Install:** when another profile has the same mod, choose Keep separate or Share. A new version of a shared mod
  offers Update here or Update everywhere.
- **Duplicate:** choose to copy the mods or share them with the original.
- **DLL mods:** Put in folders moves a DLL that isn't in its own folder, with its own settings files. Undo it in
  Activity.

### Changed

- **Install:** a DLL's folder keeps the DLL's own spelling (`natives\UnlockTheFps\`).
- **Combine:** for a profile with its own folder, merged parameters go to `builds\combined-parameters`.
- **Split into folders:** uses `packages` for each new profile.
- **Rename, Move into the launcher's folder, Split:** paths to the profile's own files are written as relative
  paths, so they keep working when the folder moves.
- **Releases:** the notes on GitHub are this changelog's section for the version.

## [4.2.0] - 2026-10-21

Each profile now has a folder of its own with its own mods, kept per game in one folder the launcher owns. Profiles
no longer share mod folders, so changing one profile never changes another. Mod READMEs show as formatted text.

### Highlights

- **One folder per profile:** `roundtable\<game>\profiles\<name>\` in me3's profiles folder holds the profile, its
  game-file mods (`packages`), its DLL mods (`natives`) and the launcher's files for it.
- **Your profiles move once, safely:** profiles in the old shared `rs-<game>` folder move into the new layout on the
  first start. A mod that two profiles shared is copied to each. Undo it in Activity.
- **Move into Roundtable's folder:** a plain me3 profile can join the launcher's folder from the Profile menu. Mods
  other profiles still use are copied, not moved.
- **Mod READMEs:** a mod's README shows on Mod Configs as formatted text.

### Added

- **Profiles:** a notice when a profile's folder is named differently from the profile (Rename folder), or when one
  folder holds several profiles (Split into folders). Both can be undone.
- **Mod Configs:** a mod's `README.md` or `readme.txt` is listed with its settings and shown formatted, with Edit as
  text to change it.
- **Mod Configs:** a mod the profile has switched off shows a **Disabled** tag instead of a line of text.

### Changed

- **Profiles:** Duplicate copies the profile's mods too, and Rename also renames its folder.
- **Remove:** removing a mod deletes it from that profile only.
- **Pages:** the profile's name stands out in the Mods, Mod Configs and Export headers.
- **Mod Configs:** help icons that only repeated the help line under a setting are gone.
- **Nightreign saves:** the Saves page says the character data is not documented yet, instead of calling the save
  "encrypted".
- **Records:** rebuild runs, backup notes and keep flags, the save library index and profile history are also kept in
  the launcher's database. The files stay the source of truth, so an older version still reads them.

### Fixed

- The Mods page no longer fails to open when no profile is selected.

### Removed

- **Adopt into the Library** and the "Outside the library" and "Shared" tags, which only applied to shared mod
  folders. Plain me3 profiles outside the launcher's folder keep working where they are.
- Unused code left from the retired merge paths. Game file names now come from one catalog.

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
