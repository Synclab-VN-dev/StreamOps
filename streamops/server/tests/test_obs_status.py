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
        assert (await first.get())["obs"]["current_scene"] == "Camera"
        assert (await second.get())["runtime"]["state"] == "READY"

        await hub.refresh()
        assert first.empty()
        assert second.empty()

        scenes.scene = "Gameplay"
        await hub.refresh()
        assert (await first.get())["obs"]["current_scene"] == "Gameplay"
        assert (await second.get())["obs"]["current_scene"] == "Gameplay"
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

    assert snapshot["type"] == "obs.snapshot"
    assert snapshot["runtime"]["state"] == "READY"
    assert snapshot["node"]["status"] == "ok"
    assert "current_scene" in snapshot["obs"]
