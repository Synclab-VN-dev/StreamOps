"""Compatibility wrapper for canonical server-owned scene reconciliation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..server.obs import scene as _impl

ApplyResult = _impl.ApplyResult
Change = _impl.Change
Check = _impl.Check
VerifyResult = _impl.VerifyResult
SceneClient = _impl.SceneClient

# Legacy tests monkeypatch this helper. The wrappers synchronize the hook into
# the canonical module before each operation.
_windows_monitor_ids = _impl._windows_monitor_ids


def apply_scene(
    scene_name: str,
    *,
    client: SceneClient | None = None,
    root: Path | None = None,
    config_path: Path | None = None,
) -> ApplyResult:
    original = _impl._windows_monitor_ids
    _impl._windows_monitor_ids = _windows_monitor_ids
    try:
        return _impl.apply_scene(
            scene_name,
            client=client,
            root=root,
            config_path=config_path,
        )
    finally:
        _impl._windows_monitor_ids = original


def verify_scene(
    scene_name: str,
    *,
    client: SceneClient | None = None,
    root: Path | None = None,
    config_path: Path | None = None,
    runtime_audio: bool = False,
    runtime_video: bool = False,
) -> VerifyResult:
    original = _impl._windows_monitor_ids
    _impl._windows_monitor_ids = _windows_monitor_ids
    try:
        return _impl.verify_scene(
            scene_name,
            client=client,
            root=root,
            config_path=config_path,
            runtime_audio=runtime_audio,
            runtime_video=runtime_video,
        )
    finally:
        _impl._windows_monitor_ids = original


__all__ = [
    "ApplyResult",
    "Change",
    "Check",
    "SceneClient",
    "VerifyResult",
    "apply_scene",
    "verify_scene",
]
