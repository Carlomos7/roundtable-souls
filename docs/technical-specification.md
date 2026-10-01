# Roundtable Souls — Technical Specification, Directory Blueprint, and Agent Action Plan

**Specification version:** 1.1 · **Date:** 2026-09-30 (status updated 2026-10-01) · **Core implementation phases:** 0–6 · **Follow-on feature:** Phase 7 rename; optional Phase 8 UI extraction

This document supersedes earlier conversation phase numbering and architectural sketches. Core Phase 0–6 numbers below are authoritative; Section 8 adds an independent UI change and explicitly scoped follow-on Phase 7/8 work without renumbering the core plan. It specifies the intended implementation, not a declaration that proposed modules or capabilities already exist. Confirm the current checkout before modifying code; retain completed work and update status from evidence. Existing repository instructions and explicit user authorization govern git operations and publication.

Normative terms: **MUST** is required; **SHOULD** is the default unless a documented reason justifies deviation; **MAY** is optional. An uncompleted acceptance check remains pending; it must not be reported as passing. This specification does not authorize automatic release publication.

## 1. EXECUTIVE SUMMARY & OBJECTIVE

Roundtable Souls is a high-performance desktop launcher, universal mod merger, and toolbox written in **Python ≥3.14 and PySide6**, with PySide6-Fluent-Widgets for the desktop interface. “Universal” describes extensible per-format/per-game handling, not permission to merge arbitrary binary files blindly.

The core game portfolio is **Elden Ring, Nightreign, Dark Souls 3, and Sekiro**. Capability is explicit per game and platform. Elden Ring is the initial merge-validation target. Existing Nightreign features are preserved; unavailable regulation-writing or merge capabilities must not be invented. me3 added DS3 support in v0.8.0; DS3 format compatibility remains separate work. Sekiro loader compatibility must still be confirmed before advertising new capabilities.

Core behavior includes:

- Native management of user-owned **me3 TOML profiles**, package/native entries, ordering constraints, and owned-entry edits.
- **Seamless Co-op** integration and existing launch workflows.
- Custom **Grace Menu** handling through focused ESD parsing and a deliberately limited structural merge rule.
- Existing automated backup, reversion, save analysis and repair utilities, with undo/history preserved. Save-related functionality remains limited to supported formats; this refactor does not authorize changing unresolved save-integrity algorithms.
- Rebuilding merged output from original game files plus enabled mod inputs. The build must be repeatable, inspectable, stale when inputs change, and undoable.

Primary objective: eliminate duplicated BND4 infrastructure, reuse a proven ESD implementation, align predicted file winners with me3, consolidate build lifecycle and retire replaced recipe/external-tool paths. Keep verified binary implementations where replacement provides no demonstrated benefit.

### 1.1 Technology decisions

| Technology | Decision and scope |
|---|---|
| Python ≥3.14, PySide6, Fluent Widgets | Existing runtime/UI; Qt remains in presentation integration only. |
| Pydantic | Existing settings; extend to game/setup configs and persisted records as needed. |
| `struct`, `dataclasses` | Retain existing DCX/BND4/FMG/PARAM/archive code and internal models. |
| constrata ≥1.3.3 | Phase 2 runtime addition; MIT, no dependencies confirmed. |
| Focused Soulstruct ESD source | Phase 2 vendoring/adaptation; GPL-3.0-or-later; exact pin below. |
| Full Soulstruct | Separate development verification environment; never shipped as a runtime dependency. |
| cryptography | Existing AES and RSA key parsing; archive-index RSA exponentiation uses Python `pow()`. |
| py7zr, zipfile, existing RAR tooling | Preserve extraction workflows. |
| uv / uv_build, PyInstaller, Inno Setup | Preserve dependency/build tools and Windows installer. |
| pytest, coverage, Ruff, Pyright, pre-commit, Pillow | Preserve existing development/build tooling. |
| GitHub Actions / Dependabot | Preserve test/release workflows, pinned actions and release checksum checks. |
| tomlkit, psutil, Hypothesis | Proposed later adoptions; not required additions to Phases 0–6. |
| me3 schema models | Proposed; exact authoritative schema/version must first be confirmed. |
| TPF adaptation, Paramdex, sharing, expanded game support | Deferred feature work; no premature implementation in this specification. |
| graphlib | Rejected for me3 order replication; valid topological order is insufficient. |
| Full Soulstruct runtime, generic deepmerge/JSON-patch merger, existing-format ports, pythonnet, ESDLang, Qt-bound merger | Excluded from this implementation path. |
| send2trash, pyooz, parallel compression, VDF library | On hold pending a demonstrated need and evidence. |

## 2. MANDATORY REPO & DEVELOPMENT RULES

The following requirements apply to all phases.

1. **Complete isolation of backend packages from Qt/PySide6 framework dependencies.** `game/`, `formats/`, `merging/`, `mods/`, `saves/`, `safety/`, `findings/`, `system/` backend operations and `app/` MUST NOT import Qt/PySide6. UI callbacks, signals, dialogs and widget scheduling belong in `ui/`. Headless `--play` and verification must work without creating a QApplication.
2. **Strict preservation of existing behavior unless a phase explicitly dictates a change.** Declared exceptions are the Phase 3 me3 ordering correction, validated DCX capability selection, Phase 5 ESD merging, and Phase 6 setup migration. Preserve existing settings, saves, restore tracking, installation and launch behavior otherwise.
3. **Separation of mechanical file moves from behavioral code modifications.** Use distinct commits or clearly isolated changes. Preserve caller inventories and avoid simultaneously moving modules, redesigning models and changing policy.
4. **Clean enforcement of fixture/temp-dir automated testing.** Automated tests MUST use synthetic/minimal fixtures and temporary directories. They MUST NOT touch real saves, profiles, game installations or mod folders.
5. **Isolated real-data verification writing to distinct output folders.** `scripts/verify/` accepts input paths as arguments or local ignored config. Real source data is read-only; rewritten files, builds and test profiles are written to separate scratch output directories. Do not commit copyrighted game data or machine-specific paths.
6. **Retention of upstream commit hashes, modification dates, and licensing for vendored data/code.** Preserve applicable copyright/license/warranty notices; record the full SHA and upstream paths; mark local modifications and relevant dates; include license texts/notices and corresponding source/build scripts for distributed GPL releases. Attribution alone is insufficient.
7. Formats answer what a file contains and how to read/write it. Merge rules answer which changes apply, which removals are trusted, and who wins. `formats/` MUST NOT import `merging/`; merge-rule registration belongs in the merging layer.
8. Every replacement MUST list migrated callers and retired code. Delete the replaced implementation after checks pass; temporary adapters must have an explicit removal condition. Do not accumulate permanent parallel implementations.
9. User profiles remain user-owned. Preserve unrelated entries, unknown supported data, comments and restoration behavior. Launcher-owned changes remain undoable. A mechanical trash move MUST preserve Windows Recycle Bin/freedesktop trash behavior; no silent switch to a private bin.
10. Do not create abstractions merely to match the tree. Use Pydantic for external configs/records, dataclasses for internal data and classes/functions where actual behavior warrants them. No blanket `slots=True`, `frozen=True`, wrapper or class conversion.
11. Game binaries are not inherently trusted. Readers validate supported headers, offsets, lengths, entry bounds and string termination; malformed inputs must fail, not hang.
12. Each phase report MUST state additions, migrated callers, deletions, verification commands/results, pending platform/game checks and remaining risks. Do not claim tested behavior from source inspection alone.
13. Preserve failure recovery and distinguish development verification from activation. Stage and validate output before activation; do not publish or replace live output merely to complete a structural refactor.

### 2.1 Data model rules

- Pydantic models contain configuration/record structure and validation, not game merge behavior. Use discriminated/tagged patch unions.
- Version migrations are explicit transformations followed by current-model validation; Pydantic does not automatically upgrade data.
- Unknown-key preservation requires retaining extras through the entire read/edit/write path. `extra="allow"` does not establish semantic compatibility with newer versions.
- Generated JSON Schema assists editors; explanatory documentation is still required. TOML editors need an association with the schema.
- Dataclasses may have methods. Immutable/slotted models are adopted only where compatible with callers and useful.
- Retain the adapted Soulstruct object model initially rather than introducing redundant ESD wrappers.

## 3. PROPOSED REPOSITORY DIRECTORY TREE

Tags identify when a responsibility is established or migrated. **P0 KEEP** means retained baseline, not a new implementation. P6 optional extractions occur only when touched; they do not gate the setup migration. Intermediate paths are explicit below. Omitted unchanged save/UI files retain their current names and responsibilities.

```text
roundtable-souls/                                      # [P0] existing root; phased migration
├── pyproject.toml                                    # [P0 KEEP; P2 EDIT] constrata; no full Soulstruct runtime
├── LICENSE                                           # [P0 KEEP] GPL-3.0-or-later
├── THIRD_PARTY_NOTICES.md                             # [P2 NEW; P3 EDIT] ESD/constrata/me3 notices and pins
├── installer/                                        # [P0 KEEP] Windows installer assets
│   └── RoundtableSouls.iss                            # [P0 KEEP] per-user Inno Setup installer
├── .github/                                          # [P0 KEEP] CI/dependency maintenance
│   ├── workflows/                                    # [P0 KEEP] pinned test/release/checksum workflows
│   └── <existing dependabot configuration>            # [P0 KEEP] retain actual current path
├── scripts/                                          # [P0 KEEP] build and development entry points
│   ├── build.py                                      # [P0 KEEP; P3 CHECK] collect migrated code/data
│   ├── <existing utility scripts>                    # [P0 KEEP] version/icon/share helpers
│   └── verify/                                       # [P0 NEW] local real-data checks; isolated outputs
│       ├── ingame_checklist.md                        # [P0 NEW] platform/version/file acceptance evidence
│       ├── verify_output.py                          # [P0 NEW] output/content/addition/removal comparison
│       ├── calibrate.py                              # [P0 NEW] verify checker on known-good inputs
│       ├── eval_soulstruct.py                         # [P2 NEW] focused ESD rewrite evaluation
│       ├── order_parity.py                            # [P3 NEW] compare Python order to pinned Rust harness
│       └── clash_corpus.py                            # [P4 NEW] representative ordinary-mod conflicts
├── tests/                                            # [P0 KEEP] hermetic regression/unit tests
│   ├── fixtures/                                     # [P0 EXTEND] synthetic format/profile/order cases
│   ├── test_bnd4.py                                   # [P1 NEW/MIGRATE] shared archive layout regressions
│   ├── test_esd.py                                    # [P2 NEW; P5 EXTEND] structure and merge invariants
│   ├── test_order.py                                  # [P3 NEW] upstream cases and minimized regressions
│   └── <existing and new area tests>                  # [P0 KEEP; P1–P6 EXTEND] relevant behavior checks
├── docs/                                             # [P0 EXTEND] authoritative plan and acceptance records
│   ├── technical-specification.md                    # [P0 NEW] this document, status updated with evidence
│   └── decisions/                                    # [P0 NEW; P1–P6 EDIT] compatibility/pins/deletion records
└── src/roundtable_souls/                              # [P0 KEEP] application package
    ├── __init__.py                                   # [P0 KEEP] package metadata
    ├── __main__.py                                   # [P0 KEEP; P6 OPTIONAL SPLIT] GUI/headless entry points
    ├── settings.py                                   # [P0 KEEP] Pydantic launcher settings
    ├── updates.py                                    # [P0 KEEP] existing self-update behavior
    ├── resources.py                                  # [P0 KEEP] bundled resource access
    ├── core.py                                       # [P0 KEEP; P6 OPTIONAL SPLIT] facade until callers move
    ├── game/                                         # [P3 NEW] game configuration/discovery/access
    │   ├── config.py                                 # [P3 NEW] Pydantic GameConfig/capabilities
    │   ├── discovery.py                              # [P3 SPLIT] inventory location/edition helpers first
    │   ├── archives.py                               # [P3 MOVE] BHD5/BDT, RSA/AES ranges, index cache
    │   ├── oodle.py                                  # [P3 CONSOLIDATE] native codec; explicit capabilities
    │   └── loads.py                                  # [P3 NEW IF NEEDED] providers using resolved me3 order
    ├── formats/                                      # [P3 NEW] binary models/readers/writers only
    │   ├── dcx.py                                    # [P3 MOVE] wrappers and accepted layout enforcement
    │   ├── bnd4.py                                   # [P1 CONSOLIDATE; P3 MOVE] one binder implementation
    │   ├── fmg.py                                    # [P3 MOVE] text tables, IDs, entries and layout
    │   ├── param.py                                  # [P3 MOVE] row bytes/order/duplicate-ID occurrences
    │   ├── regulation.py                             # [P3 SPLIT] encryption/DCX/binder composition
    │   └── esd/                                      # [P2 VENDOR; P3 MOVE] version-3 ESD binary support
    │       ├── __init__.py                            # [P2 NEW; P3 MOVE] local ESD interface/configuration
    │       ├── core.py                               # [P2 ADAPT; P3 MOVE] offsets/header/read/write
    │       ├── state.py                              # [P2 ADAPT; P3 MOVE] ordered state content
    │       ├── condition.py                          # [P2 ADAPT; P3 MOVE] conditions/targets/opaque EZL
    │       ├── command.py                            # [P2 ADAPT; P3 MOVE] commands/opaque arguments
    │       └── <required supporting modules>         # [P2 ADAPT; P3 MOVE] traced imports; minimal support
    ├── merging/                                      # [P4 NEW] policy and build orchestration
    │   ├── changes.py                                # [P4 NEW] additions/changes/removals/results
    │   ├── rules/                                    # [P4 NEW] format-specific policy and registration
    │   │   ├── bnd4.py                               # [P4 MOVE] inner-file comparison and recursion
    │   │   ├── fmg.py                                # [P4 MOVE] text-entry changes and clashes
    │   │   ├── param.py                              # [P4 MOVE] four-byte merge policy
    │   │   └── esd.py                                # [P5 NEW] supported dispatcher merge/ID mapping
    │   ├── merger.py                                 # [P4 CONSOLIDATE] resolved layers/dispatch/clashes
    │   ├── build.py                                  # [P4 CONSOLIDATE] stage/validate/activate/recover
    │   ├── record.py                                 # [P4 NEW] input hashes/version/staleness records
    │   └── choices.py                                # [P4 NEW] defaults/decisions; later UI deferred
    ├── mods/                                         # [P0 KEEP; P1–P6 REFACTOR] profile/install/setup
    │   ├── order.py                                  # [P3 NEW; P6 EXTEND; P7 EDIT] me3 order/reference edits
    │   ├── profile.py                                # [P0 KEEP; P3 EDIT; P7 EDIT] order; coordinated rename edits
    │   ├── manage.py                                 # [P0 KEEP; P6 SPLIT] retain TOML editing until replaced
    │   ├── install.py                                # [P6 SPLIT/EDIT] installs; named DLL folders (Section 8)
    │   ├── setup.py                                  # [P6 NEW] Pydantic declarative setup model
    │   ├── patches.py                                # [P6 NEW] tagged, required setup operations
    │   ├── downloads.py                              # [P6 NEW IF NEEDED] download storage/lifecycle
    │   ├── profile_settings.py                       # [P0 KEEP; P6 EDIT] explicit roundtable.json migration
    │   ├── configs.py                                # [P0 KEEP] existing config operations
    │   ├── overview.py                               # [P0 KEEP] mod overview
    │   ├── item_names.py                              # [P0 KEEP] existing item names
    │   ├── service.py                                # [P0 KEEP; P6 OPTIONAL SPLIT] orchestration facade
    │   ├── history.py                                # [P0 KEEP; P6 OPTIONAL MOVE] existing history
    │   └── undo.py                                   # [P0 KEEP; P6 OPTIONAL MOVE] existing undo
    ├── saves/                                        # [P0 KEEP; P3 IMPORT MIGRATION] existing save utilities
    │   ├── regulation.py                             # [P3 EDIT] shared regulation implementation
    │   └── <existing save modules>                   # [P0 KEEP] no blanket save rewrite
    ├── system/                                       # [P0 KEEP; P3 TARGETED EDIT] platform integrations
    │   ├── common.py                                 # [P0 KEEP; P3 TARGETED SPLIT] retain unmigrated helpers
    │   ├── processes.py                              # [P0 KEEP] special cleanup; psutil deferred
    │   ├── me3_info.py                               # [P3 EDIT] version/ordering capability detection
    │   ├── trash.py                                  # [P0 KEEP; P6 OPTIONAL MOVE] OS trash and exact restore
    │   ├── session.py                                # [P0 KEEP] session behavior
    │   └── logging.py                                # [P0 KEEP] logging; Activity is separate
    ├── safety/                                       # [P6 OPTIONAL EXTRACT] only when touched/justified
    │   ├── change.py                                 # [P6 OPTIONAL NEW] shared undoable change lifecycle
    │   ├── records.py                                # [P6 OPTIONAL NEW] persisted record validation
    │   ├── history.py                                # [P6 OPTIONAL MOVE] existing history semantics
    │   ├── undo.py                                   # [P6 OPTIONAL MOVE] existing undo semantics
    │   └── trash.py                                  # [P6 OPTIONAL MOVE] retain OS trash semantics
    ├── findings/                                     # [P6 OPTIONAL EXTRACT] preserve existing diagnostics first
    │   ├── finding.py                                # [P6 OPTIONAL NEW] common result shape
    │   ├── mods.py                                   # [P6 OPTIONAL SPLIT] mod/build capability findings
    │   └── saves.py                                  # [P6 OPTIONAL SPLIT] existing save findings
    ├── app/                                          # [P6 OPTIONAL EXTRACT] Qt-free operations when touched
    │   ├── play.py                                   # [P6 OPTIONAL SPLIT] launch workflow
    │   ├── mods.py                                   # [P6 OPTIONAL SPLIT] mod operations
    │   ├── saves.py                                  # [P6 OPTIONAL SPLIT] save operations
    │   ├── coop.py                                   # [P6 OPTIONAL SPLIT] existing co-op integration
    │   └── check.py                                  # [P6 OPTIONAL SPLIT] check orchestration
    ├── ui/                                           # [P0 KEEP] presentation; incremental extraction deferred
    │   ├── window.py                                 # [P0 KEEP] existing pages/window
    │   └── <existing dialogs/widgets/UI modules>     # [P0 KEEP] no wholesale page rewrite
    └── data/                                         # [P0 KEEP; P3/P6 MIGRATE] bundled configs/resources
        ├── games/                                    # [P3 NEW] versioned capabilities and archive config
        │   ├── eldenring.json                        # [P3 MIGRATE] existing archive/config information
        │   └── <additional game configs>             # [P3 IF EXISTING; OTHERWISE DEFER] verified facts only
        ├── setups/                                   # [P6 NEW] shipped declarative setups
        │   └── overhaul.toml                         # [P6 NEW] replaces supported legacy overhaul recipe
        ├── schemas/                                  # [P3 NEW; P6 EXTEND] generated config schemas
        └── known_item_ids.txt                        # [P0 KEEP] existing data
```

**Intermediate paths:** Phase 1 uses `mods/formats.py` as the shared BND4 implementation and retains `mods/paramfile.py` for PARAM/regulation code. Phase 2 adds `mods/formats_esd/`. Phase 3 migrates them to `formats/` and deletes old paths once callers move. Optional Phase 6 safety/app moves are alternatives to their existing locations, not permission to keep two implementations.

TPF, Paramdex, profile sharing, new conflict-choice UI and broad new-game implementations are intentionally absent from the Phase 0–6 committed tree. They remain follow-on scope rather than receiving misleading Phase 6 completion tags.

## 4. CORE ARCHITECTURAL & FORMAT SPECIFICATIONS

### 4.1 Format boundaries and unchanged detection

Keep existing `struct` implementations. Do not port them wholesale to constrata or another binary DSL. A minimal common interface MAY expose parsing, part enumeration and writing; do not require every format to inherit an elaborate Document abstraction. Format-specific comparisons may expose facts; interpretation and selection live in merge rules.

Detect changes at the appropriate part level. Byte-identical writing is valuable existing evidence, not a prerequisite for every future writer. Preserve original bytes when there are no applied changes. Claims of byte-exactness apply to the tested corpus only. Regulation encryption uses a random IV; compare the decrypted/decompressed binder and table contents rather than requiring unchanged encrypted bytes after rewriting.

### 4.2 DCX and native compression

Phase 0 variants are **payload level/header level 4/4, 4/6 and 6/6**. They are experimental configurations, not automatically supported runtime modes. Soulstruct refusing header level 4 demonstrates a recognition limitation, not game rejection. Native/reference headers using 6/9 do not prove a relabeled level-4 payload works in game.

Phase 3 MUST enforce layouts actually accepted in Phase 0 for each supported writer configuration. Keep payload compression choice distinct from wrapper layout. A level-4/level-6 speed comparison is not an equal-settings writer benchmark.

`game/oodle.py` centralizes native-library discovery, safe signatures, compression/decompression calls and platform capability reporting. Use the installed game's Oodle library; do not redistribute Soulstruct's bundled DLL. Existing Windows native functionality remains supported; Linux functionality is not presumed.

If DFLT works for tested KRAK file types, implement the corresponding compression fallback behind the interface. Otherwise emit a capability finding for affected builds. Linux KRAK **input decompression** is a separate prerequisite; a DFLT output encoder does not solve it. pyooz failed on known-good inputs in the current setup; its cause is unresolved.

### 4.3 BND4 and FMG

BND4 is the binder/container layer holding named/identified entries with flags and contents. DCX compression is a separate wrapper. Consolidation MUST support both the general archive paths and the regulation binder's fixed entry-header size 36, Unicode names and format 0x74.

Preserve tested entry ordering, names, IDs, flags, contents, alignment and hash-table behavior. Existing entries retain original order; additions have an explicit deterministic mod/entry ordering. Preserve duplicate/case-collision information rather than silently discarding entries in lookup maps.

FMG change detection is by text ID and value; report overlapping different edits. Preserve the existing writer's tested no-op behavior and metadata. Missing text entries follow an explicit rule, not an undocumented deletion assumption.

### 4.4 PARAM and regulation

Retain raw row bytes, ordering, names, metadata and duplicate IDs. Row identity includes ID plus duplicate occurrence where appropriate. Verification MUST NOT collapse rows into an ID-keyed dictionary.

Current merge granularity is **four-byte chunks**, not genuine fields. Separate fields within one chunk may conflict; report/document this limitation. Preserve existing behavior of retaining absent rows and skipping incompatible row sizes until a separately specified change is validated. Mod-vs-current-vanilla differences from older versions can include vanilla drift; header/version labels are evidence to investigate, not an automatic trusted baseline.

The regulation's zstd frame MUST use a 64 KB window (`window_log` 16) without the content-size field: zstd's default frame crashes Elden Ring 1.17.1 at start even with unchanged content, and so does a 64 MB window with 64 KB blocks (evidence ledger E-011). Phase 1 MUST NOT change this.

Soulstruct's evaluated parameter writer lost 26 duplicate-ID rows in RandomAppearParam and altered NetworkParam rows. Do not use it as the regulation writer or sole duplicate-row oracle. The existing output's 194-table match to Assets.exe was reference agreement, not independently derived intended semantics.

### 4.5 ESD adaptation and safe merge envelope

Source: Soulstruct 2.6.0 at **`12b69189a2ccebbc623a1b6565be89a18d6c9958`**, focused `base/ezstate/esd/{core,state,condition,command}.py` plus traced required support. The original core imports compiler/parser/support modules; four files and two unchanged shims are not standalone. Remove/adapt unused compilation/decompilation functionality; do not vendor the full package or native executables.

Use constrata for binary plumbing and the adapted ESD implementation for format knowledge. Configure version 3 and correct ER binary sizes. Conditions retain ordered lists, structured next-state targets and opaque EZL; commands retain opaque argument bytes. Reader and writer offsets may differ while preserving structure.

Phase 2 validation compares machines, state IDs, condition order, nested conditions, targets, commands and opaque bytecode. Identical-condition sharing/padding changes alone are not defects. Game loading alone is insufficient; behavior must be observed.

Phase 5 supports the dispatcher extension pattern: distinct added machines/states where safe, append-only new dispatcher conditions with deterministic order, and renumbering colliding **new state IDs** through supported structured references. Never renumber machine IDs or blindly patch opaque bytecode. Unsupported existing-state command edits, differing machine collisions, unrecognized bytecode references and option-number collisions are clashes. Identical unchanged machines may coexist without being mislabeled conflicts.

Inspect only the bytecode subset needed to establish supported option-number comparisons. If reference safety cannot be established, report a clash. Preserve opaque bytes from their sources. Compare against Assets.exe under a documented state-ID mapping; exact numeric IDs need not match.

### 4.6 Game archives, caching and me3 order

BHD5/BDT access retains cached RSA-decrypted indexes and existing AES range handling. cryptography parses PEM keys; `pow(ciphertext, exponent, modulus)` performs RSA math. The previously reported decrypt time is not proof of a bug; retain caching and measure before optimizing.

**me3 ordering is authoritative.** Port `sort_dependencies` from commit **`9b1e080bcf691608021e7bd8a4447198a2dcb94c`**, `crates/mod-protocol/src/dependency.rs`; separately apply packages/native filtering/order as in `crates/cli/src/db/profile.rs`. Preserve insertion/iteration details, dependency runs, run-splice placement, required missing dependency errors, optional absent dependency behavior and cycle errors. Credit the applicable MIT/Apache upstream license choice/notices.

The existing repeated-move `effective_order` is different. Reported fuzz results: 475 differing orders in 2,000 acyclic profiles, seed 1, against a Python port. Minimal reported input A B C D with D after A gives port order A D B C versus launcher A B C D. Both satisfy constraints but select different later-wins providers. This is a correctness fix and may intentionally change output.

Port upstream tests and independently compare with a pinned Rust harness. The old-vs-new fuzz script is diagnostic; permanent assertions use me3-compatible expected results. Version semantics changed in v0.8.0; record the actual me3 version and ordering-model revision. Unknown/unverified semantics yield a finding rather than an authoritative winner prediction. Do not assume every version after 0.8.0 is identical without evidence.

### 4.7 Merge/build/record contract

- Normalize game-relative lookup keys consistently, including slash and case handling; retain original names and detect ambiguous collisions.
- Apply enabled layers in resolved me3 package order. Native dependency ordering remains separate.
- Three-way comparison uses original game content and each mod's contribution; conflict defaults are explicit and recorded. Generic two-way dict merging is not a substitute.
- “Missing inner file = deliberately removed” is unvalidated for the 58 animation clips. Establish the target baseline or require a recorded trust choice with a finding; do not infer intent from Assets.exe agreement.
- Rebuild from originals and current inputs, not the previous merged output.
- Stage in a distinct location, verify supported formats/content, check the game is closed before activation, activate through a recoverable operation, and record the active build consistently. Preserve the previous valid build on failure. Define interruption/recovery behavior; avoid overclaiming multi-file atomicity.
- Record hashes of **contributing game archives and indexes, vanilla regulation, contributing mod files**, merger version, game/config schema/version, decisions, compression capability selection, me3 version and ordering-model revision. Input or semantic changes invalidate affected builds.
- Cache hashing with an explicit invalidation policy; size/mtime fast checks are not cryptographic identity. Do not claim constant-time launch checks and unconditional detection of arbitrary metadata-preserving edits simultaneously.
- Record all clashes/default winners now; editable per-part UI is deferred. Budget staged output plus retained prior build and clean obsolete staging after success/recovery.

### 4.8 Evidence ledger

`docs/evidence-ledger.md` is the record; this is its summary as of 2026-10-01. Accepted on Windows (Elden Ring 1.17.1,
me3 0.13.0): launcher-written menu text and player animations in the KRAK layouts 6/6, 4/4 and 4/6 and in DFLT, and
launcher-written parameters once the regulation's zstd frame was fixed (E-005, E-006, E-011). Each in-game test shows
that the game loaded the file and, for text and parameters, that a marker change took effect; for animations it shows
only that the archive loaded (no visible change was tested). Withdrawn: the earlier claim that a played Revive build
was launcher-written; it was Revive's tool's output (E-001). Independent reading (E-002) still stands with its limits:
Soulstruct uses Oodle too; text matched the reference in 15 languages but the 166 map changes and 27 new strings were
checked in English only; PARAM matches all 194 reference tables but the intended output was not independently
derived; the removal rule shares the reference tool's unvalidated assumption. ESD structural rewrite was checked once.
TPF byte-exactness was shown on one 56-texture file only and is deferred. Open: a visible animation change, the intent
behind the 58 omitted animations (E-007), me3 ordering parity (E-010, Phase 3), every Deck check, and Linux.

## 5. PHASED AGENT ACTION PLAN (CHRONOLOGICAL CHECKLIST)

### Phase 0 — Establish acceptance evidence

**Goal:** create a calibrated baseline and resolve platform/format uncertainties. This work may run alongside Phase 1; unperformed human/game checks remain pending.

- [x] Inventory the checkout, current workflows, callers, supported capabilities and existing verification artifacts. *(Ledger section 1.)*
- [x] Establish `scripts/verify/` and isolated output paths; make input paths configurable. *(`--game`/`--out` or `local.toml`; outputs refused inside the game, profiles, saves or repo.)*
- [x] Calibrate readers against known-good vanilla/reference data before interpreting failures. *(E-009; pyooz not calibrated.)*
- [x] Verify PARAM checks retain ordered duplicate-ID occurrences and metadata. *(E-008.)*
- [ ] Enumerate actual animation removals/additions; investigate the 58 omissions against the mod's target baseline and changelog; record unknowns. *(Enumerated and recorded as unknown, E-007; the intent investigation is open and moved to Phase 4 by the owner's decision.)*
- [x] Test DCX 4/4, 4/6 and 6/6 on isolated outputs; record payload/header/file-type/game-version/platform separately. *(Windows, E-005; Deck open under the item below.)*
- [x] Test DFLT replacement on representative KRAK file types; record output encoding acceptance separately from Linux decoding availability. *(Windows, menu text and player animations written by the launcher, E-006; effects only as Revive's tool's output, E-001.)*
- [ ] Use a marker FMG, an obvious regulation change and a controlled animation change to demonstrate launcher output is loaded. *(Marker text and parameter change seen in game, E-005 and E-011; the controlled animation change is open: no clip pair with an obvious difference identified yet.)*
- [ ] Record effects/animations/text/parameter acceptance on Windows and Deck; do not silently treat unavailable Deck tests as passed. *(Windows recorded; every Deck check open: no Deck available.)*
- [x] Record the ordering-model mismatch and the Rust-parity work required in Phase 3. *(E-010; parity itself is Phase 3 work and open.)*

**Deletions:** none.

**Verification/completion:** a versioned evidence ledger identifies accepted paths, failed experiments and unresolved checks. Shipping a chosen path requires its relevant acceptance evidence; every experimental variant need not pass.

**Status (2026-10-01): not complete.** Seven of ten checks are done. Open: the controlled animation change, the intent behind the 58 omitted animations (moved to Phase 4), and every Deck check. Phase 1 runs alongside, as allowed above.

### Phase 1 — Consolidate BND4

**Goal:** one archive reader/writer with no unrelated policy change.

- [ ] Inventory callers of both BND4 implementations.
- [ ] Keep `mods/formats.py` as the shared location for this phase.
- [ ] Adapt the general implementation to preserve both existing layout requirements where necessary.
- [ ] Migrate `paramfile.py` binder operations; use a thin data-model adapter only if needed.
- [ ] Preserve format metadata/order and existing archive/hash behavior.
- [ ] Remove duplicate `read_bnd4`, `write_bnd4`, `_hash_table`, `_is_prime`, `_align` and other now-unused binder-only helpers from `paramfile.py`.
- [ ] Run existing regression tests and byte-exact archive/binder round trips.
- [ ] Compare all 194 regulation tables by ordered rows, duplicate occurrences, row contents and metadata.
- [ ] Report moved callers and deleted code; keep compression/removal policy unchanged.

**Completion:** one BND4 binary implementation serves archives and regulation. The decrypted/decompressed regulation binder is tested byte-exact; encrypted-IV differences are not false failures.

### Phase 2 — Adapt ESD reading and writing

**Goal:** reuse the missing format implementation without shipping full Soulstruct.

- [ ] Add constrata ≥1.3.3 and its MIT notice; no repeated license investigation is needed.
- [ ] Vendor the exact focused Soulstruct pin into `mods/formats_esd/`.
- [ ] Trace every import; adapt required definitions and remove compiler/decompiler dependencies.
- [ ] Add ER version-3 configuration and explicit supported binary sizes.
- [ ] Preserve notices; add full provenance and dated per-file modification records.
- [ ] Keep runtime imports independent of full Soulstruct, bundled Oodle and ParamCrypt.
- [ ] Round-trip ESDs from vanilla/map-mod/overhaul/Assets.exe; assert complete relevant structure and opaque bytes.
- [ ] Test a launcher-written, otherwise unchanged menu in game; record pending checks honestly.
- [ ] Delete unused adapted functionality/imports, not required support merely to meet a line-count target.

**Completion:** ESD is integrated for reading/writing and structurally verified. It stays outside production merging until relevant in-game validation succeeds; harmless layout differences alone do not justify another writer.

### Phase 3 — Create the game and formats packages

**Goal:** clean boundaries and faithful me3 winner prediction.

- [ ] Move existing binary implementations and adapted ESD into `formats/`; move archive/cache/native backend responsibilities into `game/`.
- [ ] Introduce Pydantic GameConfig and migrate actual archive/config data to `data/games/`; publish schema where useful.
- [ ] Inventory and migrate all format callers, including save regulation utilities.
- [ ] Enforce every supported DCX writer layout against Phase 0 acceptance fixtures/results.
- [ ] Implement the tested DFLT fallback only for accepted capabilities; emit findings for unsupported compression/decompression paths.
- [ ] Centralize Oodle discovery/calls; preserve game-supplied library usage and cache behavior.
- [ ] Port me3 `sort_dependencies` into `mods/order.py`, preserving upstream iteration/run/splice semantics.
- [ ] Apply separately to native/package inputs; match filtering/ID/optional/required semantics at the profile boundary.
- [ ] Migrate conflict scans, stay-last display, merger layers and cycle checks to the same model.
- [ ] Add me3 provenance/license notices and version/ordering-model capability detection.
- [ ] Port upstream order tests and confirm parity using a pinned Rust harness; retain minimized fuzz regressions.
- [ ] Delete old repeated-move ordering, separate obsolete cycle logic, temporary old-vs-new comparator and old format/archive paths after callers migrate.
- [ ] Run Windows/Ubuntu tests, Phase 1–2 regressions and cache timing checks; verify packaged imports/resources.

**Completion:** clean packages, validated DCX capability enforcement and me3-compatible ordering for supported versions. Ordinary dependency profiles may change winners deliberately; document the correctness fix. Structural moves remain separate from that behavior change.

### Phase 4 — Consolidate the merger and build lifecycle

**Goal:** one deterministic build route using correct resolved order.

- [ ] Create `merging/` and format-specific rule modules; move existing BND4/FMG/PARAM policy without silently upgrading granularity.
- [ ] Implement one dispatcher and explicit conflict/default-choice recording.
- [ ] Ensure normalized lookup detects ambiguous collisions and preserves source naming/order.
- [ ] Apply validated removal policy or recorded trust choices; do not conceal the 58-clip uncertainty.
- [ ] Centralize staging, validation, activation, recovery, previous-build retention and undo.
- [ ] Refuse activation while the game runs; test failed/interrupted-build recovery with temporary fixtures.
- [ ] Implement build records with game archive/index/regulation hashes, mod inputs, configs, decisions, merger version and me3 version/ordering revision.
- [ ] Make play-time staleness checks consume those records with a documented hash-cache invalidation policy.
- [ ] Return original bytes for unchanged content; define deterministic entry/layer ordering and disk budget.
- [ ] Run representative ordinary-mod conflict corpus checks; record findings without fetching unspecified paid/private mods.
- [ ] Test nonconflicting preservation, explicit clash outcomes and removal/rebuild equivalence to remaining inputs.
- [ ] Validate the full supported overhaul build in game on applicable platforms.
- [ ] Delete replaced `mods/merge.py`, `filemerge.py` and `param_merge.py` implementations only after all their responsibilities/callers migrate.

**Completion:** the new merger owns accepted builds and staleness. Legacy setup/adaptor responsibilities may remain until Phase 6. Ordering parity and output-path acceptance are prerequisites to production activation.

### Phase 5 — Add ESD merge rules

**Goal:** native grace-menu merging within a documented safe envelope.

- [ ] Implement dispatcher extension merging with deterministic condition order.
- [ ] Allocate/remap supported new state IDs; preserve machine IDs and opaque bytes.
- [ ] Detect unsafe references, unsupported existing-state edits, differing machine collisions and option-number collisions.
- [ ] Parse only the required bytecode subset for supported option checks; ambiguous cases become clashes.
- [ ] Generate a dry-run structural diff and record merge decisions.
- [ ] Compare structure/behavior with Assets.exe under the recorded state-ID mapping.
- [ ] Validate unmerged rewrite and merged menu behavior separately; exercise both mods' options/actions in game.
- [ ] Patch adapted code only for demonstrated structural/behavior failures; document changes and rerun checks.
- [ ] Migrate accepted grace-menu production to the native rule; remove replaced menu-specific paths.

**Completion:** supported ESD merges work in game; unsupported combinations produce explicit findings. Broader external-tool calls remain only for responsibilities not yet migrated.

### Phase 6 — Migrate setup mods and retire legacy engines

**Goal:** declarative setup configs plus one native build path, with undoable profile migration.

- [ ] Define Pydantic SetupConfig and discriminated patches required by actual setups: `copy_files`, `keep_config`, `add_text`, `merge_file`; narrowly structured script operations only if demonstrated necessary.
- [ ] Add TOML setups under `data/setups/`, a local override folder and generated schemas with a short guide.
- [ ] Introduce explicit versioned roundtable.json migration; preserve supported unknown keys and user-owned profile content.
- [ ] Migrate the overhaul's recipe/adaptor behavior into setup config plus ordinary mod layers.
- [ ] Split install/extraction responsibilities from `manage.py` as needed; retain existing TOML editing until a separately gated replacement is adopted.
- [ ] Offer named native folders for new loose DLL installs and archives containing only a DLL with its associated config; implement the recorded install/undo behavior in Section 8.2.
- [ ] Add download storage only where the workflow needs it; preserve current install/uninstall behavior.
- [ ] Move stay-last bookkeeping into `mods/order.py` while preserving authoritative me3 order and user exceptions.
- [ ] Verify every legacy recipe/adaptor responsibility has a replacement before deletion.
- [ ] Compare the complete observed merged-file set and grace menu against accepted reference behavior; do not hard-code an obsolete file count as the entire contract.
- [ ] Verify owned-entry-only profile changes, comment preservation, backup/undo and restoration end to end.
- [ ] Validate Windows/Deck supported builds and co-op/menu/save workflows affected by migration.
- [ ] Delete replaced `mods/engine.py`, recipes, backends, stay-last module, compatibility outputs and remaining replaced Assets.exe calls.
- [ ] Remove dead imports, settings, tests and packaging entries belonging only to retired paths.
- [ ] Optionally extract Qt-free app/safety/findings services when touched; preserve OS trash and headless behavior. Do not make a wholesale UI/service rewrite a gate.

**Completion:** migrated setups no longer run external mod programs; one build route covers accepted behavior; migration is undoable; no retired implementation remains reachable.

### 5.1 Agent execution/report contract

For each phase: identify current state → implement bounded work → migrate callers → run relevant checks → retire replaced code → report evidence. Continue independent authorized work while human/platform verification is pending, but do not activate unaccepted behavior or report pending checks as complete. Prepare small reviewable commits; do not start speculative follow-on features to satisfy the blueprint.

Each report must include: current commit/branch; exact additions and deletions; caller migration inventory; relevant test commands/results; real-data corpus identities without private paths; game/platform acceptance; unresolved findings; build/undo implications; next authorized step.

## 6. DEFERRED WORK AND OPEN ACCEPTANCE ITEMS

The following remain visible but are not implicit Phase 0–6 implementation requirements:

- tomlkit: no-op/profile edit/comment/remove-restore corpus checks before replacing text surgery; the replacement is not “1,500 lines” by assumption.
- psutil: ordinary enumeration only; Wine/Proton matching and elevation/special dead-process handling remain project behavior.
- Hypothesis: meaningful generated invariants, not “every change survives” under conflicts.
- me3 schema-generated models: source/version confirmation first; schema does not replace filesystem checks or guarantee me3-equivalent validation.
- TPF source adaptation: same provenance discipline; one-file byte-exactness is initial evidence only.
- Paramdex: license/coverage/version handling first; names do not supply a field merge engine automatically.
- New games: DS3 loader support confirmed; validate format versions/compression/regulation independently. Sekiro loader support remains to verify. Existing Nightreign features are preserved without claiming unknown regulation capabilities.
- Linux: test input decoding separately from output compression. Failed pyooz calibration does not establish either output corruption or its exact failure cause.
- GUI page extraction, profile sharing, editable per-part choices, private trash design and parallel compression are separate features/improvements.

## 7. SOURCE AND PROVENANCE ANCHORS

- Project: https://github.com/Carlomos7/roundtable-souls
- Initial inspected project revision: `1d774a05a9c566f29546b0c722909b84df99bfaf`; agents must inspect the current checkout rather than assume it remains unchanged.
- Soulstruct ESD pin: https://github.com/Grimrukh/soulstruct/tree/12b69189a2ccebbc623a1b6565be89a18d6c9958/src/soulstruct/base/ezstate/esd
- Soulstruct metadata: https://github.com/Grimrukh/soulstruct/blob/12b69189a2ccebbc623a1b6565be89a18d6c9958/pyproject.toml
- constrata: https://github.com/Grimrukh/constrata
- me3 order pin: https://github.com/garyttierney/me3/blob/9b1e080bcf691608021e7bd8a4447198a2dcb94c/crates/mod-protocol/src/dependency.rs
- me3 profile application: https://github.com/garyttierney/me3/blob/9b1e080bcf691608021e7bd8a4447198a2dcb94c/crates/cli/src/db/profile.rs
- me3 v0.8.0: https://github.com/garyttierney/me3/releases/tag/v0.8.0 (ordering change PR #484 / 0812fd4; DS3 support dde3047).
- Baseline local reports: independent-output-check-report(1).md and prior phase document. Verification scripts/corpus evidence must be attached or referenced in-repo as implementation proceeds; this specification is not a substitute for running them.


## 8. MODS-PAGE ADDITIONS AND FOLLOW-ON ACTION PLAN

These are intentional product changes, not silent behavior changes within mechanical moves. The independent wording change may ship whenever convenient; named DLL installation belongs to Phase 6. Rename is Phase 7 follow-on work after profile-writing consolidation. Phase 8 page extraction is optional and can accompany rename, but is not a prerequisite. Section 3 remains the core Phase 0–6 blueprint; the extensions below explicitly annotate later paths.

### 8.1 Independent UI wording — “Attach” replaces “Tie”

**Goal:** name the existing loose configuration-file association action clearly. No implementation-path or association semantics change.

- [ ] Rename the visible action/button from “Tie” to “Attach”; update tooltips, accessibility labels, confirmation/status text, newly generated Activity messages and relevant docs.
- [ ] Search UI, documentation and Activity-message producers case-insensitively for the old term; inspect matches rather than replacing unrelated words/substrings.
- [ ] Preserve existing persisted Activity/history records and undo compatibility. Do not rewrite historical records or rename internal event identifiers solely for wording.
- [ ] Verify newly generated Activity entries describe attachment correctly and existing association/undo behavior is unchanged.

**Deletions:** obsolete user-facing wording only. Internal symbol renames are unnecessary unless they improve clarity without serialization consequences.

**Completion:** users see “Attach”; no new symlink behavior or modified config-file handling is introduced.

### 8.2 Phase 6 addition — Install new loose DLLs into named folders

**Goal:** organize new native installs without migrating existing loose DLLs.

- [ ] When installing a bare DLL, or an archive containing only one native DLL and its associated config/support files, offer a folder-name field defaulted from the DLL basename. Ambiguous/multi-DLL or package-containing archives retain existing detection/selection behavior.
- [ ] Validate the proposed single folder name: prevent traversal, separators, invalid platform names, ambiguous case collisions and unintended overwrites. Preserve established collision/overwrite choices or request a new name.
- [ ] Install under the resolved native root as `natives/<name>/<dll>` (respect an existing custom native root rather than assuming every profile uses a literal natives directory).
- [ ] Keep associated config/support files with the DLL and write the native profile path to the installed DLL. Folder naming alone must not silently change the native ID or dependency references.
- [ ] Record installed files, folder ownership and profile edits as one logical undoable installation change. Avoid creating an empty folder on cancellation/failure; undo removes newly owned artifacts and the entry while restoring pre-existing state.
- [ ] Preserve comments, entry placement/options and effective load order. Do not move existing loose DLLs automatically.
- [ ] Test bare-DLL install, DLL-plus-config archive, custom native root, naming collision, cancellation/failure and undo using fake files/temp profiles.

**Deletions:** replace only the eligible new-install loose-placement branch; retain legacy reading/support for existing loose natives.

**Completion:** eligible new installs use a user-visible named folder; their profile paths and undo records are correct; unrelated installs and existing loose DLLs are unchanged. “Move existing loose DLL into folder” remains separate optional Phase 7 work.

### 8.3 Phase 7 follow-on — Rename an installed mod folder and ID

**Prerequisite:** profile edits are consolidated behind one writer in `mods/profile.py`. tomlkit is optional; retained tested surgery behind that interface is acceptable. Schema-generated entry models are optional and do not block the feature.

**Goal:** one coordinated, undoable operation to rename a package/native identity and owned folder. Multiple profile/metadata writes and a filesystem rename are not a single filesystem-atomic operation; use preflight, snapshots, staged writes, a journal and rollback/recovery to provide a consistent logical transaction.

Preflight and ownership:

- [ ] Resolve the selected entry, its effective ID, old/new paths, owned folder and all affected references. Derive implicit IDs from me3 semantics; making an implicit ID explicit may be necessary to preserve or intentionally rename identity.
- [ ] Refuse while the game is running; recheck before commit. Enforce ID uniqueness in the applicable me3 namespace and reject ambiguous case-insensitive matches. Reference matching must account for the requested case-insensitive lookup without silently changing me3's actual identifier semantics.
- [ ] Reject invalid paths, collisions, unsupported/shared-folder ownership and unresolved references before mutation. Do not rename the common natives root, package root or a folder shared by unrelated entries. Case-only rename needs platform-specific handling and tests.
- [ ] Inventory profile `load_after`/`load_before`, both dictionary/string forms supported by the writer, package/native namespaces, roundtable.json kept-after settings and ID-keyed options/choices, relevant records and restore history. Unknown reference-bearing metadata that cannot safely be transformed prevents rename with an actionable finding.
- [ ] For a restored mod, update only applicable active tracking/location references; preserve historical records needed to undo the original trash/restore operation. An unresolved live trashed item requires a separate supported operation, not an implicit filesystem rename.

Transaction:

- [ ] Snapshot exact profile/roundtable.json bytes and applicable tracking/build-state metadata; record old/new paths and IDs. Prepare all edits before moving the folder.
- [ ] Update the selected profile entry ID/path and every applicable cross-entry dependency reference. `mods/order.py` may provide a pure dependency-reference transform; validation/order must still use the authoritative me3 model.
- [ ] Update kept-after settings and per-mod metadata keyed by the old identity, preserving unknown supported keys and comments.
- [ ] Mark the merged build stale/invalidate its active association. Preserve original source hashes and build provenance; never rewrite a historical build record to pretend it was built from the new identity.
- [ ] Commit the folder move and prepared file writes using a journaled sequence with rollback on any failure and defined restart recovery. Publish one Activity/undo action only with a consistent transaction state.
- [ ] Undo restores exact original metadata bytes and folder location subject to conflict checks; do not overwrite files or user edits that occurred afterward silently.

Verification:

- [ ] Test package and native rename, implicit/explicit IDs, dependency forms, kept-after/options/choices, build staleness, restore tracking, collisions, shared folders, case-only names and game-running refusal.
- [ ] Assert rename then undo restores profile, roundtable.json, folder and applicable tracking state.
- [ ] Inject failure after individual commit steps and test rollback/recovery; no dangling required dependencies or stranded rename state may remain.
- [ ] Validate dependency order/missing IDs against supported me3 behavior; validate against the authoritative schema if adopted. Schema validation alone does not prove references resolve.
- [ ] Verify next Play rebuilds stale output, and unaffected resolved dependencies retain their meaning.

**Deletions:** remove any superseded ad-hoc rename/reference-update path once callers migrate. Do not delete history/trash support.

**Completion:** the operation is preflighted, recoverable and undoable across every supported side effect. Unsupported ownership/reference cases fail before mutation rather than applying a partial rename.

### 8.4 Directory blueprint extensions

```text
mods/install.py       # [P6] named native installation; existing loose installs remain supported
mods/profile.py       # [P7] coordinated profile edits through one established writer
mods/order.py         # [P7] pure reference transform + authoritative dependency validation
mods/entries.py       # [P7 IF ADOPTED] authoritative-schema models; optional
safety/               # [P7] rename snapshots/journal/undo; reuse existing mechanisms where possible
merging/record.py     # [P7 EDIT] active-build invalidation; preserve historical provenance
ui/window.py          # [INDEPENDENT/P6/P7] surface Attach/install naming/rename in existing page
ui/pages/mods.py      # [P8 OPTIONAL] extract mods page when touched; no duplicate UI path
```

A Phase 7 action may use existing backend modules until a coherent extraction is warranted. The Qt-free backend rule still applies. Do not introduce a private trash design, schema dependency or wholesale UI rewrite merely to deliver rename.
