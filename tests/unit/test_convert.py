"""Standard -> Seamless Co-op copy (.sl2 -> .co2): a byte copy with a backup of whatever it overwrites."""

import pytest

from roundtable_souls.platform import paths
from roundtable_souls.saves import backups as save_backups
from roundtable_souls.services import saves as saves_service
from support import er


def test_sl2_to_co2_copies_and_backs_up(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "exe_running", lambda _exe: False)
    src = tmp_path / "ER0000.sl2"
    src.write_bytes(b"standard")
    out = saves_service.convert_sl2_to_co2(src, loc=er())
    assert out == tmp_path / "ER0000.co2" and out.read_bytes() == b"standard"
    out.write_bytes(b"older coop")
    saves_service.convert_sl2_to_co2(src, loc=er())
    assert out.read_bytes() == b"standard"
    backups = [p for p in save_backups.backups(tmp_path).iterdir() if p.suffix == ".bak"]
    assert [p.read_bytes() for p in backups] == [b"older coop"]  # only the file that was replaced
    assert saves_service.list_backups(out, loc=er())[0]["action"] == "Before copying the standard save over it"


def test_sl2_to_co2_refusals(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "exe_running", lambda _exe: False)
    with pytest.raises(RuntimeError):
        saves_service.convert_sl2_to_co2(tmp_path / "ER0000.co2", loc=er())
    monkeypatch.setattr(paths, "exe_running", lambda _exe: True)
    src = tmp_path / "ER0000.sl2"
    src.write_bytes(b"x")
    with pytest.raises(RuntimeError):
        saves_service.convert_sl2_to_co2(src, loc=er())
