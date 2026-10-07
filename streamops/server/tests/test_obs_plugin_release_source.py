from dataclasses import fields

from streamops.server.services.obs_plugin_release_source import (
    PluginRelease,
    PluginReleaseSourceConfig,
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
    github = PluginReleaseSourceConfig(
        provider="github-release",
        location="Synclab-VN-dev/StreamOps-OBS-Plugins",
        credential_env="STREAMOPS_OBS_PLUGIN_SOURCE_TOKEN",
    )
    future = PluginReleaseSourceConfig(
        provider="object-store",
        location="plugins/releases/stable",
        credential_env="STREAMOPS_OBS_PLUGIN_SOURCE_TOKEN",
    )
    assert github.provider != future.provider
    assert github.location != future.location
