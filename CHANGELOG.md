# Changelog

All notable changes to Roundtable Souls. The version is shown in the window title.

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
