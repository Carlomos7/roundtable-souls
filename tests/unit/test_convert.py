"""Standard -> Seamless Co-op copy (.sl2 -> .co2): a byte copy with a backup of whatever it overwrites."""

import pytest

from roundtable_souls import core as g


def test_sl2_to_co2_copies_and_backs_up(tmp_path, monkeypatch):
    monkeypatch.setattr(g.common, "game_running", lambda: False)
    src = tmp_path / "ER0000.sl2"
    src.write_bytes(b"standard")
    out = g.convert_sl2_to_co2(src)
    assert out == tmp_path / "ER0000.co2" and out.read_bytes() == b"standard"
    out.write_bytes(b"older coop")
    g.convert_sl2_to_co2(src)
    assert out.read_bytes() == b"standard"
    backups = list((tmp_path / "sl2-to-co2-backups").iterdir())
    assert any(p.name.startswith("ER0000.co2.") and p.read_bytes() == b"older coop" for p in backups)
    assert any(p.name.startswith("ER0000.sl2.") and p.suffix == ".src" for p in backups)


def test_sl2_to_co2_refusals(tmp_path, monkeypatch):
    monkeypatch.setattr(g.common, "game_running", lambda: False)
    with pytest.raises(RuntimeError):
        g.convert_sl2_to_co2(tmp_path / "ER0000.co2")
    monkeypatch.setattr(g.common, "game_running", lambda: True)
    src = tmp_path / "ER0000.sl2"
    src.write_bytes(b"x")
    with pytest.raises(RuntimeError):
        g.convert_sl2_to_co2(src)
