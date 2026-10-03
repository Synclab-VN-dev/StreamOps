from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from streamops.server.errors import StreamingError
from streamops.server.services.live import LiveService
from streamops.server.streaming import DestinationStore, SecretStore


class FakeManager:
    def __init__(self, state: str = "READY") -> None:
        self.state = state

    def status(self):
        return SimpleNamespace(state=self.state)


class FakeSceneService:
    def __init__(self, profile_id: str) -> None:
        self.profile = {"id": profile_id, "name": "D4 Livestream", "obs_scene_name": "D4"}
        self.verify_status = "PASS"
        self.activated: list[str] = []

    def get_profile(self, profile_id: str):
        if profile_id != self.profile["id"]:
            raise KeyError(profile_id)
        return self.profile

    def verify_profile(self, profile_id: str, *, runtime: bool = True):
        self.get_profile(profile_id)
        return SimpleNamespace(status=self.verify_status)

    def activate_profile(self, profile_id: str):
        self.get_profile(profile_id)
        self.activated.append(profile_id)
        return {"profile_id": profile_id, "active": True}


class FakeObsClient:
    def __init__(self) -> None:
        self.active = False
        self.start_calls = 0
        self.stop_calls = 0
        self.service = {
            "streamServiceType": "rtmp_common",
            "streamServiceSettings": {"service": "Existing", "key": "old-private-key"},
        }
        self.service_history: list[tuple[str, dict]] = []

    def close(self) -> None:
        pass

    def get_stream_status(self):
        return {
            "outputActive": self.active,
            "outputReconnecting": False,
            "outputDuration": 1000 if self.active else 0,
            "outputBytes": 5000 if self.active else 0,
            "outputCongestion": 0.0,
            "outputSkippedFrames": 0,
            "outputTotalFrames": 60 if self.active else 0,
        }

    def get_stats(self):
        return {"activeFps": 60.0, "cpuUsage": 4.0}

    def get_stream_service_settings(self):
        return {
            "streamServiceType": self.service["streamServiceType"],
            "streamServiceSettings": dict(self.service["streamServiceSettings"]),
        }

    def set_stream_service_settings(self, service_type: str, settings: dict):
        self.service = {"streamServiceType": service_type, "streamServiceSettings": dict(settings)}
        self.service_history.append((service_type, dict(settings)))

    def start_stream(self):
        self.start_calls += 1
        self.active = True

    def stop_stream(self):
        self.stop_calls += 1
        self.active = False


def _service(tmp_path: Path):
    profile_id = str(uuid4())
    scenes = FakeSceneService(profile_id)
    client = FakeObsClient()
    service = LiveService(
        FakeManager(),
        scenes,
        DestinationStore(tmp_path / "destinations"),
        SecretStore(tmp_path / "secrets"),
        client_factory=lambda: client,
        poll_interval=0.001,
    )
    destination = service.create_destination({
        "name": "LAN Test",
        "type": "custom_rtmp",
        "enabled": True,
        "settings": {"server_url": "rtmp://192.168.1.20:1935/live"},
    })
    return service, scenes, client, profile_id, destination["id"]


def test_preflight_requires_credential(tmp_path: Path) -> None:
    service, _, _, profile_id, destination_id = _service(tmp_path)

    result = service.preflight(profile_id, destination_id)

    assert result["status"] == "FAIL"
    assert next(item for item in result["checks"] if item["id"] == "credential")["status"] == "FAIL"


def test_start_is_idempotent_and_stop_restores_previous_service(tmp_path: Path) -> None:
    service, scenes, client, profile_id, destination_id = _service(tmp_path)
    service.set_credential(destination_id, "new-private-key")

    started = service.start(profile_id, destination_id)
    started_again = service.start(profile_id, destination_id)

    assert started["state"] == "LIVE"
    assert started_again["state"] == "LIVE"
    assert started["managed"] is True
    assert client.start_calls == 1
    assert scenes.activated == [profile_id]
    assert client.service["streamServiceType"] == "rtmp_custom"
    assert client.service["streamServiceSettings"]["key"] == "new-private-key"
    assert "new-private-key" not in repr(started)

    stopped = service.stop()
    stopped_again = service.stop()

    assert stopped["state"] == "IDLE"
    assert stopped_again["state"] == "IDLE"
    assert client.stop_calls == 1
    assert client.service["streamServiceType"] == "rtmp_common"
    assert client.service["streamServiceSettings"]["key"] == "old-private-key"


def test_profile_verify_failure_blocks_start_before_obs_mutation(tmp_path: Path) -> None:
    service, scenes, client, profile_id, destination_id = _service(tmp_path)
    service.set_credential(destination_id, "new-private-key")
    scenes.verify_status = "FAIL"

    with pytest.raises(StreamingError) as error:
        service.start(profile_id, destination_id)

    assert error.value.code == "profile_verify_failed"
    assert client.start_calls == 0
    assert not client.service_history


def test_active_destination_mutations_are_locked_until_stop_cleanup(tmp_path: Path) -> None:
    service, _, _, profile_id, destination_id = _service(tmp_path)
    service.set_credential(destination_id, "new-private-key")
    assert service.start(profile_id, destination_id)["state"] == "LIVE"

    mutations = (
        lambda: service.update_destination(destination_id, {
            "name": "Blocked Rename",
            "type": "custom_rtmp",
            "enabled": True,
            "settings": {"server_url": "rtmp://192.168.1.20:1935/live"},
        }),
        lambda: service.delete_destination(destination_id),
        lambda: service.set_credential(destination_id, "replacement-private-key"),
        lambda: service.delete_credential(destination_id),
    )
    for mutate in mutations:
        with pytest.raises(StreamingError) as error:
            mutate()
        assert error.value.code == "destination_in_use"
        assert error.value.status_code == 409

    assert service.stop()["state"] == "IDLE"
    renamed = service.update_destination(destination_id, {
        "name": "Allowed Rename",
        "type": "custom_rtmp",
        "enabled": True,
        "settings": {"server_url": "rtmp://192.168.1.20:1935/live"},
    })
    assert renamed["name"] == "Allowed Rename"
