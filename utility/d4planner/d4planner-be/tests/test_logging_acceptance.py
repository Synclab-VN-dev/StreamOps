"""Evidence validator negatives; these tests are not LOG-09/10 native PASS."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from logging_acceptance import comparison, log_evidence, percentiles
from windows_logging_setup_e2e import inventory, preserved, seed_upgrade_data


@pytest.mark.parametrize("values", [[], [-1], [float("nan")], [float("inf")]])
def test_invalid_measurements_are_not_pass(values):
    with pytest.raises(ValueError):
        percentiles(values)


def test_quantiles_preserve_samples_and_signed_overhead():
    result = comparison([10, 20, 30], [11, 22, 33])
    assert result["baseline"]["p50"] == 20
    assert result["baseline"]["p95"] == 29
    assert result["p50Overhead"] == 2
    assert result["p50OverheadPercent"] == 10
    assert result["INFO"]["samples"] == [11, 22, 33]
    assert comparison([0], [1])["p50OverheadPercent"] is None


def logs(tmp_path):
    folder = tmp_path / "logs/run"; folder.mkdir(parents=True)
    for name, component in (("fe.log", "FE"), ("be.log", "BE"), ("rulekit.log", "RULEKIT")):
        rows = [{"schemaVersion": "d4planner-runtime-log/v1", "event": event, "component": component,
                 "runId": "same", "ts": "2026-11-03T00:00:00Z", "fields": {}} for event in ("SESSION_HEADER", "READY")]
        (folder / name).write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return folder


def test_three_files_and_common_identity_required(tmp_path):
    folder = logs(tmp_path)
    assert log_evidence(tmp_path)["runId"] == "same"
    path = folder / "be.log"
    path.write_text(path.read_text().replace('"same"', '"different"'))
    with pytest.raises(AssertionError, match="runId"):
        log_evidence(tmp_path)


def test_selected_run_does_not_mix_historical_identity(tmp_path):
    import shutil
    folder = logs(tmp_path)
    shutil.copytree(folder, folder.with_name("history"))
    with pytest.raises(AssertionError): log_evidence(tmp_path)
    assert log_evidence(tmp_path, "run")["runId"] == "same"
    with pytest.raises(AssertionError): log_evidence(tmp_path, "../run")


@pytest.mark.parametrize("fault", ["missing", "extra", "no-ready", "truncated"])
def test_missing_or_invalid_logs_cannot_pass(tmp_path, fault):
    folder = logs(tmp_path)
    if fault == "missing": (folder / "fe.log").unlink()
    if fault == "extra": (folder / "raw.log").write_text("unowned")
    if fault == "no-ready":
        path = folder / "rulekit.log"; path.write_text(path.read_text().replace('"READY"', '"START"'))
    if fault == "truncated":
        with (folder / "be.log").open("a") as stream: stream.write('{"event":')
    with pytest.raises((AssertionError, ValueError)):
        log_evidence(tmp_path)


@pytest.mark.parametrize("fault", ["changed", "removed"])
def test_user_data_preservation_detects_loss(tmp_path, fault):
    path = tmp_path / "user.sqlite3"; path.write_bytes(b"private fixture")
    before = inventory(tmp_path)
    assert preserved(tmp_path, before)["unchanged"]
    if fault == "changed": path.write_bytes(b"wrong")
    else: path.unlink()
    with pytest.raises(AssertionError): preserved(tmp_path, before)


def test_upgrade_fixture_does_not_downgrade_new_runtime_database(tmp_path):
    source, destination = tmp_path / "new-data", tmp_path / "old-data"
    destination.mkdir()
    for directory in ("logs", "state", "targets"):
        (source / directory).mkdir(parents=True)
        (source / directory / "user-file").write_bytes(b"preserved")
    for name in ("hud.sqlite3", "hud.sqlite3-wal", "hud.sqlite3-shm"):
        (source / "state" / name).write_bytes(b"newer schema")
    for name in ("settings.json", "user-owned.bin", "recorded-producer.sqlite3"):
        (source / name).write_bytes(b"preserved")
    (source / "launcher.json").write_text(json.dumps({"equipmentRepository": {"path": "old path"}}))
    seed_upgrade_data(source, destination)
    assert not list((destination / "state").glob("hud.sqlite3*"))
    assert (destination / "state/user-file").read_bytes() == b"preserved"
    assert (source / "state/hud.sqlite3").read_bytes() == b"newer schema"
    assert json.loads((destination / "launcher.json").read_text())["equipmentRepository"]["path"] == str(destination / "recorded-producer.sqlite3")
