from __future__ import annotations

from pathlib import Path

from streamops.server.services.live import LiveService
from streamops.server.streaming import DestinationStore, SecretStore


DESTINATION = {
    "name": "LAN Test",
    "type": "custom_rtmp",
    "enabled": True,
    "settings": {"server_url": "rtmp://192.168.1.20:1935/live"},
}


class _NeverUsed:
    def status(self):
        raise AssertionError("not used")


def test_destination_store_survives_corrupted_record(tmp_path: Path) -> None:
    store = DestinationStore(tmp_path / "destinations")
    created = store.create(DESTINATION)
    (store.root / "broken.json").write_text("{not-json", encoding="utf-8")

    result = store.list()

    assert [item["id"] for item in result["destinations"]] == [created["id"]]
    assert result["errors"][0]["file"] == "broken.json"


def test_secret_is_separate_and_public_destination_only_exposes_configured_flag(tmp_path: Path) -> None:
    destinations = DestinationStore(tmp_path / "destinations")
    secrets = SecretStore(tmp_path / "secrets")
    service = LiveService(_NeverUsed(), _NeverUsed(), destinations, secrets)
    created = service.create_destination(DESTINATION)

    assert created["credential_configured"] is False
    assert "credential" not in str(created).lower()

    result = service.set_credential(created["id"], "super-secret-stream-key")
    public = service.get_destination(created["id"])

    assert result == {"credential_configured": True}
    assert public["credential_configured"] is True
    assert "super-secret-stream-key" not in repr(public)
    assert secrets.get(created["id"]) == "super-secret-stream-key"
