"""The launcher's own update check: daily cache, skip-this-version, and the Tools toggle."""

from roundtable_souls import __version__, settings, updates


def _bump(v: str) -> str:
    a, b, c = (int(x) for x in v.split("."))
    return f"{a}.{b}.{c + 1}"


def test_newer_release_is_reported_and_cached():
    calls = []
    newer = _bump(__version__)

    def fetch(url):
        calls.append(url)
        return {"version": newer, "url": "https://example.test/rel"}

    clock = [1000.0]
    out = updates.launcher_update(fetch=fetch, now=lambda: clock[0])
    assert out == {"version": newer, "url": "https://example.test/rel", "assets": {}} and calls == [
        updates.RELEASES_LATEST
    ]
    assert settings.load_settings()["launcher_latest"]["version"] == newer
    clock[0] += 3600
    assert updates.launcher_update(fetch=fetch, now=lambda: clock[0]) == out and len(calls) == 1  # cached
    clock[0] += updates.CHECK_EVERY
    updates.launcher_update(fetch=fetch, now=lambda: clock[0])
    assert len(calls) == 2  # a day later it asks again


def test_same_or_older_release_is_quiet():
    assert updates.launcher_update(fetch=lambda url: {"version": __version__, "url": ""}) is None
    assert updates.launcher_update(fetch=lambda url: {"version": "0.1.0", "url": ""}) is None
    assert updates.launcher_update(fetch=lambda url: None) is None  # offline, nothing cached


def test_skip_and_toggle():
    newer = _bump(__version__)
    fetch = lambda url: {"version": newer, "url": ""}
    out = updates.launcher_update(fetch=fetch)
    assert out and out["url"] == updates.RELEASES_URL  # empty url falls back to the releases page
    updates.skip_update(newer)
    assert updates.launcher_update(fetch=fetch) is None
    assert updates.launcher_update(fetch=lambda url: {"version": _bump(newer), "url": ""}) is None  # still cached
    settings.save_settings(launcher_latest=None, launcher_latest_checked=0.0)
    assert updates.launcher_update(fetch=lambda url: {"version": _bump(newer), "url": ""})  # a newer one shows again
    settings.save_settings(check_launcher_updates=False)
    assert updates.launcher_update(fetch=fetch) is None
    assert updates.launcher_update(fetch=fetch, force=True)  # Check now ignores the toggle, the cache and the skip


def test_force_refetches_even_when_cached(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        return {"version": __version__, "url": ""}

    assert updates.launcher_update(fetch=fetch) is None and len(calls) == 1
    assert updates.launcher_update(fetch=fetch) is None and len(calls) == 1  # cached
    assert updates.launcher_update(fetch=fetch, force=True) is None and len(calls) == 2


# ---------------------------------------------------------------- download, verify, swap


def _release(tmp_path, exe_bytes=b"new exe", corrupt=False):
    import hashlib
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("RoundtableSouls.exe", exe_bytes)
        z.writestr("How to use.txt", "hi")
    data = buf.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    sums = f"{'0' * 64 if corrupt else digest}  RoundtableSouls.zip\n{'1' * 64}  RoundtableSouls.exe\n".encode()
    urls = {"https://x/zip": data, "https://x/sums": sums}
    calls = []

    def opener(url, progress=None):
        calls.append(url)
        if progress:
            progress(len(urls[url]), len(urls[url]))
        return urls[url]

    info = {
        "version": "9.9.9",
        "url": "",
        "assets": {"RoundtableSouls.zip": "https://x/zip", "SHA256SUMS.txt": "https://x/sums"},
    }
    return info, opener, calls


def test_parse_checksums_accepts_sha256sum_output():
    text = "ab" * 32 + "  RoundtableSouls.zip\n" + "cd" * 32 + " *RoundtableSouls.exe\nnot a line\n"
    assert updates.parse_checksums(text) == {"RoundtableSouls.zip": "ab" * 32, "RoundtableSouls.exe": "cd" * 32}


def test_download_update_verifies_and_unpacks(tmp_path):
    info, opener, calls = _release(tmp_path)
    seen = []
    exe = updates.download_update(
        info, opener=opener, progress=lambda d, t: seen.append((d, t)), workdir=tmp_path, platform="win32"
    )
    assert exe.name == "RoundtableSouls.exe" and exe.read_bytes() == b"new exe" and exe.parent.parent == tmp_path
    assert calls == ["https://x/sums", "https://x/zip"] and seen and seen[-1][0] == seen[-1][1]


def test_download_update_refuses_bad_checksum_or_missing_assets(tmp_path):
    import pytest

    info, opener, _ = _release(tmp_path, corrupt=True)
    with pytest.raises(updates.UpdateError):
        updates.download_update(info, opener=opener, workdir=tmp_path, platform="win32")
    with pytest.raises(updates.UpdateError):
        updates.download_update(
            {"assets": {"RoundtableSouls.zip": "https://x/zip"}}, opener=opener, workdir=tmp_path, platform="win32"
        )
    assert not any(p.is_dir() and any(p.iterdir()) and (p / "RoundtableSouls.exe").exists() for p in tmp_path.iterdir())


def test_apply_update_swaps_and_parks_then_cleanup(tmp_path):
    current = tmp_path / "RoundtableSouls.exe"
    current.write_bytes(b"old exe")
    new = tmp_path / "dl" / "RoundtableSouls.exe"
    new.parent.mkdir()
    new.write_bytes(b"new exe")
    parked = updates.apply_update(new, current, restart=False)
    assert (
        current.read_bytes() == b"new exe"
        and parked.read_bytes() == b"old exe"
        and parked.name == "RoundtableSouls.old.exe"
    )
    assert not new.exists()
    assert updates.remove_parked_exe(current) is True and not parked.exists()
    assert updates.remove_parked_exe(current) is True  # nothing to do is fine


def test_relaunch_drops_pyinstaller_markers(tmp_path, monkeypatch):
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "x")
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "y")
    monkeypatch.setenv("_MEIPASS2", "z")
    monkeypatch.setenv("PATH_KEEP_ME", "1")
    env = updates.child_environment()
    assert "PATH_KEEP_ME" in env and not any(k.startswith(("_PYI_", "_MEIPASS")) for k in env)
    current = tmp_path / "RoundtableSouls.exe"
    current.write_bytes(b"old")
    new = tmp_path / "new.exe"
    new.write_bytes(b"new")
    seen = {}

    def fake_popen(args, **kw):
        seen.update(kw, args=args)

    monkeypatch.setattr(updates.subprocess, "Popen", fake_popen)
    updates.apply_update(new, current, restart=True)
    assert (
        seen["args"] == [str(current)] and "_PYI_ARCHIVE_FILE" not in seen["env"] and seen["env"]["PATH_KEEP_ME"] == "1"
    )


def test_apply_update_restores_on_failure(tmp_path):
    import pytest

    current = tmp_path / "RoundtableSouls.exe"
    current.write_bytes(b"old exe")
    with pytest.raises(FileNotFoundError):
        updates.apply_update(tmp_path / "missing.exe", current, restart=False)
    assert current.read_bytes() == b"old exe" and not current.with_name("RoundtableSouls.old.exe").exists()


def test_installed_copy_downloads_and_verifies_the_setup(tmp_path, monkeypatch):
    import hashlib

    import pytest

    setup_bytes = b"MZ fake setup"
    sums = f"{hashlib.sha256(setup_bytes).hexdigest()}  {updates.SETUP_NAME}\n".encode()
    urls = {"https://x/setup": setup_bytes, "https://x/sums": sums}
    info = {
        "version": "9.9.9",
        "assets": {updates.SETUP_NAME: "https://x/setup", updates.CHECKSUMS_NAME: "https://x/sums"},
    }
    opener = lambda url, progress=None: urls[url]
    assert updates.can_self_update(info, installed=True, platform="win32") and not updates.can_self_update(
        info, installed=False, platform="win32"
    )
    setup = updates.download_update(info, opener=opener, workdir=tmp_path, installed=True, platform="win32")
    assert setup.name == updates.SETUP_NAME and setup.read_bytes() == setup_bytes
    urls["https://x/setup"] = b"tampered"
    with pytest.raises(updates.UpdateError):
        updates.download_update(info, opener=opener, workdir=tmp_path, installed=True, platform="win32")
    seen = {}
    monkeypatch.setattr(updates.subprocess, "Popen", lambda args, **kw: seen.update(kw, args=args))
    updates.run_installer(setup)
    assert seen["args"][0] == str(setup) and "/VERYSILENT" in seen["args"] and "/RELAUNCH=1" in seen["args"]


def test_install_kind_is_detected_from_the_uninstaller(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "FROZEN", True)
    monkeypatch.setattr(settings, "exe_dir", lambda: tmp_path)
    assert not settings.is_installed()
    (tmp_path / "unins000.exe").write_bytes(b"x")
    assert settings.is_installed()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "local"))
    assert (
        settings.data_dir() == tmp_path / "local" / settings.APP_DIR_NAME
    )  # installed copies never write beside the exe
