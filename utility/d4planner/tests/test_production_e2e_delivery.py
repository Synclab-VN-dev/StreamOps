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
                "health":{"ruleKitWorker":"UNAVAILABLE","targetRepository":"READY",
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


def test_public_runtime_environment_never_inherits_bundled_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv('D4_RULEKIT_PROFILE_JSON', '/private/profile.json')
    monkeypatch.setenv('D4_RULEKIT_SNAPSHOT_ROOT', '/private/snapshots')
    env = production._runtime_env(tmp_path / 'app', tmp_path / 'data/bootstrap.json', tmp_path / 'evidence.json')
    assert env['D4_RULEKIT_DATA_ROOT'] == str(tmp_path / 'data/rulekit')
    assert 'D4_RULEKIT_PROFILE_JSON' not in env
    assert 'D4_RULEKIT_SNAPSHOT_ROOT' not in env


def test_unavailable_rulekit_writes_blocker_evidence_with_nonzero_exit(monkeypatch, tmp_path):
    stopped = []
    class Client:
        async def snapshot_call(self, method):
            assert method == 'getActive'
            return {'active':None, 'calculationAvailability':'UNAVAILABLE', 'reason':'SNAPSHOT_NOT_SELECTED'}
    class Runtime:
        client = Client()
        async def start(self): return {'ready':True, 'calculationAvailability':'UNAVAILABLE'}
        async def stop(self): stopped.append(True)
    monkeypatch.setattr(production.RuleKitRuntimeService, 'from_environment', lambda values: Runtime())
    output = tmp_path / 'blocked.json'
    code = production.main(['rulekit', '--install-root', str(tmp_path / 'app'),
                            '--data-root', str(tmp_path / 'data'), '--output', str(output)])
    assert code == 2
    result = json.loads(output.read_text())
    assert result['ok'] is False
    assert result['status'] == 'BLOCKED'
    assert result['reason'] == 'SNAPSHOT_NOT_SELECTED'
    assert stopped == [True]


def test_native_target_delta_requires_independent_score_and_item_change():
    original = json.loads((ROOT / 'utility/d4planner/contracts/release1/v1/fixtures/target.valid.synthetic.json').read_text())
    changed = production._native_target_b(original)
    assert original['assessmentPolicy']['criteria'][0]['parameters'][0]['expected']['value'] == 8
    assert changed['canonicalBuild']['equipment']['slots'][0]['item']['affixes'][0]['values'] == [12]
    assert changed['assessmentPolicy']['criteria'][0]['parameters'][0]['expected']['value'] == 12
    def payload(score, warn, passing, glove_status):
        return {'score': {'value':score,'passedWeight':8 if score == 100 else 5,
                         'evaluableWeight':8,'failIssueCount':0,'warnCount':warn,
                         'itemsPassing':passing,'itemsTargeted':2},
                'equipment':[{'slotId':'gloves','status':glove_status}, {'slotId':'ring-1','status':'PASS'}]}
    before = payload(100, 0, 2, 'PASS')
    with pytest.raises(production.E2EFailure, match='HUD-02 independent'):
        production._assert_native_delta(before, before)
    production._assert_native_delta(before, payload(62.5, 1, 1, 'WARN'))


def test_native_fixture_scores_through_production_adapter_and_domain(tmp_path):
    from d4planner.release1.capture_adapter import EquipmentCaptureAdapter
    from d4planner.release1.assessment import EquipmentAssessmentService
    from d4planner.release1.target_repository import TargetRepository, TargetValidator
    folder = tmp_path / 'targets'; folder.mkdir()
    original = json.loads((ROOT / 'utility/d4planner/contracts/release1/v1/fixtures/target.valid.synthetic.json').read_text())
    (folder / 'a.json').write_text(json.dumps(original))
    (folder / 'b.json').write_text(json.dumps(production._native_target_b(original)))
    repo = TargetRepository(folder, tmp_path / 'selection.json', TargetValidator.from_contract_tree(ROOT))
    current = EquipmentCaptureAdapter().from_event(json.loads((ROOT / 'utility/d4planner/release1/equipment.recorded.synthetic.json').read_text()))
    listing = repo.list()
    results = []
    for name in ('synthetic-charge-bolt', 'synthetic-target-b'):
        entry = next(entry for entry in listing.entries if entry.target_id == name)
        target = repo.activate(entry.target_id, entry.content_sha256, listing.revision)
        result = EquipmentAssessmentService().assess(current, target)
        results.append({'score':result.score_payload(), 'equipment':result.rows})
    production._assert_native_delta(*results)
