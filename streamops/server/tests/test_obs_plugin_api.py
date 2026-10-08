from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from streamops.server.app import create_app
from streamops.server.errors import ObsPluginError
from streamops.server.services.obs_plugin import ObsPluginOperationResult, ObsPluginStatus


LOADED = ObsPluginStatus("obs-multi-rtmp", "0.7.4.0", "LOADED", True, True, True)


class FakePluginService:
    def __init__(self):
        self.calls = []
        self.failure = None

    async def _result(self, action, plugin_id):
        self.calls.append((action, plugin_id))
        if self.failure:
            raise self.failure
        if action == "status":
            return LOADED
        result = {"install": "already_installed", "verify": "verified", "rollback": "rolled_back"}[action]
        return ObsPluginOperationResult(LOADED, action, result)

    async def status(self, plugin_id): return await self._result("status", plugin_id)
    async def install(self, plugin_id): return await self._result("install", plugin_id)
    async def verify(self, plugin_id): return await self._result("verify", plugin_id)
    async def rollback(self, plugin_id): return await self._result("rollback", plugin_id)


def client(server_config, capture_service, service):
    return TestClient(create_app(
        server_config,
        capture_service=capture_service,
        obs_plugin_service=service,
        manage_runtime=False,
    ))


def test_status_and_operation_contracts(server_config, capture_service):
    service = FakePluginService()
    with client(server_config, capture_service, service) as api:
        status = api.get("/api/v1/obs/plugins/obs-multi-rtmp")
        install = api.post("/api/v1/obs/plugins/obs-multi-rtmp/install")
        verify = api.post("/api/v1/obs/plugins/obs-multi-rtmp/verify")
        rollback = api.post("/api/v1/obs/plugins/obs-multi-rtmp/rollback")
    assert status.json() == LOADED.api_payload()
    assert install.json()["result"] == "already_installed"
    assert verify.json()["state"] == "LOADED"
    assert rollback.json()["operation"] == "rollback"
    assert all(response.headers["cache-control"] == "no-store" for response in (status, install, verify, rollback))


@pytest.mark.parametrize("suffix", ["install", "verify", "rollback"])
@pytest.mark.parametrize("payload", [
    {"url": "https://evil.invalid/plugin.zip"},
    {"path": r"C:\\temp\\plugin.dll"},
    {"command": "powershell"},
    {"binary": "secret-token"},
])
def test_operations_reject_all_client_input(server_config, capture_service, suffix, payload):
    service = FakePluginService()
    with client(server_config, capture_service, service) as api:
        response = api.post(f"/api/v1/obs/plugins/obs-multi-rtmp/{suffix}", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_plugin_request"
    assert service.calls == []
    assert "secret-token" not in response.text


def test_status_rejects_query_parameters(server_config, capture_service):
    service = FakePluginService()
    with client(server_config, capture_service, service) as api:
        response = api.get("/api/v1/obs/plugins/obs-multi-rtmp?path=C%3A%5Ctemp")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_plugin_request"
    assert service.calls == []


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("plugin_not_supported", 404),
        ("plugin_incompatible", 409),
        ("plugin_install_permission_denied", 403),
        ("plugin_install_failed", 503),
        ("plugin_verify_failed", 409),
        ("plugin_rollback_failed", 503),
        ("obs_busy_streaming", 409),
        ("obs_busy_recording", 409),
        ("obs_restart_failed", 503),
        ("plugin_state_conflict", 409),
    ],
)
def test_typed_error_mapping_has_stable_safe_shape(server_config, capture_service, code, status):
    service = FakePluginService()
    service.failure = ObsPluginError(code, "safe public message", status)
    with client(server_config, capture_service, service) as api:
        response = api.post("/api/v1/obs/plugins/obs-multi-rtmp/install")
    assert response.status_code == status
    assert response.json() == {"error": {"code": code, "message": "safe public message"}}


def test_websocket_uses_same_plugin_service_as_rest(server_config, capture_service):
    service = FakePluginService()
    with client(server_config, capture_service, service) as api:
        with api.websocket_connect("/api/v1/obs/plugins/ws") as websocket:
            websocket.send_json({
                "type": "request",
                "request_id": "status-1",
                "operation": "obs_plugin.status",
                "payload": {"plugin_id": "obs-multi-rtmp"},
            })
            response = websocket.receive_json()

    assert response == {
        "type": "response",
        "request_id": "status-1",
        "ok": True,
        "data": LOADED.api_payload(),
    }
    assert service.calls == [("status", "obs-multi-rtmp")]


def test_websocket_preserves_typed_core_error(server_config, capture_service):
    service = FakePluginService()
    service.failure = ObsPluginError("obs_busy_streaming", "OBS plugin changes are blocked while streaming.", 409)
    with client(server_config, capture_service, service) as api:
        with api.websocket_connect("/api/v1/obs/plugins/ws") as websocket:
            websocket.send_json({
                "type": "request",
                "request_id": "install-1",
                "operation": "obs_plugin.install",
                "payload": {"plugin_id": "obs-multi-rtmp"},
            })
            response = websocket.receive_json()

    assert response["ok"] is False
    assert response["error"] == {
        "code": "obs_busy_streaming",
        "message": "OBS plugin changes are blocked while streaming.",
    }


def test_websocket_rejects_transport_specific_extra_input(server_config, capture_service):
    service = FakePluginService()
    with client(server_config, capture_service, service) as api:
        with api.websocket_connect("/api/v1/obs/plugins/ws") as websocket:
            websocket.send_json({
                "type": "request",
                "request_id": "bad-1",
                "operation": "obs_plugin.install",
                "payload": {"plugin_id": "obs-multi-rtmp", "url": "https://evil.invalid/plugin.zip"},
            })
            response = websocket.receive_json()

    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_request"
    assert service.calls == []


def test_websocket_update_uses_distinct_service_operation(server_config, capture_service):
    class FakePluginService:
        def __init__(self):
            self.calls = []

        async def update(self, plugin_id):
            self.calls.append(("update", plugin_id))
            return ObsPluginOperationResult(LOADED, "update", "updated")

    service = FakePluginService()
    with client(server_config, capture_service, service) as api:
      with api.websocket_connect("/api/v1/obs/plugins/ws") as websocket:
          websocket.send_json({
            "type": "request",
            "request_id": "plugin-update-1",
            "operation": "obs_plugin.update",
            "payload": {"plugin_id": "obs-multi-rtmp"},
        })
          response = websocket.receive_json()

    assert response["ok"] is True
    assert response["request_id"] == "plugin-update-1"
    assert response["data"]["operation"] == "update"
    assert service.calls == [("update", "obs-multi-rtmp")]


@pytest.mark.parametrize("operation", ["install", "update", "verify", "rollback"])
def test_websocket_rejects_source_override_for_every_mutation(server_config, capture_service, operation):
    service = FakePluginService()
    with client(server_config, capture_service, service) as api:
        with api.websocket_connect("/api/v1/obs/plugins/ws") as websocket:
            websocket.send_json({
                "type": "request",
                "request_id": "reject-source",
                "operation": f"obs_plugin.{operation}",
                "payload": {"plugin_id": "obs-multi-rtmp", "source": "https://untrusted.invalid"},
            })
            response = websocket.receive_json()
    assert response["ok"] is False
    assert response["request_id"] == "reject-source"
    assert response["error"]["code"] == "invalid_request"
    assert service.calls == []


@pytest.mark.parametrize("operation", ["install", "update", "verify", "rollback"])
def test_rest_rejects_source_override_for_every_mutation(server_config, capture_service, operation):
    service = FakePluginService()
    with client(server_config, capture_service, service) as api:
        response = api.post(
            f"/api/v1/obs/plugins/obs-multi-rtmp/{operation}",
            json={"source": "https://untrusted.invalid"},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_plugin_request"
    assert service.calls == []


def test_websocket_correlates_multiple_requests_and_preserves_order(server_config, capture_service):
    service = FakePluginService()
    with client(server_config, capture_service, service) as api:
        with api.websocket_connect("/api/v1/obs/plugins/ws") as websocket:
            for request_id in ("status-first", "status-second", "status-third"):
                websocket.send_json({
                    "type": "request",
                    "request_id": request_id,
                    "operation": "obs_plugin.status",
                    "payload": {"plugin_id": "obs-multi-rtmp"},
                })
                response = websocket.receive_json()
                assert response["type"] == "response"
                assert response["request_id"] == request_id
                assert response["ok"] is True
                assert response["data"] == LOADED.api_payload()
    assert service.calls == [("status", "obs-multi-rtmp")] * 3


@pytest.mark.parametrize("operation", ["install", "verify", "rollback"])
def test_rest_ws_operation_parity_for_success(server_config, capture_service, operation):
    service = FakePluginService()
    with client(server_config, capture_service, service) as api:
        rest = api.post(f"/api/v1/obs/plugins/obs-multi-rtmp/{operation}")
        with api.websocket_connect("/api/v1/obs/plugins/ws") as websocket:
            websocket.send_json({
                "type": "request",
                "request_id": f"parity-{operation}",
                "operation": f"obs_plugin.{operation}",
                "payload": {"plugin_id": "obs-multi-rtmp"},
            })
            ws = websocket.receive_json()
    assert rest.status_code == 200
    assert ws["ok"] is True
    assert ws["data"] == rest.json()
    assert service.calls == [(operation, "obs-multi-rtmp")] * 2


@pytest.mark.parametrize("code,status", [
    ("obs_busy_streaming", 409),
    ("plugin_incompatible", 409),
    ("plugin_install_failed", 503),
])
def test_rest_ws_operation_parity_for_typed_failure(server_config, capture_service, code, status):
    service = FakePluginService()
    service.failure = ObsPluginError(code, "safe error", status)
    with client(server_config, capture_service, service) as api:
        rest = api.post("/api/v1/obs/plugins/obs-multi-rtmp/install")
        with api.websocket_connect("/api/v1/obs/plugins/ws") as websocket:
            websocket.send_json({
                "type": "request",
                "request_id": "parity-failure",
                "operation": "obs_plugin.install",
                "payload": {"plugin_id": "obs-multi-rtmp"},
            })
            ws = websocket.receive_json()
    assert rest.status_code == status
    assert ws["ok"] is False
    assert ws["error"] == rest.json()["error"]
    assert ws["request_id"] == "parity-failure"


@pytest.mark.parametrize("operation", ["install", "update", "verify", "rollback"])
def test_rest_ws_parity_all_mutations_with_single_service(server_config, capture_service, operation):
    class FullService(FakePluginService):
        async def update(self, plugin_id):
            self.calls.append(("update", plugin_id))
            return ObsPluginOperationResult(LOADED, "update", "updated")
    service = FullService()
    with client(server_config, capture_service, service) as api:
        rest = api.post(f"/api/v1/obs/plugins/obs-multi-rtmp/{operation}")
        with api.websocket_connect("/api/v1/obs/plugins/ws") as websocket:
            websocket.send_json({
                "type": "request", "request_id": f"all-{operation}",
                "operation": f"obs_plugin.{operation}",
                "payload": {"plugin_id": "obs-multi-rtmp"},
            })
            ws = websocket.receive_json()
    assert rest.status_code == 200
    assert ws["ok"] is True
    assert ws["request_id"] == f"all-{operation}"
    assert rest.json() == ws["data"]
    assert service.calls == [(operation, "obs-multi-rtmp")] * 2



def test_inventory_schema_is_renderable_without_hardcoded_ui_state(server_config, capture_service):
    class Service(FakePluginService):
        async def inventory(self):
            return [LOADED]
    with client(server_config, capture_service, Service()) as api:
        response = api.get("/api/v1/obs/plugins")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    plugins = response.json()["plugins"]
    assert len(plugins) == 1
    fields = {"plugin_id", "display_name", "installed", "installed_version",
              "available_version", "state", "restart_required", "compatible",
              "last_verification"}
    assert fields <= set(plugins[0])


@pytest.mark.parametrize("operation", ["install", "update", "verify", "rollback"])
def test_rest_ws_typed_error_equivalence_for_every_mutation(server_config, capture_service, operation):
    class AllOperations(FakePluginService):
        async def update(self, plugin_id):
            return await self._result("install", plugin_id)
    service = AllOperations()
    service.failure = ObsPluginError("plugin_state_conflict", "Safe conflict", 409)
    with client(server_config, capture_service, service) as api:
        rest = api.post(f"/api/v1/obs/plugins/obs-multi-rtmp/{operation}")
        with api.websocket_connect("/api/v1/obs/plugins/ws") as ws:
            ws.send_json({"type": "request", "operation": f"obs_plugin.{operation}",
                          "request_id": "error-" + operation,
                          "payload": {"plugin_id": "obs-multi-rtmp"}})
            received = ws.receive_json()
    assert rest.status_code == 409
    assert received["ok"] is False
    assert received["request_id"] == "error-" + operation
    assert received["error"] == rest.json()["error"]


def test_e2e_real_service_install_process_api_restart_verify_and_inventory(server_config, capture_service):
    """HTTP transport -> lifecycle service -> fake OBS process/vendor boundaries."""
    from streamops.server.services.obs_plugin import (
        ObsPluginService, PluginHostResult, PluginHostStatus,
    )
    from streamops.server.obs.manager import ObsRuntimeStatus

    class VendorClient:
        def connect(self):
            pass
        def request(self, request_type, payload):
            assert request_type == "CallVendorRequest"
            assert payload["vendorName"] == "sorayuki.multi_rtmp"
            return {"vendorResponseData": {"targets": [], "count": 0}}
        def close(self):
            pass

    class Manager:
        def __init__(self):
            self.state = "READY"
            self.calls = []
            self.client_factory = VendorClient
        def status(self):
            return ObsRuntimeStatus(
                state=self.state, process={"running": self.state == "READY"},
                websocket={"connected": self.state == "READY", "obs_version": "32.2.1"},
                output={"streaming": False, "recording": False},
                last_operation=None, error=None,
            )
        def stop(self):
            self.calls.append("stop")
            self.state = "STOPPED"
            return self.status()
        def start(self):
            self.calls.append("start")
            self.state = "READY"
            return self.status()

    class Host:
        def __init__(self):
            self.installed, self.loaded = False, False
        def status(self):
            return PluginHostStatus(
                "exact" if self.installed else "absent", True, self.loaded,
                "0.7.4.0" if self.loaded else None,
                installed_version="0.7.4.0" if self.installed else None,
                available_version="0.7.4.0",
            )
        def install(self):
            self.installed = True
            return PluginHostResult("installed")
        def verify(self):
            self.loaded = True
            return self.status()
        def rollback(self):
            self.installed, self.loaded = False, False
            return PluginHostResult("rolled_back")

    manager, host = Manager(), Host()
    service = ObsPluginService(manager, host, defer_restart=True)
    with TestClient(create_app(
        server_config, capture_service=capture_service, obs_manager=manager,
        obs_plugin_service=service, manage_runtime=False,
    )) as api:
        result = api.post("/api/v1/obs/plugins/obs-multi-rtmp/install")
        assert result.status_code == 200
        assert result.json()["state"] == "RESTART_REQUIRED"
        assert result.json()["restart_required"] is True
        assert manager.calls == ["stop"]
        inventory = api.get("/api/v1/obs/plugins").json()["plugins"]
        assert inventory[0]["restart_required"] is True
        assert inventory[0]["state"] == "RESTART_REQUIRED"
        started = api.post("/api/v1/obs/process/start")
        assert started.status_code == 200
        assert manager.calls == ["stop", "start"]
        verified = api.post("/api/v1/obs/plugins/obs-multi-rtmp/verify")
        assert verified.status_code == 200
        assert verified.json()["state"] == "VERIFIED"
        assert verified.json()["restart_required"] is False
        assert verified.json()["last_verification"] is not None
        status = api.get("/api/v1/obs/plugins/obs-multi-rtmp").json()
        assert status["state"] == "VERIFIED"
        assert status["last_verification"] is not None


def test_websocket_unexpected_error_never_logs_or_returns_secret(server_config, capture_service, caplog):
    import logging

    secret = "SUPERSECRET-stream-key-test"

    class BrokenService(FakePluginService):
        async def install(self, plugin_id):
            raise RuntimeError("credential=" + secret)

    with caplog.at_level(logging.ERROR, logger="streamops.server.api.obs_plugin_ws"):
        with client(server_config, capture_service, BrokenService()) as api:
            with api.websocket_connect("/api/v1/obs/plugins/ws") as ws:
                ws.send_json({
                    "type": "request", "request_id": "sanitized-1",
                    "operation": "obs_plugin.install",
                    "payload": {"plugin_id": "obs-multi-rtmp"},
                })
                response = ws.receive_json()
    assert response["ok"] is False
    assert response["request_id"] == "sanitized-1"
    assert response["error"]["code"] == "internal_error"
    assert secret not in repr(response)
    assert secret not in caplog.text


def test_e2e_http_update_timeout_is_bounded_and_typed(server_config, capture_service):
    import threading
    entered = threading.Event()
    release = threading.Event()
    from streamops.server.services.obs_plugin import ObsPluginService, PluginHostStatus, PluginHostResult
    from streamops.server.obs.manager import ObsRuntimeStatus

    class Manager:
        def __init__(self):
            self.state = "STOPPED"
        def status(self):
            return ObsRuntimeStatus(
                state=self.state, process={"running": False},
                websocket={"connected": False, "obs_version": "32.2.1"},
                output={"streaming": False, "recording": False},
                last_operation=None, error=None,
            )
        def start(self):
            self.state = "READY"
            return ObsRuntimeStatus(
                state=self.state, process={"running": True},
                websocket={"connected": True, "obs_version": "32.2.1"},
                output={"streaming": False, "recording": False},
                last_operation=None, error=None,
            )

    class Host:
        def status(self):
            return PluginHostStatus("exact", True, False, None)
        def update(self):
            entered.set()
            assert release.wait(timeout=3)
            return PluginHostResult("updated")
        def verify(self):
            return self.status()

    manager = Manager()
    service = ObsPluginService(manager, Host(), operation_timeout=0.01)
    with TestClient(create_app(
        server_config, capture_service=capture_service,
        obs_manager=manager, obs_plugin_service=service,
        manage_runtime=False,
    )) as api:
        try:
            response = api.post("/api/v1/obs/plugins/obs-multi-rtmp/update")
            assert entered.is_set()
            # The HTTP request must return even though the worker has not
            # finished. Event gating avoids timing-dependent/flaky assertions.
            assert response.status_code == 504
            assert response.json()["error"]["code"] == "plugin_operation_timeout"
            assert not release.is_set()
        finally:
            release.set()
