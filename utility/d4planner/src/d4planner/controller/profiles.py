"""Load packaged profiles without depending on the current working directory."""
from __future__ import annotations

from importlib.resources import files
import json

from .contract import LAYOUT_ALIAS, ControllerProfile, ProfileValidationError, validate_profile


def available_profiles() -> tuple[str, ...]:
    return (LAYOUT_ALIAS,)


def load_profile(name: str) -> ControllerProfile:
    if not isinstance(name, str) or name.strip().casefold() != LAYOUT_ALIAS:
        raise ProfileValidationError(
            f"unknown controller profile {name!r}; available: {LAYOUT_ALIAS}"
        )
    asset = files("d4planner.controller.data").joinpath("xbox-steaminput-18-v1.json")
    try:
        with asset.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        raise ProfileValidationError(f"cannot load packaged profile: {exc}") from exc
    return validate_profile(payload)
