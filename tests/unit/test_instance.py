"""One window at a time: the names (mutexes / lock files), a second start talking to the window, and --play handing
its Play to an open window. Every name here is unique to the test, so a real launcher on this PC is never touched."""

import os
import uuid

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QApplication

from roundtable_souls.platform import filelock, instance


@pytest.fixture
def name():
    return f"RoundtableSouls.Test.{uuid.uuid4().hex}"


def test_a_name_is_held_once_until_released(name):
    assert not instance.held(name)
    first = instance.acquire(name)
    assert first is not None and instance.held(name)
    assert instance.acquire(name) is None  # a second window (or this one again) does not get it
    first.release()
    first.release()  # twice is harmless
    assert not instance.held(name)
    again = instance.acquire(name)
    assert again is not None
    again.release()


def _wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_a_second_start_reaches_the_window(name):
    app = QApplication.instance() or QApplication([])
    server_name = name if os.name == "nt" else str(instance._lock_dir() / f"{name}.sock")
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    got = []

    def on_conn():
        while (sock := server.nextPendingConnection()) is not None:
            sock.readyRead.connect(lambda s=sock: got.append(bytes(s.readAll().data())))
            if sock.bytesAvailable():
                got.append(bytes(sock.readAll().data()))

    server.newConnection.connect(on_conn)
    assert server.listen(server_name)
    try:
        sent = []
        # the client blocks while the server's event loop runs, as in real life (two processes)
        import threading

        t = threading.Thread(target=lambda: sent.append(instance.send("play nr", name=server_name)))
        t.start()
        for _ in range(40):
            _wait(25)
            if got:
                break
        t.join(5)
        app.processEvents()
        assert sent == [True] and b"".join(got) == b"play nr\n"
    finally:
        server.close()
    assert instance.send("show", name=server_name + "-nobody") is False


def test_play_from_a_shortcut_hands_off_or_holds_the_play_name(monkeypatch):
    from roundtable_souls import cli
    from roundtable_souls.game import catalog as games
    from roundtable_souls.services import play as core

    played, sent = [], []
    monkeypatch.setattr(
        core, "play_headless", lambda settings, loc, notice=None: played.append(instance.held(instance.PLAY)) or 0
    )
    monkeypatch.setattr(instance, "WINDOW", f"RoundtableSouls.Test.{uuid.uuid4().hex}")
    monkeypatch.setattr(instance, "PLAY", f"RoundtableSouls.Test.{uuid.uuid4().hex}")
    monkeypatch.setattr(instance, "send", lambda msg, name=None: sent.append(msg) or True)
    nr = games.get("nightreign")
    assert cli.play_from_shortcut(nr) == 0 and played == [True] and sent == []  # no window: plays here
    assert not instance.held(instance.PLAY)  # released when Play ends
    window = instance.acquire(instance.WINDOW)
    try:
        assert cli.play_from_shortcut(nr) == 0 and sent == ["play nightreign"] and len(played) == 1
        hold = instance.acquire(instance.PLAY)
        monkeypatch.setattr(instance, "send", lambda msg, name=None: False)  # a window that does not answer
        assert cli.play_from_shortcut(nr) == 1  # a shortcut Play already runs
        hold.release()
    finally:
        window.release()


def test_file_lock_excludes_a_second_holder(tmp_path):
    target = tmp_path / "settings.json"
    with filelock.locked(target) as first:
        assert first
        with filelock.locked(target, timeout=0.2) as second:
            assert not second  # gave up after the timeout and ran anyway
    with filelock.locked(target, timeout=0.2) as again:
        assert again
