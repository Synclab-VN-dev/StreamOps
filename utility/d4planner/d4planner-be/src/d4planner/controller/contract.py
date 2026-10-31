"""Strict, immutable Xbox16 mapping contract for multi-key input capture.

Validation never accesses Win32/Steam; safe to import on non-Windows CI.
The layout establishes configured association, NOT physical Steam provenance.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping

LAYOUT_ID = "xbox-steaminput-18-v1"
LAYOUT_ALIAS = "xbox16"
MAPPING_SOURCE = "configuredLayout"
EXPECTED_DIGITAL: dict[str, tuple[str, int]] = {
    "A": ("F11", 0x7A), "B": ("F12", 0x7B),
    "X": ("F10", 0x79), "Y": ("F9", 0x78),
    "LB": ("F8", 0x77), "RB": ("F7", 0x76),
    "LT": ("F6", 0x75), "RT": ("F5", 0x74),
    "SELECT": ("F4", 0x73), "START": ("F3", 0x72),
    "L3": ("F2", 0x71), "R3": ("F1", 0x70),
    "DPAD_UP": ("[", 0xDB), "DPAD_DOWN": ("]", 0xDD),
    "DPAD_LEFT": ("\\", 0xDC), "DPAD_RIGHT": ("`", 0xC0),
}
EXPECTED_ANALOG = {"LEFT_STICK", "RIGHT_STICK"}


class ProfileValidationError(ValueError):
    """An invalid or incompatible controller mapping profile."""


@dataclass(frozen=True, slots=True)
class DigitalBinding:
    control_id: str
    key: str
    virtual_key: int
    capture_enabled: bool


@dataclass(frozen=True, slots=True)
class AnalogControl:
    control_id: str
    axes: tuple[str, str]
    capture_enabled: bool


@dataclass(frozen=True, slots=True)
class ControllerProfile:
    layout_id: str
    schema_version: int
    alias: str
    mapping_source: str
    digital: tuple[DigitalBinding, ...]
    analog: tuple[AnalogControl, ...]
    sha256: str

    @property
    def configured_count(self) -> int:
        return len(self.digital)

    @property
    def analog_disabled_count(self) -> int:
        return sum(not entry.capture_enabled for entry in self.analog)


def _error(message: str) -> ProfileValidationError:
    return ProfileValidationError(f"controller profile invalid: {message}")


def _object(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        raise _error(f"{context} must be an object with string keys")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], *, context: str) -> None:
    missing, extra = expected - value.keys(), value.keys() - expected
    if missing or extra:
        raise _error(f"{context}: missing={sorted(missing)} unexpected={sorted(extra)}")


def _string(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(f"{context} must be a non-empty string")
    return value.strip()


def validate_profile(raw: Any) -> ControllerProfile:
    """Validate the full V1 mapping. No fallback to a single F11 marker."""
    data = _object(raw, context="root")
    _exact_keys(data, {"layoutId", "schemaVersion", "alias", "mappingSource",
                       "digital", "analog"}, context="root")
    layout_id = _string(data["layoutId"], context="layoutId")
    if layout_id != LAYOUT_ID:
        raise _error(f"unsupported layoutId {layout_id!r}")
    if type(data["schemaVersion"]) is not int or data["schemaVersion"] != 1:
        raise _error("schemaVersion must be integer 1")
    alias = _string(data["alias"], context="alias")
    if alias.casefold() != LAYOUT_ALIAS:
        raise _error(f"alias must be {LAYOUT_ALIAS!r}")
    source = _string(data["mappingSource"], context="mappingSource")
    if source != MAPPING_SOURCE:
        raise _error("mappingSource must be configuredLayout")

    if not isinstance(data["digital"], list) or len(data["digital"]) != 16:
        raise _error("digital must contain exactly 16 bindings")
    digital: list[DigitalBinding] = []
    ids: set[str] = set()
    vks: set[int] = set()
    for index, row in enumerate(data["digital"]):
        obj = _object(row, context=f"digital[{index}]")
        _exact_keys(obj, {"controlId", "key", "virtualKey", "captureEnabled"},
                    context=f"digital[{index}]")
        control = _string(obj["controlId"], context="controlId").upper()
        key = _string(obj["key"], context="key").upper()
        vk = obj["virtualKey"]
        enabled = obj["captureEnabled"]
        if control not in EXPECTED_DIGITAL:
            raise _error(f"unknown controlId {control!r}")
        if control in ids:
            raise _error(f"duplicate controlId {control!r}")
        if type(vk) is not int or vk < 1 or vk > 255:
            raise _error(f"{control}: virtualKey must be an integer 1..255")
        if vk in vks:
            raise _error(f"duplicate virtualKey {vk}")
        if enabled is not True:
            raise _error(f"{control}: digital captureEnabled must be true")
        expected_key, expected_vk = EXPECTED_DIGITAL[control]
        if (key, vk) != (expected_key, expected_vk):
            raise _error(f"{control}: key/virtualKey mismatch "
                         f"{key!r}/0x{vk:02X}, expected {expected_key!r}/0x{expected_vk:02X}")
        digital.append(DigitalBinding(control, expected_key, vk, True))
        ids.add(control)
        vks.add(vk)
    if ids != EXPECTED_DIGITAL.keys():
        raise _error(f"missing digital IDs {sorted(EXPECTED_DIGITAL.keys() - ids)}")

    if not isinstance(data["analog"], list) or len(data["analog"]) != 2:
        raise _error("analog must contain exactly 2 reserved sticks")
    analog: list[AnalogControl] = []
    analog_ids: set[str] = set()
    for index, row in enumerate(data["analog"]):
        obj = _object(row, context=f"analog[{index}]")
        _exact_keys(obj, {"controlId", "axes", "captureEnabled"},
                    context=f"analog[{index}]")
        control = _string(obj["controlId"], context="controlId").upper()
        if control not in EXPECTED_ANALOG or control in analog_ids:
            raise _error(f"unknown/duplicate analog controlId {control!r}")
        if obj["axes"] != ["X", "Y"]:
            raise _error(f"{control}: analog axes must be ['X', 'Y']")
        if obj["captureEnabled"] is not False:
            raise _error(f"{control}: analog capture must be disabled in V1")
        analog.append(AnalogControl(control, ("X", "Y"), False))
        analog_ids.add(control)
    if analog_ids != EXPECTED_ANALOG:
        raise _error("missing reserved analog stick")

    # Canonical hashing is independent of JSON whitespace and object-key order,
    # while preserving the specified digital control order.
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":")).encode("utf-8")
    digest = sha256(canonical).hexdigest()
    return ControllerProfile(
        layout_id, 1, LAYOUT_ALIAS, source, tuple(digital),
        tuple(analog), digest,
    )
