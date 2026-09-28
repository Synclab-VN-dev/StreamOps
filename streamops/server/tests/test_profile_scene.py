from __future__ import annotations

import pytest

from streamops.server.errors import SceneOperationError
from streamops.server.obs.profile_scene import apply_profile, verify_profile
from streamops.server.scene_profiles import MANAGED_PREFIX, normalize_profile
from streamops.tests.fake_obs import FakeObsClient


def _profile() -> dict:
    return normalize_profile({
        "name": "Generic",
        "canvas": {"width": 1920, "height": 1080, "fps": 60},
        "sources": [{
            "name": "Display", "type": "display_capture", "enabled": True, "layer": 0,
            "settings": {"monitor_id": "DISPLAY1"},
            "transform": {"x": 10, "y": 20, "width": 1280, "height": 720},
        }],
    })


def test_generic_apply_is_idempotent_and_preserves_unrelated_resources() -> None:
    profile = _profile()
    obs = FakeObsClient()
    obs.create_scene(profile["obs_scene_name"])
    obs.inputs.extend([
        {"inputName": "Operator Overlay", "inputKind": "browser_source", "unversionedInputKind": "browser_source"},
        {"inputName": f"{MANAGED_PREFIX}stale", "inputKind": "browser_source", "unversionedInputKind": "browser_source"},
    ])
    unrelated_id = obs.create_scene_item(profile["obs_scene_name"], "Operator Overlay")
    obs.create_scene_item(profile["obs_scene_name"], f"{MANAGED_PREFIX}stale")

    first = apply_profile(profile, obs)
    second = apply_profile(profile, obs)
    verified = verify_profile(profile, obs)

    assert first.changed is True
    assert second.changed is False
    assert verified.status == "PASS"
    assert any(item["sceneItemId"] == unrelated_id for item in obs.get_scene_item_list(profile["obs_scene_name"]))
    assert any(item["inputName"] == f"{MANAGED_PREFIX}stale" for item in obs.get_input_list())
    assert not any(item["sourceName"] == f"{MANAGED_PREFIX}stale" for item in obs.get_scene_item_list(profile["obs_scene_name"]))


def test_live_apply_allows_noop_but_blocks_drift_before_mutation() -> None:
    profile = _profile()
    obs = FakeObsClient()
    apply_profile(profile, obs)
    obs.streaming = True
    assert apply_profile(profile, obs).changed is False

    input_name = profile["sources"][0]["obs_name"]
    obs.input_settings[input_name]["monitor_id"] = "DRIFTED"
    original_video = dict(obs.video_settings)
    with pytest.raises(SceneOperationError, match="Refusing OBS mutations while streaming"):
        apply_profile(profile, obs)
    assert obs.video_settings == original_video
    assert obs.input_settings[input_name]["monitor_id"] == "DRIFTED"


def test_wrong_managed_input_kind_is_rejected_without_mutation() -> None:
    profile = _profile()
    obs = FakeObsClient()
    name = profile["sources"][0]["obs_name"]
    obs.inputs.append({"inputName": name, "inputKind": "browser_source", "unversionedInputKind": "browser_source"})
    before = dict(obs.video_settings)
    with pytest.raises(SceneOperationError, match="already exists with input kind"):
        apply_profile(profile, obs)
    assert obs.video_settings == before


def test_display_auto_binding_resolves_to_available_monitor() -> None:
    profile = _profile()
    profile["sources"][0]["settings"]["monitor_id"] = "auto"
    obs = FakeObsClient()
    apply_profile(profile, obs)
    assert obs.input_settings[profile["sources"][0]["obs_name"]]["monitor_id"] == r"\\.\DISPLAY1"
    assert verify_profile(profile, obs).status == "PASS"
