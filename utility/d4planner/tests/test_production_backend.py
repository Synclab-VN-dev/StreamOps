from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil

import pytest
from websockets.asyncio.client import connect

from d4planner.character.equipment.projector import EquipmentProjector
from d4planner.character.repository import (
    EquipmentProjectionView, EquipmentRepository, EquipmentRepositoryTransient,
)
from d4planner.production import (
    ORIGIN, ProductionBackendRuntime, RepositoryEquipmentEventSource,
    _resolve_repository_root,
)
from d4planner.rulekit import LaunchSpecification, RuleKitProcessWrapper, RuleKitRuntimeService


ROOT = Path(__file__).resolve().parents[3]
TARGET = ROOT / "utility/d4planner/contracts/release1/v1/fixtures/target.valid.synthetic.json"
WORKER = ROOT / "utility/d4planner/rulekit-worker/worker.js"
COMPOSITION = ROOT / "utility/d4planner/tests/fixtures/rulekit-test-composition.js"
CREDENTIAL = "production-integration-test-credential-000000"


def _rulekit() -> RuleKitRuntimeService:
    return RuleKitRuntimeService(RuleKitProcessWrapper(LaunchSpecification(
        executable="node", args=(str(WORKER),), working_directory=ROOT,
        environment_allow_list={"D4_RULEKIT_COMPOSITION_MODULE": str(COMPOSITION)},
        readiness_timeout=3, graceful_stop_timeout=2, kill_timeout=1,
        operation_timeout=1, max_pending=8,
    )))


def _message(message_id: str, kind: str, generation: int, **extra):
    return {
        "protocolVersion": "d4planner-ws/v1", "messageId": message_id,
        "type": kind, "correlationId": None, "backendGeneration": generation, **extra,
    }


def _evidence(revision: int = 1) -> dict:
    def value(number, unit):
        return {"type": "NUMBER", "value": number, "unit": unit, "evidence": "OBSERVED"}
    def entity(kind, group, entity_id, values):
        return {"kind": kind, "group": group, "entityId": entity_id, "occurrence": 0,
                "label": entity_id, "values": values}
    return {
        "schemaVersion": "d4planner-equipment-evidence/v1",
        "characterId": "recorded-character", "characterDisplayName": "Recorded Character",
        "currentRevision": revision, "capturedAt": f"2026-10-26T03:00:0{revision}Z",
        "captureHealth": "HEALTHY",
        "slots": [{
            "slotId": "gloves", "presence": "OBSERVED", "evidence": ["COMPLETE_SLOT"],
            "item": {"itemId": "recorded-gloves", "displayName": "Recorded Gloves",
                     "observedAt": f"2026-10-26T03:00:0{revision}Z", "source": "RECORDED_CAPTURE",
                     "entities": [
                         entity("AFFIX", "AFFIXES", "attack-speed", [value(9, "PERCENT")]),
                         entity("AFFIX", "AFFIXES", "core-skill-ranks", [value(2, "RANK")]),
                         entity("EFFECT", "ASPECTS", "charge-bolt-core-effect", [value(10, "PERCENT"), value(2, "FLAT")]),
                     ]},
        }, {
            "slotId": "ring-1", "presence": "OBSERVED", "evidence": ["COMPLETE_SLOT"],
            "item": {"itemId": "recorded-ring", "displayName": "Recorded Ring",
                     "observedAt": f"2026-10-26T03:00:0{revision}Z", "source": "RECORDED_CAPTURE",
                     "entities": [entity("AFFIX", "AFFIXES", "resource-cost-reduction", [value(6, "PERCENT")])]},
        }],
    }


def test_production_runtime_real_worker_target_capture_sqlite_and_authenticated_ws(tmp_path, monkeypatch):
    trace = tmp_path / "latency.ndjson"
    monkeypatch.setenv("D4PLANNER_LATENCY_TRACE", str(trace.resolve()))
    async def scenario():
        targets = tmp_path / "targets"; targets.mkdir()
        shutil.copy2(TARGET, targets / "target.json")
        bootstrap = {
            "ownerInstanceId": "owner-production", "childInstanceId": "backend-production",
            "generation": 7, "dataDir": str(tmp_path / "data"), "targetFolder": str(targets),
            "wsEndpoint": {"host": "127.0.0.1", "port": 0}, "credential": CREDENTIAL,
        }
        runtime = ProductionBackendRuntime(bootstrap, rulekit=_rulekit())
        ready = await runtime.start()
        assert ready["health"]["ruleKitWorker"] == "READY"
        assert ready["health"]["wsTransport"] == "READY"
        assert ready["wsEndpoint"]["port"] > 0
        uri = f"ws://127.0.0.1:{ready['wsEndpoint']['port']}"
        try:
            async with connect(uri, origin=ORIGIN, ping_interval=None) as ws:
                await ws.send(json.dumps(_message(
                    "hello", "hello", 7, credential=CREDENTIAL, origin=ORIGIN,
                    lastSeen={"hudRevision": None},
                )))
                accepted = json.loads(await ws.recv())
                assert accepted["type"] == "hello.accepted"
                await ws.send(json.dumps(_message("list", "target.list.request", 7)))
                listed = json.loads(await ws.recv())
                target = next(item for item in listed["targets"] if item["validation"] == "VALID")
                await ws.send(json.dumps(_message(
                    "snapshot", "hud.snapshot.request", 7,
                    requestContext={"mode": "DISCOVER_ACTIVE_CONTEXT", "reason": "INITIAL_CONNECTION",
                                    "attempt": 1, "runtimeInstanceId": "backend-production", "minimumHudRevision": 0},
                )))
                snapshot = json.loads(await ws.recv())
                assert snapshot["hud"]["context"]["state"] == "STARTUP"
                await ws.send(json.dumps(_message(
                    "select", "target.select.request", 7, targetId=target["targetId"],
                    expectedSha256=target["contentSha256"], expectedListRevision=listed["listRevision"],
                )))
                selection_messages = [json.loads(await ws.recv()), json.loads(await ws.recv())]
                selected = next(message for message in selection_messages if message["type"] == "target.select.result")
                assert selected["status"] == "ACTIVATED"
                committed = await runtime.ingest(_evidence())
                update = json.loads(await asyncio.wait_for(ws.recv(), 1))
                assert update["type"] == "hud.update"
                assert update["hud"]["hudRevision"] == committed["hudRevision"]
                assert update["hud"]["score"] == {
                    **update["hud"]["score"], "status": "SCORED", "value": 100.0,
                    "passedWeight": 8, "evaluableWeight": 8, "failIssueCount": 0,
                    "warnCount": 0, "itemsPassing": 2, "itemsTargeted": 2,
                }
                assert runtime.store.latest_authoritative()["context"]["binding"]["targetId"] == target["targetId"]
                assert (tmp_path / "data/hud.sqlite3").is_file()
                latency = json.loads(trace.read_text().splitlines()[-1])
                assert latency["hudRevision"] == committed["hudRevision"]
                assert latency["captureToAssessmentNs"] >= 0
                assert latency["assessmentToCommitNs"] >= 0
                assert latency["commitToWsDeliveryNs"] >= 0
                try:
                    await runtime.ingest(_evidence())
                except ValueError as exc:
                    assert str(exc) == "STALE_CURRENT_REVISION"
                else:
                    raise AssertionError("duplicate current revision was accepted")
        finally:
            await runtime.stop()
        assert runtime.rulekit.wrapper._child is None

    asyncio.run(scenario())


def test_production_runtime_applies_explicit_recorded_evidence_before_ready(tmp_path, monkeypatch):
    async def scenario():
        targets = tmp_path / "targets"; targets.mkdir()
        target_path = targets / "target.json"
        shutil.copy2(TARGET, target_path)
        document = json.loads(target_path.read_text())
        digest = __import__("hashlib").sha256(target_path.read_bytes()).hexdigest()
        data = tmp_path / "data"; data.mkdir()
        (data / "selected-target.json").write_text(json.dumps({
            "targetId": document["targetId"], "contentSha256": digest,
            "selectionRevision": 1,
            "policyVersion": document["assessmentPolicy"]["version"] + "+" +
                document["assessmentPolicy"]["weightProfile"]["profileId"],
        }))
        evidence = tmp_path / "recorded-equipment.json"
        evidence.write_text(json.dumps(_evidence()))
        monkeypatch.setenv("D4PLANNER_EQUIPMENT_EVIDENCE_FILE", str(evidence.resolve()))
        runtime = ProductionBackendRuntime({
            "ownerInstanceId": "owner-recorded", "childInstanceId": "backend-recorded",
            "generation": 4, "dataDir": str(data), "targetFolder": str(targets),
            "wsEndpoint": {"host": "127.0.0.1", "port": 0}, "credential": CREDENTIAL,
        }, rulekit=_rulekit())
        try:
            ready = await runtime.start()
            assert ready["health"]["equipmentCapture"] == "RECORDED_EVIDENCE_APPLIED"
            latest = runtime.store.latest_authoritative()
            assert latest["score"]["value"] == 100.0
            assert latest["context"]["binding"]["targetId"] == document["targetId"]
        finally:
            await runtime.stop()
    asyncio.run(scenario())


def test_packaged_contract_root_is_explicit_and_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("D4PLANNER_REPOSITORY_ROOT", "relative")
    with pytest.raises(ValueError, match="contract repository root"):
        ProductionBackendRuntime({
            "ownerInstanceId": "owner", "childInstanceId": "child", "generation": 1,
            "dataDir": str(tmp_path / "data"), "targetFolder": str(tmp_path / "targets"),
            "wsEndpoint": {"host": "127.0.0.1", "port": 0}, "credential": CREDENTIAL,
        }, rulekit=_rulekit())


def test_packaged_contract_root_is_discovered_from_embedded_module(tmp_path):
    install = tmp_path / "install"
    for relative in (
        "utility/d4planner/contracts/release1/v1/schemas/target.schema.json",
        "utility/d4-rulekit/providers/maxroll/d4-build-v1.schema.json",
    ):
        path = install / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    module = install / "backend/site-packages/d4planner/production.py"
    module.parent.mkdir(parents=True)
    module.touch()
    assert _resolve_repository_root(None, module) == install.resolve()


def test_repository_capture_revision_commits_and_pushes_without_fuzzy_identity(tmp_path, monkeypatch):
    async def scenario():
        targets = tmp_path / "targets"; targets.mkdir()
        data = tmp_path / "data"; data.mkdir()
        repository_path = tmp_path / "capture" / "character.db"
        repository = EquipmentRepository(repository_path)
        projector = EquipmentProjector(repository)
        monkeypatch.setenv("D4PLANNER_EQUIPMENT_REPOSITORY_DB", str(repository_path.resolve()))
        monkeypatch.setenv("D4PLANNER_CHARACTER_ID", "character-repository")
        monkeypatch.setenv("D4PLANNER_CHARACTER_DISPLAY_NAME", "Repository Character")
        runtime = ProductionBackendRuntime({
            "ownerInstanceId": "owner-repository", "childInstanceId": "backend-repository",
            "generation": 9, "dataDir": str(data), "targetFolder": str(targets),
            "wsEndpoint": {"host": "127.0.0.1", "port": 0}, "credential": CREDENTIAL,
        }, rulekit=_rulekit())
        ready = await runtime.start()
        assert ready["health"]["equipmentCapture"] == "REPOSITORY_HEALTHY"
        uri = f"ws://127.0.0.1:{ready['wsEndpoint']['port']}"
        try:
            async with connect(uri, origin=ORIGIN, ping_interval=None) as ws:
                await ws.send(json.dumps(_message(
                    "hello-repository", "hello", 9, credential=CREDENTIAL, origin=ORIGIN,
                    lastSeen={"hudRevision": None},
                )))
                await ws.recv()
                await ws.send(json.dumps(_message(
                    "snapshot-repository", "hud.snapshot.request", 9,
                    requestContext={"mode": "DISCOVER_ACTIVE_CONTEXT", "reason": "INITIAL_CONNECTION",
                                    "attempt": 1, "runtimeInstanceId": "backend-repository",
                                    "minimumHudRevision": 0},
                )))
                initial = json.loads(await ws.recv())
                initial_revision = initial["hud"]["hudRevision"]
                for sequence, text in enumerate(
                    ["Head", "EQUIPPED", "RECORDED HELM", "Rare Helm", "850 Item Power", "Unequip"], 1,
                ):
                    projector.consume({
                        "eventSeq": sequence, "type": "speech.raw",
                        "timestamp": f"2026-10-26T04:00:0{sequence}Z",
                        "sessionId": "recorded-repository-session", "data": {"text": text},
                    })
                update = json.loads(await asyncio.wait_for(ws.recv(), 2))
                assert update["type"] == "hud.update"
                assert update["hud"]["hudRevision"] > initial_revision
                assert update["hud"]["context"]["character"]["currentRevision"] == 1
                assert update["hud"]["context"]["character"]["characterId"] == "character-repository"
                assert update["hud"]["score"]["status"] == "NO_DATA"
                assert update["hud"]["score"]["failIssueCount"] == 0
                await asyncio.sleep(.25)
                assert runtime.store.latest_authoritative()["hudRevision"] == update["hud"]["hudRevision"]
                await runtime.capture_health_changed("DEGRADED")
                stale = runtime.store.latest_authoritative()
                assert stale["health"]["capture"] == "STALE"
                assert stale["health"]["scoreFreshness"] == "STALE"
                await runtime.capture_health_changed("HEALTHY")
                recovered = runtime.store.latest_authoritative()
                assert recovered["health"]["capture"] == "HEALTHY"
                assert recovered["health"]["scoreFreshness"] == "NO_DATA"
        finally:
            await runtime.stop()
    asyncio.run(scenario())


def test_repository_watcher_retries_recovers_rejects_duplicates_and_stops():
    row = {
        "slotFamily": "helm", "slotIndex": None, "name": "Recorded Helm",
        "itemFingerprint": "helm-stable", "observedAt": "2026-10-26T03:00:00Z",
        "affixes": [], "effectsRaw": [],
    }

    class Repository:
        def __init__(self):
            self.revision = 1
            self.failure = None
            self.invalid = False

        def projection_snapshot(self):
            if self.failure:
                raise self.failure
            rows = ({"slotFamily": "helm"},) if self.invalid else (row,)
            return EquipmentProjectionView(
                (self.revision, "session", self.revision, "2026-10-26T03:00:00Z"), rows,
            )

    class Runtime:
        def __init__(self):
            self.revisions = []
            self.health = []

        async def ingest_snapshot(self, snapshot):
            self.revisions.append(snapshot.current_revision)

        async def capture_health_changed(self, status):
            self.health.append(status)

    async def wait_for(predicate, timeout=.5):
        deadline = asyncio.get_running_loop().time() + timeout
        while not predicate():
            if asyncio.get_running_loop().time() >= deadline:
                raise AssertionError("watcher condition timed out")
            await asyncio.sleep(.005)

    async def scenario():
        repository = Repository(); runtime = Runtime()
        source = RepositoryEquipmentEventSource(
            runtime, repository, character_id="c", character_display_name="C",
            interval_seconds=.005, maximum_backoff_seconds=.02,
        )
        await source.start()
        assert runtime.revisions == [1]
        repository.failure = EquipmentRepositoryTransient("EQUIPMENT_DB_BUSY")
        await wait_for(lambda: source.health_status == "DEGRADED")
        repository.failure = None; repository.revision = 2
        await wait_for(lambda: runtime.revisions == [1, 2])
        assert source.health_status == "HEALTHY"
        await asyncio.sleep(.03)
        assert runtime.revisions == [1, 2]
        repository.invalid = True; repository.revision = 3
        await wait_for(lambda: source.health_status == "ERROR")
        assert runtime.revisions == [1, 2]
        repository.invalid = False
        await wait_for(lambda: runtime.revisions == [1, 2, 3])
        assert source.health_status == "HEALTHY"
        assert source.poll_count >= 4
        assert source.last_poll_duration_ns > 0
        assert source.maximum_poll_duration_ns >= source.last_poll_duration_ns
        await source.stop()
        assert source._task is None and source.health_status == "STOPPED"

    asyncio.run(scenario())



def test_uninjected_composition_resolves_and_forwards_rulekit_configuration(tmp_path, monkeypatch):
    """Exercise the production factory branch; IPC input remains explicitly synthetic."""
    forwarded = []
    def factory(environment):
        forwarded.append(environment)
        return _rulekit()
    monkeypatch.setattr(RuleKitRuntimeService, 'from_environment', factory)
    monkeypatch.setenv('D4PLANNER_REPOSITORY_ROOT', str(ROOT))
    monkeypatch.delenv('D4_RULEKIT_DATA_ROOT', raising=False)
    monkeypatch.delenv('D4_RULEKIT_INSTALLATION_ROOT', raising=False)
    async def scenario():
        runtime = ProductionBackendRuntime({
            'ownerInstanceId':'synthetic-owner', 'childInstanceId':'synthetic-backend',
            'generation':1, 'dataDir':str(tmp_path / 'data'), 'targetFolder':str(tmp_path / 'targets'),
            'wsEndpoint':{'host':'127.0.0.1','port':0}, 'credential':CREDENTIAL,
        })
        try:
            ready = await runtime.start()
            assert ready['health']['wsTransport'] == 'READY'
            assert forwarded[0]['D4_RULEKIT_INSTALLATION_ROOT'] == str(ROOT)
            assert forwarded[0]['D4_RULEKIT_DATA_ROOT'] == str(tmp_path / 'data/rulekit')
        finally:
            await runtime.stop()
    asyncio.run(scenario())
