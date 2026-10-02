from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from streamops.server.errors import StreamingError
from streamops.server.services.live import LiveService
from streamops.server.streaming import DestinationStore, LiveSessionStore, SecretStore
from streamops.server.streaming.adapters import CustomRtmpAdapter, destination_type_catalog
from streamops.server.streaming.outputs import ObsNativeOutputEngine


class FakeManager:
    def __init__(self, state: str = "READY") -> None:
        self.state = state

    def status(self):
        return SimpleNamespace(state=self.state)


class FakeSceneService:
    def __init__(self, profile_id: str) -> None:
        self.profile = {"id": profile_id, "name": "D4", "obs_scene_name": "D4"}
        self.verify_status = "PASS"

    def get_profile(self, profile_id: str):
        if profile_id != self.profile["id"]:
            raise KeyError(profile_id)
        return self.profile

    def verify_profile(self, profile_id: str, *, runtime: bool = True):
        self.get_profile(profile_id)
        return SimpleNamespace(status=self.verify_status)

    def activate_profile(self, profile_id: str):
        self.get_profile(profile_id)
        return {"active": True}


class FakeObsClient:
    def __init__(self) -> None:
        self.active = False
        self.start_mode = "normal"
        self.stop_mode = "normal"
        self.fail_restore = False
        self.start_calls = 0
        self.stop_calls = 0
        self.service = {
            "streamServiceType": "rtmp_common",
            "streamServiceSettings": {"service": "Existing", "key": "old-private-key"},
        }

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
        return {"activeFps": 60.0, "cpuUsage": 3.0}

    def get_stream_service_settings(self):
        return {
            "streamServiceType": self.service["streamServiceType"],
            "streamServiceSettings": dict(self.service["streamServiceSettings"]),
        }

    def set_stream_service_settings(self, service_type: str, settings: dict):
        if self.fail_restore and service_type == "rtmp_common":
            raise RuntimeError("restore failed with hidden settings")
        self.service = {
            "streamServiceType": service_type,
            "streamServiceSettings": dict(settings),
        }

    def start_stream(self):
        self.start_calls += 1
        if self.start_mode == "raise":
            raise RuntimeError("start failed")
        if self.start_mode == "normal":
            self.active = True

    def stop_stream(self):
        self.stop_calls += 1
        if self.stop_mode == "raise":
            raise RuntimeError("stop failed")
        if self.stop_mode == "normal":
            self.active = False


DESTINATION = {
    "name": "LAN Test",
    "type": "custom_rtmp",
    "enabled": True,
    "settings": {"server_url": "rtmp://127.0.0.1:1935/live"},
}


def make_service(tmp_path: Path, client: FakeObsClient, *, manager_state: str = "READY"):
    profile_id = str(uuid4())
    scenes = FakeSceneService(profile_id)
    destinations = DestinationStore(tmp_path / "destinations")
    secrets = SecretStore(tmp_path / "secrets")
    session = LiveSessionStore(tmp_path / "live-session")
    service = LiveService(
        FakeManager(manager_state),
        scenes,
        destinations,
        secrets,
        session_store=session,
        client_factory=lambda: client,
        poll_interval=0.001,
        start_timeout=0.01,
        stop_timeout=0.01,
    )
    destination = service.create_destination(DESTINATION)
    service.set_credential(destination["id"], "noru-live")
    return service, scenes, destinations, secrets, session, profile_id, destination["id"]


def test_custom_rtmp_adapter_and_catalog_are_generic() -> None:
    adapter = CustomRtmpAdapter()
    destination = {
        "id": str(uuid4()),
        **DESTINATION,
    }
    resolved = adapter.resolve(destination, "noru-live")

    assert resolved["service_type"] == "rtmp_custom"
    assert resolved["settings"]["server"] == "rtmp://127.0.0.1:1935/live"
    assert resolved["settings"]["key"] == "noru-live"

    catalog = destination_type_catalog()
    assert catalog[0]["type"] == "custom_rtmp"
    assert catalog[0]["settings"][0]["key"] == "server_url"
    assert catalog[0]["credential"]["type"] == "password"
    assert "noru-live" not in repr(catalog)


def test_obs_native_engine_enforces_single_output(tmp_path: Path) -> None:
    engine = ObsNativeOutputEngine(
        FakeObsClient(),
        LiveSessionStore(tmp_path / "session"),
        poll_interval=0.001,
    )
    resolved = {
        "service_type": "rtmp_custom",
        "settings": {"server": "rtmp://127.0.0.1/live", "key": "secret"},
    }

    with pytest.raises(StreamingError) as error:
        engine.prepare([resolved, resolved])

    assert error.value.code == "output_limit_exceeded"
    assert engine.max_destinations == 1


def test_start_timeout_rolls_back_service_and_clears_session(tmp_path: Path) -> None:
    client = FakeObsClient()
    client.start_mode = "stuck"
    service, _, _, _, session, profile_id, destination_id = make_service(tmp_path, client)

    with pytest.raises(StreamingError) as error:
        service.start(profile_id, destination_id)

    assert error.value.code == "stream_start_timeout"
    assert client.active is False
    assert client.service["streamServiceType"] == "rtmp_common"
    assert session.load_session() is None
    assert session.load_restore() is None


def test_stop_timeout_keeps_recovery_state(tmp_path: Path) -> None:
    client = FakeObsClient()
    service, _, _, _, session, profile_id, destination_id = make_service(tmp_path, client)
    service.start(profile_id, destination_id)
    client.stop_mode = "stuck"

    with pytest.raises(StreamingError) as error:
        service.stop()

    assert error.value.code == "stream_stop_timeout"
    assert client.active is True
    assert session.load_session()["state"] == "RECOVERY_REQUIRED"
    assert session.has_restore() is True


def test_restore_failure_is_reported_without_leaking_snapshot(tmp_path: Path) -> None:
    client = FakeObsClient()
    service, _, _, _, session, profile_id, destination_id = make_service(tmp_path, client)
    service.start(profile_id, destination_id)
    client.fail_restore = True

    with pytest.raises(StreamingError) as error:
        service.stop()

    assert error.value.code == "stream_restore_failed"
    assert "old-private-key" not in str(error.value)
    assert session.load_session()["state"] == "RESTORE_FAILED"
    assert session.has_restore() is True
    assert service.status()["state"] == "RESTORE_FAILED"


def test_persisted_session_recovers_after_node_restart(tmp_path: Path) -> None:
    client = FakeObsClient()
    service, scenes, destinations, secrets, session, profile_id, destination_id = make_service(
        tmp_path, client
    )
    service.start(profile_id, destination_id)

    assert client.active is True
    assert session.load_session()["state"] == "LIVE"
    assert "old-private-key" not in session.session_path.read_text(encoding="utf-8")
    assert "old-private-key" in session.restore_path.read_text(encoding="utf-8")

    restarted = LiveService(
        FakeManager(),
        scenes,
        destinations,
        secrets,
        session_store=LiveSessionStore(tmp_path / "live-session"),
        client_factory=lambda: client,
        poll_interval=0.001,
        start_timeout=0.01,
        stop_timeout=0.01,
    )

    recovered = restarted.status()
    assert recovered["state"] == "LIVE"
    assert recovered["managed"] is True
    assert recovered["destination"]["id"] == destination_id

    stopped = restarted.stop()
    assert stopped["state"] == "IDLE"
    assert client.active is False
    assert client.service["streamServiceType"] == "rtmp_common"
    assert restarted.session_store.load_session() is None
    assert restarted.session_store.load_restore() is None


def test_obs_not_ready_and_disabled_destination_block_start(tmp_path: Path) -> None:
    client = FakeObsClient()
    service, _, destinations, _, _, profile_id, destination_id = make_service(
        tmp_path, client, manager_state="STOPPED"
    )

    with pytest.raises(StreamingError) as error:
        service.start(profile_id, destination_id)
    assert error.value.code == "obs_not_ready"
    assert client.start_calls == 0

    service.manager.state = "READY"
    destination = destinations.get(destination_id)
    destination["enabled"] = False
    destinations.update(destination_id, destination)

    with pytest.raises(StreamingError) as error:
        service.start(profile_id, destination_id)
    assert error.value.code == "destination_disabled"
    assert client.start_calls == 0
