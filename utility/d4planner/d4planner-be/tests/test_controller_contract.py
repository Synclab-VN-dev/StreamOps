"""Issue #87: strict mapping V1 and no Win32 dependency during import."""
from __future__ import annotations

from copy import deepcopy
from importlib.resources import files
import json
import os
import subprocess
import sys

import pytest

from d4planner.controller import ControllerResolver, ProfileValidationError, load_profile, validate_profile
from d4planner.controller.contract import EXPECTED_DIGITAL


def raw():
    return json.loads(
        files("d4planner.controller.data")
        .joinpath("xbox-steaminput-18-v1.json")
        .read_text(encoding="utf-8")
    )


def test_exact_contract_and_analog_reserved():
    profile = load_profile("xbox16")
    assert profile.layout_id == "xbox-steaminput-18-v1"
    assert profile.configured_count == 16
    assert profile.analog_disabled_count == 2
    assert len({d.control_id for d in profile.digital}) == 16
    assert len({d.virtual_key for d in profile.digital}) == 16
    assert {d.control_id:(d.key,d.virtual_key) for d in profile.digital} == EXPECTED_DIGITAL
    assert profile.mapping_source == "configuredLayout"
    assert profile.digital[0].key == "F11" and profile.digital[0].virtual_key == 0x7A


@pytest.mark.parametrize("change", [
    lambda data: data["digital"].pop(),
    lambda data: data["digital"].append(deepcopy(data["digital"][0])),
    lambda data: data["digital"].__setitem__(1, deepcopy(data["digital"][0])),
    lambda data: data["digital"][0].update(virtualKey=0x7B),
    lambda data: data["digital"][0].update(controlId="GUIDE"),
    lambda data: data["digital"][0].update(key="F8"),
    lambda data: data.update(schemaVersion=2),
    lambda data: data.update(schemaVersion=True),
    lambda data: data.update(other="unexpected"),
    lambda data: data["analog"][0].update(captureEnabled=True),
    lambda data: data["analog"][0].update(axes=["X", "Z"]),
])
def test_invalid_profiles_are_rejected(change):
    data = raw()
    change(data)
    with pytest.raises(ProfileValidationError):
        validate_profile(data)


def test_resolver_all_keys_and_unconfigured_key():
    resolver = ControllerResolver(load_profile("XBOX16"))
    for control, (key, vk) in EXPECTED_DIGITAL.items():
        value = resolver.by_virtual_key(vk)
        assert value and (value.control_id, value.key) == (control, key)
        assert resolver.by_control_id(control.lower()) == value
    assert resolver.by_virtual_key(0xFF) is None
    assert resolver.by_virtual_key(True) is None
    assert resolver.by_control_id("GUIDE") is None


def test_profile_hash_is_stable_under_key_reordering():
    data = raw()
    changed = {k: data[k] for k in reversed(list(data))}
    assert validate_profile(changed).sha256 == validate_profile(data).sha256
    assert load_profile("xbox16").sha256 == validate_profile(data).sha256


def test_load_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_profile("xbox16").configured_count == 16
    with pytest.raises(ProfileValidationError, match="unknown"):
        load_profile("missing")
