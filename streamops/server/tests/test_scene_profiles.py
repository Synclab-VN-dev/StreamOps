from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from streamops.server.app import create_app
from streamops.server.profile_store import SceneProfileStore
from streamops.server.services.obs_scene import ObsSceneService
from streamops.server.errors import SceneProfileValidationError
from streamops.server.scene_profiles import normalize_profile


def test_profile_store_crud_duplicate_and_corrupt_isolation(tmp_path: Path) -> None:
    store = SceneProfileStore(tmp_path / "profiles")
    created = store.create({"name": "Studio"})
    assert created["name"] == "Studio"
    assert store.get(created["id"])["id"] == created["id"]

    created["sources"] = [{
        "name": "Overlay", "type": "browser_source", "enabled": True, "layer": 0,
        "settings": {"url": "https://example.invalid"},
        "transform": {"x": 0, "y": 0, "width": 640, "height": 360},
    }]
    updated = store.update(created["id"], created)
    duplicate = store.duplicate(created["id"])
    assert duplicate["id"] != updated["id"]
    assert duplicate["obs_scene_name"] != updated["obs_scene_name"]
    assert duplicate["sources"][0]["id"] != updated["sources"][0]["id"]
    assert duplicate["sources"][0]["obs_name"] != updated["sources"][0]["obs_name"]

    (store.root / "corrupt.json").write_text("{broken", encoding="utf-8")
    listing = store.list()
    assert len(listing["profiles"]) == 2
    assert listing["errors"][0]["file"] == "corrupt.json"
    assert json.loads((store.root / "index.json").read_text(encoding="utf-8"))["profiles"]

    store.delete(created["id"])
    assert len(store.list()["profiles"]) == 1


def test_profile_crud_api_does_not_contact_obs(server_config, capture_service, tmp_path: Path) -> None:
    service = ObsSceneService(root=Path.cwd(), data_dir=tmp_path / "profiles")
    with TestClient(create_app(server_config, capture_service=capture_service, obs_scene_service=service, manage_runtime=False)) as client:
        created = client.post("/api/v1/scene-profiles", json={"name": "API profile"})
        profile = created.json()
        listed = client.get("/api/v1/scene-profiles")
        profile["name"] = "Renamed"
        updated = client.put(f"/api/v1/scene-profiles/{profile['id']}", json=profile)
        copied = client.post(f"/api/v1/scene-profiles/{profile['id']}/duplicate", json={"name": "Copy"})
        deleted = client.delete(f"/api/v1/scene-profiles/{profile['id']}")

    assert created.status_code == 201
    assert listed.json()["profiles"][0]["name"] == "API profile"
    assert updated.json()["name"] == "Renamed"
    assert copied.status_code == 201 and copied.json()["id"] != profile["id"]
    assert deleted.status_code == 204


def test_profile_api_rejects_unknown_fields(server_config, capture_service, tmp_path: Path) -> None:
    service = ObsSceneService(root=Path.cwd(), data_dir=tmp_path / "profiles")
    with TestClient(create_app(server_config, capture_service=capture_service, obs_scene_service=service, manage_runtime=False)) as client:
        response = client.post("/api/v1/scene-profiles", json={"name": "Bad", "command": "raw shell"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "scene_profile_invalid"


@pytest.mark.parametrize(
    "source,error",
    [
        ({"name": "Unknown", "type": "shell_source", "settings": {}}, "Unsupported source type"),
        ({"name": "Existing", "type": "existing_video", "settings": {}}, "requires one of"),
        ({"name": "Browser", "type": "browser_source", "settings": {"url": "https://example.invalid", "width": "wide"}}, "must be an integer"),
        ({"name": "Window", "type": "window_capture", "settings": {"window": ""}}, "requires one of"),
    ],
)
def test_source_validation_negative_matrix(source: dict, error: str) -> None:
    with pytest.raises(SceneProfileValidationError, match=error):
        normalize_profile({"name": "Invalid", "sources": [source]})
