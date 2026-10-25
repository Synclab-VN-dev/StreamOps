from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from statistics import median
import time
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from d4planner.transport import (
    D4PlannerWebSocketServer,
    HudHub,
    TargetActivationError,
    WebSocketServerConfig,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "release1" / "v1"
FIXTURES = CONTRACT / "fixtures"
SCHEMAS = CONTRACT / "schemas"
CREDENTIAL = "test-only-private-credential-000000000000"
ORIGIN = "tauri://localhost"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ws_validator() -> Draft202012Validator:
    hud = load(SCHEMAS / "hud.schema.json")
    ws = load(SCHEMAS / "ws.schema.json")
    registry = Registry().with_resource(hud["$id"], Resource.from_contents(hud))
    return Draft202012Validator(ws, registry=registry)


class SyntheticDomain:
    """TEST_ONLY domain port; it is never a production fallback."""

    def __init__(self, initial_hud: dict[str, Any]) -> None:
        self.initial_hud = initial_hud
        self.activations: list[tuple[str, str, int]] = []
        self.list_revision = 4

    async def list_targets(self) -> dict[str, Any]:
        return {
            "listRevision": self.list_revision,
            "targets": [
                {
                    "targetId": "synthetic-charge-bolt",
                    "displayName": "Synthetic Charge Bolt",
                    "contentSha256": "a" * 64,
                    "byteLength": 1024,
                    "validation": "VALID",
                    "errorCodes": [],
                },
                {
                    "targetId": "synthetic-invalid",
                    "displayName": "Synthetic Invalid",
                    "contentSha256": "b" * 64,
                    "byteLength": 12,
                    "validation": "INVALID",
                    "errorCodes": ["SCHEMA_INVALID"],
                },
            ],
        }

    async def activate_target(
        self, target_id: str, expected_sha256: str, expected_list_revision: int,
    ) -> dict[str, Any]:
        self.activations.append((target_id, expected_sha256, expected_list_revision))
        if target_id != "synthetic-charge-bolt":
            raise TargetActivationError("TARGET_INVALID", "/private/path/must-not-leak.json")
        if expected_sha256 != "a" * 64 or expected_list_revision != self.list_revision:
            raise TargetActivationError("TARGET_CHANGED", "Target bytes changed.", retryable=True)
        return {
            "status": "ACTIVATED",
            "targetId": target_id,
            "contentSha256": expected_sha256,
            "selectionRevision": 7,
            "hudRevision": self.initial_hud["hudRevision"],
        }


def hello(*, credential: str = CREDENTIAL, generation: int = 3) -> dict[str, Any]:
    return {
        "protocolVersion": "d4planner-ws/v1",
        "messageId": "hello-1",
        "type": "hello",
        "correlationId": None,
        "backendGeneration": generation,
        "credential": credential,
        "origin": ORIGIN,
        "lastSeen": {"hudRevision": None},
    }


def request(message_id: str, message_type: str, **extra: Any) -> dict[str, Any]:
    return {
        "protocolVersion": "d4planner-ws/v1",
        "messageId": message_id,
        "type": message_type,
        "correlationId": None,
        "backendGeneration": 3,
        **extra,
    }


def bumped_hud(hud: dict[str, Any], revision: int) -> dict[str, Any]:
    result = deepcopy(hud)
    result["hudRevision"] = revision
    return result


async def start_server() -> tuple[D4PlannerWebSocketServer, SyntheticDomain, HudHub]:
    hud = load(FIXTURES / "hud.partial.synthetic.json")
    domain = SyntheticDomain(hud)
    hub = HudHub(hud, backend_generation=3)
    server = D4PlannerWebSocketServer(
        WebSocketServerConfig(
            credential=CREDENTIAL,
            runtime_instance_id="backend-synthetic-a",
            backend_generation=3,
            origin=ORIGIN,
        ),
        domain,
        hub,
    )
    await server.start()
    return server, domain, hub


def test_real_socket_initial_list_snapshot_push_and_duplicate_command() -> None:
    async def scenario() -> None:
        server, domain, hub = await start_server()
        validator = ws_validator()
        try:
            async with connect(f"ws://127.0.0.1:{server.port}", origin=ORIGIN, ping_interval=None) as ws:
                await ws.send(json.dumps(hello()))
                accepted = json.loads(await ws.recv())
                validator.validate(accepted)
                assert accepted["type"] == "hello.accepted"

                list_request = request("list-1", "target.list.request")
                await ws.send(json.dumps(list_request))
                listed = json.loads(await ws.recv())
                validator.validate(listed)
                assert [item["validation"] for item in listed["targets"]] == ["VALID", "INVALID"]

                await ws.send(json.dumps(list_request))
                duplicate = json.loads(await ws.recv())
                assert duplicate == listed

                snapshot_request = request(
                    "snapshot-1",
                    "hud.snapshot.request",
                    requestContext={
                        "mode": "DISCOVER_ACTIVE_CONTEXT",
                        "reason": "INITIAL_CONNECTION",
                        "attempt": 1,
                        "runtimeInstanceId": "backend-synthetic-a",
                        "minimumHudRevision": 0,
                    },
                )
                await ws.send(json.dumps(snapshot_request))
                snapshot = json.loads(await ws.recv())
                validator.validate(snapshot)
                assert snapshot["hud"]["hudRevision"] == 12

                assert await hub.publish_after_commit(bumped_hud(snapshot["hud"], 13)) is True
                update = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
                validator.validate(update)
                assert update["previousHudRevision"] == 12
                assert update["hud"]["hudRevision"] == 13

                resync_request = deepcopy(snapshot_request)
                resync_request["messageId"] = "snapshot-2"
                resync_request["requestContext"] = {
                    "mode": "RESYNC_KNOWN_CONTEXT",
                    "runtimeInstanceId": "backend-synthetic-a",
                    "minimumHudRevision": 13,
                    "expectedContext": {
                        "state": "TARGET_ONLY",
                        "characterId": None,
                        "targetId": "synthetic-charge-bolt",
                        "selectionRevision": 7,
                    },
                }
                await ws.send(json.dumps(resync_request))
                resync = json.loads(await ws.recv())
                validator.validate(resync)
                assert resync["subscriptionId"] != snapshot["subscriptionId"]
                assert await hub.publish_after_commit(bumped_hud(resync["hud"], 14)) is True
                after_resync = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
                assert after_resync["subscriptionId"] == resync["subscriptionId"]
                assert after_resync["hud"]["hudRevision"] == 14
                assert domain.activations == []
        finally:
            await server.close()

    asyncio.run(scenario())


def test_target_selection_validates_safe_id_hash_and_domain_result() -> None:
    async def scenario() -> None:
        server, domain, _hub = await start_server()
        validator = ws_validator()
        try:
            async with connect(f"ws://127.0.0.1:{server.port}", origin=ORIGIN, ping_interval=None) as ws:
                await ws.send(json.dumps(hello()))
                await ws.recv()
                select = request(
                    "select-1", "target.select.request",
                    targetId="synthetic-charge-bolt",
                    expectedSha256="a" * 64,
                    expectedListRevision=4,
                )
                await ws.send(json.dumps(select))
                selected = json.loads(await ws.recv())
                validator.validate(selected)
                assert selected["status"] == "ACTIVATED"
                assert domain.activations == [("synthetic-charge-bolt", "a" * 64, 4)]

                await ws.send(json.dumps(select))
                assert json.loads(await ws.recv()) == selected
                assert domain.activations == [("synthetic-charge-bolt", "a" * 64, 4)]

                changed = dict(select, messageId="select-2", expectedSha256="c" * 64)
                await ws.send(json.dumps(changed))
                error = json.loads(await ws.recv())
                validator.validate(error)
                assert (error["code"], error["retryable"]) == ("TARGET_CHANGED", True)

                unsafe = dict(select, messageId="select-3", targetId="../../secret")
                await ws.send(json.dumps(unsafe))
                rejected = json.loads(await ws.recv())
                assert rejected["code"] == "INVALID_MESSAGE"

                wrong_type = dict(select, messageId="select-4", expectedListRevision="4")
                await ws.send(json.dumps(wrong_type))
                rejected_type = json.loads(await ws.recv())
                assert rejected_type["code"] == "INVALID_MESSAGE"
                assert len(domain.activations) == 2

                invalid = dict(select, messageId="select-5", targetId="synthetic-invalid")
                await ws.send(json.dumps(invalid))
                safe_error = json.loads(await ws.recv())
                assert safe_error["code"] == "TARGET_INVALID"
                assert safe_error["message"] == "Target cannot be activated."
                assert "/private/" not in json.dumps(safe_error)
        finally:
            await server.close()

    asyncio.run(scenario())


def test_auth_origin_generation_size_and_malformed_are_fail_closed() -> None:
    async def scenario() -> None:
        server, _domain, _hub = await start_server()
        try:
            with pytest.raises(InvalidStatus):
                async with connect(f"ws://127.0.0.1:{server.port}", origin="https://evil.invalid"):
                    pass

            async with connect(f"ws://127.0.0.1:{server.port}", origin=ORIGIN) as ws:
                await ws.send(json.dumps(hello(credential="wrong-credential-that-is-still-long-enough")))
                error = json.loads(await ws.recv())
                assert error["code"] == "AUTH_FAILED"
                await ws.wait_closed()
                assert ws.close_code == 1008

            async with connect(f"ws://127.0.0.1:{server.port}", origin=ORIGIN) as ws:
                await ws.send(json.dumps(hello()))
                await ws.recv()
                await ws.send("not-json")
                malformed = json.loads(await ws.recv())
                assert malformed["code"] == "INVALID_MESSAGE"
                stale = request("list-stale", "target.list.request")
                stale["backendGeneration"] = 2
                await ws.send(json.dumps(stale))
                conflict = json.loads(await ws.recv())
                assert conflict["code"] == "REVISION_CONFLICT"

            async with connect(f"ws://127.0.0.1:{server.port}", origin=ORIGIN) as ws:
                await ws.send(json.dumps(hello()))
                await ws.recv()
                await ws.send("x" * 262_145)
                with pytest.raises(ConnectionClosed):
                    await ws.recv()
                assert ws.close_code == 1009
        finally:
            await server.close()

    asyncio.run(scenario())


def test_slow_consumer_coalesces_to_resync_and_old_commit_is_ignored() -> None:
    async def scenario() -> None:
        hud = load(FIXTURES / "hud.partial.synthetic.json")
        hub = HudHub(hud, backend_generation=3)
        _snapshot, _subscription, queue = await hub.snapshot_and_subscribe()
        for revision in range(13, 513):
            assert await hub.publish_after_commit(bumped_hud(hud, revision)) is True
        message = queue.get_nowait()
        assert message["type"] == "resync.required"
        assert message["reason"] == "SLOW_CONSUMER"
        assert message["latestHudRevision"] == 512
        assert queue.qsize() == 0
        assert await hub.publish_after_commit(bumped_hud(hud, 13)) is False
        assert queue.empty()

    asyncio.run(scenario())


def test_loopback_and_private_credential_configuration_are_enforced() -> None:
    with pytest.raises(ValueError, match="loopback"):
        WebSocketServerConfig(
            credential=CREDENTIAL,
            runtime_instance_id="backend-a",
            backend_generation=1,
            origin=ORIGIN,
            host="0.0.0.0",
        )
    with pytest.raises(ValueError, match="32"):
        WebSocketServerConfig(
            credential="too-short",
            runtime_instance_id="backend-a",
            backend_generation=1,
            origin=ORIGIN,
        )


def test_commit_to_receive_latency_is_measured_without_inventing_an_sla() -> None:
    async def scenario() -> tuple[float, float]:
        server, _domain, hub = await start_server()
        samples: list[float] = []
        try:
            async with connect(f"ws://127.0.0.1:{server.port}", origin=ORIGIN, ping_interval=None) as ws:
                await ws.send(json.dumps(hello()))
                await ws.recv()
                snapshot_request = request(
                    "latency-snapshot", "hud.snapshot.request",
                    requestContext={
                        "mode": "DISCOVER_ACTIVE_CONTEXT", "reason": "INITIAL_CONNECTION", "attempt": 1,
                        "runtimeInstanceId": "backend-synthetic-a", "minimumHudRevision": 0,
                    },
                )
                await ws.send(json.dumps(snapshot_request))
                snapshot = json.loads(await ws.recv())
                for revision in range(13, 43):
                    started = time.perf_counter_ns()
                    await hub.publish_after_commit(bumped_hud(snapshot["hud"], revision))
                    update = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
                    samples.append((time.perf_counter_ns() - started) / 1_000_000)
                    assert update["hud"]["hudRevision"] == revision
        finally:
            await server.close()
        ordered = sorted(samples)
        return median(samples), ordered[int((len(ordered) - 1) * 0.95)]

    p50, p95 = asyncio.run(scenario())
    print(f"S5_TEST_ONLY_COMMIT_TO_RECEIVE_MS p50={p50:.3f} p95={p95:.3f} samples=30")
    assert p50 >= 0 and p95 >= p50
