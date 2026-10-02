"""Standard -> Seamless Co-op copy (.sl2 -> .co2): a byte copy with a backup of whatever it overwrites."""

import pytest

from roundtable_souls import folders
from roundtable_souls.services import play as g


def test_sl2_to_co2_copies_and_backs_up(tmp_path, monkeypatch):
    monkeypatch.setattr(g.common, "game_running", lambda: False)
    src = tmp_path / "ER0000.sl2"
    src.write_bytes(b"standard")
    out = g.convert_sl2_to_co2(src)
    assert out == tmp_path / "ER0000.co2" and out.read_bytes() == b"standard"
    out.write_bytes(b"older coop")
    g.convert_sl2_to_co2(src)
    assert out.read_bytes() == b"standard"
    backups = [p for p in folders.backups(tmp_path).iterdir() if p.suffix == ".bak"]
    assert [p.read_bytes() for p in backups] == [b"older coop"]  # only the file that was replaced
    assert g.list_backups(out)[0]["action"] == "Before copying the standard save over it"


def test_sl2_to_co2_refusals(tmp_path, monkeypatch):
    monkeypatch.setattr(g.common, "game_running", lambda: False)
    with pytest.raises(RuntimeError):
        g.convert_sl2_to_co2(tmp_path / "ER0000.co2")
    monkeypatch.setattr(g.common, "game_running", lambda: True)
    src = tmp_path / "ER0000.sl2"
    src.write_bytes(b"x")
    with pytest.raises(RuntimeError):
        g.convert_sl2_to_co2(src)
