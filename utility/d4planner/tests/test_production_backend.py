from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil

from websockets.asyncio.client import connect

from d4planner.production import ORIGIN, ProductionBackendRuntime
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


def test_production_runtime_real_worker_target_capture_sqlite_and_authenticated_ws(tmp_path):
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

