"""Idempotent OBS scene reconciliation and verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from io import BytesIO
from pathlib import Path
import re
from typing import Any, Protocol

from ..errors import SceneOperationError
from ..scene_config import SceneConfig, SourceConfig, find_project_root, load_scene_config
from .client import ObsClient
from .transforms import desired_transform, transform_differences, transform_matches


class SceneClient(Protocol):
    def close(self) -> None: ...
    def get_version(self) -> dict[str, Any]: ...
    def get_video_settings(self) -> dict[str, Any]: ...
    def set_video_settings(self, settings: dict[str, Any]) -> None: ...
    def get_record_status(self) -> dict[str, Any]: ...
    def get_stream_status(self) -> dict[str, Any]: ...
    def get_scene_list(self) -> list[dict[str, Any]]: ...
    def create_scene(self, scene_name: str) -> None: ...
    def get_input_list(self) -> list[dict[str, Any]]: ...
    def get_input_kind_list(self) -> list[str]: ...
    def create_input(self, scene_name: str, input_name: str, input_kind: str, input_settings: dict[str, Any], *, enabled: bool = True) -> int: ...
    def get_input_settings(self, input_name: str) -> dict[str, Any]: ...
    def set_input_settings(self, input_name: str, settings: dict[str, Any], *, overlay: bool = True) -> None: ...
    def get_input_properties_list_property_items(self, input_name: str, property_name: str) -> list[dict[str, Any]]: ...
    def get_monitor_list(self) -> list[dict[str, Any]]: ...
    def get_scene_item_list(self, scene_name: str) -> list[dict[str, Any]]: ...
    def create_scene_item(self, scene_name: str, source_name: str, *, enabled: bool = True) -> int: ...
    def remove_scene_item(self, scene_name: str, scene_item_id: int) -> None: ...
    def get_scene_item_transform(self, scene_name: str, scene_item_id: int) -> dict[str, Any]: ...
    def set_scene_item_transform(self, scene_name: str, scene_item_id: int, transform: dict[str, Any]) -> None: ...
    def set_scene_item_enabled(self, scene_name: str, scene_item_id: int, enabled: bool) -> None: ...
    def set_scene_item_index(self, scene_name: str, scene_item_id: int, index: int) -> None: ...
    def get_input_mute(self, input_name: str) -> bool: ...
    def set_input_mute(self, input_name: str, muted: bool) -> None: ...
    def get_input_volume(self, input_name: str) -> dict[str, Any]: ...
    def set_input_volume_db(self, input_name: str, volume_db: float) -> None: ...
    def get_input_audio_sync_offset(self, input_name: str) -> int: ...
    def set_input_audio_sync_offset(self, input_name: str, offset_ms: int) -> None: ...
    def get_input_audio_tracks(self, input_name: str) -> dict[str, bool]: ...
    def set_input_audio_tracks(self, input_name: str, tracks: dict[str, bool]) -> None: ...
    def sample_input_volume_meters(self, input_names: list[str], *, seconds: float) -> dict[str, dict[str, Any]]: ...
    def get_source_screenshot(self, source_name: str, *, width: int, height: int) -> bytes: ...


@dataclass(frozen=True)
class Change:
    action: str
    detail: str


@dataclass(frozen=True)
class ApplyResult:
    scene: str
    changed: bool
    changes: tuple[Change, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene": self.scene,
            "changed": self.changed,
            "changes": [{"action": item.action, "detail": item.detail} for item in self.changes],
        }


@dataclass(frozen=True)
class Check:
    id: str
    status: str
    message: str
    expected: Any = None
    actual: Any = None


@dataclass
class VerifyResult:
    scene: str
    status: str
    generated_at: str
    obs_version: str | None
    checks: list[Check] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)

    def add(self, check: Check) -> None:
        self.checks.append(check)

    def finalize(self) -> "VerifyResult":
        if any(check.status == "FAIL" for check in self.checks):
            self.status = "FAIL"
        elif any(check.status == "WARN" for check in self.checks):
            self.status = "WARN"
        else:
            self.status = "PASS"
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene": self.scene,
            "status": self.status,
            "generated_at": self.generated_at,
            "obs_version": self.obs_version,
            "checks": [
                {
                    "id": check.id,
                    "status": check.status,
                    "message": check.message,
                    "expected": check.expected,
                    "actual": check.actual,
                }
                for check in self.checks
            ],
            "artifacts": dict(self.artifacts),
        }


def apply_scene(
    scene_name: str,
    *,
    client: SceneClient | None = None,
    root: Path | None = None,
    config_path: Path | None = None,
) -> ApplyResult:
    project_root = root or find_project_root()
    config = load_scene_config(scene_name, root=project_root, config_path=config_path)
    owns_client = client is None
    obs: SceneClient = client or ObsClient.from_env()
    changes: list[Change] = []
    try:
        obs.get_version()
        _preflight_configured_sources(obs, config, project_root)
        _ensure_video_settings(obs, config, changes)
        _ensure_scene_exists(obs, config, changes)
        _ensure_managed_inputs(obs, config, project_root, changes)
        _remove_duplicate_configured_items(obs, config, changes)
        item_ids = _ensure_configured_scene_items(obs, config, changes)
        _disable_unmanaged_items(obs, config, changes)
        _apply_transforms(obs, config, item_ids, changes)
        _apply_visibility(obs, config, item_ids, changes)
        _apply_visual_order(obs, config, item_ids, changes)
        _apply_audio(obs, config, changes)
    finally:
        if owns_client:
            obs.close()
    return ApplyResult(scene=config.name, changed=bool(changes), changes=tuple(changes))


def verify_scene(
    scene_name: str,
    *,
    client: SceneClient | None = None,
    root: Path | None = None,
    config_path: Path | None = None,
    runtime_audio: bool = False,
    runtime_video: bool = False,
) -> VerifyResult:
    project_root = root or find_project_root()
    config = load_scene_config(scene_name, root=project_root, config_path=config_path)
    owns_client = client is None
    obs: SceneClient = client or ObsClient.from_env()
    result = VerifyResult(
        scene=config.name,
        status="FAIL",
        generated_at=datetime.now(timezone.utc).isoformat(),
        obs_version=None,
    )
    try:
        version = obs.get_version()
        result.obs_version = version.get("obsVersion") or version.get("obsStudioVersion")
        _verify_video(obs, config, result)
        _verify_sources(obs, config, result, project_root)
        scene_exists = _scene_exists(obs, config.name)
        result.add(Check(
            id="scene.exists",
            status="PASS" if scene_exists else "FAIL",
            message=f"Scene {config.name!r} exists." if scene_exists else f"Scene {config.name!r} is missing.",
            expected=True,
            actual=scene_exists,
        ))
        if scene_exists:
            _verify_items(obs, config, result)
        _verify_audio(obs, config, result, runtime_audio=runtime_audio)
        if runtime_video:
            _verify_runtime_video(obs, config, result)
    finally:
        if owns_client:
            obs.close()
    return result.finalize()


def _ensure_video_settings(obs: SceneClient, config: SceneConfig, changes: list[Change]) -> None:
    current = obs.get_video_settings()
    if _video_matches(current, config):
        return
    if obs.get_stream_status().get("outputActive") or obs.get_record_status().get("outputActive"):
        raise SceneOperationError(
            "OBS video settings differ from desired state while streaming or recording is active."
        )
    obs.set_video_settings(_video_request(config))
    changes.append(Change(
        "video.set",
        f"Set OBS video to {config.video.base_width}x{config.video.base_height}@{config.video.fps}.",
    ))


def _preflight_configured_sources(obs: SceneClient, config: SceneConfig, root: Path) -> None:
    inputs = _inputs_by_name(obs)
    scenes = {item.get("sceneName") for item in obs.get_scene_list()}
    available_sources = set(inputs) | scenes
    missing_external = [
        source.source_name
        for source in config.sources
        if not source.managed and source.source_name not in available_sources
    ]
    if missing_external:
        raise SceneOperationError(
            "Configured OBS source(s) are missing: "
            + ", ".join(repr(item) for item in missing_external)
            + ". Create/bind the sources in OBS or update the scene config."
        )

    managed_sources = [source for source in config.sources if source.managed]
    if not managed_sources:
        return
    input_kinds = set(obs.get_input_kind_list())
    unsupported = sorted({
        source.input_kind
        for source in managed_sources
        if source.input_kind is not None and source.input_kind not in input_kinds
    })
    if unsupported:
        raise SceneOperationError(
            "OBS does not support required input kind(s): " + ", ".join(repr(item) for item in unsupported)
        )
    for source in managed_sources:
        _resolve_input_settings(obs, source, root, inputs)
        if source.source_name in scenes:
            raise SceneOperationError(
                f"Managed source {source.source_name!r} conflicts with an existing OBS scene name."
            )
        existing = inputs.get(source.source_name)
        if existing is None:
            continue
        actual_kinds = {
            kind
            for kind in (existing.get("inputKind"), existing.get("unversionedInputKind"))
            if isinstance(kind, str)
        }
        if actual_kinds and source.input_kind not in actual_kinds:
            raise SceneOperationError(
                f"Managed source {source.source_name!r} exists with {sorted(actual_kinds)!r}; "
                f"expected {source.input_kind!r}."
            )


def _ensure_managed_inputs(
    obs: SceneClient,
    config: SceneConfig,
    root: Path,
    changes: list[Change],
) -> None:
    inputs = _inputs_by_name(obs)
    for source in config.sources:
        if not source.managed:
            continue
        desired = _resolve_input_settings(obs, source, root, inputs)
        if source.source_name not in inputs:
            if source.input_kind is None:
                raise SceneOperationError(f"Managed source {source.source_name!r} requires input_kind.")
            obs.create_input(config.name, source.source_name, source.input_kind, desired, enabled=True)
            changes.append(Change("input.create", f"Created {source.input_kind!r} input {source.source_name!r}."))
            inputs[source.source_name] = {"inputName": source.source_name, "inputKind": source.input_kind}
            continue
        current = obs.get_input_settings(source.source_name)
        if _settings_match(current, desired):
            continue
        obs.set_input_settings(source.source_name, desired, overlay=True)
        changes.append(Change("input.settings", f"Updated settings for {source.source_name!r}."))


def _ensure_scene_exists(obs: SceneClient, config: SceneConfig, changes: list[Change]) -> None:
    if _scene_exists(obs, config.name):
        return
    obs.create_scene(config.name)
    changes.append(Change("scene.create", f"Created scene {config.name!r}."))


def _remove_duplicate_configured_items(obs: SceneClient, config: SceneConfig, changes: list[Change]) -> None:
    items = obs.get_scene_item_list(config.name)
    for source in config.sources:
        matching = [item for item in items if item.get("sourceName") == source.source_name]
        if len(matching) <= 1:
            continue
        keep = min(matching, key=lambda item: int(item["sceneItemId"]))
        for item in matching:
            if item is keep:
                continue
            obs.remove_scene_item(config.name, int(item["sceneItemId"]))
            changes.append(Change("item.remove_duplicate", f"Removed duplicate for {source.source_name!r}."))


def _ensure_configured_scene_items(
    obs: SceneClient,
    config: SceneConfig,
    changes: list[Change],
) -> dict[str, int]:
    ids: dict[str, int] = {}
    items = obs.get_scene_item_list(config.name)
    for source in config.sources:
        item = _find_scene_item(items, source.source_name)
        if item is None:
            scene_item_id = obs.create_scene_item(config.name, source.source_name, enabled=True)
            changes.append(Change("item.create", f"Added {source.source_name!r} to {config.name!r}."))
        else:
            scene_item_id = int(item["sceneItemId"])
        ids[source.role] = scene_item_id
    return ids


def _disable_unmanaged_items(obs: SceneClient, config: SceneConfig, changes: list[Change]) -> None:
    configured = {source.source_name for source in config.sources}
    for item in obs.get_scene_item_list(config.name):
        if item.get("sourceName") in configured or not bool(item.get("sceneItemEnabled", True)):
            continue
        obs.set_scene_item_enabled(config.name, int(item["sceneItemId"]), False)
        changes.append(Change("item.disable_unmanaged", f"Disabled unmanaged item {item.get('sourceName')!r}."))


def _apply_transforms(
    obs: SceneClient,
    config: SceneConfig,
    item_ids: dict[str, int],
    changes: list[Change],
) -> None:
    for source in config.visual_sources:
        scene_item_id = item_ids[source.role]
        current = obs.get_scene_item_transform(config.name, scene_item_id)
        desired = desired_transform(config, source, current)
        if transform_matches(current, desired):
            continue
        obs.set_scene_item_transform(config.name, scene_item_id, desired)
        changes.append(Change("item.transform", f"Updated transform for {source.source_name!r}."))


def _apply_visibility(
    obs: SceneClient,
    config: SceneConfig,
    item_ids: dict[str, int],
    changes: list[Change],
) -> None:
    items = obs.get_scene_item_list(config.name)
    enabled = {int(item["sceneItemId"]): bool(item.get("sceneItemEnabled", True)) for item in items}
    for source in config.sources:
        scene_item_id = item_ids[source.role]
        if enabled.get(scene_item_id) is True:
            continue
        obs.set_scene_item_enabled(config.name, scene_item_id, True)
        changes.append(Change("item.enable", f"Enabled {source.source_name!r}."))


def _apply_visual_order(
    obs: SceneClient,
    config: SceneConfig,
    item_ids: dict[str, int],
    changes: list[Change],
) -> None:
    for target_index, source in enumerate(sorted(config.visual_sources, key=lambda item: item.layer)):
        items = obs.get_scene_item_list(config.name)
        current = {
            int(item["sceneItemId"]): int(item.get("sceneItemIndex", 0))
            for item in items
        }
        scene_item_id = item_ids[source.role]
        if current.get(scene_item_id) == target_index:
            continue
        obs.set_scene_item_index(config.name, scene_item_id, target_index)
        changes.append(Change("item.order", f"Set visual layer for {source.source_name!r} to {target_index}."))


def _apply_audio(obs: SceneClient, config: SceneConfig, changes: list[Change]) -> None:
    for source in config.audio_sources:
        if source.audio is None:
            continue
        desired = source.audio
        muted = obs.get_input_mute(source.source_name)
        if muted != desired.muted:
            obs.set_input_mute(source.source_name, desired.muted)
            changes.append(Change("audio.mute", f"Set mute={desired.muted} for {source.source_name!r}."))
        volume = obs.get_input_volume(source.source_name)
        actual_db = float(volume.get("inputVolumeDb", -100.0))
        if abs(actual_db - desired.volume_db) > 0.1:
            obs.set_input_volume_db(source.source_name, desired.volume_db)
            changes.append(Change("audio.volume", f"Set volume {desired.volume_db:g} dB for {source.source_name!r}."))
        sync = obs.get_input_audio_sync_offset(source.source_name)
        if sync != desired.sync_offset_ms:
            obs.set_input_audio_sync_offset(source.source_name, desired.sync_offset_ms)
            changes.append(Change("audio.sync", f"Set sync offset {desired.sync_offset_ms} ms for {source.source_name!r}."))
        tracks = obs.get_input_audio_tracks(source.source_name)
        normalized = {str(i): bool(tracks.get(str(i), False)) for i in range(1, 7)}
        expected = {str(i): bool(desired.tracks.get(str(i), False)) for i in range(1, 7)}
        if normalized != expected:
            obs.set_input_audio_tracks(source.source_name, expected)
            changes.append(Change("audio.tracks", f"Updated audio tracks for {source.source_name!r}."))


def _verify_video(obs: SceneClient, config: SceneConfig, result: VerifyResult) -> None:
    current = obs.get_video_settings()
    expected = _video_request(config)
    result.add(Check(
        id="video.settings",
        status="PASS" if _video_matches(current, config) else "FAIL",
        message="OBS video settings match desired state.",
        expected=expected,
        actual={key: current.get(key) for key in expected},
    ))


def _verify_sources(obs: SceneClient, config: SceneConfig, result: VerifyResult, root: Path) -> None:
    input_items = _inputs_by_name(obs)
    available = set(input_items) | {item.get("sceneName") for item in obs.get_scene_list()}
    for source in config.sources:
        exists = source.source_name in available
        result.add(Check(
            id=f"source.{source.role}.exists",
            status="PASS" if exists else "FAIL",
            message=f"Source {source.source_name!r} {'exists' if exists else 'is missing'}.",
            expected=True,
            actual=exists,
        ))
        if not exists or not source.managed:
            continue
        input_item = input_items.get(source.source_name) or {}
        actual_kinds = {
            kind
            for kind in (input_item.get("inputKind"), input_item.get("unversionedInputKind"))
            if isinstance(kind, str)
        }
        kind_matches = not actual_kinds or source.input_kind in actual_kinds
        result.add(Check(
            id=f"source.{source.role}.kind",
            status="PASS" if kind_matches else "FAIL",
            message=f"{source.source_name!r} uses the expected input kind.",
            expected=source.input_kind,
            actual=sorted(actual_kinds) or None,
        ))
        expected_settings = _resolve_input_settings(obs, source, root, input_items)
        current_settings = obs.get_input_settings(source.source_name)
        differences = _settings_differences(current_settings, expected_settings)
        result.add(Check(
            id=f"source.{source.role}.settings",
            status="PASS" if not differences else "FAIL",
            message=f"{source.source_name!r} settings match desired state.",
            expected=expected_settings,
            actual=differences or {key: current_settings.get(key) for key in expected_settings},
        ))


def _verify_items(obs: SceneClient, config: SceneConfig, result: VerifyResult) -> None:
    items = obs.get_scene_item_list(config.name)
    configured = {source.source_name for source in config.sources}
    unknown_visible = [
        item.get("sourceName")
        for item in items
        if item.get("sourceName") not in configured and bool(item.get("sceneItemEnabled", True))
    ]
    if unknown_visible:
        result.add(Check(
            id="scene.unmanaged_visible_items",
            status="WARN",
            message="Scene has visible unmanaged item(s).",
            expected=[],
            actual=unknown_visible,
        ))

    visual_indexes: dict[str, int] = {}
    for source in config.sources:
        matching = [item for item in items if item.get("sourceName") == source.source_name]
        result.add(Check(
            id=f"item.{source.role}.count",
            status="PASS" if len(matching) == 1 else "FAIL",
            message=f"Scene has exactly one item for {source.source_name!r}.",
            expected=1,
            actual=len(matching),
        ))
        if len(matching) != 1:
            continue
        item = matching[0]
        scene_item_id = int(item["sceneItemId"])
        enabled = bool(item.get("sceneItemEnabled", True))
        result.add(Check(
            id=f"item.{source.role}.enabled",
            status="PASS" if enabled else "FAIL",
            message=f"{source.source_name!r} is enabled.",
            expected=True,
            actual=enabled,
        ))
        if not source.is_video:
            continue
        visual_indexes[source.role] = int(item.get("sceneItemIndex", 0))
        current = obs.get_scene_item_transform(config.name, scene_item_id)
        expected_transform = desired_transform(config, source, current)
        differences = transform_differences(current, expected_transform)
        result.add(Check(
            id=f"item.{source.role}.transform",
            status="PASS" if not differences else "FAIL",
            message=f"{source.source_name!r} transform matches desired layout.",
            expected=expected_transform,
            actual=differences or {key: current.get(key) for key in expected_transform},
        ))

    ordered_visuals = sorted(config.visual_sources, key=lambda item: item.layer)
    if all(source.role in visual_indexes for source in ordered_visuals):
        actual = [visual_indexes[source.role] for source in ordered_visuals]
        result.add(Check(
            id="item.order",
            status="PASS" if actual == sorted(actual) else "FAIL",
            message="Visual scene-item order matches desired layers.",
            expected=[source.role for source in ordered_visuals],
            actual={source.role: visual_indexes[source.role] for source in ordered_visuals},
        ))


def _verify_audio(
    obs: SceneClient,
    config: SceneConfig,
    result: VerifyResult,
    *,
    runtime_audio: bool,
) -> None:
    signal_sources: list[SourceConfig] = []
    for source in config.audio_sources:
        if source.audio is None:
            continue
        desired = source.audio
        try:
            muted = obs.get_input_mute(source.source_name)
            volume = obs.get_input_volume(source.source_name)
            sync = obs.get_input_audio_sync_offset(source.source_name)
            tracks = obs.get_input_audio_tracks(source.source_name)
        except Exception as exc:
            result.add(Check(
                id=f"audio.{source.role}.state",
                status="FAIL",
                message=f"Could not read audio state for {source.source_name!r}: {exc}",
            ))
            continue
        expected_tracks = {str(i): bool(desired.tracks.get(str(i), False)) for i in range(1, 7)}
        actual_tracks = {str(i): bool(tracks.get(str(i), False)) for i in range(1, 7)}
        actual_db = float(volume.get("inputVolumeDb", -100.0))
        state_ok = (
            muted == desired.muted
            and abs(actual_db - desired.volume_db) <= 0.1
            and sync == desired.sync_offset_ms
            and actual_tracks == expected_tracks
        )
        result.add(Check(
            id=f"audio.{source.role}.state",
            status="PASS" if state_ok else "FAIL",
            message=f"Audio routing for {source.source_name!r} matches desired state.",
            expected={
                "muted": desired.muted,
                "volume_db": desired.volume_db,
                "sync_offset_ms": desired.sync_offset_ms,
                "tracks": expected_tracks,
            },
            actual={
                "muted": muted,
                "volume_db": actual_db,
                "sync_offset_ms": sync,
                "tracks": actual_tracks,
            },
        ))
        if desired.signal_required:
            signal_sources.append(source)

    if not runtime_audio or not signal_sources:
        return
    window = max(source.audio.signal_window_seconds for source in signal_sources if source.audio)
    meters = obs.sample_input_volume_meters(
        [source.source_name for source in signal_sources],
        seconds=window,
    )
    for source in signal_sources:
        desired = source.audio
        if desired is None:
            continue
        meter = meters.get(source.source_name, {})
        peak_db = meter.get("peak_db")
        signal_ok = peak_db is not None and float(peak_db) >= desired.signal_threshold_db
        result.add(Check(
            id=f"audio.{source.role}.signal",
            status="PASS" if signal_ok else "FAIL",
            message=(
                f"{source.source_name!r} has runtime audio signal."
                if signal_ok
                else f"{source.source_name!r} is silent or below threshold."
            ),
            expected={"peak_db_at_least": desired.signal_threshold_db},
            actual=meter,
        ))



def _verify_runtime_video(
    obs: SceneClient,
    config: SceneConfig,
    result: VerifyResult,
) -> None:
    try:
        from PIL import Image, ImageStat
    except ImportError:
        result.add(Check(
            id="runtime.video.dependencies",
            status="WARN",
            message="Pillow is unavailable; black-frame runtime checks were skipped.",
            expected="Pillow installed",
            actual=False,
        ))
        return

    width = min(config.video.output_width, 640)
    height = max(1, round(width * config.video.output_height / config.video.output_width))
    for source in config.visual_sources:
        try:
            content = obs.get_source_screenshot(
                source.source_name,
                width=width,
                height=height,
            )
            with Image.open(BytesIO(content)) as image:
                gray = image.convert("L")
                gray.thumbnail((96, 54))
                mean = float(ImageStat.Stat(gray).mean[0])
                extrema = gray.getextrema()
                maximum = float(extrema[1] if isinstance(extrema, tuple) else 0)
            has_content = mean >= 2.0 or maximum >= 8.0
            result.add(Check(
                id=f"video.{source.role}.signal",
                status="PASS" if has_content else "FAIL",
                message=(
                    f"{source.source_name!r} produced a non-black runtime frame."
                    if has_content
                    else f"{source.source_name!r} runtime frame is effectively black."
                ),
                expected={"non_black": True},
                actual={"mean_luma": round(mean, 3), "max_luma": round(maximum, 3)},
            ))
        except Exception as exc:
            result.add(Check(
                id=f"video.{source.role}.signal",
                status="FAIL",
                message=f"Could not capture runtime frame for {source.source_name!r}: {exc}",
                expected={"non_black": True},
                actual=None,
            ))


def _scene_exists(obs: SceneClient, scene_name: str) -> bool:
    return any(item.get("sceneName") == scene_name for item in obs.get_scene_list())


def _inputs_by_name(obs: SceneClient) -> dict[str, dict[str, Any]]:
    return {
        str(item["inputName"]): item
        for item in obs.get_input_list()
        if isinstance(item.get("inputName"), str)
    }


def _find_scene_item(items: list[dict[str, Any]], source_name: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("sourceName") == source_name), None)


def _resolve_input_settings(
    obs: SceneClient,
    source: SourceConfig,
    root: Path,
    inputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    settings = dict(source.settings)
    local_file = settings.get("local_file")
    if local_file is not None:
        if not isinstance(local_file, str) or not local_file.strip():
            raise SceneOperationError(f"Managed source {source.source_name!r} has invalid local_file.")
        path = Path(local_file).expanduser()
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        if not path.exists():
            raise SceneOperationError(f"Managed source {source.source_name!r} local_file does not exist: {path}")
        settings["local_file"] = str(path)
    if source.input_kind == "monitor_capture":
        monitor_id = settings.get("monitor_id")
        if monitor_id == "auto":
            settings["monitor_id"] = _select_monitor_id(obs, source, inputs)
        elif not _valid_monitor_id(monitor_id):
            raise SceneOperationError(
                f"Managed monitor_capture source {source.source_name!r} requires valid monitor_id or 'auto'."
            )
    return settings


def _select_monitor_id(
    obs: SceneClient,
    source: SourceConfig,
    inputs: dict[str, dict[str, Any]],
) -> str:
    if source.source_name in inputs:
        try:
            value = _select_monitor_id_from_property_items(
                obs.get_input_properties_list_property_items(source.source_name, "monitor_id")
            )
            if value:
                return value
        except Exception:
            pass
    try:
        value = _select_monitor_id_from_monitor_list(obs.get_monitor_list())
        if value:
            return value
    except Exception:
        pass
    for monitor_id in _windows_monitor_ids():
        if _valid_monitor_id(monitor_id):
            return monitor_id
    raise SceneOperationError(
        f"Could not resolve a valid desktop display for {source.source_name!r}."
    )


def _select_monitor_id_from_property_items(items: list[dict[str, Any]]) -> str | None:
    candidates = [
        item for item in items
        if item.get("itemEnabled", True) is True and _valid_monitor_id(item.get("itemValue"))
    ]
    if not candidates:
        return None
    primary = [item for item in candidates if "primary" in str(item.get("itemName", "")).casefold()]
    return str((primary[0] if primary else candidates[0])["itemValue"])


def _select_monitor_id_from_monitor_list(monitors: list[dict[str, Any]]) -> str | None:
    for monitor in sorted(monitors, key=lambda item: int(item.get("monitorIndex", 9999))):
        name = monitor.get("monitorName")
        if not isinstance(name, str):
            continue
        monitor_id = re.sub(r"\(\d+\)$", "", name)
        if _valid_monitor_id(monitor_id):
            return monitor_id
    return None


def _valid_monitor_id(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value != "DUMMY"


def _windows_monitor_ids() -> list[str]:
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return []

    user32 = ctypes.windll.user32
    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
    class MONITORINFOEXA(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("rcMonitor", RECT), ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD), ("szDevice", ctypes.c_char * 32),
        ]
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM)
    ids: list[str] = []
    def callback(handle: Any, _hdc: Any, _rect: Any, _param: Any) -> bool:
        info = MONITORINFOEXA()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoA(handle, ctypes.byref(info)):
            ids.append(bytes(info.szDevice).split(b"\x00", 1)[0].decode("mbcs", errors="replace"))
        return True
    user32.EnumDisplayMonitors(0, 0, proc(callback), 0)
    return ids


def _settings_match(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return not _settings_differences(actual, expected)


def _settings_differences(actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, dict[str, Any]]:
    differences: dict[str, dict[str, Any]] = {}
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if key == "local_file" and isinstance(actual_value, str) and isinstance(expected_value, str):
            matches = _normalized_file_path(actual_value) == _normalized_file_path(expected_value)
        elif isinstance(expected_value, bool):
            matches = bool(actual_value) is expected_value
        elif isinstance(expected_value, int | float) and not isinstance(expected_value, bool):
            try:
                matches = abs(float(actual_value) - float(expected_value)) <= 0.01
            except (TypeError, ValueError):
                matches = False
        else:
            matches = actual_value == expected_value
        if not matches:
            differences[key] = {"expected": expected_value, "actual": actual_value}
    return differences


def _normalized_file_path(value: str) -> str:
    try:
        return str(Path(value).expanduser().resolve(strict=False)).casefold()
    except OSError:
        return str(Path(value).expanduser()).casefold()


def _video_request(config: SceneConfig) -> dict[str, Any]:
    return {
        "baseWidth": config.video.base_width,
        "baseHeight": config.video.base_height,
        "outputWidth": config.video.output_width,
        "outputHeight": config.video.output_height,
        "fpsNumerator": config.video.fps,
        "fpsDenominator": 1,
    }


def _video_matches(current: dict[str, Any], config: SceneConfig) -> bool:
    expected = _video_request(config)
    return all(int(current.get(key, -1)) == int(value) for key, value in expected.items())
