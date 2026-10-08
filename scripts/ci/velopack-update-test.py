"""Release check on a clean Windows runner: the previous published release updates itself to this build.

What users do: the installed launcher's Update now. Here, its headless form (`--update`):
  1. the newest published release older than this build installs silently (Velopack setup);
  2. its identity is pointed at a local feed served by this script and at a throwaway signing key (an override file
     in the installed copy's data folder, which releases read; nothing is rebuilt), so the real checks run: the feed's
     minisign signature and trusted comment, then the package's checksums;
  3. `--update` downloads this build's package from that feed, keeps the old version for a rollback, and hands over
     to Velopack, which installs it and restarts the launcher;
  4. this build must start, open (create) its database at the current schema and report ready before the update
     watchdog's 90 s; no rollback may happen;
  5. the copy is uninstalled.

Every wait is bounded; a step that does not finish fails the test after printing the update and watchdog logs.
It runs only on CI (GITHUB_ACTIONS): it installs with the real app ID and clears that app's data folder first.

Run from the repository root after scripts/build.py:  uv run python scripts/ci/velopack-update-test.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NoReturn

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

ROOT = Path(__file__).resolve().parents[2]
SHARE = ROOT / "dist" / "share"
PACK = "Carlomos7.RoundtableSouls"
TITLE = "Roundtable Souls"
PORT = 8797
LOCAL = Path(os.environ.get("LOCALAPPDATA", ""))
DATA = LOCAL / "RoundtableSouls"  # the app's data folder (its identity's data_dir_name)
WORK = Path(os.environ.get("RUNNER_TEMP", ROOT / "build")) / "update-test"
INSTALL = WORK / "install"
STARTED = time.time()


def say(message: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {message}", flush=True)


def tail(path: Path, lines: int = 30) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    print(f"  --- {path} (last {lines} lines)", flush=True)
    for line in text[-lines:]:
        print(f"    {line}", flush=True)


def diagnostics() -> None:
    say("diagnostics")
    print(f"  installed version: {installed()}", flush=True)
    for folder in (DATA / "updates" / "state", DATA / "logs" / "jobs"):
        for p in sorted(folder.glob("*"), key=lambda p: p.stat().st_mtime)[-6:] if folder.is_dir() else []:
            if p.is_file() and p.stat().st_mtime >= STARTED:
                tail(p)
    for p in (INSTALL / "velopack.log", LOCAL / PACK / "velopack.log", DATA / "logs" / "launcher.log"):
        if p.is_file():
            tail(p, 40)


def fail(message: str) -> NoReturn:
    print(f"::error::{message}", flush=True)
    diagnostics()
    stop_launchers()
    sys.exit(1)


def wait_until(condition, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.5)
    return bool(condition())


def run_bounded(args: list, seconds: int, what: str) -> int:
    """Waits for this process only (never its children: a setup or an update starts the launcher)."""
    say(f"start: {what}")
    proc = subprocess.Popen([str(a) for a in args], env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    try:
        code = proc.wait(seconds)
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        fail(f"{what} did not finish within {seconds} s")
    say(f"end: {what} (exit code {code})")
    return code


def stop_launchers() -> None:
    script = (
        f"Get-Process | Where-Object {{ $_.Path -and $_.Path.StartsWith('{INSTALL}', 'OrdinalIgnoreCase') }} | "
        "Stop-Process -Force"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True)


def installed() -> str:
    try:
        text = (INSTALL / "current" / "sq.version").read_text(encoding="utf-8")
    except OSError:
        return "?"
    m = re.search(r"<version>([^<]+)</version>", text)
    return m.group(1) if m else "?"


def version_key(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def is_prerelease(v: str) -> bool:
    """A beta (X.Y.Z-beta.N): published to the Beta channel only, so the installed copy must be on that channel to
    see it (the Stable channel takes GitHub's /releases/latest, which never names a pre-release)."""
    return "-" in v


# ----------------------------------------------------------------------------- a throwaway signing key
class Key:
    def __init__(self):
        self.private = Ed25519PrivateKey.generate()
        self.key_id = os.urandom(8)

    def public_text(self) -> str:
        raw = self.private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return "untrusted comment: update test key\n" + base64.b64encode(b"Ed" + self.key_id + raw).decode() + "\n"

    def sign(self, data: bytes, comment: str) -> str:
        """minisign's default (prehashed) signature, as release.yml makes them."""
        body = self.private.sign(hashlib.blake2b(data, digest_size=64).digest())
        line = base64.b64encode(b"ED" + self.key_id + body).decode()
        glob = base64.b64encode(self.private.sign(body + comment.encode())).decode()
        return f"untrusted comment: update test\n{line}\ntrusted comment: {comment}\n{glob}\n"


# ----------------------------------------------------------------------------- the local feed
def serve(version: str, files: dict[str, bytes]) -> ThreadingHTTPServer:
    base = f"http://127.0.0.1:{PORT}"
    release = {
        "tag_name": f"v{version}",
        "name": f"Roundtable Souls v{version}",
        "draft": False,
        "prerelease": is_prerelease(version),
        "html_url": f"{base}/releases/v{version}",
        "body": "update test",
        "assets": [{"name": n, "browser_download_url": f"{base}/dl/{n}"} for n in files],
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 (the base class's name)
            say(f"feed: {self.command} {self.path}")

        def send(self, code: int, body: bytes, kind: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/advisory.json":
                return self.send(200, b'{"minimum": null}')
            if path in ("/api/releases/latest", f"/api/releases/tags/v{version}"):
                return self.send(200, json.dumps(release).encode())
            if path == "/api/releases":
                return self.send(200, json.dumps([release]).encode())
            if path.startswith("/dl/") and path[4:] in files:
                return self.send(200, files[path[4:]], "application/octet-stream")
            return self.send(404, b"{}")

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ----------------------------------------------------------------------------- the test
def previous_release(new: str) -> str:
    """The newest published release older than this build (a re-run of a published version updates from the one
    before it)."""
    out = subprocess.run(
        ["gh", "release", "list", "--repo", os.environ["GITHUB_REPOSITORY"], "--exclude-drafts",
         "--exclude-pre-releases", "--limit", "20", "--json", "tagName", "--jq", ".[].tagName"],
        capture_output=True, text=True, check=True,
    ).stdout.split()  # fmt: skip
    older = [t for t in out if version_key(t) < version_key(new)]
    if not older:
        fail(f"no published release older than {new} to update from")
    return max(older, key=version_key)


def main() -> None:
    if not os.environ.get("GITHUB_ACTIONS"):
        sys.exit("velopack-update-test: runs only on CI (it installs with the real app ID and clears its data folder)")
    new = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    feed_name, sig_name = "releases.win.json", "releases.win.json.minisig"
    if not (SHARE / feed_name).is_file():
        fail(f"{SHARE / feed_name} is missing: run scripts/build.py first")
    prev = previous_release(new)
    say(f"this build: {new}; updating from the published {prev}")

    shutil.rmtree(WORK, ignore_errors=True)
    shutil.rmtree(DATA, ignore_errors=True)  # a clean start (the install test before this one used it)
    WORK.mkdir(parents=True)
    subprocess.run(
        ["gh", "release", "download", prev, "--repo", os.environ["GITHUB_REPOSITORY"],
         "--pattern", "RoundtableSouls-Setup.exe", "--dir", str(WORK)],
        check=True,
    )  # fmt: skip
    code = run_bounded(
        [WORK / "RoundtableSouls-Setup.exe", "--silent", "--installto", INSTALL], 300, f"the {prev} setup"
    )
    if code != 0 or not wait_until(lambda: installed() == prev.lstrip("v"), 60):
        fail(f"the {prev} setup did not install (exit code {code}, installed {installed()})")
    time.sleep(3)
    stop_launchers()

    # 2. the installed copy checks this feed, with this key (the real checks, a different key and address)
    key = Key()
    base = f"http://127.0.0.1:{PORT}"
    override = {
        "pack_id": PACK,
        "api_base": f"{base}/api",
        "releases_page": f"{base}/releases",
        "advisory_url": f"{base}/advisory.json",
        "signing_key": key.public_text(),
        "qt_platform": "offscreen",
    }
    data_dir = INSTALL / "current" / "_internal" / "roundtable_souls" / "data"
    if not data_dir.is_dir():
        fail(f"{data_dir} is not there: the installed layout changed")
    (data_dir / "build-identity.json").write_text(json.dumps(override, indent=1), encoding="utf-8")
    files = {p.name: p.read_bytes() for p in SHARE.iterdir() if p.is_file() and p.suffix in (".nupkg", ".json")}
    files[sig_name] = key.sign(files[feed_name], f"roundtable-souls {new} win").encode()
    if is_prerelease(new):  # a beta: the installed copy is put on the Beta channel first, as a beta tester would be
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / "launcher_settings.json").write_text(json.dumps({"launcher_channel": "beta"}), encoding="utf-8")
        say("this build is a beta: the installed copy's Settings put on the Beta channel")
    server = serve(new, files)
    try:
        # 3. Update now, without the window
        code = run_bounded([INSTALL / "current" / "RoundtableSouls.exe", "--update"], 300, f"--update in {prev}")
        if code != 0:
            fail(f"--update exited with {code}")
        if not wait_until(lambda: installed() == new, 180):
            fail(f"Velopack did not install {new} (installed: {installed()})")
        say(f"installed {new}; waiting for it to report ready")
        ready = DATA / "updates" / "state" / f"ready-{new}"
        if not wait_until(ready.exists, 150):
            fail(f"{new} did not report ready (the watchdog would roll it back)")
        say(f"ready: {ready.read_text(encoding='utf-8', errors='replace').strip()}")
        time.sleep(5)
        # 4. its database, and no rollback
        db = DATA / "roundtable.db"
        if not db.is_file():
            fail(f"{new} started without creating its database at {db}")
        conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        finally:
            conn.close()
        say(f"database: {db} at schema {row[0] if row else '?'}")
        if row is None:
            fail("the database has no schema version")
        if (DATA / "updates" / "state" / "rollback.json").exists() or installed() != new:
            fail(f"a rollback happened (installed: {installed()})")
        say(f"updated {prev} -> {new}: ready, database at {row[0]}, no rollback")
    finally:
        server.shutdown()
    stop_launchers()
    if not wait_until(lambda: not any(p for p in [INSTALL / "current" / "RoundtableSouls.exe"] if _running(p)), 30):
        fail("the launcher did not stop")

    # 5. uninstall
    run_bounded([INSTALL / "Update.exe", "uninstall", "--silent"], 300, "the uninstaller")
    if not wait_until(lambda: not (INSTALL / f"{TITLE}.exe").exists(), 60):
        fail("the uninstaller left the program")
    say("uninstalled")


def _running(exe: Path) -> bool:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"@(Get-Process | Where-Object {{ $_.Path -eq '{exe}' }}).Count"],
        capture_output=True, text=True,
    ).stdout.strip()  # fmt: skip
    return out not in ("", "0")


if __name__ == "__main__":
    main()
