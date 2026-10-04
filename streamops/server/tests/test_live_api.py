from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from streamops.server.app import create_app
from streamops.server.services.live import LiveService
from streamops.server.services.live_status import LiveStatusHub
from streamops.server.streaming import DestinationStore, SecretStore


class FakeManager:
    def status(self):
        return SimpleNamespace(state="READY")


RUNTIME_SOURCE_ID = "runtime-clock"


class FakeSceneService:
    def __init__(self, profile_id: str) -> None:
        self.profile = {
            "id": profile_id,
            "name": "D4 Livestream",
            "obs_scene_name": "D4",
            "sources": [{
                "id": RUNTIME_SOURCE_ID,
                "name": "Clock",
                "type": "browser_source",
                "obs_name": "StreamOps Clock",
                "enabled": False,
                "settings": {"url": "http://example.invalid"},
                "transform": {"x": 100, "y": 50, "width": 320, "height": 180},
            }],
        }

    def close(self) -> None:
        pass

    def current_scene(self) -> str:
        return "D4"

    def get_profile(self, profile_id: str):
        if profile_id != self.profile["id"]:
            raise KeyError(profile_id)
        return self.profile

    def verify_profile(self, profile_id: str, *, runtime: bool = True):
        self.get_profile(profile_id)
        return SimpleNamespace(status="PASS")

    def activate_profile(self, profile_id: str):
        self.get_profile(profile_id)
        return {"profile_id": profile_id, "active": True}


class FakeObsClient:
    def __init__(self) -> None:
        self.active = False
        self.service = {"streamServiceType": "rtmp_common", "streamServiceSettings": {"service": "Existing"}}
        self.item = {"sceneItemId": 7, "sourceName": "StreamOps Clock", "sceneItemEnabled": False}
        self.transform = {
            "positionX": 100.0,
            "positionY": 50.0,
            "scaleX": 1.0,
            "scaleY": 1.0,
            "rotation": 0.0,
            "cropLeft": 0,
            "cropRight": 0,
            "cropTop": 0,
            "cropBottom": 0,
        }

    def close(self):
        pass

    def get_stream_status(self):
        return {
            "outputActive": self.active,
            "outputReconnecting": False,
            "outputDuration": 1000 if self.active else 0,
            "outputBytes": 10000 if self.active else 0,
            "outputCongestion": 0.0,
            "outputSkippedFrames": 0,
            "outputTotalFrames": 60 if self.active else 0,
        }

    def get_stats(self):
        return {"activeFps": 60.0, "cpuUsage": 5.0}

    def get_stream_service_settings(self):
        return {"streamServiceType": self.service["streamServiceType"], "streamServiceSettings": dict(self.service["streamServiceSettings"])}

    def set_stream_service_settings(self, service_type: str, settings: dict):
        self.service = {"streamServiceType": service_type, "streamServiceSettings": dict(settings)}

    def start_stream(self):
        self.active = True

    def stop_stream(self):
        self.active = False

    def get_scene_item_list(self, scene_name: str):
        assert scene_name == "D4"
        return [dict(self.item)]

    def set_scene_item_enabled(self, scene_name: str, item_id: int, enabled: bool):
        assert scene_name == "D4"
        assert item_id == 7
        self.item["sceneItemEnabled"] = enabled

    def get_scene_item_transform(self, scene_name: str, item_id: int):
        assert scene_name == "D4"
        assert item_id == 7
        return dict(self.transform)

    def set_scene_item_transform(self, scene_name: str, item_id: int, transform: dict):
        assert scene_name == "D4"
        assert item_id == 7
        self.transform.update(transform)


class NoopObsStatusHub:
    async def start(self):
        pass

    async def close(self):
        pass

    def trigger_refresh(self):
        pass


DESTINATION = {
    "name": "LAN Test",
    "type": "custom_rtmp",
    "enabled": True,
    "settings": {"server_url": "rtmp://192.168.1.20:1935/live"},
}


def _app(server_config, capture_service, tmp_path: Path):
    profile_id = str(uuid4())
    manager = FakeManager()
    scenes = FakeSceneService(profile_id)
    obs = FakeObsClient()
    live = LiveService(
        manager,
        scenes,
        DestinationStore(tmp_path / "destinations"),
        SecretStore(tmp_path / "secrets"),
        client_factory=lambda: obs,
        poll_interval=0.001,
    )
    hub = LiveStatusHub(live, reconcile_interval=1000, heartbeat_interval=1000)
    app = create_app(
        server_config,
        capture_service=capture_service,
        obs_manager=manager,
        obs_scene_service=scenes,
        obs_status_hub=NoopObsStatusHub(),
        live_service=live,
        live_status_hub=hub,
        manage_runtime=False,
    )
    return app, profile_id


def test_http_streaming_contract(server_config, capture_service, tmp_path: Path) -> None:
    app, profile_id = _app(server_config, capture_service, tmp_path)
    with TestClient(app) as client:
        catalog = client.get("/api/v1/stream-destination-types")
        assert catalog.status_code == 200
        assert catalog.json()["types"][0]["type"] == "custom_rtmp"
        assert catalog.json()["types"][0]["settings"][0]["key"] == "server_url"

        created = client.post("/api/v1/stream-destinations", json=DESTINATION)
        assert created.status_code == 201
        destination_id = created.json()["id"]
        assert created.json()["credential_configured"] is False
        assert client.get(f"/api/v1/stream-destinations/{destination_id}").status_code == 200

        updated_payload = {
            **DESTINATION,
            "name": "LAN Test Renamed",
            "enabled": False,
        }
        updated = client.put(
            f"/api/v1/stream-destinations/{destination_id}",
            json=updated_payload,
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "LAN Test Renamed"
        assert updated.json()["enabled"] is False

        updated_payload["enabled"] = True
        assert client.put(
            f"/api/v1/stream-destinations/{destination_id}",
            json=updated_payload,
        ).json()["enabled"] is True

        credential = client.put(
            f"/api/v1/stream-destinations/{destination_id}/credential",
            json={"credential": "private-key"},
        )
        assert credential.json() == {"credential_configured": True}
        assert "private-key" not in client.get("/api/v1/stream-destinations").text

        args = {"profile_id": profile_id, "destination_id": destination_id}
        assert client.post("/api/v1/live/preflight", json=args).json()["status"] == "PASS"
        assert client.post("/api/v1/live/start", json=args).json()["state"] == "LIVE"
        assert client.get("/api/v1/live/status").json()["state"] == "LIVE"

        shown = client.patch(
            f"/api/v1/live/sources/{RUNTIME_SOURCE_ID}/visibility",
            json={"visible": True},
        )
        assert shown.status_code == 200
        assert shown.json()["actual"]["visible"] is True

        positioned = client.patch(
            f"/api/v1/live/sources/{RUNTIME_SOURCE_ID}/position",
            json={"x": 40},
        )
        assert positioned.status_code == 200
        assert positioned.json()["actual"]["position"] == {"x": 40.0, "y": 50.0}

        moved = client.post(
            f"/api/v1/live/sources/{RUNTIME_SOURCE_ID}/move",
            json={"dx": 20, "dy": 10},
        )
        assert moved.status_code == 200
        assert moved.json()["actual"]["position"] == {"x": 60.0, "y": 60.0}

        runtime_status = client.get("/api/v1/live/status").json()["runtime_scene"]
        assert runtime_status["status"] == "PASS"
        assert runtime_status["sources"][0]["override"]["visibility"] is True

        rejected = client.patch(
            f"/api/v1/live/sources/{RUNTIME_SOURCE_ID}/position",
            json={"x": 1, "rotation": 90},
        )
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "invalid_request"

        reset = client.delete(
            f"/api/v1/live/sources/{RUNTIME_SOURCE_ID}/overrides"
        )
        assert reset.status_code == 200
        assert reset.json()["override"] == {}

        blocked_update = client.put(
            f"/api/v1/stream-destinations/{destination_id}",
            json={**updated_payload, "name": "Blocked While Live"},
        )
        assert blocked_update.status_code == 409
        assert blocked_update.json()["error"]["code"] == "destination_in_use"
        blocked_credential = client.delete(
            f"/api/v1/stream-destinations/{destination_id}/credential"
        )
        assert blocked_credential.status_code == 409
        assert blocked_credential.json()["error"]["code"] == "destination_in_use"

        assert client.post("/api/v1/live/stop").json()["state"] == "IDLE"

        removed = client.delete(f"/api/v1/stream-destinations/{destination_id}")
        assert removed.status_code == 200
        assert removed.json() == {"deleted": True}
        assert client.get(f"/api/v1/stream-destinations/{destination_id}").status_code == 404


def _response(websocket, request_id: str, *, collect_events: bool = False):
    events = []
    while True:
        message = websocket.receive_json()
        if message.get("type") == "response" and message.get("request_id") == request_id:
            return (message, events) if collect_events else message
        if collect_events and message.get("type") == "event":
            events.append(message)


def _event(websocket, event: str, *, state: str | None = None) -> dict:
    while True:
        message = websocket.receive_json()
        if message.get("type") != "event" or message.get("event") != event:
            continue
        if state is None or message.get("data", {}).get("state") == state:
            return message


def test_live_websocket_initial_snapshot_and_commands(server_config, capture_service, tmp_path: Path) -> None:
    app, profile_id = _app(server_config, capture_service, tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/live/ws") as websocket:
            initial = websocket.receive_json()
            assert initial["type"] == "event"
            assert initial["event"] == "stream.snapshot"
            assert initial["data"]["state"] == "IDLE"

            websocket.send_json({
                "type": "request",
                "request_id": "create-1",
                "operation": "destinations.create",
                "payload": {"destination": DESTINATION},
            })
            created = _response(websocket, "create-1")
            assert created["ok"] is True
            destination_id = created["data"]["id"]

            websocket.send_json({
                "type": "request",
                "request_id": "credential-1",
                "operation": "destinations.set_credential",
                "payload": {"destination_id": destination_id, "credential": "private-key"},
            })
            assert _response(websocket, "credential-1")["ok"] is True

            websocket.send_json({
                "type": "request",
                "request_id": "start-1",
                "operation": "live.start",
                "payload": {"profile_id": profile_id, "destination_id": destination_id},
            })
            started, events = _response(websocket, "start-1", collect_events=True)
            assert started["ok"] is True
            assert started["data"]["state"] == "LIVE"
            live_event = next(
                (
                    item for item in events
                    if item.get("event") == "stream.snapshot" and item.get("data", {}).get("state") == "LIVE"
                ),
                None,
            )
            if live_event is None:
                live_event = _event(websocket, "stream.snapshot", state="LIVE")
            assert live_event["data"]["destination"]["id"] == destination_id
            assert "private-key" not in repr(live_event)

            websocket.send_json({
                "type": "request",
                "request_id": "show-source-1",
                "operation": "live.source.visibility",
                "payload": {"source_id": RUNTIME_SOURCE_ID, "visible": True},
            })
            shown = _response(websocket, "show-source-1")
            assert shown["ok"] is True
            assert shown["data"]["actual"]["visible"] is True

            websocket.send_json({
                "type": "request",
                "request_id": "move-source-1",
                "operation": "live.source.move",
                "payload": {"source_id": RUNTIME_SOURCE_ID, "dx": 20, "dy": 10},
            })
            moved = _response(websocket, "move-source-1")
            assert moved["ok"] is True
            assert moved["data"]["actual"]["position"] == {"x": 120.0, "y": 60.0}

            with client.websocket_connect("/api/v1/live/ws") as reconnected:
                initial_after_reconnect = reconnected.receive_json()
                assert initial_after_reconnect["type"] == "event"
                assert initial_after_reconnect["event"] == "stream.snapshot"
                assert initial_after_reconnect["data"]["state"] == "LIVE"
                runtime_scene = initial_after_reconnect["data"]["runtime_scene"]
                assert runtime_scene["status"] == "PASS"
                assert runtime_scene["overrides"][RUNTIME_SOURCE_ID]["visibility"] is True
                assert runtime_scene["overrides"][RUNTIME_SOURCE_ID]["position"] == {
                    "x": 120.0,
                    "y": 60.0,
                }

            websocket.send_json({
                "type": "request",
                "request_id": "bad-transform-1",
                "operation": "live.source.position",
                "payload": {"source_id": RUNTIME_SOURCE_ID, "x": 1, "rotation": 90},
            })
            rejected = _response(websocket, "bad-transform-1")
            assert rejected["ok"] is False
            assert rejected["error"]["code"] == "invalid_request"

            websocket.send_json({
                "type": "request",
                "request_id": "reset-source-1",
                "operation": "live.source.reset",
                "payload": {"source_id": RUNTIME_SOURCE_ID},
            })
            reset = _response(websocket, "reset-source-1")
            assert reset["ok"] is True
            assert reset["data"]["override"] == {}

            websocket.send_json({
                "type": "request",
                "request_id": "blocked-update-1",
                "operation": "destinations.update",
                "payload": {
                    "destination_id": destination_id,
                    "destination": {**DESTINATION, "name": "Blocked While Live"},
                },
            })
            blocked = _response(websocket, "blocked-update-1")
            assert blocked["ok"] is False
            assert blocked["error"]["code"] == "destination_in_use"

            websocket.send_json({
                "type": "request",
                "request_id": "stop-1",
                "operation": "live.stop",
                "payload": {},
            })
            stopped = _response(websocket, "stop-1")
            assert stopped["ok"] is True
            assert stopped["data"]["state"] == "IDLE"
