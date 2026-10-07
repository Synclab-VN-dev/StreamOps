from __future__ import annotations

import json
from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest

from streamops.server.app import create_app
from streamops.server.errors import StreamingError
from streamops.server.multistream.repository import MultistreamRepository
from streamops.server.multistream.secrets import MultistreamSecretStore
from streamops.server.services.multistream import MultistreamService


class FakeAdapter:
    def __init__(self) -> None:
        self.targets: list[dict] = []
        self.runtime: dict[str, dict] = {}
        self.calls: list[tuple] = []
        self.next_id = 1
        self.fail_with: Exception | None = None

    def list_targets(self):
        return [dict(target) for target in self.targets]

    def add_target(self, name):
        self.calls.append(("add", name))
        target = {"id": str(self.next_id), "name": name}
        self.next_id += 1
        self.targets.append(target)
        self.runtime[target["id"]] = {"runtimeState": "IDLE", "status": "stopped"}
        return {"status": "target_added"}

    def delete_target(self, target_id):
        self.calls.append(("delete", target_id))
        self.targets = [target for target in self.targets if target["id"] != target_id]
        self.runtime.pop(target_id, None)
        return {}

    def update_name(self, target_id, name):
        self.calls.append(("name", target_id, name))
        next(target for target in self.targets if target["id"] == target_id)["name"] = name
        return {}

    def update_server(self, target_id, server_url):
        self.calls.append(("server", target_id, server_url))
        return {}

    def update_stream_key(self, target_id, key):
        self.calls.append(("key", target_id, key))
        if self.fail_with is not None:
            raise self.fail_with
        return {"status": "updated"}

    def start(self, target_id):
        self.calls.append(("start", target_id))
        self.runtime[target_id] = {"runtimeState": "STARTING", "status": "connecting"}
        return {"status": "start_requested", "id": target_id}

    def stop(self, target_id):
        self.calls.append(("stop", target_id))
        self.runtime[target_id] = {"runtimeState": "STOPPING", "status": "stopping"}
        return {"status": "stop_requested", "id": target_id}

    def state(self, target_id):
        self._fail()
        if target_id not in self.runtime:
            raise RuntimeError("target missing")
        return dict(self.runtime[target_id])

    def stats(self, target_id):
        self._fail()
        return {
            **self.runtime[target_id],
            "id": target_id,
            "totalBytes": 123,
            "totalFrames": 45,
            "bitrateValue": 6000,
            "fpsValue": 30,
            "streamKey": "must-not-leak",
        }

    def set_state(self, target_id: str, state: str) -> None:
        self.runtime[target_id] = {
            "runtimeState": state,
            "status": state.casefold(),
            "isRunning": state in {"LIVE", "RECONNECTING"},
        }

    def _fail(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with


class NoopCapture:
    def start(self):
        pass

    def close(self):
        pass


def make(tmp_path: Path, **kwargs):
    adapter = FakeAdapter()
    service = MultistreamService(
        MultistreamRepository(tmp_path / "multi"),
        adapter,
        MultistreamSecretStore(tmp_path / "secrets"),
        **kwargs,
    )
    return service, adapter


def payload(destination_id: str = "destination-a", name: str = "Destination A"):
    return {
        "destination_id": destination_id,
        "name": name,
        "server_url": "rtmp://receiver/live",
        "credential": "super-secret",
    }


def assert_private_values_absent(value) -> None:
    rendered = json.dumps(value, sort_keys=True)
    assert "super-secret" not in rendered
    assert "must-not-leak" not in rendered
    assert "credential" not in rendered.casefold()
    assert "streamkey" not in rendered.casefold()
    assert "stream_key" not in rendered.casefold()
    assert "plugin_target_id" not in rendered


def wait_for_state(client: TestClient, destination_id: str, state: str) -> dict:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/multistream/destinations/{destination_id}/status")
        if response.status_code == 200 and response.json()["state"] == state:
            return response.json()
        time.sleep(0.01)
    raise AssertionError(f"destination {destination_id} did not reach {state}")


def test_core_crud_identity_and_secret_redaction(tmp_path):
    service, adapter = make(tmp_path)
    created = service.create_destination(payload())
    assert created["destination_id"] == "destination-a"
    assert_private_values_absent(created)

    updated = service.update_destination("destination-a", {"name": "Renamed", "credential": "new-secret"})
    assert updated["destination_id"] == "destination-a"
    assert service.repository.get("destination-a")["plugin_target_id"] == "1"
    assert adapter.targets[0]["name"] == "Renamed"
    assert service.secrets.get("destination-a") == "new-secret"

    assert service.delete_destination("destination-a") == {"deleted": True}
    assert adapter.targets == []
    assert not service.secrets.exists("destination-a")


def test_vendor_ack_is_starting_until_runtime_reports_live(tmp_path):
    service, adapter = make(tmp_path)
    service.create_destination(payload())
    events: list[dict] = []
    service.subscribe(events.append)

    started = service.start_destination("destination-a")
    assert started["state"] == "STARTING"
    assert [call[0] for call in adapter.calls].count("start") == 1
    assert service.start_destination("destination-a")["state"] == "STARTING"
    assert [call[0] for call in adapter.calls].count("start") == 1

    adapter.set_state("1", "LIVE")
    assert service.status("destination-a")["state"] == "LIVE"
    states = [event["data"]["state"] for event in events if event["type"] == "destination.state_changed"]
    assert states == ["STARTING", "LIVE"]

    stopped = service.stop_destination("destination-a")
    assert stopped["state"] == "STOPPING"
    assert service.stop_destination("destination-a")["state"] == "STOPPING"
    assert [call[0] for call in adapter.calls].count("stop") == 1
    adapter.set_state("1", "IDLE")
    assert service.status("destination-a")["state"] == "IDLE"


@pytest.mark.parametrize("state", ["IDLE", "STARTING", "LIVE", "RECONNECTING", "STOPPING", "FAILED"])
def test_runtime_state_normalization_uses_vendor_machine_state(tmp_path, state):
    service, adapter = make(tmp_path)
    service.create_destination(payload())
    adapter.set_state("1", state)
    assert service.status("destination-a")["state"] == state


def test_stats_are_allowlisted_and_do_not_expose_vendor_identity(tmp_path):
    service, adapter = make(tmp_path)
    service.create_destination(payload())
    adapter.set_state("1", "LIVE")
    result = service.stats("destination-a")
    assert result == {
        "destination_id": "destination-a",
        "state": "LIVE",
        "stats": {"total_bytes": 123, "total_frames": 45, "bitrate_bps": 6000, "fps": 30},
    }
    assert_private_values_absent(result)


def test_validation_and_structured_errors(tmp_path):
    service, _adapter = make(tmp_path)
    with pytest.raises(StreamingError) as missing:
        service.create_destination({})
    assert (missing.value.code, missing.value.status_code) == ("credential_invalid", 422)

    service.create_destination(payload())
    with pytest.raises(StreamingError) as duplicate:
        service.create_destination(payload("destination-b"))
    assert (duplicate.value.code, duplicate.value.status_code) == ("destination_conflict", 409)
    with pytest.raises(StreamingError) as unknown:
        service.update_destination("destination-a", {"plugin_target_id": "public-leak"})
    assert (unknown.value.code, unknown.value.status_code) == ("destination_invalid", 422)
    with pytest.raises(StreamingError) as missing_destination:
        service.status("missing")
    assert (missing_destination.value.code, missing_destination.value.status_code) == ("destination_not_found", 404)


def test_vendor_failures_are_normalized_and_secret_is_redacted(tmp_path):
    service, adapter = make(tmp_path)
    adapter.fail_with = StreamingError("vendor_rejected", "bad credential super-secret", 503)
    with pytest.raises(StreamingError) as failure:
        service.create_destination(payload())
    assert failure.value.code == "vendor_rejected"
    assert "super-secret" not in str(failure.value)


def test_reconcile_repairs_or_recreates_mapping_without_public_identity_change(tmp_path):
    service, adapter = make(tmp_path)
    service.create_destination(payload())
    item = service.repository.get("destination-a")
    item["plugin_target_id"] = "stale"
    service.repository.save(item)
    assert service.reconcile() == {"reconciled": ["destination-a"]}
    assert service.repository.get("destination-a")["plugin_target_id"] == "1"

    adapter.targets.clear()
    adapter.runtime.clear()
    assert service.reconcile() == {"reconciled": ["destination-a"]}
    recreated = service.repository.get("destination-a")
    assert recreated["plugin_target_id"] == "2"
    assert service.get_destination("destination-a")["destination_id"] == "destination-a"


def test_http_ws_shared_core_snapshot_commands_events_and_state_parity(tmp_path, server_config):
    service, adapter = make(tmp_path, poll_interval=0.01)
    app = create_app(
        server_config,
        capture_service=NoopCapture(),
        multistream_service=service,
        manage_runtime=False,
    )
    with TestClient(app) as client:
        created = client.post("/api/v1/multistream/destinations", json=payload())
        assert created.status_code == 201
        assert_private_values_absent(created.json())

        with client.websocket_connect("/api/v1/multistream/ws") as websocket:
            snapshot = websocket.receive_json()
            assert snapshot["type"] == "multistream.snapshot"
            assert snapshot["data"] == client.get("/api/v1/multistream/destinations").json()

            started = client.post("/api/v1/multistream/destinations/destination-a/start")
            assert started.json()["state"] == "STARTING"
            start_event = websocket.receive_json()
            assert (start_event["type"], start_event["data"]["state"]) == (
                "destination.state_changed",
                "STARTING",
            )

            adapter.set_state("1", "LIVE")
            assert wait_for_state(client, "destination-a", "LIVE")["state"] == "LIVE"
            live_event = websocket.receive_json()
            assert (live_event["type"], live_event["data"]["state"]) == (
                "destination.state_changed",
                "LIVE",
            )

            websocket.send_json(
                {
                    "type": "request",
                    "request_id": "stop-1",
                    "operation": "destination.stop",
                    "payload": {"destination_id": "destination-a"},
                }
            )
            messages = [websocket.receive_json(), websocket.receive_json()]
            response = next(message for message in messages if message.get("type") == "response")
            event = next(
                message for message in messages
                if message.get("type") == "destination.state_changed"
            )
            assert response["request_id"] == "stop-1"
            assert response["ok"] is True and response["data"]["state"] == "STOPPING"
            assert event["data"]["state"] == "STOPPING"

            adapter.set_state("1", "IDLE")
            assert wait_for_state(client, "destination-a", "IDLE")["state"] == "IDLE"
            idle_event = websocket.receive_json()
            assert (idle_event["type"], idle_event["data"]["state"]) == (
                "destination.state_changed",
                "IDLE",
            )

        adapter.set_state("1", "LIVE")
        service.refresh()
        with client.websocket_connect("/api/v1/multistream/ws") as reconnected:
            snapshot = reconnected.receive_json()
            assert snapshot["type"] == "multistream.snapshot"
            assert snapshot["data"]["destinations"][0]["state"] == "LIVE"

    assert [call[0] for call in adapter.calls].count("start") == 1
    assert [call[0] for call in adapter.calls].count("stop") == 1


def test_http_and_ws_return_same_normalized_missing_destination_error(tmp_path, server_config):
    service, _adapter = make(tmp_path, poll_interval=0.01)
    app = create_app(
        server_config,
        capture_service=NoopCapture(),
        multistream_service=service,
        manage_runtime=False,
    )
    with TestClient(app) as client:
        http = client.post("/api/v1/multistream/destinations/missing/start")
        assert http.status_code == 404
        with client.websocket_connect("/api/v1/multistream/ws") as websocket:
            assert websocket.receive_json()["type"] == "multistream.snapshot"
            websocket.send_json(
                {
                    "type": "request",
                    "request_id": "missing-1",
                    "operation": "destination.start",
                    "payload": {"destination_id": "missing"},
                }
            )
            ws = websocket.receive_json()
        assert ws["ok"] is False
        assert ws["error"]["code"] == http.json()["error"]["code"] == "destination_not_found"
