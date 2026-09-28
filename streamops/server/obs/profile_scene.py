"""Generic desired-state reconciliation for persisted scene profiles."""

from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any

from ..errors import SceneOperationError
from ..scene_profiles import MANAGED_PREFIX, SOURCE_CATALOG
from .scene import ApplyResult, Change, Check, VerifyResult


def verify_profile(profile: dict[str, Any], client: Any, *, runtime: bool = False) -> VerifyResult:
    scene_name = profile["obs_scene_name"]
    version = client.get_version()
    result = VerifyResult(
        scene=scene_name,
        status="FAIL",
        generated_at=datetime.now(UTC).isoformat(),
        obs_version=version.get("obsVersion") or version.get("obsStudioVersion"),
    )
    desired_video = _video_settings(profile)
    actual_video = client.get_video_settings()
    for key, value in desired_video.items():
        result.add(_check(f"video.{key}", actual_video.get(key) == value, value, actual_video.get(key)))

    scenes = {item.get("sceneName") for item in client.get_scene_list()}
    scene_exists = scene_name in scenes
    result.add(_check("scene.exists", scene_exists, True, scene_exists))
    inputs = {item.get("inputName"): item for item in client.get_input_list()}
    items = client.get_scene_item_list(scene_name) if scene_exists else []
    desired_names = {_input_name(source) for source in profile["sources"]}

    audio_names: list[str] = []
    for source in profile["sources"]:
        capability = SOURCE_CATALOG[source["type"]]
        input_name = _input_name(source)
        source_checks = f"source.{source['id']}"
        existing = inputs.get(input_name)
        expected_kind = capability.get("obs_kind")
        result.add(_check(f"{source_checks}.exists", existing is not None, True, existing is not None))
        if existing is not None and expected_kind:
            actual_kind = existing.get("unversionedInputKind") or existing.get("inputKind")
            result.add(_check(f"{source_checks}.kind", actual_kind == expected_kind, expected_kind, actual_kind))
            actual_settings = client.get_input_settings(input_name)
            for key, value in _effective_settings(client, source).items():
                result.add(_check(f"{source_checks}.setting.{key}", actual_settings.get(key) == value, value, actual_settings.get(key)))

        matching = [item for item in items if item.get("sourceName") == input_name]
        result.add(_check(f"item.{source['id']}.count", len(matching) == 1, 1, len(matching)))
        if len(matching) == 1:
            item = matching[0]
            result.add(_check(f"item.{source['id']}.enabled", bool(item.get("sceneItemEnabled")) == source["enabled"], source["enabled"], bool(item.get("sceneItemEnabled"))))
            if capability.get("video") and source.get("transform"):
                actual_transform = client.get_scene_item_transform(scene_name, int(item["sceneItemId"]))
                for key, value in _obs_transform(source["transform"]).items():
                    actual = actual_transform.get(key)
                    result.add(_check(f"item.{source['id']}.transform.{key}", _number_equal(actual, value), value, actual))

        if capability.get("audio") and source.get("audio") and existing is not None:
            audio_names.append(input_name)
            audio = source["audio"]
            actual_muted = client.get_input_mute(input_name)
            result.add(_check(f"audio.{source['id']}.muted", actual_muted == audio["muted"], audio["muted"], actual_muted))
            actual_volume = client.get_input_volume(input_name).get("inputVolumeDb")
            result.add(_check(f"audio.{source['id']}.volume", _number_equal(actual_volume, audio["volume_db"]), audio["volume_db"], actual_volume))
            actual_sync = client.get_input_audio_sync_offset(input_name)
            result.add(_check(f"audio.{source['id']}.sync", actual_sync == audio["sync_offset_ms"], audio["sync_offset_ms"], actual_sync))
            actual_tracks = client.get_input_audio_tracks(input_name)
            result.add(_check(f"audio.{source['id']}.tracks", actual_tracks == audio["tracks"], audio["tracks"], actual_tracks))

    if scene_exists:
        stale = [
            item.get("sourceName") for item in items
            if str(item.get("sourceName") or "").startswith(MANAGED_PREFIX)
            and item.get("sourceName") not in desired_names
        ]
        result.add(_check("scene.stale_managed_items", not stale, [], stale))
        expected_order = [
            _input_name(source) for source in sorted(profile["sources"], key=lambda item: item["layer"])
        ]
        actual_order = [
            item.get("sourceName")
            for item in sorted(items, key=lambda item: int(item.get("sceneItemIndex", 0)))
            if item.get("sourceName") in desired_names
        ]
        result.add(_check("scene.configured_order", actual_order == expected_order, expected_order, actual_order))

    if runtime and audio_names:
        seconds = max(source["verification"]["sample_seconds"] for source in profile["sources"] if _input_name(source) in audio_names)
        meters = client.sample_input_volume_meters(audio_names, seconds=seconds)
        for source in profile["sources"]:
            if not source["verification"]["audio_signal"]:
                continue
            name = _input_name(source)
            peak = (meters.get(name) or {}).get("peak_db")
            threshold = source["verification"]["audio_threshold_db"]
            result.add(_check(f"runtime.{source['id']}.audio_signal", peak is not None and peak >= threshold, f">= {threshold} dB", peak))
    configured_audio = [source for source in profile["sources"] if source.get("audio")]
    if configured_audio:
        track_1 = all(source["audio"]["tracks"]["1"] for source in configured_audio)
        result.add(Check("routing.final_mix", "PASS" if track_1 else "FAIL", "All configured audio sources must feed final mix track 1.", True, track_1))
        for track in ("2", "3"):
            present = any(source["audio"]["tracks"][track] for source in configured_audio)
            result.add(Check(f"routing.track_{track}", "PASS" if present else "WARN", f"Optional isolated track {track} routing.", True, present))
    return result.finalize()


def apply_profile(profile: dict[str, Any], client: Any) -> ApplyResult:
    before = verify_profile(profile, client)
    active = bool(client.get_stream_status().get("outputActive"))
    recording = bool(client.get_record_status().get("outputActive"))
    if active or recording:
        if before.status == "FAIL":
            modes = "streaming" if active else "recording"
            raise SceneOperationError(f"Refusing OBS mutations while {modes} is active; stop output or resolve drift first.")
        return ApplyResult(scene=profile["obs_scene_name"], changed=False, changes=())

    # Validate all create/update decisions before the first setter so a bad
    # profile or incompatible existing input cannot leave a half-applied scene.
    preflight_inputs = {item.get("inputName"): item for item in client.get_input_list()}
    available_kinds = set(client.get_input_kind_list())
    for source in profile["sources"]:
        capability = SOURCE_CATALOG[source["type"]]
        name = _input_name(source)
        _effective_settings(client, source)
        existing = preflight_inputs.get(name)
        kind = capability.get("obs_kind")
        if existing is None and capability.get("existing"):
            raise SceneOperationError(f"Existing OBS input not found: {name}")
        if existing is None and kind not in available_kinds:
            raise SceneOperationError(f"OBS input kind is unavailable: {kind}")
        if existing is not None and kind:
            actual_kind = existing.get("unversionedInputKind") or existing.get("inputKind")
            if actual_kind != kind:
                raise SceneOperationError(
                    f"Input {name!r} already exists with input kind {actual_kind!r}; expected {kind!r}."
                )

    changes: list[Change] = []
    scene_name = profile["obs_scene_name"]
    actual_video = client.get_video_settings()
    desired_video = _video_settings(profile)
    if any(actual_video.get(key) != value for key, value in desired_video.items()):
        client.set_video_settings(desired_video)
        changes.append(Change("video.update", "Updated OBS canvas and output settings."))
    scenes = {item.get("sceneName") for item in client.get_scene_list()}
    if scene_name not in scenes:
        client.create_scene(scene_name)
        changes.append(Change("scene.create", f"Created managed scene {scene_name}."))

    inputs = {item.get("inputName"): item for item in client.get_input_list()}
    desired_names: set[str] = set()
    item_ids: dict[str, int] = {}
    for source in profile["sources"]:
        capability = SOURCE_CATALOG[source["type"]]
        name = _input_name(source)
        desired_names.add(name)
        existing = inputs.get(name)
        kind = capability.get("obs_kind")
        if existing is None:
            if capability.get("existing"):
                raise SceneOperationError(f"Existing OBS input not found: {name}")
            available = set(client.get_input_kind_list())
            if kind not in available:
                raise SceneOperationError(f"OBS input kind is unavailable: {kind}")
            item_ids[source["id"]] = client.create_input(
                scene_name, name, kind, _effective_settings(client, source), enabled=source["enabled"]
            )
            inputs[name] = {"inputName": name, "inputKind": kind, "unversionedInputKind": kind}
            changes.append(Change("input.create", f"Created {name}."))
        else:
            actual_kind = existing.get("unversionedInputKind") or existing.get("inputKind")
            if kind and actual_kind != kind:
                raise SceneOperationError(f"Input {name!r} already exists with input kind {actual_kind!r}; expected {kind!r}.")
            if kind:
                actual_settings = client.get_input_settings(name)
                desired = _effective_settings(client, source)
                if any(actual_settings.get(key) != value for key, value in desired.items()):
                    client.set_input_settings(name, desired, overlay=True)
                    changes.append(Change("input.update", f"Updated settings for {name}."))

    items = client.get_scene_item_list(scene_name)
    for source in profile["sources"]:
        name = _input_name(source)
        matching = [item for item in items if item.get("sourceName") == name]
        if source["id"] in item_ids:
            item_id = item_ids[source["id"]]
        elif not matching:
            item_id = client.create_scene_item(scene_name, name, enabled=source["enabled"])
            changes.append(Change("item.create", f"Added {name} to scene."))
        else:
            item_id = int(matching[0]["sceneItemId"])
            for duplicate in matching[1:]:
                client.remove_scene_item(scene_name, int(duplicate["sceneItemId"]))
                changes.append(Change("item.remove_duplicate", f"Removed duplicate scene item for {name}."))
        item_ids[source["id"]] = item_id

    # Remove stale items owned by StreamOps from this scene only; never delete global inputs.
    for item in client.get_scene_item_list(scene_name):
        source_name = str(item.get("sourceName") or "")
        if source_name.startswith(MANAGED_PREFIX) and source_name not in desired_names:
            client.remove_scene_item(scene_name, int(item["sceneItemId"]))
            changes.append(Change("item.remove_stale", f"Removed stale managed item {source_name}."))

    for source in sorted(profile["sources"], key=lambda item: item["layer"]):
        item_id = item_ids[source["id"]]
        current_items = {int(item["sceneItemId"]): item for item in client.get_scene_item_list(scene_name)}
        current = current_items[item_id]
        if bool(current.get("sceneItemEnabled")) != source["enabled"]:
            client.set_scene_item_enabled(scene_name, item_id, source["enabled"])
            changes.append(Change("item.visibility", f"Updated visibility for {source['name']}."))
        capability = SOURCE_CATALOG[source["type"]]
        if capability.get("video") and source.get("transform"):
            desired_transform = _obs_transform(source["transform"])
            actual_transform = client.get_scene_item_transform(scene_name, item_id)
            if any(not _number_equal(actual_transform.get(key), value) for key, value in desired_transform.items()):
                client.set_scene_item_transform(scene_name, item_id, desired_transform)
                changes.append(Change("item.transform", f"Updated transform for {source['name']}."))
        if capability.get("audio") and source.get("audio"):
            _apply_audio(client, name=_input_name(source), desired=source["audio"], changes=changes)

    # OBS index 0 is bottom; layers are ordered bottom to top.
    for index, source in enumerate(sorted(profile["sources"], key=lambda item: item["layer"])):
        item_id = item_ids[source["id"]]
        current = next(item for item in client.get_scene_item_list(scene_name) if int(item["sceneItemId"]) == item_id)
        if int(current.get("sceneItemIndex", -1)) != index:
            client.set_scene_item_index(scene_name, item_id, index)
            changes.append(Change("item.order", f"Moved {source['name']} to layer {index}."))

    return ApplyResult(scene=scene_name, changed=bool(changes), changes=tuple(changes))


def _apply_audio(client: Any, *, name: str, desired: dict[str, Any], changes: list[Change]) -> None:
    if client.get_input_mute(name) != desired["muted"]:
        client.set_input_mute(name, desired["muted"]); changes.append(Change("audio.mute", f"Updated mute for {name}."))
    actual_volume = client.get_input_volume(name).get("inputVolumeDb")
    if not _number_equal(actual_volume, desired["volume_db"]):
        client.set_input_volume_db(name, desired["volume_db"]); changes.append(Change("audio.volume", f"Updated volume for {name}."))
    if client.get_input_audio_sync_offset(name) != desired["sync_offset_ms"]:
        client.set_input_audio_sync_offset(name, desired["sync_offset_ms"]); changes.append(Change("audio.sync", f"Updated sync for {name}."))
    if client.get_input_audio_tracks(name) != desired["tracks"]:
        client.set_input_audio_tracks(name, desired["tracks"]); changes.append(Change("audio.tracks", f"Updated tracks for {name}."))


def _input_name(source: dict[str, Any]) -> str:
    if SOURCE_CATALOG[source["type"]].get("existing"):
        return str(source["settings"]["source_name"])
    return source["obs_name"]


def _effective_settings(client: Any, source: dict[str, Any]) -> dict[str, Any]:
    settings = dict(source["settings"])
    if source["type"] == "display_capture" and settings.get("monitor_id") == "auto":
        monitors = client.get_monitor_list()
        for monitor in monitors:
            name = str(monitor.get("monitorName") or "")
            candidate = re.sub(r"\(\d+\)$", "", name)
            if candidate:
                settings["monitor_id"] = candidate
                break
        if settings.get("monitor_id") == "auto":
            raise SceneOperationError("Could not resolve display_capture settings.monitor_id='auto'.")
    return settings


def _video_settings(profile: dict[str, Any]) -> dict[str, int]:
    canvas = profile["canvas"]
    return {"baseWidth": canvas["width"], "baseHeight": canvas["height"], "outputWidth": canvas["width"], "outputHeight": canvas["height"], "fpsNumerator": canvas["fps"], "fpsDenominator": 1}


def _obs_transform(value: dict[str, int]) -> dict[str, Any]:
    return {
        "positionX": value["x"], "positionY": value["y"], "rotation": 0,
        "cropLeft": value["crop_left"], "cropTop": value["crop_top"],
        "cropRight": value["crop_right"], "cropBottom": value["crop_bottom"],
        "boundsType": "OBS_BOUNDS_STRETCH", "boundsAlignment": 5,
        "boundsWidth": value["width"], "boundsHeight": value["height"], "alignment": 5,
    }


def _check(identifier: str, passed: bool, expected: Any, actual: Any) -> Check:
    return Check(identifier, "PASS" if passed else "FAIL", "Desired state matches OBS." if passed else "Desired state differs from OBS.", expected, actual)


def _number_equal(actual: Any, expected: Any) -> bool:
    if actual == expected:
        return True
    try:
        return abs(float(actual) - float(expected)) < 0.01
    except (TypeError, ValueError):
        return False
