from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

from streamops.server.app import create_app
from streamops.server.services.obs_status import ObsStatusHub
from streamops.server.tests.test_obs_process_api import FakeObsManager, runtime_status


class FakeSceneService:
    def __init__(self) -> None:
        self.scene = "Camera"

    def current_scene(self) -> str:
        return self.scene


def test_hub_fans_changed_snapshot_to_all_clients_and_deduplicates() -> None:
    async def scenario() -> None:
        manager = FakeObsManager()
        scenes = FakeSceneService()
        capture = SimpleNamespace(ready=True, backend_name="test")
        hub = ObsStatusHub(manager, scenes, capture)  # type: ignore[arg-type]

        first = await hub.subscribe()
        second = await hub.subscribe()
        first_event = await first.get()
        second_event = await second.get()
        assert first_event["type"] == "event"
        assert first_event["event"] == "obs.snapshot"
        assert first_event["data"]["obs"]["current_scene"] == "Camera"
        assert second_event["data"]["runtime"]["state"] == "READY"

        await hub.refresh()
        assert first.empty()
        assert second.empty()

        scenes.scene = "Gameplay"
        await hub.refresh()
        assert (await first.get())["data"]["obs"]["current_scene"] == "Gameplay"
        assert (await second.get())["data"]["obs"]["current_scene"] == "Gameplay"
        hub.unsubscribe(first)
        hub.unsubscribe(second)
        await hub.close()

    asyncio.run(scenario())


def test_hub_ignores_uptime_only_changes() -> None:
    async def scenario() -> None:
        manager = FakeObsManager()
        scenes = FakeSceneService()
        hub = ObsStatusHub(manager, scenes, SimpleNamespace(ready=True, backend_name="test"))  # type: ignore[arg-type]
        queue = await hub.subscribe()
        await queue.get()
        manager.status_result = runtime_status()
        manager.status_result.process["uptime_seconds"] = 999
        await hub.refresh()
        assert queue.empty()
        await hub.close()

    asyncio.run(scenario())


def test_websocket_sends_initial_full_snapshot(server_config, capture_service) -> None:
    manager = FakeObsManager()
    app = create_app(
        server_config,
        capture_service=capture_service,
        obs_manager=manager,  # type: ignore[arg-type]
        manage_runtime=False,
    )
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/obs/ws") as websocket:
            snapshot = websocket.receive_json()

    assert snapshot["type"] == "event"
    assert snapshot["event"] == "obs.snapshot"
    assert snapshot["data"]["runtime"]["state"] == "READY"
    assert snapshot["data"]["node"]["status"] == "ok"
    assert "current_scene" in snapshot["data"]["obs"]


def _response(websocket, request_id: str) -> dict:
    while True:
        message = websocket.receive_json()
        if message.get("type") == "response" and message.get("request_id") == request_id:
            return message


def test_websocket_correlates_profile_catalog_and_lifecycle_operations(server_config, capture_service) -> None:
    manager = FakeObsManager()
    app = create_app(
        server_config,
        capture_service=capture_service,
        obs_manager=manager,  # type: ignore[arg-type]
        manage_runtime=False,
    )
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/obs/ws") as websocket:
            websocket.receive_json()
            websocket.send_json({
                "type": "request", "request_id": "create-1",
                "operation": "scene_profiles.create", "payload": {"profile": {"name": "Socket profile"}},
            })
            created = _response(websocket, "create-1")
            assert created["ok"] is True
            assert created["data"]["name"] == "Socket profile"

            requests = (
                ("list-1", "scene_profiles.list", {}),
                ("get-1", "scene_profiles.get", {"profile_id": created["data"]["id"]}),
                ("catalog-1", "source_catalog.list", {}),
                ("templates-1", "scene_profile_templates.list", {}),
                ("start-1", "obs.lifecycle.start", {}),
            )
            for request_id, operation, payload in requests:
                websocket.send_json({"type": "request", "request_id": request_id, "operation": operation, "payload": payload})
                response = _response(websocket, request_id)
                assert response["ok"] is True
            assert manager.calls.count("start") == 1

    assert not app.state.obs_status_hub._subscribers


def test_websocket_returns_stable_errors_for_bad_requests(server_config, capture_service) -> None:
    app = create_app(server_config, capture_service=capture_service, obs_manager=FakeObsManager(), manage_runtime=False)  # type: ignore[arg-type]
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/obs/ws") as websocket:
            websocket.receive_json()
            websocket.send_json({"type": "request", "request_id": "bad-1", "operation": "shell.run", "payload": {}})
            unknown = _response(websocket, "bad-1")
            assert unknown == {
                "type": "response", "request_id": "bad-1", "ok": False,
                "error": {"code": "unknown_operation", "message": "Unsupported operation: shell.run"},
            }
            websocket.send_text("not json")
            malformed = websocket.receive_json()
            assert malformed["type"] == "response"
            assert malformed["request_id"] is None
            assert malformed["ok"] is False
            assert malformed["error"]["code"] == "invalid_request"
