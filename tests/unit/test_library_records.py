"""mods.records: the library's versioned records, their round trip, migrations and published schemas."""

from __future__ import annotations

import json

import pytest

from roundtable_souls.mods import records
from roundtable_souls.mods.records import (
    BuildRecord,
    OverhaulRecord,
    RecordError,
    SideEffectsRecord,
    SourcesRecord,
)

FACTS = {
    "merger_revision": 5,
    "ordering": "me3 sort_dependencies, me3 9b1e080 (me3 0.11.0 to 0.13.0)",
    "game_config_sha256": "c" * 64,
    "removal_choice": "removed: an inner file a mod's copy leaves out is left out of the result",
}

EXAMPLES = {
    OverhaulRecord: {
        "version": 1,
        "build": "nightreign-revive-lite",
        "fingerprint": "f" * 64,
        "installed": "2026-10-09T12:00:00Z",
        "from": "C:/Downloads/NightreignRevive-0.1.33-rc3.zip",
    },
    SourcesRecord: {
        "version": 1,
        "files": {
            "merge/chr/c0000.anibnd.dcx": {"from": "payload/mod/chr/c0000.anibnd.dcx", "sha256": "a" * 64},
            "hooks/revive.hks": {"from": "installer/revive.hks", "sha256": "b" * 64},
        },
    },
    BuildRecord: {
        "version": 1,
        **FACTS,
        "me3_version": "0.13.0",
        "game": {"archives": "0123456789abcdef", "regulation_sha256": "d" * 64, "regulation_version": "11711000"},
        "config_sha256": "e" * 64,
        "made_by": "Roundtable Souls 3.21.0",
        "packages": [{"path": "packages/hair/chr/c0000.anibnd.dcx", "sha256": "1" * 64}],
        "sources": "2" * 64,
        "order": ["hair", "map-for-goblins"],
    },
    SideEffectsRecord: {
        "version": 1,
        "changes": [
            {"entry": "ersc.dll", "setting": "enabled", "before": False, "before_set": True, "after": True},
            {"setting": "start_online", "before_set": False, "after": False},
        ],
    },
}


@pytest.mark.parametrize("kind", records.RECORDS)
def test_round_trip(kind):
    data = EXAMPLES[kind]
    rec = kind.read(json.dumps(data))
    again = kind.read(rec.text())
    assert again == rec
    for key, value in data.items():  # what was written reads back as written
        if value is not None:
            assert json.loads(rec.text())[key] == value


@pytest.mark.parametrize("kind", records.RECORDS)
def test_unknown_keys_newer_versions_and_bad_values_are_refused(kind):
    with pytest.raises(RecordError, match="surprise"):
        kind.read({**EXAMPLES[kind], "surprise": 1})
    with pytest.raises(RecordError, match="newer launcher"):
        kind.read({**EXAMPLES[kind], "version": 2})
    with pytest.raises(RecordError):
        kind.read({**EXAMPLES[kind], "version": "1"})
    with pytest.raises(RecordError, match="not JSON"):
        kind.read("{")
    with pytest.raises(RecordError, match="JSON object"):
        kind.read("[]")


def test_a_nested_unknown_key_is_refused():
    bad = json.loads(json.dumps(EXAMPLES[SourcesRecord]))
    bad["files"]["hooks/revive.hks"]["size"] = 3
    with pytest.raises(RecordError, match="size"):
        SourcesRecord.read(bad)


def test_load_and_unreadable_files(tmp_path):
    path = tmp_path / "roundtable.json"
    path.write_text(OverhaulRecord.read(EXAMPLES[OverhaulRecord]).text(), encoding="utf-8")
    assert OverhaulRecord.load(path).build == "nightreign-revive-lite"
    with pytest.raises(RecordError, match="could not be read"):
        OverhaulRecord.load(tmp_path / "missing.json")


def test_a_build_record_from_before_the_library_moves_forward():
    """Version 0 is what a build kept before the library: Combine's record, or the launcher's overhaul build in its
    installation.json."""
    combine = {
        "combined": 1,
        "made_by": "Roundtable Souls 3.20.0",
        "when": "2026-10-09 10:00:00",
        "files": {},
        "archives": "0123456789abcdef",
        **FACTS,
        "me3_version": None,
        "base": "C:/Game/regulation.bin",
        "base_sha256": "d" * 64,
        "base_version": "11711000",
        "packs": [{"name": "a", "path": "C:\\mods\\a\\regulation.bin", "sha256": "A" * 64}],
        "sources": [{"path": "C:\\Game\\regulation.bin", "sha256": "d" * 64}],
        "report": [],
        "output_sha256": "0" * 64,
    }
    rec = BuildRecord.read(combine)
    assert rec.version == 1 and rec.made_by == "Roundtable Souls 3.20.0"
    assert rec.game is not None and rec.game.archives == "0123456789abcdef"
    assert (rec.game.regulation_sha256, rec.game.regulation_version) == ("d" * 64, "11711000")
    assert [(p.path, p.sha256) for p in rec.packages] == [("C:/Game/regulation.bin", "d" * 64)]
    assert rec.merger_revision == 5
    manifest = {  # the engine's installation.json from 3.20, Revive's own keys around it
        "version": "0.1.33-rc3",
        "edition": "LITE",
        "sources": [{"path": "C:/p/mod/chr/c0000.anibnd.dcx", "sha256": "1" * 64}],
        "refreshProtocol": 1,
        "builtBy": "Roundtable Souls 3.20.0",
        "recipe": "nightreign-revive-lite",
        "buildKey": "k",
        "inputs": {**FACTS, "game": {"archives": "x"}, "config_sha256": "e" * 64},
    }
    rec = BuildRecord.read({**manifest, "version": 0})
    assert (rec.made_by, rec.config_sha256, rec.game and rec.game.archives) == (
        "Roundtable Souls 3.20.0",
        "e" * 64,
        "x",
    )
    with pytest.raises(RecordError, match="merger_revision"):  # facts it can't know aren't made up
        BuildRecord.read({"made_by": "x", "sources": []})


@pytest.mark.parametrize("kind", [OverhaulRecord, SourcesRecord, SideEffectsRecord])
def test_older_versions_move_forward_one_step_at_a_time(kind, monkeypatch):
    """No earlier version of these exists yet; a migration registered for one runs before the model is checked,
    each step after the one before."""
    seen = []

    def step(n):
        def run(data):
            seen.append(n)
            return data if n else {k: v for k, v in data.items() if k != "legacy"}

        return run

    old = {k: v for k, v in EXAMPLES[kind].items() if k != "version"} | {"legacy": True}
    with monkeypatch.context() as m:
        m.setattr(kind, "VERSION", 1)
        m.setattr(kind, "MIGRATIONS", {0: step(0)})
        assert kind.read(old) == kind.read(EXAMPLES[kind])
        assert seen == [0]
        m.setattr(kind, "MIGRATIONS", {})
        with pytest.raises(RecordError, match="version 0 can't be read"):
            kind.read(old)


@pytest.mark.parametrize("kind", records.RECORDS)
def test_the_published_schemas_are_the_models(kind):
    assert json.loads(records.schema_path(kind).read_text(encoding="utf-8")) == records.schema(kind)


def test_each_record_has_its_own_migrations():
    assert BuildRecord.MIGRATIONS and 0 in BuildRecord.MIGRATIONS
    assert all(k.MIGRATIONS == {} for k in (OverhaulRecord, SourcesRecord, SideEffectsRecord))
    assert (
        len({id(k.MIGRATIONS) for k in records.RECORDS} | {id(records.Record.MIGRATIONS)}) == len(records.RECORDS) + 1
    )
