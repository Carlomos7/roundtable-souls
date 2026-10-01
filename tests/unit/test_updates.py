"""The launcher's own updates: the check (cache, ETag, failures, backoff, channels, skip, blocked versions), the
verified download (signed Velopack feed, full or delta package, resume, downgrade refusal, cleanup), applying it
through Velopack with a watchdog, readiness and rollback reporting, and where a copy keeps its data."""

import hashlib
import io
import json
import os
import sys
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


# ---------------------------------------------------------------------------- download and verify


def test_download_verifies_the_signed_feed_then_the_full_package(tmp_path):
    rel = fakerelease.make()
    seen = []
    prepared = rel.download(progress=lambda d, t: seen.append((d, t)), workdir=tmp_path)
    assert prepared.version == "99.0.0" and prepared.files == [rel.full["FileName"]] and not prepared.delta
    assert rel.calls[:2] == ["https://x/feed", "https://x/sig"] and seen
    local = json.loads((prepared.folder / updates.FEED_NAME).read_text(encoding="utf-8"))
    assert local == {"Assets": [rel.full]}  # Velopack reads only entries copied from the signed feed
    assert sorted(p.name for p in prepared.folder.iterdir()) == sorted([updates.FEED_NAME, rel.full["FileName"]])
    updates.verify_prepared(prepared)


def test_the_delta_is_used_only_against_the_version_it_was_made_from(tmp_path):
    rel = fakerelease.make(base="98.0.0")
    prepared = rel.download(base_available=updates._base_available, current="98.0.0", workdir=tmp_path)
    assert prepared.files == [rel.full["FileName"]]  # no packages folder here: Velopack has no base, full it is
    rel = fakerelease.make(base="98.0.0")
    prepared = rel.download(base_available=lambda feed, current: True, current="98.0.0", workdir=tmp_path / "d")
    assert prepared.delta and prepared.files == [rel.delta["FileName"]]
    local = json.loads((prepared.folder / updates.FEED_NAME).read_text(encoding="utf-8"))
    assert local == {"Assets": [rel.full, rel.delta]}  # the target's full entry, its file not needed
    assert rel.full["FileName"] not in [c.rsplit("/", 1)[-1] for c in rel.calls]  # only the delta downloaded
    updates.verify_prepared(prepared)


def test_base_available_needs_the_exact_base_in_velopacks_packages(tmp_path, monkeypatch):
    rel = fakerelease.make(base="98.0.0")
    feed = updates.verified_feed(rel.info, fetch=rel.fetch, key=rel.key.public)
    packages = tmp_path / "packages"
    packages.mkdir()
    monkeypatch.setattr(updates, "velopack_packages_dir", lambda: packages)
    assert not updates._base_available(feed, "98.0.0")  # base package missing
    (packages / feed.base["FileName"]).write_bytes(b"x")
    assert updates._base_available(feed, "98.0.0")
    assert not updates._base_available(feed, "97.0.0")  # this copy is two versions behind: full package


def test_download_refuses_what_it_cannot_trust(tmp_path):
    other_key = fakerelease.Key()
    cases = {
        "no signed update feed": fakerelease.make(signed=False),
        "did not check out": fakerelease.make(key=other_key),
        "not 99.0.0 on": fakerelease.make(signed_for="98.0.0"),  # an older release's signed feed
        "on " + updates.OS_CHANNEL: fakerelease.make(channel="mac"),  # another system's feed
        "signature did not": fakerelease.make(feed_edit=lambda d: d["Assets"][0].update(SHA256="0" * 64)),
        "did not match the signed feed": fakerelease.make(package_edit=lambda b: b[:-1] + b"X"),
    }
    for expect, rel in cases.items():
        key = fakerelease.Key().public if expect == "did not check out" else rel.key.public
        with pytest.raises(updates.UpdateError, match=expect):
            rel.download(workdir=tmp_path, key=key)
    assert not list(tmp_path.rglob("*.nupkg"))


def test_feed_entries_are_checked_even_when_signed(tmp_path):
    for edit, expect in (
        (lambda e: e.update(FileName="..\\evil.exe"), "unsafe file"),
        (lambda e: e.update(PackageId="Someone.Else"), "not this launcher"),
        (lambda e: e.update(Size=0), "no usable size"),
    ):
        key = fakerelease.Key()
        rel = fakerelease.make(key=key)
        doc = json.loads(rel.urls["https://x/feed"])
        edit(doc["Assets"][0])
        raw = json.dumps(doc).encode()
        rel.urls["https://x/feed"] = raw
        rel.urls["https://x/sig"] = key.sign(
            raw, updates.SIGNED_COMMENT.format(version="99.0.0", channel=updates.OS_CHANNEL)
        ).encode()
        with pytest.raises(updates.UpdateError, match=expect):
            rel.download(workdir=tmp_path)


def test_download_refuses_not_newer_and_blocked_versions(tmp_path):
    rel = fakerelease.make(version="1.0.0")
    with pytest.raises(updates.UpdateError, match="not newer"):
        rel.download(workdir=tmp_path, current="1.0.0")
    settings.save_settings(update_blocked=["99.0.0"])
    rel = fakerelease.make()
    with pytest.raises(updates.UpdateError, match="failed to start here before"):
        rel.download(workdir=tmp_path)
    assert rel.calls == []  # refused before anything was downloaded


def test_verify_prepared_catches_anything_changed_after_the_check(tmp_path):
    for change in (
        lambda p: (p.folder / p.files[0]).write_bytes(b"swapped"),
        lambda p: (p.folder / "extra.nupkg").write_bytes(b"x"),
        lambda p: (p.folder / updates.FEED_NAME).write_text(
            json.dumps({"Assets": [{**p.signed[0], "SHA256": "A" * 64}]}), encoding="utf-8"
        ),
    ):
        prepared = fakerelease.make().download(workdir=tmp_path / str(len(list(tmp_path.iterdir()))))
        change(prepared)
        with pytest.raises(updates.UpdateError):
            updates.verify_prepared(prepared)


def test_only_a_managed_copy_with_a_signed_feed_updates_itself(monkeypatch, tmp_path):
    info = fakerelease.make().info
    monkeypatch.setattr(updates, "velopack_root", lambda: None)
    monkeypatch.setattr(updates, "appimage", lambda: None)
    assert not updates.can_self_update(info)  # running from source or a raw build
    monkeypatch.setattr(updates, "velopack_root", lambda: tmp_path)
    monkeypatch.setattr(updates, "identity_matches", lambda: False)
    assert not updates.can_self_update(info)  # a build of another app ID never updates this install
    monkeypatch.setattr(updates, "identity_matches", lambda: True)
    assert updates.can_self_update(info)
    assert not updates.can_self_update(fakerelease.make(signed=False).info)


def test_rollback_package_comes_from_velopacks_packages_or_the_release(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "appimage", lambda: None)
    packages = tmp_path / "packages"
    packages.mkdir()
    suffix = "" if updates.OS_CHANNEL == "win" else "-linux"
    kept = packages / f"{fakerelease.PACK}-5.0.0{suffix}-full.nupkg"
    kept.write_bytes(b"installed version")
    monkeypatch.setattr(updates, "velopack_packages_dir", lambda: packages)
    out = updates.stage_rollback(current="5.0.0", release_of=lambda v: pytest.fail("no download needed"))
    assert out.read_bytes() == b"installed version" and out.parent == updates.rollback_dir()
    kept.unlink()  # a portable copy has no package of its own version: it comes from that version's release
    rel = fakerelease.make(version="5.0.0", base=None)
    out = updates.stage_rollback(
        current="5.0.0", release_of=lambda v: rel.info, fetch=rel.fetch, fetch_file=rel.fetch_file, key=rel.key.public
    )
    assert out.name == rel.full["FileName"] and out.stat().st_size == rel.full["Size"]


def test_rollback_on_linux_keeps_the_appimage(tmp_path, monkeypatch):
    image = tmp_path / "RoundtableSouls.AppImage"
    image.write_bytes(b"ELF current")
    monkeypatch.setattr(updates, "appimage", lambda: image)
    out = updates.stage_rollback(current="5.0.0")
    assert out.read_bytes() == b"ELF current" and "5.0.0" in out.name


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


def test_clean_downloads_keeps_the_pending_one_this_versions_rollback_and_recent_temp_folders(tmp_path):
    root = updates.updates_dir()
    for v in ("9.0.0", "9.1.0"):
        (root / v).mkdir(parents=True)
        (root / v / "f").write_text("x")
    (root / "not-a-version").mkdir()
    keep = updates.rollback_dir()
    keep.mkdir(parents=True)
    (keep / "X-5.0.0-full.nupkg").write_text("this")
    (keep / "X-4.0.0-full.nupkg").write_text("older")
    temp = tmp_path / "temp"
    old, new = temp / "roundtable-update-old", temp / "roundtable-update-new"
    old.mkdir(parents=True)
    new.mkdir()
    os.utime(old, (1, 1))
    assert updates.clean_downloads(keep="9.1.0", current="5.0.0", temp=temp) == 3
    assert not (root / "9.0.0").exists() and (root / "9.1.0").exists() and (root / "not-a-version").exists()
    assert sorted(p.name for p in keep.iterdir()) == ["X-5.0.0-full.nupkg"]
    assert not old.exists() and new.exists()


# ---------------------------------------------------------------------------- applying, readiness, rollback


class _FakeVelopack:
    """Stands in for the velopack module: records what the updater asks of it."""

    def __init__(self, target="99.0.0"):
        self.calls = []
        outer = self

        class Asset:
            Version = target

        class Info:
            TargetFullRelease = Asset()

        class UpdateManager:
            def __init__(self, source, options=None):
                outer.calls.append(("source", source))

            def check_for_updates(self):
                return Info()

            def download_updates(self, info):
                outer.calls.append(("download",))

            def wait_exit_then_apply_updates(self, info, silent=False, restart=True, restart_args=None):
                outer.calls.append(("apply", silent, restart, list(restart_args or [])))

        self.UpdateManager = UpdateManager
        self.UpdateOptions = lambda *a: a


def _managed(monkeypatch, tmp_path):
    root = tmp_path / "root"
    (root / "current").mkdir(parents=True)
    image = tmp_path / "RoundtableSouls.AppImage"
    image.write_bytes(b"ELF")
    monkeypatch.setattr(updates, "velopack_root", lambda: root if updates.OS_CHANNEL == "win" else None)
    monkeypatch.setattr(updates, "appimage", lambda: image if updates.OS_CHANNEL == "linux" else None)
    monkeypatch.setattr(updates, "identity_matches", lambda: True)
    return root


def test_apply_hands_velopack_the_verified_folder_and_starts_the_watchdog(tmp_path, monkeypatch):
    _managed(monkeypatch, tmp_path)
    prepared = fakerelease.make().download(workdir=tmp_path / "dl")
    prepared.rollback = tmp_path / "kept.nupkg"
    prepared.rollback.write_bytes(b"previous")
    vp, started = _FakeVelopack(), []
    updates.apply_update(prepared, restart_args=["--game", "er", "--play"], velopack_module=vp,
                         popen=lambda args, **kw: started.append((args, kw)))  # fmt: skip
    assert vp.calls[0] == ("source", str(prepared.folder))
    assert vp.calls[-1] == ("apply", True, True, ["--game", "er", "--play"])
    ((args, kw),) = started
    assert "99.0.0" in args and str(prepared.rollback) in args and kw["cwd"] == str(updates.state_dir())
    assert (
        updates.state_dir() / ("update-watchdog.ps1" if updates.OS_CHANNEL == "win" else "update-watchdog.sh")
    ).is_file()
    pending = settings.load_settings()["update_pending"]
    assert pending["version"] == "99.0.0" and pending["rollback"] == str(prepared.rollback)


def test_apply_refuses_without_a_rollback_copy_or_with_another_target(tmp_path, monkeypatch):
    _managed(monkeypatch, tmp_path)
    prepared = fakerelease.make().download(workdir=tmp_path / "dl")
    with pytest.raises(updates.UpdateError, match="put this version back"):
        updates.apply_update(prepared, velopack_module=_FakeVelopack(), popen=lambda *a, **k: None)
    prepared.rollback = tmp_path / "kept.nupkg"
    prepared.rollback.write_bytes(b"previous")
    with pytest.raises(updates.UpdateError, match="did not match"):
        updates.apply_update(prepared, velopack_module=_FakeVelopack(target="98.5.0"), popen=lambda *a, **k: None)
    assert settings.load_settings()["update_pending"] is None


def test_ready_finishes_a_pending_update(tmp_path):
    assert updates.mark_ready("window", current="99.0.0") is None  # nothing pending: just the marker
    assert (updates.state_dir() / "ready-99.0.0").is_file()
    settings.save_settings(update_pending={"version": "99.0.0", "from": "98.0.0", "started": 1.0})
    result = updates.mark_ready("play", current="99.0.0")
    assert result["status"] == "ok" and result["how"] == "play" and settings.load_settings()["update_pending"] is None


def test_a_rollback_is_reported_once_and_blocks_that_version():
    settings.save_settings(update_pending={"version": "99.0.0", "from": "98.0.0", "started": 1.0})
    state = updates.state_dir()
    state.mkdir(parents=True)
    (state / "rollback.json").write_text(
        '﻿{"version": "99.0.0", "reason": "it did not finish starting within 90 seconds"}', encoding="utf-8"
    )
    result = updates.update_outcome(current="98.0.0")
    assert result["status"] == "rolled_back" and result["version"] == "99.0.0" and "90 seconds" in result["error"]
    s = settings.load_settings()
    assert s["update_blocked"] == ["99.0.0"] and s["update_pending"] is None and not (state / "rollback.json").exists()
    fetch = _fetcher(updates.Fetched("ok", data=_rel("99.0.0")))
    check = updates.check_launcher_update(fetch=fetch, force=True, current="98.0.0")
    assert check.offer is None and check.blocked == "99.0.0"  # not even Check for updates offers it
    check = updates.check_launcher_update(
        fetch=_fetcher(updates.Fetched("ok", data=_rel("99.0.1"))), force=True, current="98.0.0"
    )
    assert check.offer["version"] == "99.0.1"  # a newer release is offered
    updates.clear_outcome()
    assert updates.update_outcome(current="98.0.0") is None


def test_an_update_that_never_applied_is_reported_after_the_watchdogs_time():
    settings.save_settings(update_pending={"version": "99.0.0", "from": "98.0.0", "started": 1000.0})
    assert updates.update_outcome(current="98.0.0", now=lambda: 1000.0 + 60) is None  # still being applied
    late = 1000.0 + updates.WATCHDOG_APPLY + updates.WATCHDOG_READY + 61
    result = updates.update_outcome(current="98.0.0", now=lambda: late)
    assert result["status"] == "failed" and settings.load_settings()["update_pending"] is None


def test_busy_reason_names_a_shortcut_play(monkeypatch):
    from roundtable_souls.system import instance

    monkeypatch.setattr(instance, "held", lambda name: name == instance.PLAY)
    assert "Steam shortcut" in updates.busy_reason()
    monkeypatch.setattr(instance, "held", lambda name: False)
    assert updates.busy_reason() == ""


def test_velopack_startup_never_auto_applies(monkeypatch):
    calls = []

    class App:
        def set_auto_apply_on_startup(self, value):
            calls.append(("auto", value))
            return self

        def run(self):
            calls.append(("run",))

    monkeypatch.setattr(updates, "velopack_root", lambda: None)
    monkeypatch.setattr(updates, "appimage", lambda: None)
    monkeypatch.setattr(updates, "_velopack", lambda: pytest.fail("not a Velopack copy"))
    updates.velopack_startup()
    monkeypatch.setattr(updates, "velopack_root", lambda: Path("x"))
    monkeypatch.setattr(updates, "_velopack", lambda: type("vp", (), {"App": App}))
    updates.velopack_startup()
    assert calls == [("auto", False), ("run",)]


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


def _frozen_at(monkeypatch, exe: Path):
    monkeypatch.setattr(settings, "FROZEN", True)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.delenv(settings.DATA_ENV, raising=False)
    monkeypatch.delenv("APPIMAGE", raising=False)


def test_data_never_lives_where_updates_or_uninstall_replace_files(tmp_path, monkeypatch):
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("XDG_DATA_HOME", str(local))
    root = tmp_path / "Carlomos7.RoundtableSouls"
    (root / "current").mkdir(parents=True)
    (root / "Update.exe").write_bytes(b"x")
    _frozen_at(monkeypatch, root / "current" / "RoundtableSouls.exe")
    assert settings.velopack_root() == root and settings.is_installed() and not settings.is_portable()
    assert settings.data_dir() == local / settings.APP_DIR_NAME  # installed: per-user app data
    (root / ".portable").write_text("")
    assert settings.is_portable() and not settings.is_installed()
    assert settings.data_dir() == root / "RoundtableSouls-data"  # portable: beside Update.exe, never in current\
    monkeypatch.setenv(settings.DATA_ENV, str(tmp_path / "explicit"))
    assert settings.data_dir() == tmp_path / "explicit"


def test_data_folder_and_install_folder_can_never_be_the_same(tmp_path, monkeypatch):
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("XDG_DATA_HOME", str(local))
    root = local / settings.APP_DIR_NAME  # an app ID equal to the data folder's name
    (root / "current").mkdir(parents=True)
    (root / "Update.exe").write_bytes(b"x")
    _frozen_at(monkeypatch, root / "current" / "RoundtableSouls.exe")
    with pytest.raises(RuntimeError, match="app ID must differ"):
        settings.data_dir()
    from roundtable_souls import identity

    assert identity.Identity().pack_id.lower() != identity.Identity().data_dir_name.lower()  # the release default


def test_appimage_and_raw_builds(tmp_path, monkeypatch):
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("XDG_DATA_HOME", str(local))
    mount = tmp_path / "mount"
    mount.mkdir()
    _frozen_at(monkeypatch, mount / "RoundtableSouls")
    assert settings.data_dir() == mount  # a build run straight from its folder keeps data beside itself
    monkeypatch.setenv("APPIMAGE", str(tmp_path / "RoundtableSouls.AppImage"))
    assert settings.data_dir() == local / settings.APP_DIR_NAME  # never the AppImage's read-only mount
    assert settings.launch_target() == tmp_path / "RoundtableSouls.AppImage"


def test_shortcuts_start_the_stub_not_the_replaceable_program(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "current").mkdir(parents=True)
    (root / "Update.exe").write_bytes(b"x")
    (root / "Roundtable Souls.exe").write_bytes(b"stub")
    _frozen_at(monkeypatch, root / "current" / "RoundtableSouls.exe")
    assert settings.launch_target() == root / "Roundtable Souls.exe"


def test_apply_refuses_when_the_build_is_not_this_installs(tmp_path, monkeypatch):
    _managed(monkeypatch, tmp_path)
    monkeypatch.setattr(updates, "identity_matches", lambda: False)
    prepared = fakerelease.make().download(workdir=tmp_path / "dl")
    prepared.rollback = tmp_path / "kept.nupkg"
    prepared.rollback.write_bytes(b"previous")
    with pytest.raises(updates.UpdateError, match="app ID"):
        updates.apply_update(
            prepared, velopack_module=_FakeVelopack(), popen=lambda *a, **k: pytest.fail("no watchdog")
        )


def test_identity_matches_reads_the_installed_app_id(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "current").mkdir(parents=True)
    (root / "Update.exe").write_bytes(b"x")
    _frozen_at(monkeypatch, root / "current" / "RoundtableSouls.exe")
    from roundtable_souls import identity

    (root / "current" / "sq.version").write_text(
        f"<package><metadata><id>{identity.get().pack_id}</id><version>1.0.0</version></metadata></package>"
    )
    assert settings.installed_pack_id() == identity.get().pack_id and settings.identity_matches()
    (root / "current" / "sq.version").write_text("<package><metadata><id>Someone.Else</id></metadata></package>")
    assert not settings.identity_matches()
    (root / "current" / "sq.version").unlink()
    assert not settings.identity_matches()  # unknown: treated as not ours
