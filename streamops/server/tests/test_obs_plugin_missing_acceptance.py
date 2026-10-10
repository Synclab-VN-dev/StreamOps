"""Red/green contract tests for Issue #47 outstanding acceptance criteria.

These tests intentionally describe the required behavior. Do not xfail, skip, or
weaken assertions merely because the current installer is incomplete.
"""
from __future__ import annotations

from dataclasses import replace
from io import BytesIO
import asyncio
import hashlib

import pytest

from streamops.server.services.obs_plugin import (
    ObsPluginService, PluginHostResult, PluginHostStatus,
)
from streamops.server.services.obs_plugin_release_source import (
    ManagedPluginReleaseSource, PluginRelease,
)
from streamops.server.platform.windows.obs_plugin.installer import (
    WindowsObsMultiRtmpInstaller,
)


def release(version="1.0.0", **changes):
    item = PluginRelease(
        plugin_id="obs-multi-rtmp", version=version,
        source_commit="abc123", platform="windows", architecture="x64",
        obs_version="32.2.1", artifact_name="plugin.zip",
        artifact_sha256="a" * 64, vendor="approved", metadata={},
    )
    return replace(item, **changes)


class Provider:
    def __init__(self, version="1.0.0", data=b"artifact"):
        self.version, self.data, self.calls = version, data, []
    def latest(self, plugin_id):
        self.calls.append(("latest", plugin_id))
        return release(self.version, artifact_sha256=hashlib.sha256(self.data).hexdigest())
    def open_artifact(self, item):
        self.calls.append(("artifact", item.version))
        return BytesIO(self.data)


@pytest.mark.parametrize("field,value", [
    ("version", ""), ("source_commit", ""), ("platform", "linux"),
    ("architecture", "arm64"), ("obs_version", "31.0.0"),
    ("artifact_sha256", "invalid"), ("artifact_name", "../escape.zip"),
])
def test_unit_managed_release_rejects_invalid_metadata(field, value):
    class InvalidProvider(Provider):
        def latest(self, plugin_id):
            return replace(super().latest(plugin_id), **{field: value})
    source = ManagedPluginReleaseSource(InvalidProvider())
    from streamops.server.errors import ObsPluginError
    with pytest.raises(ObsPluginError) as caught:
        source.latest("obs-multi-rtmp")
    assert caught.value.code == "plugin_release_invalid"


def test_unit_installer_accepts_injected_managed_source(tmp_path):
    source = ManagedPluginReleaseSource(Provider())
    installer = WindowsObsMultiRtmpInstaller(
        tmp_path, plugin_root=tmp_path / "plugins",
        process_probe=lambda: [], version_probe=lambda _: "32.2.1",
        release_source=source,
    )
    assert installer.release_source is source


@pytest.mark.parametrize("version", ["1.0.0", "2.0.0"])
def test_unit_available_version_is_discovered_from_managed_source(tmp_path, version):
    source = ManagedPluginReleaseSource(Provider(version))
    installer = WindowsObsMultiRtmpInstaller(
        tmp_path, plugin_root=tmp_path / "plugins",
        process_probe=lambda: [], version_probe=lambda _: "32.2.1",
        release_source=source,
    )
    assert installer.status().available_version == version


def test_unit_status_contract_has_full_lifecycle_fields():
    from dataclasses import fields
    from streamops.server.services.obs_plugin import ObsPluginStatus
    names = {f.name for f in fields(ObsPluginStatus)}
    assert {"installed_version", "available_version", "restart_required"} <= names


@pytest.mark.parametrize("state", [
    "NOT_INSTALLED", "VERIFIED", "UPDATE_AVAILABLE",
    "RESTART_REQUIRED", "VERIFY_FAILED", "FAILED",
])
def test_unit_status_supports_required_states(state):
    from typing import get_args
    from streamops.server.services.obs_plugin import PluginState
    assert state in get_args(PluginState)


def test_unit_update_stops_obs_and_verifies_after_restart():
    class Manager:
        def __init__(self):
            self.state, self.calls = "READY", []
        def status(self):
            from streamops.server.obs.manager import ObsRuntimeStatus
            return ObsRuntimeStatus(
                state=self.state, process={"running": self.state == "READY"},
                websocket={"connected": self.state == "READY", "obs_version": "32.2.1"},
                output={"streaming": False, "recording": False},
                last_operation=None, error=None,
            )
        def stop(self):
            self.calls.append("stop")
            self.state = "STOPPED"
            return self.status()
        def start(self):
            self.calls.append("start")
            self.state = "READY"
            return self.status()
    class Host:
        def __init__(self):
            self.calls = []
        def status(self):
            return PluginHostStatus("exact", True, True, "0.7.4.0")
        def update(self):
            self.calls.append("update")
            return PluginHostResult("updated")
        def verify(self):
            self.calls.append("verify")
            return self.status()
        def rollback(self):
            self.calls.append("rollback")
            return PluginHostResult("rolled_back")
    manager, host = Manager(), Host()
    result = asyncio.run(ObsPluginService(manager, host).update("obs-multi-rtmp"))
    assert result.result == "updated"
    assert manager.calls == ["stop", "start"]
    assert host.calls == ["update", "verify"]


def test_unit_update_verify_failure_rolls_back_baseline():
    from streamops.server.errors import ObsPluginError
    class Manager:
        def __init__(self):
            self.state, self.calls = "READY", []
        def status(self):
            from streamops.server.obs.manager import ObsRuntimeStatus
            return ObsRuntimeStatus(
                state=self.state, process={"running": self.state == "READY"},
                websocket={"connected": self.state == "READY", "obs_version": "32.2.1"},
                output={"streaming": False, "recording": False},
                last_operation=None, error=None,
            )
        def stop(self):
            self.calls.append("stop")
            self.state = "STOPPED"
            return self.status()
        def start(self):
            self.calls.append("start")
            self.state = "READY"
            return self.status()
    class Host:
        def __init__(self):
            self.calls = []
        def status(self):
            return PluginHostStatus("exact", True, True, "0.7.4.0")
        def update(self):
            self.calls.append("update")
            return PluginHostResult("updated")
        def verify(self):
            self.calls.append("verify")
            raise ObsPluginError("plugin_verify_failed", "module missing", 409)
        def rollback(self):
            self.calls.append("rollback")
            return PluginHostResult("rolled_back")
    manager, host = Manager(), Host()
    with pytest.raises(ObsPluginError):
        asyncio.run(ObsPluginService(manager, host).update("obs-multi-rtmp"))
    assert host.calls == ["update", "verify", "rollback"]
    assert manager.calls.count("start") >= 2


def test_unit_release_provider_is_swappable():
    events = []
    for name in ("primary", "replacement"):
        class NamedProvider(Provider):
            def latest(self, plugin_id):
                events.append((name, "latest"))
                return super().latest(plugin_id)
        managed = ManagedPluginReleaseSource(NamedProvider())
        assert managed.latest("obs-multi-rtmp").version == "1.0.0"
    assert events == [("primary", "latest"), ("replacement", "latest")]
