"""Versioned, generic OBS scene-profile model and source catalog."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import math
from typing import Any
from uuid import UUID, uuid4

from .errors import SceneProfileValidationError


SCHEMA_VERSION = 1
MANAGED_PREFIX = "StreamOps Source "
SCENE_PREFIX = "StreamOps Scene "

SOURCE_CATALOG: dict[str, dict[str, Any]] = {
    "game_capture": {"label": "Game capture", "obs_kind": "game_capture", "video": True, "setting_fields": ["capture_mode", "window", "capture_cursor"]},
    "window_capture": {"label": "Window capture", "obs_kind": "window_capture", "video": True, "setting_fields": ["window", "method", "cursor"], "required_any": ["window"]},
    "display_capture": {"label": "Display capture", "obs_kind": "monitor_capture", "video": True, "setting_fields": ["monitor_id", "method", "capture_cursor", "force_sdr"], "required_any": ["monitor_id"]},
    "video_capture_device": {"label": "Video capture device", "obs_kind": "dshow_input", "video": True, "audio": True, "setting_fields": ["video_device_id", "res_type", "resolution", "frame_interval"], "required_any": ["video_device_id"]},
    "media_stream": {"label": "Media stream (SRT/RTSP)", "obs_kind": "ffmpeg_source", "video": True, "audio": True, "setting_fields": ["input", "buffering_mb", "restart_on_activate"], "required_any": ["input"]},
    "browser_source": {"label": "Browser", "obs_kind": "browser_source", "video": True, "audio": True, "setting_fields": ["url", "is_local_file", "local_file", "width", "height", "fps", "reroute_audio"], "required_any": ["url", "local_file"]},
    "image": {"label": "Image", "obs_kind": "image_source", "video": True, "setting_fields": ["file", "unload"], "required_any": ["file"]},
    "video_file": {"label": "Video file", "obs_kind": "ffmpeg_source", "video": True, "audio": True, "setting_fields": ["local_file", "looping", "restart_on_activate"], "required_any": ["local_file"]},
    "existing_video": {"label": "Existing OBS video input", "obs_kind": None, "video": True, "audio": True, "existing": True, "setting_fields": ["source_name"], "required_any": ["source_name"]},
    "audio_input": {"label": "Audio input", "obs_kind": "wasapi_input_capture", "audio": True, "setting_fields": ["device_id"], "required_any": ["device_id"]},
    "application_audio": {"label": "Application audio", "obs_kind": "wasapi_process_output_capture", "audio": True, "setting_fields": ["window", "priority"], "required_any": ["window"]},
    "audio_output": {"label": "Audio output", "obs_kind": "wasapi_output_capture", "audio": True, "setting_fields": ["device_id"], "required_any": ["device_id"]},
    "existing_audio": {"label": "Existing OBS audio input", "obs_kind": None, "audio": True, "existing": True, "setting_fields": ["source_name"], "required_any": ["source_name"]},
}

# These descriptors are the contract used by both the browser and validator.
FIELD_RULES = {
    "capture_mode": {"type": "string", "enum": ["any_fullscreen", "window", "hotkey"], "default": "any_fullscreen"},
    "method": {"type": "integer", "min": 0, "max": 2},
    "priority": {"type": "integer", "min": 0, "max": 2},
    "res_type": {"type": "integer", "enum": [0, 1], "min": 0, "max": 1},
    "width": {"type": "integer", "min": 1, "max": 16384},
    "height": {"type": "integer", "min": 1, "max": 16384},
    "fps": {"type": "integer", "min": 1, "max": 240},
    "frame_interval": {"type": "integer", "min": -1, "max": 100000000},
    "buffering_mb": {"type": "integer", "min": 0, "max": 512},
}
for _key in ("cursor", "capture_cursor", "force_sdr", "restart_on_activate", "is_local_file", "looping", "unload", "reroute_audio"):
    FIELD_RULES[_key] = {"type": "boolean"}
for _key in ("window", "monitor_id", "video_device_id", "device_id", "source_name"):
    FIELD_RULES[_key] = {"type": "string", "inventory": True}


def now_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid4())


def source_catalog() -> list[dict[str, Any]]:
    return [{"type": key, **deepcopy(value), "fields": [
        {"key": field, "label": field.replace('_', ' ').capitalize(), **FIELD_RULES.get(field, {"type": "string"})}
        for field in value["setting_fields"]
    ]} for key, value in SOURCE_CATALOG.items()]


def new_profile(name: str = "Untitled profile") -> dict[str, Any]:
    profile_id = new_id()
    stamp = now_utc()
    return {
        "schema_version": SCHEMA_VERSION,
        "id": profile_id,
        "name": name.strip() or "Untitled profile",
        "obs_scene_name": f"{SCENE_PREFIX}{profile_id}",
        "created_at": stamp,
        "updated_at": stamp,
        "canvas": {"width": 1920, "height": 1080, "fps": 60},
        "sources": [],
    }


def normalize_profile(
    raw: Any,
    *,
    existing: dict[str, Any] | None = None,
    regenerate_ids: bool = False,
    preserve_updated_at: bool = False,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SceneProfileValidationError("Scene profile must be a JSON object.")
    unknown = set(raw) - {
        "schema_version", "id", "name", "obs_scene_name", "created_at", "updated_at",
        "canvas", "sources",
    }
    if unknown:
        raise SceneProfileValidationError(f"Unknown profile fields: {', '.join(sorted(unknown))}.")

    result = deepcopy(raw)
    version = result.get("schema_version", SCHEMA_VERSION)
    if type(version) is not int or version != SCHEMA_VERSION:
        raise SceneProfileValidationError(f"Unsupported schema_version {version!r}.")

    profile_id = new_id() if regenerate_ids else str(result.get("id") or (existing or {}).get("id") or new_id())
    _require_uuid(profile_id, "profile id")
    name = _string(result.get("name", ""), "Profile name").strip()
    if not name or len(name) > 120:
        raise SceneProfileValidationError("Profile name must contain 1 to 120 characters.")

    canvas = result.get("canvas", {})
    if not isinstance(canvas, dict) or set(canvas) - {"width", "height", "fps"}:
        raise SceneProfileValidationError("Canvas only supports width, height and fps.")
    width = _integer(canvas.get("width", 1920), "canvas.width", 16, 16384)
    height = _integer(canvas.get("height", 1080), "canvas.height", 16, 16384)
    fps = _integer(canvas.get("fps", 60), "canvas.fps", 1, 240)

    old_sources = {item.get("id"): item for item in (existing or {}).get("sources", []) if isinstance(item, dict)} if isinstance((existing or {}).get("sources", []), list) else {}
    source_ids: set[str] = set()
    obs_names: set[str] = set()
    sources = result.get("sources", [])
    if not isinstance(sources, list):
        raise SceneProfileValidationError("Profile sources must be an array.")
    normalized_sources = []
    submitted_ids = set()
    for index, source in enumerate(sources):
        if isinstance(source, dict) and source.get("id"):
            _require_uuid(str(source["id"]), "source id")
            if source["id"] in submitted_ids:
                raise SceneProfileValidationError("Duplicate source id.")
            submitted_ids.add(source["id"])
        normalized = _normalize_source(
            source, index=index, existing_sources=old_sources, regenerate_ids=regenerate_ids
        )
        if normalized["id"] in source_ids:
            raise SceneProfileValidationError(f"Duplicate source id: {normalized['id']}.")
        binding = normalized['settings']['source_name'] if SOURCE_CATALOG[normalized['type']].get('existing') else normalized['obs_name']
        if binding in obs_names:
            raise SceneProfileValidationError(f"Duplicate OBS source binding: {normalized['obs_name']}.")
        source_ids.add(normalized["id"])
        obs_names.add(binding)
        normalized_sources.append(normalized)

    stamp = now_utc()
    created_at = stamp if regenerate_ids else str((existing or {}).get("created_at") or result.get("created_at") or stamp)
    old_scene_name = (existing or {}).get("obs_scene_name")
    obs_scene_name = f"{SCENE_PREFIX}{profile_id}" if regenerate_ids else str(old_scene_name or result.get("obs_scene_name") or f"{SCENE_PREFIX}{profile_id}")
    return {
        "schema_version": SCHEMA_VERSION,
        "id": profile_id,
        "name": name,
        "obs_scene_name": obs_scene_name,
        "created_at": created_at,
        "updated_at": str(result.get("updated_at") or stamp) if preserve_updated_at else stamp,
        "canvas": {"width": width, "height": height, "fps": fps},
        "sources": normalized_sources,
    }


def duplicate_profile(profile: dict[str, Any], *, name: str | None = None) -> dict[str, Any]:
    draft = deepcopy(profile)
    draft["name"] = (name or f"{profile['name']} copy").strip()
    return normalize_profile(draft, regenerate_ids=True)


def _normalize_source(raw: Any, *, index: int, existing_sources: dict[str, dict[str, Any]], regenerate_ids: bool) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SceneProfileValidationError(f"Source {index + 1} must be an object.")
    allowed = {"id", "name", "obs_name", "type", "enabled", "layer", "settings", "transform", "audio", "verification"}
    unknown = set(raw) - allowed
    if unknown:
        raise SceneProfileValidationError(f"Unknown source fields: {', '.join(sorted(unknown))}.")
    source_type = str(raw.get("type") or "")
    capability = SOURCE_CATALOG.get(source_type)
    if capability is None:
        raise SceneProfileValidationError(f"Unsupported source type: {source_type!r}.")
    old_id = str(raw.get("id") or "")
    source_id = new_id() if regenerate_ids or not old_id else old_id
    _require_uuid(source_id, f"source {index + 1} id")
    old = existing_sources.get(old_id, {})
    name = _string(raw.get("name", capability["label"]), "Source name").strip()
    if not name or len(name) > 120:
        raise SceneProfileValidationError(f"Source {index + 1} name is invalid.")
    settings = raw.get("settings", {})
    if not isinstance(settings, dict):
        raise SceneProfileValidationError(f"Source {name!r} settings must be an object.")
    required_any = capability.get("required_any", [])
    if required_any and not any(_present_setting(settings.get(key)) for key in required_any):
        raise SceneProfileValidationError(
            f"Source {name!r} requires one of: {', '.join('settings.' + key for key in required_any)}."
        )
    _unknown(settings, set(capability['setting_fields']), f"Source {name!r} settings")
    for key, value in settings.items():
        rule = FIELD_RULES.get(key, {'type': 'string'})
        field = f"Source {name!r} settings.{key}"
        if rule['type'] == 'boolean':
            _boolean(value, field)
        elif rule['type'] == 'integer':
            _integer(value, field, rule['min'], rule['max'])
        else:
            _string(value, field)
        if 'enum' in rule and value not in rule['enum']:
            raise SceneProfileValidationError(f"{field} must be one of {rule['enum']}.")
    if source_type == 'game_capture' and settings.get('capture_mode') == 'window' and not settings.get('window'):
        raise SceneProfileValidationError('Window capture mode requires settings.window.')
    if source_type == 'browser_source':
        field = 'local_file' if settings.get('is_local_file', False) else 'url'
        if not settings.get(field):
            raise SceneProfileValidationError(f'Browser requires settings.{field}.')
    # OBS bindings are server-owned identities. Display-name edits and crafted
    # request bodies must never rename or hijack a managed OBS input.
    obs_name = str(old.get("obs_name") or f"{MANAGED_PREFIX}{source_id}")
    if raw.get('transform') is not None and not capability.get('video'):
        raise SceneProfileValidationError('Audio-only sources cannot have a transform.')
    if raw.get('audio') is not None and not capability.get('audio'):
        raise SceneProfileValidationError('This source type does not support audio.')
    transform = _transform(raw.get("transform"), name) if capability.get("video") else None
    audio = (
        _audio(raw.get("audio"), name)
        if capability.get("audio") and (raw.get("audio") is not None or not capability.get("video"))
        else None
    )
    verification = raw.get("verification", {})
    if not isinstance(verification, dict):
        raise SceneProfileValidationError(f"Source {name!r} verification must be an object.")
    _unknown(verification, {'video_signal', 'audio_signal', 'audio_threshold_db', 'sample_seconds'}, 'verification')
    video_signal = _boolean(verification.get('video_signal', False), 'verification.video_signal')
    audio_signal = _boolean(verification.get('audio_signal', False), 'verification.audio_signal')
    if video_signal and not capability.get('video'):
        raise SceneProfileValidationError('Video signal requires a video-capable source.')
    if audio_signal and (not audio or not audio['enabled']):
        raise SceneProfileValidationError('Audio signal requires enabled audio configuration.')
    return {
        "id": source_id,
        "name": name,
        "obs_name": obs_name,
        "type": source_type,
        "enabled": _boolean(raw.get("enabled", True), 'source.enabled'),
        "layer": _integer(raw.get("layer", index), f"source {name} layer", 0, 999),
        "settings": deepcopy(settings),
        "transform": transform,
        "audio": audio,
        "verification": {
            "video_signal": video_signal,
            "audio_signal": audio_signal,
            "audio_threshold_db": _number(verification.get("audio_threshold_db", -50), 'verification.audio_threshold_db', -100, 0),
            "sample_seconds": _number(verification.get("sample_seconds", 2), 'verification.sample_seconds', 0.5, 10),
        },
    }


def _transform(raw: Any, name: str) -> dict[str, int]:
    value = {} if raw is None else raw
    if not isinstance(value, dict):
        raise SceneProfileValidationError(f"Source {name!r} transform must be an object.")
    allowed = {"x", "y", "width", "height", "crop_left", "crop_top", "crop_right", "crop_bottom"}
    if set(value) - allowed:
        raise SceneProfileValidationError(f"Source {name!r} transform has unknown fields.")
    result = {key: _integer(value.get(key, default), f"source {name} transform.{key}", minimum, 16384) for key, default, minimum in [
        ("x", 0, -16384), ("y", 0, -16384), ("width", 1920, 1), ("height", 1080, 1),
        ("crop_left", 0, 0), ("crop_top", 0, 0), ("crop_right", 0, 0), ("crop_bottom", 0, 0),
    ]}
    return result


def _audio(raw: Any, name: str) -> dict[str, Any]:
    value = {} if raw is None else raw
    if not isinstance(value, dict):
        raise SceneProfileValidationError(f"Source {name!r} audio must be an object.")
    _unknown(value, {'enabled', 'muted', 'volume_db', 'sync_offset_ms', 'tracks'}, 'audio')
    tracks = value.get("tracks", {"1": True, "2": False, "3": False, "4": False, "5": False, "6": False})
    if not isinstance(tracks, dict) or set(map(str, tracks)) - set("123456"):
        raise SceneProfileValidationError(f"Source {name!r} audio tracks must use keys 1 through 6.")
    return {
        "enabled": _boolean(value.get('enabled', True), 'audio.enabled'),
        "muted": _boolean(value.get("muted", False), 'audio.muted'),
        "volume_db": _number(value.get("volume_db", 0), 'audio.volume_db', -100, 26),
        "sync_offset_ms": _integer(value.get("sync_offset_ms", 0), f"source {name} audio.sync_offset_ms", -950, 20000),
        "tracks": {str(i): _boolean(tracks.get(str(i), False), f'audio.tracks.{i}') for i in range(1, 7)},
    }


def _integer(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise SceneProfileValidationError(f"{field} must be an integer from {minimum} to {maximum}.")
    return value


def _require_uuid(value: str, field: str) -> None:
    if not isinstance(value, str):
        raise SceneProfileValidationError(f'{field} must be a UUID string.')
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise SceneProfileValidationError(f"{field} must be a UUID.") from exc
    if parsed.version != 4:
        raise SceneProfileValidationError(f"{field} must be a UUIDv4.")


def _present_setting(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _unknown(value, allowed, field):
    if set(value) - allowed:
        raise SceneProfileValidationError(f"{field} has unknown fields: {sorted(set(value) - allowed)}.")


def _string(value, field):
    if not isinstance(value, str) or '\x00' in value:
        raise SceneProfileValidationError(f'{field} must be a string without NUL characters.')
    return value


def _boolean(value, field):
    if type(value) is not bool:
        raise SceneProfileValidationError(f'{field} must be a boolean.')
    return value


def _number(value, field, minimum, maximum):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise SceneProfileValidationError(f'{field} must be a finite number from {minimum} to {maximum}.')
    return float(value)
