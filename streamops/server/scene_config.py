"""Desired-state scene configuration owned by streamops-node.

This module is canonical for both the standalone server and the legacy CLI
wrappers. Keeping the parser here preserves the server's import boundary while
allowing older StreamOps entry points to reuse the same models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Literal

from .errors import ServerError


DEFAULT_CONFIG_DIR = Path("streamops") / "config" / "scenes"
DEFAULT_ARTIFACT_DIR = Path("streamops") / "artifacts"
MediaType = Literal["video", "audio"]


class SceneConfigError(ServerError):
    """Raised when a scene desired-state file is invalid."""


@dataclass(frozen=True)
class VideoConfig:
    base_width: int
    base_height: int
    output_width: int
    output_height: int
    fps: int


@dataclass(frozen=True)
class AudioConfig:
    muted: bool = False
    volume_db: float = 0.0
    sync_offset_ms: int = 0
    tracks: dict[str, bool] = field(default_factory=lambda: {"1": True})
    signal_required: bool = False
    signal_threshold_db: float = -60.0
    signal_window_seconds: float = 1.5


@dataclass(frozen=True)
class SourceConfig:
    key: str
    source_name: str
    role: str
    layer: int
    media: MediaType = "video"
    fit: str | None = None
    anchor: str | None = None
    width_percent: float | None = None
    margin_right: float = 0
    margin_bottom: float = 0
    managed: bool = False
    input_kind: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    audio: AudioConfig | None = None

    @property
    def is_video(self) -> bool:
        return self.media == "video"

    @property
    def is_audio(self) -> bool:
        return self.media == "audio"


@dataclass(frozen=True)
class SceneConfig:
    name: str
    video: VideoConfig
    sources: tuple[SourceConfig, ...]

    @property
    def visual_sources(self) -> tuple[SourceConfig, ...]:
        return tuple(source for source in self.sources if source.is_video)

    @property
    def audio_sources(self) -> tuple[SourceConfig, ...]:
        return tuple(source for source in self.sources if source.audio is not None or source.is_audio)

    @property
    def main(self) -> SourceConfig:
        return self.source_by_role("main")

    @property
    def camera(self) -> SourceConfig:
        return self.overlay

    @property
    def overlay(self) -> SourceConfig:
        for role in ("overlay", "camera"):
            try:
                return self.source_by_role(role)
            except SceneConfigError:
                continue
        raise SceneConfigError(f"Scene {self.name!r} is missing an overlay/camera source.")

    def source_by_role(self, role: str) -> SourceConfig:
        for source in self.sources:
            if source.role == role:
                return source
        raise SceneConfigError(f"Scene {self.name!r} is missing a {role!r} source.")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def find_project_root(start: Path | None = None) -> Path:
    env_root = os.environ.get("STREAMOPS_HOME")
    if env_root:
        root = Path(env_root).expanduser().resolve()
        if not (root / DEFAULT_CONFIG_DIR).exists():
            raise SceneConfigError(f"STREAMOPS_HOME does not contain {DEFAULT_CONFIG_DIR}: {root}")
        return root

    candidates: list[Path] = []
    current = (start or Path.cwd()).resolve()
    candidates.extend([current, *current.parents])
    package_root = Path(__file__).resolve().parents[1]
    candidates.extend([package_root, *package_root.parents])

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / DEFAULT_CONFIG_DIR).exists():
            return candidate

    raise SceneConfigError(
        f"Could not find {DEFAULT_CONFIG_DIR}. Run from the repo root or set STREAMOPS_HOME."
    )


def list_scene_names(*, root: Path | None = None) -> list[str]:
    config_root = (root or find_project_root()) / DEFAULT_CONFIG_DIR
    return sorted(path.stem for path in config_root.glob("*.yaml") if path.is_file())


def load_scene_config(
    scene_name: str,
    *,
    root: Path | None = None,
    config_path: Path | None = None,
) -> SceneConfig:
    path = config_path or ((root or find_project_root()) / DEFAULT_CONFIG_DIR / f"{scene_name}.yaml")
    if not path.exists():
        raise SceneConfigError(f"Scene config not found: {path}")

    import yaml

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return parse_scene_config(raw, expected_name=scene_name, source=str(path))


def parse_scene_config(raw: dict[str, Any], *, expected_name: str, source: str = "<memory>") -> SceneConfig:
    if not isinstance(raw, dict):
        raise SceneConfigError(f"{source}: scene config must be a mapping.")

    name = _require_str(raw, "name", source)
    if name != expected_name:
        raise SceneConfigError(
            f"{source}: config name {name!r} does not match requested scene {expected_name!r}."
        )

    video_raw = _require_mapping(raw, "video", source)
    video = VideoConfig(
        base_width=_require_positive_int(video_raw, "base_width", source),
        base_height=_require_positive_int(video_raw, "base_height", source),
        output_width=_require_positive_int(video_raw, "output_width", source),
        output_height=_require_positive_int(video_raw, "output_height", source),
        fps=_require_positive_int(video_raw, "fps", source),
    )

    sources_raw = _require_mapping(raw, "sources", source)
    sources: list[SourceConfig] = []
    for key, value in sources_raw.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise SceneConfigError(f"{source}: every source entry must be a mapping.")

        media = value.get("media", "video")
        if media not in {"video", "audio"}:
            raise SceneConfigError(f"{source}: source {key!r} media must be 'video' or 'audio'.")

        input_kind = _optional_str(value, "input_kind", source)
        managed = _optional_bool(value, "managed", source)
        if managed is None:
            managed = input_kind is not None
        settings = _optional_mapping(value, "settings", source) or {}
        if managed and input_kind is None:
            raise SceneConfigError(f"{source}: managed source {key!r} requires 'input_kind'.")
        if not managed and settings:
            raise SceneConfigError(f"{source}: source {key!r} has settings but is not managed.")

        audio_raw = _optional_mapping(value, "audio", source)
        audio = _parse_audio(audio_raw, source=f"{source}:{key}") if audio_raw is not None else None
        if media == "audio" and audio is None:
            audio = AudioConfig()

        sources.append(
            SourceConfig(
                key=key,
                source_name=_require_str(value, "source_name", source),
                role=_require_str(value, "role", source),
                layer=_optional_int(value, "layer", source) or 0,
                media=media,
                fit=_optional_str(value, "fit", source),
                anchor=_optional_str(value, "anchor", source),
                width_percent=_optional_number(value, "width_percent", source),
                margin_right=_optional_number(value, "margin_right", source) or 0,
                margin_bottom=_optional_number(value, "margin_bottom", source) or 0,
                managed=managed,
                input_kind=input_kind,
                settings=settings,
                audio=audio,
            )
        )

    roles = {item.role for item in sources}
    if "main" not in roles:
        raise SceneConfigError(f"{source}: missing required source role: main.")
    if not ({"overlay", "camera"} & roles):
        raise SceneConfigError(f"{source}: missing required source role: camera or overlay.")
    if len(roles) != len(sources):
        raise SceneConfigError(f"{source}: source roles must be unique.")

    source_names = {item.source_name for item in sources}
    if len(source_names) != len(sources):
        raise SceneConfigError(f"{source}: source_name values must be unique.")

    return SceneConfig(
        name=name,
        video=video,
        sources=tuple(sorted(sources, key=lambda item: (item.layer, item.role))),
    )


def _parse_audio(raw: dict[str, Any], *, source: str) -> AudioConfig:
    tracks_raw = raw.get("tracks", {"1": True})
    if not isinstance(tracks_raw, dict) or not tracks_raw:
        raise SceneConfigError(f"{source}: audio.tracks must be a non-empty mapping.")
    tracks: dict[str, bool] = {}
    for track, enabled in tracks_raw.items():
        track_name = str(track)
        if track_name not in {"1", "2", "3", "4", "5", "6"}:
            raise SceneConfigError(f"{source}: audio track must be between 1 and 6.")
        if not isinstance(enabled, bool):
            raise SceneConfigError(f"{source}: audio track values must be booleans.")
        tracks[track_name] = enabled

    muted = raw.get("muted", False)
    if not isinstance(muted, bool):
        raise SceneConfigError(f"{source}: audio.muted must be boolean.")

    sync_offset_ms = raw.get("sync_offset_ms", 0)
    if not isinstance(sync_offset_ms, int):
        raise SceneConfigError(f"{source}: audio.sync_offset_ms must be integer.")

    signal_required = raw.get("signal_required", False)
    if not isinstance(signal_required, bool):
        raise SceneConfigError(f"{source}: audio.signal_required must be boolean.")

    signal_window = float(raw.get("signal_window_seconds", 1.5))
    if not 0.1 <= signal_window <= 10:
        raise SceneConfigError(f"{source}: audio.signal_window_seconds must be between 0.1 and 10.")

    threshold = float(raw.get("signal_threshold_db", -60.0))
    if not -100 <= threshold <= 0:
        raise SceneConfigError(f"{source}: audio.signal_threshold_db must be between -100 and 0.")

    volume_db = float(raw.get("volume_db", 0.0))
    if not -100 <= volume_db <= 26:
        raise SceneConfigError(f"{source}: audio.volume_db must be between -100 and 26.")

    return AudioConfig(
        muted=muted,
        volume_db=volume_db,
        sync_offset_ms=sync_offset_ms,
        tracks=tracks,
        signal_required=signal_required,
        signal_threshold_db=threshold,
        signal_window_seconds=signal_window,
    )


def _require_mapping(raw: dict[str, Any], key: str, source: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise SceneConfigError(f"{source}: {key!r} must be a mapping.")
    return value


def _require_str(raw: dict[str, Any], key: str, source: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SceneConfigError(f"{source}: {key!r} must be a non-empty string.")
    return value


def _optional_str(raw: dict[str, Any], key: str, source: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SceneConfigError(f"{source}: {key!r} must be a non-empty string when set.")
    return value


def _optional_bool(raw: dict[str, Any], key: str, source: str) -> bool | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise SceneConfigError(f"{source}: {key!r} must be a boolean when set.")
    return value


def _optional_mapping(raw: dict[str, Any], key: str, source: str) -> dict[str, Any] | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SceneConfigError(f"{source}: {key!r} must be a mapping when set.")
    if not all(isinstance(setting_key, str) for setting_key in value):
        raise SceneConfigError(f"{source}: {key!r} keys must be strings.")
    return dict(value)


def _optional_int(raw: dict[str, Any], key: str, source: str) -> int | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise SceneConfigError(f"{source}: {key!r} must be an integer when set.")
    return value


def _require_int(raw: dict[str, Any], key: str, source: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int):
        raise SceneConfigError(f"{source}: {key!r} must be an integer.")
    return value


def _require_positive_int(raw: dict[str, Any], key: str, source: str) -> int:
    value = _require_int(raw, key, source)
    if value <= 0:
        raise SceneConfigError(f"{source}: {key!r} must be positive.")
    return value


def _optional_number(raw: dict[str, Any], key: str, source: str) -> float | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, int | float):
        raise SceneConfigError(f"{source}: {key!r} must be numeric when set.")
    return float(value)
