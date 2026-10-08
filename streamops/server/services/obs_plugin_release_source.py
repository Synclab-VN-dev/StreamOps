"""Managed distribution source contract for OBS plugins.

Every installable plugin, regardless of ownership or origin, is resolved only
through the single managed distribution source selected by server composition.
The lifecycle core never falls back to an upstream repository, arbitrary URL,
or another release host.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import PurePosixPath
from typing import BinaryIO, Mapping, Protocol

from ..errors import ObsPluginError


@dataclass(frozen=True)
class PluginRelease:
    plugin_id: str
    version: str
    source_commit: str
    platform: str
    architecture: str
    obs_version: str
    artifact_name: str
    artifact_sha256: str
    vendor: str
    metadata: Mapping[str, object]


class PluginReleaseSource(Protocol):
    """The only release boundary the plugin lifecycle core may consume."""

    def latest(self, plugin_id: str) -> PluginRelease: ...

    def open_artifact(self, release: PluginRelease) -> BinaryIO: ...


@dataclass(frozen=True)
class PluginReleaseSourceConfig:
    """Provider/location are selected at server composition time, never by clients."""

    provider: str
    location: str
    credential_env: str | None = None


class ManagedPluginReleaseSource:
    """Fail-closed wrapper enforcing one configured distribution source.

    There is deliberately no fallback source. Missing/invalid releases remain a
    typed managed-source failure instead of causing a direct upstream download.
    """

    def __init__(self, source: PluginReleaseSource) -> None:
        self._source = source

    def latest(self, plugin_id: str) -> PluginRelease:
        try:
            release = self._source.latest(plugin_id)
        except ObsPluginError:
            raise
        except Exception as exc:
            raise ObsPluginError(
                "plugin_release_unavailable",
                "No approved plugin release is available from the configured managed distribution source.",
                503,
            ) from exc
        if release.plugin_id != plugin_id:
            raise ObsPluginError(
                "plugin_release_invalid",
                "Managed distribution source returned a release for a different plugin.",
                409,
            )
        # Metadata is untrusted until validated, even when provided by the
        # configured managed source. Reject before opening any artifact.
        name = release.artifact_name
        valid = (
            bool(re.fullmatch(r"[0-9]+(?:\\.[0-9]+){1,3}", release.version))
            and bool(re.fullmatch(r"[A-Za-z0-9._-]{6,128}", release.source_commit))
            and release.platform == "windows"
            and release.architecture == "x64"
            and release.obs_version == "32.2.1"
            and isinstance(name, str) and name == PurePosixPath(name).name
            and bool(re.fullmatch(r"[A-Za-z0-9._-]+\\.zip", name))
            and bool(re.fullmatch(r"[a-fA-F0-9]{64}", release.artifact_sha256))
            and isinstance(release.vendor, str) and bool(release.vendor)
            and isinstance(release.metadata, Mapping)
        )
        if not valid:
            raise ObsPluginError("plugin_release_invalid", "Approved plugin release metadata is invalid.", 409)
        return release

    def open_artifact(self, release: PluginRelease) -> BinaryIO:
        try:
            return self._source.open_artifact(release)
        except ObsPluginError:
            raise
        except Exception as exc:
            raise ObsPluginError(
                "plugin_release_unavailable",
                "Approved plugin artifact is unavailable from the configured managed distribution source.",
                503,
            ) from exc
