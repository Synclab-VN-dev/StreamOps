"""OBS scene-item transform calculations."""

from __future__ import annotations

from typing import Any

from ..errors import SceneOperationError
from ..scene_config import SceneConfig, SourceConfig


OBS_ALIGN_TOP_LEFT = 5
OBS_ALIGN_BOTTOM_RIGHT = 10
TRANSFORM_TOLERANCE = 0.01


def desired_transform(
    config: SceneConfig,
    source: SourceConfig,
    current_transform: dict[str, Any],
) -> dict[str, Any]:
    if not source.is_video:
        raise SceneOperationError(f"Audio-only source {source.source_name!r} does not have a visual transform.")
    if source.role == "main":
        return _main_transform(config)
    if source.role in {"camera", "overlay"}:
        return _overlay_transform(config, source, current_transform)
    raise SceneOperationError(f"Unsupported visual source role: {source.role!r}")


def _main_transform(config: SceneConfig) -> dict[str, Any]:
    return {
        "alignment": OBS_ALIGN_TOP_LEFT,
        "positionX": 0.0,
        "positionY": 0.0,
        "rotation": 0.0,
        "cropLeft": 0,
        "cropRight": 0,
        "cropTop": 0,
        "cropBottom": 0,
        "boundsType": "OBS_BOUNDS_STRETCH",
        "boundsAlignment": OBS_ALIGN_TOP_LEFT,
        "boundsWidth": float(config.video.base_width),
        "boundsHeight": float(config.video.base_height),
    }


def _overlay_transform(
    config: SceneConfig,
    source: SourceConfig,
    current_transform: dict[str, Any],
) -> dict[str, Any]:
    if source.anchor != "bottom_right":
        raise SceneOperationError(
            f"Unsupported overlay anchor for {source.source_name!r}: {source.anchor!r}"
        )
    if source.width_percent is None or source.width_percent <= 0:
        raise SceneOperationError(
            f"Overlay source {source.source_name!r} requires a positive width_percent."
        )
    target_width = round(config.video.base_width * (source.width_percent / 100.0))
    return {
        "alignment": OBS_ALIGN_BOTTOM_RIGHT,
        "positionX": float(config.video.base_width - source.margin_right),
        "positionY": float(config.video.base_height - source.margin_bottom),
        "scaleX": 1.0,
        "scaleY": 1.0,
        "rotation": 0.0,
        "cropLeft": 0,
        "cropRight": 0,
        "cropTop": 0,
        "cropBottom": 0,
        "boundsType": "OBS_BOUNDS_SCALE_TO_WIDTH",
        "boundsAlignment": OBS_ALIGN_BOTTOM_RIGHT,
        "boundsWidth": float(target_width),
        "boundsHeight": 1.0,
    }


def transform_matches(
    actual: dict[str, Any],
    expected: dict[str, Any],
    *,
    tolerance: float = TRANSFORM_TOLERANCE,
) -> bool:
    return not transform_differences(actual, expected, tolerance=tolerance)


def transform_differences(
    actual: dict[str, Any],
    expected: dict[str, Any],
    *,
    tolerance: float = TRANSFORM_TOLERANCE,
) -> dict[str, dict[str, Any]]:
    differences: dict[str, dict[str, Any]] = {}
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if isinstance(expected_value, int | float):
            if actual_value is None or abs(float(actual_value) - float(expected_value)) > tolerance:
                differences[key] = {"expected": expected_value, "actual": actual_value}
        elif actual_value != expected_value:
            differences[key] = {"expected": expected_value, "actual": actual_value}
    return differences
