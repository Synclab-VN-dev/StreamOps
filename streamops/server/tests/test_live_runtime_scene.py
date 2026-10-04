from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from streamops.server.errors import StreamingError
from streamops.server.services.live import LiveService
from streamops.server.streaming import DestinationStore, SecretStore


class FakeManager:
    def status(self):
        return SimpleNamespace(state="READY")


class FakeSceneService:
    def __init__(self, profile_id: str, source_id: str) -> None:
        self.profile = {
            "id": profile_id,
            "name": "Runtime Profile",
            "obs_scene_name": "Runtime Scene",
            "sources": [
                {
                    "id": source_id,
                    "name": "Clock",
                    "type": "browser_source",
                    "obs_name": "StreamOps Clock",
                    "enabled": False,
                    "settings": {"url": "http://example.invalid"},
                    "transform": {
                        "x": 100,
                        "y": 50,
                        "width": 320,
                        "height": 180,
                    },
                }
            ],
        }

    def get_profile(self, profile_id: str):
        if profile_id != self.profile["id"]:
            raise KeyError(profile_id)
        return self.profile

    def verify_profile(self, profile_id: str, *, runtime: bool = True):
        self.get_profile(profile_id)
        return SimpleNamespace(status="PASS")

    def activate_profile(self, profile_id: str):
        self.get_profile(profile_id)
        return {"active": True}


class FakeObsClient:
    def __init__(self) -> None:
        self.active = False
        self.service = {
            "streamServiceType": "rtmp_common",
            "streamServiceSettings": {"service": "Existing", "key": "old-key"},
        }
        self.item = {
            "sceneItemId": 7,
            "sourceName": "StreamOps Clock",
            "sceneItemEnabled": False,
        }
        self.transform = {
            "positionX": 100.0,
            "positionY": 50.0,
            "scaleX": 1.25,
            "scaleY": 1.25,
            "rotation": 17.0,
            "cropLeft": 11,
            "cropRight": 12,
            "cropTop": 13,
            "cropBottom": 14,
            "boundsType": "OBS_BOUNDS_NONE",
            "boundsWidth": 320.0,
            "boundsHeight": 180.0,
        }
        self.fail_transform = False

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
        return {
            "streamServiceType": self.service["streamServiceType"],
            "streamServiceSettings": dict(self.service["streamServiceSettings"]),
        }

    def set_stream_service_settings(self, service_type: str, settings: dict):
        self.service = {
            "streamServiceType": service_type,
            "streamServiceSettings": dict(settings),
        }

    def start_stream(self):
        self.active = True

    def stop_stream(self):
        self.active = False

    def get_scene_item_list(self, scene_name: str):
        assert scene_name == "Runtime Scene"
        return [dict(self.item)]

    def set_scene_item_enabled(self, scene_name: str, item_id: int, enabled: bool):
        assert scene_name == "Runtime Scene"
        assert item_id == 7
        self.item["sceneItemEnabled"] = enabled

    def get_scene_item_transform(self, scene_name: str, item_id: int):
        assert scene_name == "Runtime Scene"
        assert item_id == 7
        return dict(self.transform)

    def set_scene_item_transform(self, scene_name: str, item_id: int, transform: dict):
        assert scene_name == "Runtime Scene"
        assert item_id == 7
        if self.fail_transform:
            raise RuntimeError("synthetic transform failure")
        self.transform.update(transform)


def service_fixture(tmp_path: Path):
    profile_id = str(uuid4())
    source_id = str(uuid4())
    scenes = FakeSceneService(profile_id, source_id)
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
        "name": "LAN",
        "type": "custom_rtmp",
        "enabled": True,
        "settings": {"server_url": "rtmp://127.0.0.1:1935/live"},
    })
    service.set_credential(destination["id"], "secret")
    return service, scenes, client, profile_id, source_id, destination["id"]


def start_live(tmp_path: Path):
    service, scenes, client, profile_id, source_id, destination_id = service_fixture(tmp_path)
    baseline_profile = deepcopy(scenes.profile)
    started = service.start(profile_id, destination_id)
    assert started["state"] == "LIVE"
    return service, scenes, client, source_id, baseline_profile


def test_runtime_visibility_position_and_move_preserve_profile_and_transform(tmp_path: Path) -> None:
    service, scenes, client, source_id, baseline_profile = start_live(tmp_path)
    protected = {
        key: value
        for key, value in client.transform.items()
        if key not in {"positionX", "positionY"}
    }

    shown = service.set_source_visibility(source_id, True)
    assert shown["actual"]["visible"] is True
    assert shown["override"]["visibility"] is True
    assert client.active is True

    positioned = service.set_source_position(source_id, x=40)
    assert positioned["actual"]["position"] == {"x": 40.0, "y": 50.0}
    assert positioned["override"]["position"] == {"x": 40.0, "y": 50.0}
    assert {
        key: value
        for key, value in client.transform.items()
        if key not in {"positionX", "positionY"}
    } == protected

    moved = service.move_source(source_id, dx=20, dy=10)
    assert moved["actual"]["position"] == {"x": 60.0, "y": 60.0}
    assert moved["drift"] == []
    assert client.active is True
    assert scenes.profile == baseline_profile

    status = service.status()
    assert status["runtime_scene"]["status"] == "PASS"
    runtime = status["runtime_scene"]["sources"][0]
    assert runtime["baseline"]["visible"] is False
    assert runtime["effective"]["visible"] is True
    assert runtime["effective"]["position"] == {"x": 60.0, "y": 60.0}
    assert status["runtime_activity"][-1]["action"] == "move"


def test_known_override_is_not_drift_but_external_mutation_is(tmp_path: Path) -> None:
    service, _, client, source_id, _ = start_live(tmp_path)
    service.set_source_visibility(source_id, True)
    service.set_source_position(source_id, x=40, y=40)

    assert service.status()["runtime_scene"]["status"] == "PASS"

    client.transform["positionX"] = 700.0
    status = service.status()
    assert status["runtime_scene"]["status"] == "DRIFTED"
    assert status["runtime_scene"]["sources"][0]["drift"] == ["position"]


def test_reset_source_and_stop_restore_verified_baseline(tmp_path: Path) -> None:
    service, _, client, source_id, _ = start_live(tmp_path)
    service.set_source_visibility(source_id, True)
    service.set_source_position(source_id, x=40, y=40)

    reset = service.reset_source_overrides(source_id)
    assert reset["actual"]["visible"] is False
    assert reset["actual"]["position"] == {"x": 100.0, "y": 50.0}
    assert reset["override"] == {}

    service.set_source_visibility(source_id, True)
    service.set_source_position(source_id, x=10, y=20)
    stopped = service.stop()
    assert stopped["state"] == "IDLE"
    assert client.active is False
    assert client.item["sceneItemEnabled"] is False
    assert client.transform["positionX"] == 100.0
    assert client.transform["positionY"] == 50.0
    assert service.session_store.load_session() is None


def test_runtime_guards_reject_idle_unknown_and_arbitrary_values(tmp_path: Path) -> None:
    service, _, _, _, source_id, _ = service_fixture(tmp_path)

    with pytest.raises(StreamingError) as idle:
        service.set_source_visibility(source_id, True)
    assert idle.value.code == "live_runtime_unavailable"

    service, _, _, source_id, _ = start_live(tmp_path / "live")
    with pytest.raises(StreamingError) as unknown:
        service.set_source_visibility("not-owned", True)
    assert unknown.value.code == "runtime_source_not_owned"

    with pytest.raises(StreamingError) as invalid:
        service.set_source_position(source_id, x=float("nan"))
    assert invalid.value.code == "invalid_request"


def test_restore_failure_keeps_override_metadata_for_recovery(tmp_path: Path) -> None:
    service, _, client, source_id, _ = start_live(tmp_path)
    service.set_source_position(source_id, x=40, y=40)
    client.fail_transform = True

    with pytest.raises(StreamingError) as error:
        service.stop()

    assert error.value.code == "runtime_restore_failed"
    persisted = service.session_store.load_session()
    assert persisted is not None
    assert persisted["state"] == "RESTORE_FAILED"
    assert persisted["runtime_overrides"][source_id]["position"] == {"x": 40.0, "y": 40.0}


def test_runtime_override_recovers_after_live_service_restart(tmp_path: Path) -> None:
    service, scenes, client, source_id, baseline_profile = start_live(tmp_path)
    service.set_source_visibility(source_id, True)
    service.set_source_position(source_id, x=40, y=40)

    recovered = LiveService(
        FakeManager(),
        scenes,
        DestinationStore(tmp_path / "destinations"),
        SecretStore(tmp_path / "secrets"),
        client_factory=lambda: client,
        poll_interval=0.001,
    )

    status = recovered.status()
    assert status["state"] == "LIVE"
    assert status["managed"] is True
    assert status["runtime_scene"]["status"] == "PASS"
    runtime = status["runtime_scene"]["sources"][0]
    assert runtime["override"] == {
        "visibility": True,
        "position": {"x": 40.0, "y": 40.0},
    }
    assert runtime["actual"]["visible"] is True
    assert runtime["actual"]["position"] == {"x": 40.0, "y": 40.0}
    assert scenes.profile == baseline_profile

    stopped = recovered.stop()
    assert stopped["state"] == "IDLE"
    assert client.item["sceneItemEnabled"] is False
    assert client.transform["positionX"] == 100.0
    assert client.transform["positionY"] == 50.0


def test_reset_all_restores_baseline_without_touching_output_configuration(tmp_path: Path) -> None:
    service, _, client, source_id, _ = start_live(tmp_path)
    output_service = deepcopy(client.service)

    service.set_source_visibility(source_id, True)
    service.set_source_position(source_id, x=40, y=40)
    assert service.status()["runtime_scene"]["overrides"]

    reset = service.reset_runtime_overrides()

    assert reset["status"] == "PASS"
    assert reset["overrides"] == {}
    assert reset["sources"][0]["actual"]["visible"] is False
    assert reset["sources"][0]["actual"]["position"] == {"x": 100.0, "y": 50.0}
    assert client.service == output_service
    assert client.active is True
