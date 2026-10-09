# 0006 Composed character scripts are checked with Lua 5.1 itself (lupa) before a build is used

**Status:** in use from 3.20.0.

## Decision

When an overhaul's build adds a mod's script fragment to the character's entry script (`c0000.hks`, the `hook`
step), the launcher compiles the result with Lua 5.1 before the build is swapped in, and refuses the build when it
does not compile. The message names the file, the line and which part introduced the error: the base and each
fragment are checked on their own first, then the whole, whose error line is traced back to the part it came from.
The previous build stays in place.

The compiler is the reference Lua 5.1, through [lupa](https://github.com/scoder/lupa) 2.8 (its `lua51` module). The
script is only loaded (`luaL_loadbuffer`), never run: nothing in it executes, and no Lua library is reached.

## Why a check at all

The game reads `c0000.hks` when a character loads. A composition that does not compile (a fragment cut short, two
scripts joined at the wrong place) fails silently in game: the player's character behaves as if the script were
missing, and nothing says why. The launcher can see it before the game starts.

## Candidates tested (2026-10-08)

On the real scripts: Nightreign Revive's text entry script (`payload/mod/action/script/c0000.hks`, 24,513 lines,
UTF-8 with a byte order mark), its fragments (`installer/revive.hks`, `load-convergence.hks`, `load-reforged.hks`),
an installed composed copy, the base with Revive's fragment composed, and five broken scripts (a missing `end`, a
bad token, an unclosed string, a stray parenthesis, a valid 24,516-line script with a broken tail).

| Candidate | Real scripts | Broken scripts | Time (24.5k lines) | Shipped as | Licence |
|---|---|---|---|---|---|
| lupa 2.8, `lua51` | all accepted | all five refused, each with its line | 0.02 s | wheels: Windows x64, Linux x64/arm64, macOS (CPython 3.14) | MIT (lupa and Lua) |
| lupa 2.8, `lua54` | all accepted | as `lua51` | 0.01 s | the same wheels | MIT |
| luaparser 4.2.0 (pure Python, ANTLR) | all accepted | three of five reported without a line ("syntax errors: None") | 5.5 s | pure Python | MIT |

`lua51` was chosen because HKS is Lua 5.1; `lua54` would accept syntax the game does not (`goto`, integer
division). luaparser fails the requirement that an error names its line.

## Limits

- **Havok's additions.** HKS extends Lua 5.1 (compound assignment, typed structures, and others). None of the scripts
  above uses any of them, so the check accepts every script known to be in use; a script that does use one is
  refused, naming the line, rather than accepted unread. If such a script turns up, this record is reopened: a
  pre-pass that rewrites the additions to plain Lua, or a different parser.
- The check is syntax only: a script that compiles can still misbehave in game.

## Would reopen it

A mod script that uses Havok-only syntax; lupa no longer shipping wheels for the Python the launcher uses; a
pure-Python parser that meets the same tests at a comparable speed.
