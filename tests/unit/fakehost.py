"""A fake machine for Play-session tests: a clock, Steam, the process list, me3 and the game, with nothing real
started. Only the edges are replaced (time, the process list, Steam's sign-in flag and executable, starting a
program, and the PowerShell calls for leftover game processes); everything between them is the launcher's own code.

    host = FakeHost(monkeypatch, steam_running=False, sign_in_after=10, me3="attached", game_starts_after=8)

Time only moves when the code sleeps, so a two-minute Steam timeout takes no time. host.events records what happened
and when: ("steam started", t), ("me3", t, command), ("game up", t), ("game down", t), ("me3 exit", t, code),
("shells killed", t, pids).
"""

from __future__ import annotations

import subprocess
import time as _real_time
from dataclasses import dataclass, field

from roundtable_souls.platform import proc, processes, session, steam
from roundtable_souls.services import play

GAME_KB = 2_000_000  # a running game uses gigabytes; platform.paths.REAL_GAME_MIN_KB tells it from a dead shell
STEAM_EXE = r"C:\Program Files (x86)\Steam\steam.exe"


class FakeClock:
    def __init__(self, host: FakeHost):
        self.now = 1_000_000.0
        self.host = host

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(float(seconds), 0.0)
        self.host.advance()


class FakeTime:
    """Stands in for the time module inside one module: time() and sleep() are the fake clock's, the rest is real."""

    def __init__(self, clock: FakeClock):
        self._clock = clock

    def time(self) -> float:
        return self._clock.time()

    def monotonic(self) -> float:
        return self._clock.time()

    def sleep(self, seconds: float) -> None:
        self._clock.sleep(seconds)

    def __getattr__(self, name):
        return getattr(_real_time, name)


@dataclass
class FakeHost:
    monkeypatch: object
    steam_installed: bool = True
    steam_running: bool = False
    signed_in: bool = False
    steam_starts_after: float = 6  # seconds after it is started until its process exists
    sign_in_after: float | None = 10  # seconds after it starts until it is signed in (None: never)
    me3: str = "attached"  # attached (stays until the game closes), handoff (returns at once), fails (no game)
    me3_exit_code: int = 0
    game_starts_after: float | None = 8  # after me3 starts (None: never)
    game_runs_for: float = 60
    interrupt_after: float | None = None  # Ctrl+C while waiting, this long after me3 starts
    dead_shells: list[int] = field(default_factory=list)
    shells_survive_kill: bool = False
    events: list[tuple] = field(default_factory=list)
    me3_output: str = "me3: launching the game\n"

    def __post_init__(self):
        self.clock = FakeClock(self)
        self.steam_up_at = self.clock.now if self.steam_running else None
        self.signed_in_at = self.clock.now if self.signed_in else None
        self.game_up_at: float | None = None
        self.game_down_at: float | None = None
        self.me3_started_at: float | None = None
        self.me3_proc: FakeMe3 | None = None
        mp = self.monkeypatch
        # session's own reference to the time module only, never the module itself (pytest and logging use it)
        mp.setattr(session, "time", FakeTime(self.clock))  # type: ignore[attr-defined]
        mp.setattr(play, "time", FakeTime(self.clock))  # type: ignore[attr-defined]
        mp.setattr(proc, "processes", self._processes)  # type: ignore[attr-defined]
        mp.setattr(steam, "steam_logged_in", self._signed_in)  # type: ignore[attr-defined]
        mp.setattr(steam, "steam_launch_command", lambda: [STEAM_EXE] if self.steam_installed else None)  # type: ignore[attr-defined]
        mp.setattr(session.subprocess, "Popen", self._popen)  # type: ignore[attr-defined]
        mp.setattr(processes, "dead_shells", lambda exe_name: list(self.dead_shells))  # type: ignore[attr-defined]
        mp.setattr(processes, "kill_elevated", self._kill_elevated)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ what the code sees
    def _processes(self, name: str) -> list[tuple[int, int]]:
        self.advance()
        name = name.lower()
        if name == steam.steam_process_name().lower():
            return [(100, 150_000)] if self._steam_up() else []
        if self._game_up():
            return [(200, GAME_KB)] + [(pid, 0) for pid in self.dead_shells]
        return [(pid, 0) for pid in self.dead_shells]

    def _steam_up(self) -> bool:
        return self.steam_up_at is not None and self.clock.now >= self.steam_up_at

    def _signed_in(self) -> bool:
        self.advance()
        return self._steam_up() and self.signed_in_at is not None and self.clock.now >= self.signed_in_at

    def _game_up(self) -> bool:
        if self.game_up_at is None or self.clock.now < self.game_up_at:
            return False
        return self.game_down_at is None or self.clock.now < self.game_down_at

    def _popen(self, cmd, stdout=None, stderr=None, creationflags=0, **kwargs):
        cmd = [str(c) for c in cmd]
        assert creationflags == proc.NO_WINDOW, "a child console would pop up"
        if cmd[0] == STEAM_EXE:
            self.events.append(("steam started", self.clock.now))
            self.steam_up_at = self.clock.now + self.steam_starts_after
            if self.sign_in_after is not None:
                self.signed_in_at = self.steam_up_at + self.sign_in_after
            return FakeProcess(0)
        self.events.append(("me3", self.clock.now, cmd))
        if stdout is not None and hasattr(stdout, "write"):
            stdout.write(self.me3_output)
        self.me3_started_at = self.clock.now
        if self.game_starts_after is not None and self.me3 != "fails":
            self.game_up_at = self.clock.now + self.game_starts_after
            self.game_down_at = self.game_up_at + self.game_runs_for
        self.me3_proc = FakeMe3(self)
        return self.me3_proc

    def _kill_elevated(self, pids, exe_name):
        self.events.append(("shells killed", self.clock.now, list(pids)))
        if not self.shells_survive_kill:
            self.dead_shells = [p for p in self.dead_shells if p not in pids]
        return [p for p in self.dead_shells if p in pids]

    # ------------------------------------------------------------------ the clock moving on
    def advance(self) -> None:
        now = self.clock.now
        for name, at in (("game up", self.game_up_at), ("game down", self.game_down_at)):
            if at is not None and now >= at and not any(e[0] == name for e in self.events):
                self.events.append((name, at))

    def happened(self) -> list[str]:
        return [e[0] for e in sorted(self.events, key=lambda e: e[1])]


class FakeProcess:
    def __init__(self, code: int):
        self.returncode = code

    def poll(self):
        return self.returncode


class FakeMe3:
    """me3 launch: 'attached' stays until the game has closed (me3 0.13), 'handoff' returns at once, 'fails' exits
    without starting the game."""

    def __init__(self, host: FakeHost):
        self.host = host
        self.returncode: int | None = None

    def poll(self):
        h = self.host
        h.advance()
        started = h.me3_started_at or 0.0
        if h.interrupt_after is not None and h.clock.now >= started + h.interrupt_after:
            raise KeyboardInterrupt
        if self.returncode is None:
            if h.me3 == "attached" and h.game_down_at is not None:
                done = h.clock.now >= h.game_down_at + 1
            elif h.me3 == "attached":
                done = h.clock.now >= started + 30
            else:  # handoff, fails
                done = h.clock.now >= started + 1
            if done:
                self.returncode = h.me3_exit_code
                h.events.append(("me3 exit", h.clock.now, self.returncode))
        return self.returncode


def setup_for(game, profile="p.me3", me3="me3.exe", exe=None, loc=None):
    """A Play setup with what job_play reads."""
    return type(
        "FakeSetup",
        (),
        {
            "profile": profile,
            "source": "x",
            "game": game,
            "problems": lambda self: [],
            "me3_path": lambda self: me3,
            "launch_exe": lambda self: exe,
            "locations": lambda self: loc,
        },
    )()


__all__ = ["FakeHost", "GAME_KB", "STEAM_EXE", "setup_for", "subprocess"]
