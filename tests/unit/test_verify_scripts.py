"""The real-data checks in scripts/verify: where they may write, and the intended result they compare against."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

VERIFY = Path(__file__).resolve().parents[2] / "scripts" / "verify"
sys.path.insert(0, str(VERIFY))

import _common  # noqa: E402  # pyright: ignore[reportMissingImports]
import verify_output  # noqa: E402  # pyright: ignore[reportMissingImports]


def test_output_folder_is_refused_inside_the_repository():
    with pytest.raises(SystemExit):
        _common.output_dir(_common.REPO / "build", "check")


def test_output_folder_is_refused_inside_the_game(tmp_path):
    game = tmp_path / "Game"
    game.mkdir()
    with pytest.raises(SystemExit):
        _common.output_dir(game, "check", game)


def test_a_folder_with_someone_elses_files_is_left_alone(tmp_path):
    (tmp_path / "check").mkdir()
    (tmp_path / "check" / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(SystemExit):
        _common.output_dir(tmp_path, "check")
    assert (tmp_path / "check" / "notes.txt").read_text(encoding="utf-8") == "mine"


def test_a_folder_a_check_made_is_emptied_for_the_next_run(tmp_path):
    out = _common.output_dir(tmp_path, "check")
    (out / "old.json").write_text("{}", encoding="utf-8")
    again = _common.output_dir(tmp_path, "check")
    assert again == out and not (out / "old.json").exists() and (out / _common.OWNED).is_file()


def part(data: bytes, ident: int = 1) -> tuple[int, int, bytes]:
    return (ident, 0x40, data)


def test_intended_result_takes_the_last_change_and_lists_removals():
    van = {"a": part(b"a0"), "b": part(b"b0"), "c": part(b"c0")}
    first = {"a": part(b"a1"), "b": part(b"b0")}  # changes a, lacks c
    second = {"a": part(b"a0"), "b": part(b"b2"), "c": part(b"c0"), "d": part(b"d2", 9)}  # changes b, adds d
    want, texts, removals = verify_output.intended_parts(van, [("first", first), ("second", second)], None)
    assert want == {"a": part(b"a1"), "b": part(b"b2"), "d": part(b"d2", 9)}
    assert texts == {} and removals == [("c", "first")]


def test_a_text_table_two_mods_change_is_merged_entry_by_entry():
    enc = lambda d: json.dumps(d).encode()  # noqa: E731  (a stand-in text table)
    fmg = lambda b: {int(k): v for k, v in json.loads(b).items()}  # noqa: E731
    van = {"menu.fmg": part(enc({1: "one", 2: "two", 3: "three"}))}
    a = {"menu.fmg": part(enc({1: "ONE", 2: "two", 3: "three"}))}
    b = {"menu.fmg": part(enc({1: "one", 2: "TWO"}))}  # changes 2, lacks 3
    _want, texts, removals = verify_output.intended_parts(van, [("a", a), ("b", b)], fmg)
    assert texts == {"menu.fmg": {1: "ONE", 2: "TWO"}} and removals == []
