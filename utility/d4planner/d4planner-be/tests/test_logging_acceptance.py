"""Evidence validator negatives; these tests are not LOG-09/10 native PASS."""
import json
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from logging_acceptance import comparison, log_evidence, percentiles, verify_resource_snapshots, collect_resource_evidence
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


def resource_row(pid, parent, second, **changes):
    return {"ProcessId": pid, "ParentProcessId": parent, "Name": "python.exe",
            "CreatedUtc": f"2026-11-03T15:00:{second:02d}.1234560Z",
            "KernelModeTime": 10, "UserModeTime": 20, "WorkingSetSize": 30,
            "ReadTransferCount": 40, "WriteTransferCount": 50, **changes}


def resource_snapshots(*rows):
    return {"identity": deepcopy(list(rows)), "counters": deepcopy(list(rows))}


def test_resource_totals_require_live_root_and_stable_ancestry():
    # An unrelated process may have exactly the same name as an owned child.
    raw = resource_snapshots(resource_row(1, 99, 10), resource_row(2, 1, 11),
                             resource_row(3, 2, 12), resource_row(4, 99, 13))
    unchanged = deepcopy(raw)
    valid = verify_resource_snapshots(1, [2, 3], raw, root_alive=True)
    assert valid["status"] == "MEASURED"
    assert [row["ProcessId"] for row in valid["accepted"]] == [2, 3]
    assert valid["totals"]["WorkingSetSize"] == 60
    partial = verify_resource_snapshots(1, [2, 3, 4], raw, root_alive=True)
    assert partial["status"] == "PARTIAL"
    assert partial["totals"] == valid["totals"]
    assert partial["rejected"] == [{"pid": 4, "reason": "PROCESS_OR_ANCESTOR_MISSING"}]
    assert raw == unchanged  # Neither evidence nor counters may be rewritten.


def test_resource_sampler_rejects_historical_system_pid_alias():
    # Same topology as the observed launcher PID / old smss PID alias. Names
    # deliberately match the real child: chronology, not a name denylist, wins.
    raw = resource_snapshots(resource_row(692, 99, 30), resource_row(900, 692, 31),
                             resource_row(708, 692, 1), resource_row(788, 692, 1),
                             resource_row(404, 788, 2), resource_row(1392, 788, 3))
    value = verify_resource_snapshots(692, [900, 708, 788, 404, 1392], raw, root_alive=True)
    assert value["status"] == "PARTIAL"
    assert [row["ProcessId"] for row in value["accepted"]] == [900]
    assert value["totals"]["UserModeTime"] == 20
    assert {r["reason"] for r in value["rejected"]} == {"PREDATES_RUN"}


def test_pid_reuse_during_collection_rejects_descendant_subtree():
    raw = resource_snapshots(resource_row(1, 99, 10), resource_row(2, 1, 11), resource_row(3, 2, 12))
    raw["counters"][1]["CreatedUtc"] = resource_row(2, 1, 20)["CreatedUtc"]
    value = verify_resource_snapshots(1, [2, 3], raw, root_alive=True)
    assert value["status"] == "NOT_MEASURED" and value["totals"] is None
    assert {r["reason"] for r in value["rejected"]} == {"PID_REUSED"}


def test_child_older_than_reused_parent_is_not_owned():
    raw = resource_snapshots(resource_row(1, 99, 10), resource_row(2, 1, 20), resource_row(3, 2, 15))
    value = verify_resource_snapshots(1, [2, 3], raw, root_alive=True)
    assert value["status"] == "PARTIAL"
    assert value["rejected"] == [{"pid": 3, "reason": "PARENT_PID_REUSED"}]


@pytest.mark.parametrize("creation", [None, "", "invalid", "2026-11-03T15:00:11"])
def test_missing_or_inaccessible_creation_time_is_not_zero_resource_pass(creation):
    raw = resource_snapshots(resource_row(1, 99, 10), resource_row(2, 1, 11, CreatedUtc=creation))
    value = verify_resource_snapshots(1, [2], raw, root_alive=True)
    assert value["status"] == "NOT_MEASURED"
    assert value["accepted"] == [] and value["totals"] is None


@pytest.mark.parametrize("fault", ["root-exited", "root-reused", "ancestor-exited", "counter-inaccessible"])
def test_incomplete_resource_evidence_never_claims_complete_measurement(fault):
    raw = resource_snapshots(resource_row(1, 99, 10), resource_row(2, 1, 11), resource_row(3, 2, 12))
    if fault == "root-reused": raw["counters"][0]["CreatedUtc"] = resource_row(1, 99, 20)["CreatedUtc"]
    if fault == "ancestor-exited": raw["counters"].pop(1)
    if fault == "counter-inaccessible": raw["counters"][2]["WorkingSetSize"] = None
    value = verify_resource_snapshots(1, [3], raw, root_alive=fault != "root-exited")
    assert value["status"] == "NOT_MEASURED" and value["totals"] is None


@pytest.mark.parametrize("fault", ["query-failed", "invalid-json", "timeout", "root-exited"])
def test_resource_collection_failure_is_nonfatal_and_audited(monkeypatch, fault):
    import subprocess
    from types import SimpleNamespace
    raw = resource_snapshots(resource_row(1, 99, 10), resource_row(2, 1, 11))
    polls = iter([None, 0 if fault == "root-exited" else None])
    process = SimpleNamespace(pid=1, poll=lambda: next(polls))
    def query(*args, **kwargs):
        if fault == "timeout": raise subprocess.TimeoutExpired("powershell.exe", 30)
        return SimpleNamespace(returncode=1 if fault == "query-failed" else 0, stderr="unavailable",
                               stdout="invalid" if fault == "invalid-json" else json.dumps(raw))
    monkeypatch.setattr(subprocess, "run", query)
    result = collect_resource_evidence(process, [{"pid": 2}])
    assert result["status"] == "NOT_MEASURED" and result["totals"] is None
    assert result["accepted"] == []
