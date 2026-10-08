from dataclasses import fields
from io import BytesIO

import pytest

from streamops.server.errors import ObsPluginError
from streamops.server.services.obs_plugin_release_source import (
    ManagedPluginReleaseSource,
    PluginRelease,
    PluginReleaseSourceConfig,
)


def _release(plugin_id="obs-multi-rtmp"):
    return PluginRelease(
        plugin_id=plugin_id,
        version="1.0.0",
        source_commit="abc123",
        platform="windows",
        architecture="x64",
        obs_version="32.2.1",
        artifact_name="plugin.zip",
        artifact_sha256="0" * 64,
        vendor="sorayuki.multi_rtmp",
        metadata={},
    )


def test_release_contract_has_no_provider_url_or_token_fields():
    names = {field.name for field in fields(PluginRelease)}
    assert "url" not in names
    assert "repository" not in names
    assert "token" not in names
    assert {
        "plugin_id", "version", "source_commit", "platform", "architecture",
        "obs_version", "artifact_name", "artifact_sha256", "vendor",
    } <= names


def test_source_location_is_opaque_to_core_contract():
    current = PluginReleaseSourceConfig(
        provider="github-release",
        location="managed/plugins",
    )
    future = PluginReleaseSourceConfig(
        provider="object-store",
        location="plugins/releases/stable",
    )
    assert current.provider != future.provider
    assert current.location != future.location


def test_managed_source_returns_only_requested_plugin():
    class Source:
        def latest(self, plugin_id):
            return _release(plugin_id)

        def open_artifact(self, release):
            return BytesIO(b"artifact")

    managed = ManagedPluginReleaseSource(Source())
    assert managed.latest("obs-multi-rtmp").plugin_id == "obs-multi-rtmp"


def test_managed_source_rejects_cross_plugin_release():
    class Source:
        def latest(self, plugin_id):
            return _release("some-other-plugin")

        def open_artifact(self, release):
            return BytesIO(b"artifact")

    with pytest.raises(ObsPluginError) as caught:
        ManagedPluginReleaseSource(Source()).latest("obs-multi-rtmp")
    assert caught.value.code == "plugin_release_invalid"


def test_missing_managed_release_fails_closed_without_fallback():
    calls = []

    class ConfiguredSource:
        def latest(self, plugin_id):
            calls.append(("configured", plugin_id))
            raise FileNotFoundError(plugin_id)

        def open_artifact(self, release):
            raise AssertionError("artifact must not be opened")

    managed = ManagedPluginReleaseSource(ConfiguredSource())
    with pytest.raises(ObsPluginError) as caught:
        managed.latest("obs-multi-rtmp")

    assert caught.value.code == "plugin_release_unavailable"
    assert calls == [("configured", "obs-multi-rtmp")]


def test_artifact_failure_does_not_try_another_source():
    calls = []

    class ConfiguredSource:
        def latest(self, plugin_id):
            return _release(plugin_id)

        def open_artifact(self, release):
            calls.append(release.plugin_id)
            raise OSError("configured source unavailable")

    managed = ManagedPluginReleaseSource(ConfiguredSource())
    with pytest.raises(ObsPluginError) as caught:
        managed.open_artifact(_release())

    assert caught.value.code == "plugin_release_unavailable"
    assert calls == ["obs-multi-rtmp"]


def test_release_version_is_explicit():
    assert _release().version == "1.0.0"
