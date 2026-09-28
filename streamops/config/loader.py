"""Compatibility exports for the canonical server-owned scene config model."""

from ..server.scene_config import (
    AudioConfig,
    DEFAULT_ARTIFACT_DIR,
    DEFAULT_CONFIG_DIR,
    SceneConfig,
    SceneConfigError,
    SourceConfig,
    VideoConfig,
    find_project_root,
    list_scene_names,
    load_scene_config,
    parse_scene_config,
)

__all__ = [
    "AudioConfig",
    "DEFAULT_ARTIFACT_DIR",
    "DEFAULT_CONFIG_DIR",
    "SceneConfig",
    "SceneConfigError",
    "SourceConfig",
    "VideoConfig",
    "find_project_root",
    "list_scene_names",
    "load_scene_config",
    "parse_scene_config",
]
