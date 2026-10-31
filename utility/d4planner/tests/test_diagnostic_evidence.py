import json
import sqlite3
from pathlib import Path
import pytest
from d4planner.diagnostic_evidence import export


def test_wal_snapshot_and_selected_sources(tmp_path):
    root = tmp_path / "capture"
    (root / "state").mkdir(parents=True)
    (root / "sessions" / "test").mkdir(parents=True)
    db = root / "state/events.db"
    with sqlite3.connect(db) as con:
        con.execute("pragma journal_mode=WAL")
        con.execute("create table events(value)")
        con.execute("insert into events values('SYNTHETIC_PRIVATE_EVIDENCE')")
        con.commit()
        (root / "sessions/test/equipment-projector.jsonl").write_text(
            '{"synthetic":true}\n{"partial":'
        )
        report = export(root, "test", tmp_path / "out", True)
        with sqlite3.connect(tmp_path / "out/events.db") as snapshot:
            assert snapshot.execute("select value from events").fetchone() == (
                "SYNTHETIC_PRIVATE_EVIDENCE",
            )
        assert (
            tmp_path / "out/equipment-projector.jsonl"
        ).read_text() == '{"synthetic":true}\n'
        assert len(report["files"]) == 2
        assert con.execute("select count(*) from events").fetchone() == (1,)


def test_consent_path_missing_corrupt(tmp_path):
    root = tmp_path / "capture"
    (root / "state").mkdir(parents=True)
    (root / "state/events.db").write_bytes(b"not sqlite")
    with pytest.raises(ValueError):
        export(root, "test", tmp_path / "out", False)
    with pytest.raises(ValueError):
        export(root, "../unsafe", tmp_path / "out", True)
    result = export(root, "test", tmp_path / "out", True)
    assert all(x["status"] == "UNAVAILABLE" for x in result["files"])
    assert list((tmp_path / "out").iterdir()) == []


def test_evidence_symlink_rejected(tmp_path):
    root = tmp_path / "root"
    (root / "state").mkdir(parents=True)
    outside = tmp_path / "private"
    outside.write_text("CANARY")
    (root / "state/events.db").symlink_to(outside)
    result = export(root, "session", tmp_path / "out", True)
    assert result["files"][0]["status"] == "UNAVAILABLE"
    assert outside.read_text() == "CANARY"
