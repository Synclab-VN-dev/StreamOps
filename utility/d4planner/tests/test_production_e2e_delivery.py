from __future__ import annotations

import argparse
import importlib.util
import io
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "utility/d4planner/tools/production_e2e.py"
spec = importlib.util.spec_from_file_location("production_e2e", TOOL)
production = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(production)


def test_performance_requires_native_capture_to_visible_evidence(tmp_path):
    args = argparse.Namespace(native_latency=tmp_path / "missing.json")
    with pytest.raises(production.E2EFailure, match="latency evidence is missing"):
        production.run_performance(args)


def test_performance_accepts_all_five_measured_stages(tmp_path):
    stages = {
        name: {
            "sampleCount": 2, "samplesMilliseconds": [1.0, 2.0],
            "p50Milliseconds": 1.5, "p95Milliseconds": 1.95,
        }
        for name in (
            "captureToAssessment", "assessmentToSqliteCommit", "commitToWsDelivery",
            "wsToHudModel", "hudModelToVisibleRender",
        )
    }
    source = tmp_path / "latency.json"
    source.write_text(json.dumps({
        "schemaVersion":"d4planner-latency-evidence/v1", "ok":True,
        "sla":"NOT_DEFINED_AS_APPROVED", **stages,
    }))
    result = production.run_performance(argparse.Namespace(native_latency=source))
    assert result["ok"] is True
    assert result["classification"] == "NATIVE_CAPTURE_TO_VISIBLE_STAGE_LATENCY"
    assert result["hudModelToVisibleRender"]["sampleCount"] == 2


def test_native_evidence_timestamp_parser_is_timezone_aware():
    value = production._parse_timestamp("2026-10-26T06:00:00Z")
    assert value.utcoffset().total_seconds() == 0


def test_backend_command_writes_case_specific_evidence_and_cleans_up(monkeypatch, tmp_path):
    data = tmp_path / "data"; data.mkdir()
    targets = data / "targets"; targets.mkdir()
    evidence = data / "equipment.json"; evidence.write_text("{}")
    monkeypatch.setattr(production, "_prepare", lambda install, root: (targets, evidence, "a" * 64))
    monkeypatch.setattr(production, "_runtime_env", lambda *args: {})
    monkeypatch.setattr(production, "_windows_descendants", lambda pid: [])

    socket_result = {
        "initialRevision": 1, "finalRevision": 3, "finalTargetId": "synthetic-target-b",
        "finalTargetSha256": "b" * 64, "authenticatedSubscriber": True,
        "gapFromRevision": 2, "resyncRevision": 3, "rollbackPrevented": True,
        "score": {"status":"SCORED", "value":100.0}, "targetCountBeforeSwitch": 1,
    }
    async def socket_flow(*args, **kwargs):
        return socket_result
    monkeypatch.setattr(production, "_socket_flow", socket_flow)

    durable = {
        "hudRevision":3, "context":{"state":"BOUND"},
        "score":{"status":"SCORED","value":100.0}, "equipment":[{"slotId":"gloves"}],
    }
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, statement):
            if "count(*)" in statement: return type("Cursor", (), {"fetchone":lambda self: (2,)})()
            return type("Cursor", (), {"fetchone":lambda self: (3, json.dumps(durable))})()
    monkeypatch.setattr(production.sqlite3, "connect", lambda path: Connection())

    class Input:
        def __init__(self): self.lines = []
        def write(self, value): self.lines.append(value)
        def flush(self): pass
    class Process:
        pid = 4321
        def __init__(self):
            self.stdin = Input(); self.stderr = io.StringIO(); self.returncode = None; self.killed = False
            self.stdout = io.StringIO(json.dumps({
                "event":"READY", "pid":self.pid,
                "health":{"ruleKitWorker":"READY","targetRepository":"READY",
                          "durableState":"READY","wsTransport":"READY"},
                "wsEndpoint":{"host":"127.0.0.1","port":38150},
            }) + "\n")
        def poll(self): return self.returncode
        def wait(self, timeout): self.returncode = 0; return 0
        def kill(self): self.killed = True; self.returncode = -9
    process = Process()
    monkeypatch.setattr(production.subprocess, "Popen", lambda *args, **kwargs: process)

    output = tmp_path / "evidence.json"
    exit_code = production.main([
        "backend", "--install-root", str(tmp_path / "install"),
        "--data-root", str(data), "--output", str(output),
    ])
    assert exit_code == 0
    result = json.loads(output.read_text())
    assert result["acceptance"] == {"e2e03":True,"e2e04":True,"e2e05":True,"e2e06":True}
    assert result["sqlite"]["hudRevision"] == result["socket"]["resyncRevision"] == 3
    assert process.killed is False
    assert any('"type": "shutdown"' in line for line in process.stdin.lines)
    assert not (data / "private-bootstrap.json").exists()


def test_backend_early_failure_cleans_owned_process_without_name_error(monkeypatch, tmp_path):
    data = tmp_path / "data"; data.mkdir(); targets = data / "targets"; targets.mkdir()
    evidence = data / "equipment.json"; evidence.write_text("{}")
    monkeypatch.setattr(production, "_prepare", lambda install, root: (targets, evidence, "a" * 64))
    monkeypatch.setattr(production, "_runtime_env", lambda *args: {})
    class Input:
        def write(self, value): raise BrokenPipeError
        def flush(self): pass
    class Process:
        pid = 9876
        stdin = Input()
        stdout = io.StringIO("")
        stderr = io.StringIO("startup failed")
        returncode = None
        killed = False
        def poll(self): return self.returncode
        def kill(self): self.killed = True; self.returncode = -9
        def wait(self, timeout): return self.returncode
    process = Process()
    monkeypatch.setattr(production.subprocess, "Popen", lambda *args, **kwargs: process)
    output = tmp_path / "failure.json"
    assert production.main([
        "backend", "--install-root", str(tmp_path / "install"),
        "--data-root", str(data), "--output", str(output),
    ]) == 1
    assert process.killed is True
    assert not output.exists()
    assert not (data / "private-bootstrap.json").exists()
