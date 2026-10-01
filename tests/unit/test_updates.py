"""The launcher's own updates: the check (cache, ETag, failures, backoff, channels, skip), the signed download
(signature, checksum, resume, downgrade refusal, cleanup), and applying it (portable hand-over and roll-back,
the silent setup and how its outcome is reported)."""

import hashlib
import io
import threading
import urllib.error
from email.message import Message
from pathlib import Path

import fakerelease
import pytest

from roundtable_souls import __version__, settings, signing, updates

VECTORS = Path(__file__).parent / "data" / "minisign"


def _bump(v: str) -> str:
    a, b, c = (int(x) for x in v.split(".")[:3])
    return f"{a}.{b}.{c + 1}"


def _rel(version, **kw):
    return {"version": version, "url": "https://example.test/rel", "assets": {}, "notes": "", **kw}


class _fetcher:
    """fetch(channel, etag) returning answers in turn (the last repeats), recording each call."""

    def __init__(self, *answers):
        self.answers = answers
        self.calls = []

    def __call__(self, channel="stable", etag=""):
        self.calls.append((channel, etag))
        return self.answers[min(len(self.calls) - 1, len(self.answers) - 1)]


# ---------------------------------------------------------------------------- versions


def test_versions_order_pre_releases_before_their_release():
    order = ["3.13.2", "3.14.0-dev", "3.14.0a1", "3.14.0-beta.2", "3.14.0rc1", "3.14.0-rc.2", "3.14.0", "3.14.1"]
    keys = [updates.version_key(v) for v in order]
    assert keys == sorted(keys) and len(set(keys)) == len(keys)
    assert updates.parse_version("v3.14.0rc1") == "3.14.0-rc.1" and updates.parse_version("v3.14.0") == "3.14.0"
    assert updates.is_newer("3.14.0", "3.14.0-rc.2") and not updates.is_newer("3.14.0-rc.2", "3.14.0")
    assert updates.is_prerelease("3.14.0-beta.1") and not updates.is_prerelease("3.14.0")
    assert not updates.is_newer("", "1.0.0") and updates.parse_version("no version") is None


# ---------------------------------------------------------------------------- the check


def test_newer_release_is_offered_and_cached_for_an_hour():
    newer = _bump(__version__)
    fetch = _fetcher(updates.Fetched("ok", data=_rel(newer), etag='"e1"'))
    clock = [1000.0]
    out = updates.check_launcher_update(fetch=fetch, now=lambda: clock[0])
    assert out.status == "fresh" and out.offer["version"] == newer and out.checked == 1000.0
    assert settings.load_settings()["launcher_latest"]["version"] == newer
    clock[0] += 1800
    again = updates.check_launcher_update(fetch=fetch, now=lambda: clock[0])
    assert again.status == "cached" and again.offer["version"] == newer and len(fetch.calls) == 1
    clock[0] += updates.CHECK_EVERY
    updates.check_launcher_update(fetch=fetch, now=lambda: clock[0])
    assert fetch.calls[-1] == ("stable", '"e1"')  # an hour later it asks again, with the ETag


def test_not_modified_keeps_the_cached_answer_and_counts_as_checked():
    newer = _bump(__version__)
    clock = [1000.0]
    updates.check_launcher_update(
        fetch=_fetcher(updates.Fetched("ok", data=_rel(newer), etag='"e1"')), now=lambda: clock[0]
    )
    clock[0] += updates.CHECK_EVERY + 1
    out = updates.check_launcher_update(fetch=_fetcher(updates.Fetched("not_modified")), now=lambda: clock[0])
    assert out.status == "fresh" and out.offer["version"] == newer and out.checked == clock[0]


def test_same_or_older_release_is_quiet():
    for v in (__version__, "0.1.0"):
        settings.save_settings(launcher_latest=None)
        out = updates.check_launcher_update(fetch=_fetcher(updates.Fetched("ok", data=_rel(v))))
        assert out.status == "fresh" and out.offer is None and not out.failed


def test_a_failed_check_is_reported_never_up_to_date():
    for status in ("offline", "rate_limited", "error"):
        settings.save_settings(launcher_latest=None, launcher_next_check=0.0, launcher_check_failures=0)
        out = updates.check_launcher_update(fetch=_fetcher(updates.Fetched(status, reason="why")), force=True)
        assert out.failed and out.status == status and out.reason == "why" and out.offer is None
        assert settings.load_settings()["launcher_check_error"] == "why"


def test_failures_back_off_and_a_success_resets():
    clock = [10_000.0]
    down = _fetcher(updates.Fetched("offline", reason="no network"))
    waits = []
    for _ in range(7):
        out = updates.check_launcher_update(fetch=down, now=lambda: clock[0], rand=lambda: 0.0)
        assert out.status == "offline"
        waits.append(out.retry_at - clock[0])
        blocked = updates.check_launcher_update(fetch=down, now=lambda: clock[0], rand=lambda: 0.0)
        assert blocked.status == "waiting" and blocked.reason == "no network"  # no request while backing off
        clock[0] = out.retry_at + 1
    assert waits[:5] == [3600, 7200, 14400, 28800, 57600] and waits[-1] == updates.MAX_BACKOFF
    assert len(down.calls) == 7
    up = updates.check_launcher_update(
        fetch=_fetcher(updates.Fetched("ok", data=_rel(__version__))), now=lambda: clock[0]
    )
    s = settings.load_settings()
    assert up.status == "fresh" and s["launcher_check_failures"] == 0 and s["launcher_check_error"] == ""


def test_github_limit_waits_until_its_reset():
    clock = [1000.0]
    out = updates.check_launcher_update(
        fetch=_fetcher(updates.Fetched("rate_limited", reason="limit", retry_at=5000.0)), now=lambda: clock[0]
    )
    assert out.status == "rate_limited" and out.retry_at == 5000.0


def test_force_ignores_cache_backoff_toggle_and_skip():
    newer = _bump(__version__)
    fetch = _fetcher(updates.Fetched("ok", data=_rel(newer)))
    assert updates.check_launcher_update(fetch=fetch).offer
    updates.skip_update(newer)
    assert updates.check_launcher_update(fetch=fetch).offer is None
    settings.save_settings(check_launcher_updates=False, launcher_next_check=1e12)
    assert updates.check_launcher_update(fetch=fetch).status == "off"
    forced = updates.check_launcher_update(fetch=fetch, force=True)
    assert forced.status == "fresh" and forced.offer["version"] == newer and len(fetch.calls) == 2


def test_channel_switch_does_not_reuse_the_other_channels_answer():
    beta = _bump(__version__) + "-rc.1"
    updates.check_launcher_update(fetch=_fetcher(updates.Fetched("ok", data=_rel(__version__))))
    settings.save_settings(launcher_channel="beta")
    fetch = _fetcher(updates.Fetched("ok", data=_rel(beta, prerelease=True)))
    out = updates.check_launcher_update(fetch=fetch)
    assert fetch.calls == [("beta", "")] and out.offer["version"] == beta


def test_channels_pick_their_release():
    docs = [
        {"tag_name": "v9.1.0-rc.1", "prerelease": True, "assets": [], "body": "rc"},
        {"tag_name": "v9.0.0", "assets": [{"name": "a", "browser_download_url": "u"}], "body": "b"},
        {"tag_name": "v9.2.0", "draft": True},
    ]
    assert updates.pick_release(docs, "beta")["version"] == "9.1.0-rc.1"
    stable = updates.pick_release(docs[1], "stable")
    assert stable["version"] == "9.0.0" and stable["assets"] == {"a": "u"} and stable["notes"] == "b"
    assert updates.pick_release(docs[0], "stable") is None  # a pre-release is never offered on Stable
    assert updates.pick_release([], "beta") is None and updates.pick_release("junk", "beta") is None


class _Resp(io.BytesIO):
    def __init__(self, body=b"", headers=None, status=200):
        super().__init__(body)
        self.headers = headers or {}
        self.status = status


def _http_error(code, headers=None):
    msg = Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    return urllib.error.HTTPError("https://x", code, "reason", msg, None)


def test_github_answers_are_told_apart():
    def opener_for(result):
        def opener(req, timeout=None):
            if isinstance(result, Exception):
                raise result
            return result

        return opener

    ok = updates.fetch_release(opener=opener_for(_Resp(b'{"tag_name": "v9.9.9"}', {"ETag": '"x"'})))
    assert ok.status == "ok" and ok.data["version"] == "9.9.9" and ok.etag == '"x"'
    seen = {}

    def recording(req, timeout=None):
        seen.update(req.headers)
        raise _http_error(304)

    assert updates.fetch_release(etag='"x"', opener=recording).status == "not_modified"
    assert seen.get("If-none-match") == '"x"'
    limited = updates.fetch_release(
        opener=opener_for(_http_error(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "12345"}))
    )
    assert limited.status == "rate_limited" and limited.retry_at == 12345.0
    assert (
        updates.fetch_release(opener=opener_for(_http_error(429, {"Retry-After": "60"})), now=lambda: 100).retry_at
        == 160
    )
    assert updates.fetch_release(opener=opener_for(urllib.error.URLError("no route"))).status == "offline"
    assert updates.fetch_release(opener=opener_for(TimeoutError())).status == "offline"
    assert updates.fetch_release(opener=opener_for(_http_error(500))).status == "error"
    assert updates.fetch_release(opener=opener_for(_Resp(b"not json"))).status == "error"


def test_advisory_warns_only_below_the_minimum():
    newer = _bump(__version__)
    got = updates.Fetched("ok", data={"minimum": newer, "message": "known bug", "url": ""})
    calls = []

    def fetch(etag=""):
        calls.append(etag)
        return got

    assert updates.check_advisory(fetch=fetch)["message"] == "known bug"
    assert updates.check_advisory(fetch=fetch) and len(calls) == 1  # cached for the hour
    settings.save_settings(launcher_advisory=None)
    got.data = {"minimum": None, "message": "", "url": ""}
    assert updates.check_advisory(fetch=fetch) is None
    settings.save_settings(launcher_advisory=None)
    got.data = {"minimum": __version__, "message": "x", "url": ""}
    assert updates.check_advisory(fetch=fetch) is None  # this version is the minimum: fine


def test_release_notes_become_plain_lines():
    md = "## What's Changed\n* **Fixed** a [bug](https://x) in `x` by @me\n\n<!-- hidden -->\n- two\n- three\n"
    assert updates.release_notes(md, lines=3) == "What's Changed\n• Fixed a bug in x by @me\n• two"


# ---------------------------------------------------------------------------- signatures


def test_signatures_made_by_minisign_itself_verify():
    key = signing.parse_public_key((VECTORS / "test.pub").read_text())
    data = (VECTORS / "SHA256SUMS.txt").read_bytes()
    for sig in ("SHA256SUMS.txt.minisig", "legacy.minisig"):  # minisign 0.12's default (prehashed) and -l
        assert signing.verify(data, (VECTORS / sig).read_text(), key) == "roundtable-souls 9.9.9"
    with pytest.raises(signing.SignatureError, match="does not match"):
        signing.verify(data + b"x", (VECTORS / "SHA256SUMS.txt.minisig").read_text(), key)
    lines = (VECTORS / "SHA256SUMS.txt.minisig").read_text().splitlines()
    lines[2] = "trusted comment: roundtable-souls 99.0.0"
    with pytest.raises(signing.SignatureError, match="trusted comment"):
        signing.verify(data, "\n".join(lines), key)
    with pytest.raises(signing.SignatureError, match="not this project's key"):
        signing.verify(data, (VECTORS / "SHA256SUMS.txt.minisig").read_text(), fakerelease.Key().public)
    with pytest.raises(signing.SignatureError):
        signing.verify(data, "garbage", key)


def test_the_shipped_release_key_reads():
    key = signing.release_key()
    assert len(key.key) == 32 and key.id_hex == "7E6CB2F456375629"


# ---------------------------------------------------------------------------- download


def test_download_verifies_signature_and_checksum_then_unpacks(tmp_path):
    rel = fakerelease.make()
    seen = []
    exe = rel.download(progress=lambda d, t: seen.append((d, t)), workdir=tmp_path, platform="win32")
    assert (
        exe.name == "RoundtableSouls.exe" and exe.read_bytes() == b"new exe" and exe.is_relative_to(tmp_path / "99.0.0")
    )
    assert rel.calls == ["https://x/sums", "https://x/sig", f"https://x/{updates.ASSET_NAME}"] and seen


def test_download_refuses_what_it_cannot_trust(tmp_path):
    cases = {
        "not signed": fakerelease.make(signed=False),
        "did not check out": fakerelease.make(),  # checked against another key below
        "for 98.0.0": fakerelease.make(signed_for="98.0.0"),  # an older release's signed checksums
        "did not match its checksum": fakerelease.make(corrupt=True),
    }
    for expect, rel in cases.items():
        key = fakerelease.Key().public if expect == "did not check out" else rel.key.public
        with pytest.raises(updates.UpdateError, match=expect):
            rel.download(workdir=tmp_path, platform="win32", key=key)
    assert not list(tmp_path.rglob("*.exe"))


def test_download_refuses_a_version_that_is_not_newer(tmp_path):
    rel = fakerelease.make(version=__version__)
    with pytest.raises(updates.UpdateError, match="not newer"):
        rel.download(workdir=tmp_path, platform="win32")
    assert rel.calls == []  # refused before anything was downloaded


def test_unsigned_releases_go_through_the_releases_page():
    assert not updates.can_self_update(fakerelease.make(signed=False).info, installed=False, platform="win32")
    assert updates.can_self_update(fakerelease.make().info, installed=False, platform="win32")


def test_installed_copy_downloads_the_setup(tmp_path):
    rel = fakerelease.make(name=updates.SETUP_NAME)
    assert updates.can_self_update(rel.info, installed=True, platform="win32")
    assert not updates.can_self_update(rel.info, installed=False, platform="win32")
    setup = rel.download(workdir=tmp_path, installed=True, platform="win32")
    assert setup.name == updates.SETUP_NAME and setup.read_bytes() == b"MZ fake setup"
    calls = len(rel.calls)
    assert rel.download(workdir=tmp_path, installed=True, platform="win32") == setup
    assert len(rel.calls) == calls + 2  # a finished download is reused: only the checksums and signature again


def test_linux_update_unpacks_the_program(tmp_path):
    rel = fakerelease.make(name=updates.LINUX_ASSET_NAME)
    program = rel.download(workdir=tmp_path, platform="linux")
    assert program.name == "RoundtableSouls" and program.read_bytes() == b"\x7fELF new build"


def test_fetch_to_file_resumes_and_hashes_the_whole_file(tmp_path):
    data = bytes(range(256)) * 4000
    part = tmp_path / "x.part"
    part.write_bytes(data[:1000])
    asked = []

    def opener(req, timeout=None):
        rng = req.headers.get("Range")
        asked.append(rng)
        start = int(rng.split("=")[1].rstrip("-")) if rng else 0
        body = data[start:]
        return _Resp(body, {"Content-Length": str(len(body))}, status=206 if rng else 200)

    seen = []
    digest = updates.fetch_to_file("https://x/u", part, progress=lambda d, t: seen.append((d, t)), opener=opener)
    assert asked == ["bytes=1000-"] and part.read_bytes() == data
    assert digest == hashlib.sha256(data).hexdigest() and seen[-1] == (len(data), len(data))


def test_fetch_to_file_starts_over_when_the_range_is_ignored_or_refused(tmp_path):
    data = b"fresh content"
    part = tmp_path / "x.part"
    part.write_bytes(b"stale bytes")
    digest = updates.fetch_to_file("https://x/u", part, opener=lambda req, timeout=None: _Resp(data, status=200))
    assert part.read_bytes() == data and digest == hashlib.sha256(data).hexdigest()
    part.write_bytes(b"too long already" * 10)
    asked = []

    def opener(req, timeout=None):
        asked.append(req.headers.get("Range"))
        if req.headers.get("Range"):
            raise _http_error(416)
        return _Resp(data)

    assert updates.fetch_to_file("https://x/u", part, opener=opener) == hashlib.sha256(data).hexdigest()
    assert asked[0] and asked[1] is None and part.read_bytes() == data


def test_fetch_to_file_keeps_the_part_when_the_connection_drops(tmp_path):
    part = tmp_path / "x.part"

    class Dropping(_Resp):
        def read(self, n: int | None = -1):
            if self.tell() >= 5:
                raise ConnectionResetError("reset")
            return super().read(5)

    with pytest.raises(updates.UpdateError, match="continues where it stopped"):
        updates.fetch_to_file("https://x/u", part, opener=lambda req, timeout=None: Dropping(b"0123456789"))
    assert part.read_bytes() == b"01234"


def test_clean_downloads_keeps_the_pending_one_and_recent_temp_folders(tmp_path):
    root = updates.updates_dir()
    for v in ("9.0.0", "9.1.0"):
        (root / v).mkdir(parents=True)
        (root / v / "f").write_text("x")
    (root / "not-a-version").mkdir()
    temp = tmp_path / "temp"
    old, new = temp / "roundtable-update-old", temp / "roundtable-update-new"
    old.mkdir(parents=True)
    new.mkdir()
    other = temp / "someone-else"
    other.mkdir()
    import os

    os.utime(old, (1, 1))
    assert updates.clean_downloads(keep="9.1.0", temp=temp) == 2
    assert not (root / "9.0.0").exists() and (root / "9.1.0").exists() and (root / "not-a-version").exists()
    assert not old.exists() and new.exists() and other.exists()


# ---------------------------------------------------------------------------- applying: portable


def _swap_setup(tmp_path):
    current = tmp_path / "RoundtableSouls.exe"
    current.write_bytes(b"old exe")
    new = tmp_path / "dl" / "RoundtableSouls.exe"
    new.parent.mkdir()
    new.write_bytes(b"new exe")
    return current, new


def test_apply_update_swaps_parks_and_records_it_pending(tmp_path):
    current, new = _swap_setup(tmp_path)
    parked, proc = updates.apply_update(new, current, "99.0.0", restart=False)
    assert proc is None and current.read_bytes() == b"new exe" and parked.read_bytes() == b"old exe"
    assert parked.name == "RoundtableSouls.old.exe" and not new.exists()
    assert settings.load_settings()["update_pending"]["version"] == "99.0.0"
    assert updates.remove_parked_exe(current) and not parked.exists() and updates.remove_parked_exe(current)


def test_apply_update_restores_on_failure(tmp_path):
    current = tmp_path / "RoundtableSouls.exe"
    current.write_bytes(b"old exe")
    with pytest.raises(FileNotFoundError):
        updates.apply_update(tmp_path / "missing.exe", current, "99.0.0", restart=False)
    assert current.read_bytes() == b"old exe" and not updates.parked_path(current).exists()
    assert settings.load_settings()["update_pending"] is None


def test_relaunch_drops_pyinstaller_markers(tmp_path, monkeypatch):
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "x")
    monkeypatch.setenv("_MEIPASS2", "z")
    monkeypatch.setenv("PATH_KEEP_ME", "1")
    current, new = _swap_setup(tmp_path)
    seen = {}

    def popen(args, **kw):
        seen.update(kw, args=args)
        return object()

    updates.apply_update(new, current, "99.0.0", popen=popen)
    env = seen["env"]
    assert seen["args"] == [str(current)] and "_PYI_ARCHIVE_FILE" not in env and env["PATH_KEEP_ME"] == "1"


def test_a_new_copy_that_cannot_start_is_rolled_back_at_once(tmp_path):
    current, new = _swap_setup(tmp_path)

    def popen(args, **kw):
        raise OSError("blocked")

    with pytest.raises(updates.UpdateError, match="put back"):
        updates.apply_update(new, current, "99.0.0", popen=popen)
    assert current.read_bytes() == b"old exe" and updates.failed_path(current).read_bytes() == b"new exe"
    s = settings.load_settings()
    assert s["update_pending"] is None and s["update_result"]["status"] == "rolled_back"


class _Proc:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


def test_hand_over_waits_for_the_new_window_to_confirm(tmp_path):
    current, new = _swap_setup(tmp_path)
    updates.apply_update(new, current, "99.0.0", restart=False)
    proc = _Proc()
    ticks = [0.0]

    def sleep(_):
        ticks[0] += 1
        if ticks[0] == 3:  # the new copy's window opens
            assert updates.confirm_started(current="99.0.0", now=lambda: 5.0)["status"] == "ok"

    assert updates.wait_for_new_version(proc, "99.0.0", sleep=sleep, now=lambda: ticks[0]) == "ok"
    s = settings.load_settings()
    assert s["update_pending"] is None and s["update_result"]["from"] == __version__


def test_hand_over_rolls_back_when_the_new_copy_exits_without_confirming(tmp_path):
    current, new = _swap_setup(tmp_path)
    updates.apply_update(new, current, "99.0.0", restart=False)
    assert updates.wait_for_new_version(_Proc(code=1), "99.0.0", sleep=lambda _: None) == "exited"
    assert updates.roll_back(current, "it closed")
    assert current.read_bytes() == b"old exe" and updates.failed_path(current).read_bytes() == b"new exe"
    assert not updates.parked_path(current).exists()
    result = updates.update_outcome(current=__version__)
    assert result["status"] == "rolled_back" and result["version"] == "99.0.0" and result["error"] == "it closed"


def test_hand_over_leaves_a_slow_new_copy_alone():
    ticks = [0.0]

    def sleep(_):
        ticks[0] += 10

    assert updates.wait_for_new_version(_Proc(), "99.0.0", timeout=30, sleep=sleep, now=lambda: ticks[0]) == "slow"


def test_confirm_started_only_for_the_pending_version():
    assert updates.confirm_started(current="99.0.0") is None  # nothing pending
    settings.save_settings(update_pending={"version": "99.0.0", "kind": "portable", "from": "1.0.0"})
    assert updates.confirm_started(current="98.0.0") is None
    assert updates.confirm_started(current="99.0.0")["status"] == "ok"


# ---------------------------------------------------------------------------- applying: installed


def test_installer_runs_silently_with_a_log_into_this_folder(tmp_path):
    seen = {}

    def popen(args, **kw):
        seen.update(kw, args=args)

    log = updates.run_installer(tmp_path / "setup.exe", "99.0.0", tmp_path / "app", popen=popen)
    args = seen["args"]
    assert args[0] == str(tmp_path / "setup.exe") and "/VERYSILENT" in args and "/RELAUNCH=1" in args
    assert f"/DIR={tmp_path / 'app'}" in args and f"/LOG={log}" in args and log.parent.is_dir()
    pending = settings.load_settings()["update_pending"]
    assert pending == {**pending, "version": "99.0.0", "kind": "installed", "log": str(log)}


def test_installed_update_that_landed_is_confirmed_at_start():
    settings.save_settings(update_pending={"version": "99.0.0", "kind": "installed", "log": ""})
    result = updates.update_outcome(current="99.0.0", held=lambda name: False)
    assert result["status"] == "ok" and settings.load_settings()["update_pending"] is None


def test_installed_update_that_failed_is_reported_with_the_logs_reason(tmp_path):
    log = tmp_path / "setup.log"
    log.write_text(
        "2026-10-01 12:00:00.123   Log opened.\n"
        "2026-10-01 12:00:00.200   Roundtable Souls: a newer version (99.1.0) is installed; refusing 99.0.0.\n"
        "2026-10-01 12:00:00.300   Log closed.\n",
        encoding="utf-8",
    )
    settings.save_settings(update_pending={"version": "99.0.0", "kind": "installed", "log": str(log)})
    result = updates.update_outcome(current=__version__, held=lambda name: False)
    assert result["status"] == "failed" and "newer version (99.1.0)" in result["error"] and result["log"] == str(log)
    assert settings.load_settings()["update_pending"] is None
    updates.clear_outcome()
    assert updates.update_outcome(current=__version__, held=lambda name: False) is None  # shown once


def test_outcome_waits_for_a_setup_that_is_still_running():
    settings.save_settings(update_pending={"version": "99.0.0", "kind": "installed", "log": ""})
    running = [True, True, False]
    result = updates.update_outcome(
        current=__version__, held=lambda name: running.pop(0) if running else False, sleep=lambda _: None
    )
    assert result["status"] == "failed"
    settings.save_settings(update_pending={"version": "99.0.0", "kind": "installed", "log": ""})
    assert updates.update_outcome(current=__version__, held=lambda n: True, sleep=lambda _: None, setup_wait=1) is None
    assert settings.load_settings()["update_pending"]  # reported at a later start


def test_busy_reason_names_a_shortcut_play_or_a_setup(monkeypatch):
    from roundtable_souls.system import instance

    monkeypatch.setattr(instance, "held", lambda name: name == instance.PLAY)
    assert "Steam shortcut" in updates.busy_reason()
    monkeypatch.setattr(instance, "held", lambda name: name == instance.SETUP)
    assert "being installed" in updates.busy_reason()
    monkeypatch.setattr(instance, "held", lambda name: False)
    assert updates.busy_reason() == ""


# ---------------------------------------------------------------------------- settings under concurrent writers


def test_settings_writes_from_many_threads_lose_nothing():
    settings.save_settings(launcher_check_failures=0)

    def bump():
        for _ in range(20):
            settings.change_settings(lambda cur: {"launcher_check_failures": cur["launcher_check_failures"] + 1})

    def other(i):
        for j in range(20):
            settings.save_settings(**{f"probe_{i}": j})

    threads = [threading.Thread(target=bump) for _ in range(4)] + [
        threading.Thread(target=other, args=(i,)) for i in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    s = settings.load_settings()
    assert s["launcher_check_failures"] == 80 and all(s[f"probe_{i}"] == 19 for i in range(4))
    assert not list(settings.settings_path().parent.glob("*.tmp"))


def test_install_kind_is_detected_from_the_uninstaller(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "FROZEN", True)
    monkeypatch.setattr(settings, "exe_dir", lambda: tmp_path)
    assert not settings.is_installed()
    (tmp_path / "unins000.exe").write_bytes(b"x")
    assert settings.is_installed()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "local"))
    assert settings.data_dir() == tmp_path / "local" / settings.APP_DIR_NAME  # installed copies never write beside it
