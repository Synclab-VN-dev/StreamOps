"""Integration contracts for WS-only OBS Plugin Manager and safe reconnect."""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from streamops.server.app import create_app
from streamops.server.errors import ObsPluginError
from streamops.server.obs.manager import ObsRuntimeStatus
from streamops.server.services.obs_plugin import (
    ObsPluginService, PluginHostStatus,
)

PLUGIN = "obs-multi-rtmp"
WS = "/api/v1/obs/plugins/ws"


class Manager:
    def status(self):
        return ObsRuntimeStatus(
            state="READY", process={"running": True},
            websocket={"connected": True, "obs_version": "32.2.1"},
            output={"streaming": False, "recording": False},
            last_operation=None, error=None,
        )


class Host:
    def __init__(self):
        self.rollback_ready = True
        self.fail = False
        self.started = threading.Event()
        self.resume = threading.Event()

    def status(self):
        return PluginHostStatus(
            "exact", True, True, "0.7.4.3",
            installed_version="0.7.4.3", available_version="0.7.4.4",
        )

    def rollback_readiness(self):
        return {
            "available": self.rollback_ready,
            "target_version": "0.7.4.2" if self.rollback_ready else None,
            "reason": None if self.rollback_ready else "config_conflict",
        }

    def verify(self):
        self.started.set()
        if self.fail:
            raise ObsPluginError("plugin_verify_failed", "safe verification failure", 409)
        return self.status()


class Source:
    def catalog_release(self, plugin_id):
        assert plugin_id == PLUGIN
        return SimpleNamespace(
            version="0.7.4.4", platform="windows", architecture="x64",
            obs_version="32.2.1", source_commit="a" * 40,
        )


def _service():
    host = Host()
    return ObsPluginService(Manager(), host, release_source=Source()), host


def _client(server_config, capture_service, service):
    return TestClient(create_app(
        server_config, capture_service=capture_service,
        obs_plugin_service=service, manage_runtime=False,
    ))


def _send(ws, op, request_id, payload):
    ws.send_json({
        "type": "request", "request_id": request_id,
        "operation": op, "payload": payload,
    })
    return ws.receive_json()


def test_ws_inventory_catalog_operation_parity(server_config, capture_service):
    service, _ = _service()
    with _client(server_config, capture_service, service) as api:
        inventory = api.get("/api/v1/obs/plugins")
        catalog = api.get("/api/v1/obs/plugins/available")
        assert inventory.status_code == catalog.status_code == 200
        with api.websocket_connect(WS) as ws:
            result = _send(ws, "obs_plugin.inventory", "i1", {})
            assert result == {"type": "response", "request_id": "i1", "ok": True, "data": inventory.json()}
            result = _send(ws, "obs_plugin.available", "a1", {})
            assert result == {"type": "response", "request_id": "a1", "ok": True, "data": catalog.json()}
            bad = _send(ws, "obs_plugin.available", "a2", {"source_url": "https://evil.invalid"})
            assert bad["ok"] is False
            assert bad["error"]["code"] == "invalid_request"
            bad = _send(ws, "obs_plugin.inventory", "i2", {"plugin_id": PLUGIN})
            assert bad["error"]["code"] == "invalid_request"


def test_status_exposes_verified_rollback_and_operation_reconcile(server_config, capture_service):
    service, host = _service()
    with _client(server_config, capture_service, service) as api:
        status = api.get("/api/v1/obs/plugins/" + PLUGIN).json()
        assert status["rollback"] == {
            "available": True, "target_version": "0.7.4.2", "reason": None,
        }
        host.rollback_ready = False
        status = api.get("/api/v1/obs/plugins/" + PLUGIN).json()
        assert status["rollback"]["available"] is False
        assert status["rollback"]["reason"] == "config_conflict"
        with api.websocket_connect(WS) as ws:
            before = _send(ws, "obs_plugin.operation_status", "op0", {"plugin_id": PLUGIN})
            assert before["data"]["operation"]["state"] == "IDLE"
            res = _send(ws, "obs_plugin.verify", "verify", {"plugin_id": PLUGIN})
            assert res["ok"] is True
            reconciled = _send(ws, "obs_plugin.operation_status", "op1", {"plugin_id": PLUGIN})
            assert reconciled["data"]["operation"]["state"] == "SUCCEEDED"
            assert reconciled["data"]["operation"]["operation"] == "verify"
            assert reconciled["data"]["operation"]["operation_id"]
            assert reconciled["data"]["revision"] > before["data"]["revision"]
            rest = api.get("/api/v1/obs/plugins/" + PLUGIN + "/operation")
            assert rest.status_code == 200
            assert rest.headers["cache-control"] == "no-store"
            assert rest.json()["operation"]["state"] == "SUCCEEDED"


def test_opt_in_push_change_and_no_secret_payload(server_config, capture_service):
    service, _ = _service()
    with _client(server_config, capture_service, service) as api:
        with api.websocket_connect(WS) as ws:
            subscribed = _send(ws, "obs_plugin.subscribe", "sub", {"plugin_id": PLUGIN})
            assert subscribed["ok"] is True
            assert subscribed["data"]["subscribed"] is True
            ws.send_json({
                "type": "request", "request_id": "verify",
                "operation": "obs_plugin.verify", "payload": {"plugin_id": PLUGIN},
            })
            response = None
            event = None
            for _ in range(5):
                message = ws.receive_json()
                if message["type"] == "event":
                    event = message
                elif message.get("request_id") == "verify":
                    response = message
                if event is not None and response is not None:
                    break
            assert response is not None and response["ok"] is True
            assert event is not None
            assert event["event"] == "obs_plugin.changed"
            assert event["plugin_id"] == PLUGIN
            assert event["revision"] > subscribed["data"]["revision"]
            assert set(event) == {"type", "event", "plugin_id", "revision", "resources"}


def test_failed_operation_safe_terminal_reconciliation():
    service, host = _service()
    host.fail = True
    async def scenario():
        with pytest.raises(ObsPluginError) as caught:
            await service.verify(PLUGIN)
        assert caught.value.code == "plugin_verify_failed"
        result = await service.operation_status(PLUGIN)
        assert result["operation"]["state"] == "FAILED"
        assert result["operation"]["error_code"] == "plugin_verify_failed"
        assert "safe verification failure" not in str(result)
    asyncio.run(scenario())


def test_cancelled_ws_request_does_not_claim_mutation_stopped():
    service, host = _service()
    def blocking_verify():
        host.started.set()
        assert host.resume.wait(5)
        return host.status()
    host.verify = blocking_verify

    async def scenario():
        task = asyncio.create_task(service.verify(PLUGIN))
        assert await asyncio.to_thread(host.started.wait, 2)
        assert (await service.operation_status(PLUGIN))["operation"]["state"] == "RUNNING"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await service.operation_status(PLUGIN))["operation"]["state"] == "RUNNING"
        host.resume.set()
        for _ in range(100):
            if (await service.operation_status(PLUGIN))["operation"]["state"] == "SUCCEEDED":
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("worker did not report terminal completion after caller cancellation")
    asyncio.run(scenario())
