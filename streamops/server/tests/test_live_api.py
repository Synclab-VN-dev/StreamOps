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


class FakeSceneService:
    def __init__(self, profile_id: str) -> None:
        self.profile = {"id": profile_id, "name": "D4 Livestream", "obs_scene_name": "D4"}

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
                "request_id": "stop-1",
                "operation": "live.stop",
                "payload": {},
            })
            stopped = _response(websocket, "stop-1")
            assert stopped["ok"] is True
            assert stopped["data"]["state"] == "IDLE"
