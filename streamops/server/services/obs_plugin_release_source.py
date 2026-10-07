"""Release-source abstraction for managed OBS plugins.

The plugin lifecycle core depends on this contract, not on GitHub, S3, NAS, or
any concrete release host.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, Mapping, Protocol


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
    """Transport-neutral source of approved plugin releases."""

    def latest(self, plugin_id: str) -> PluginRelease: ...

    def open_artifact(self, release: PluginRelease) -> BinaryIO: ...


@dataclass(frozen=True)
class PluginReleaseSourceConfig:
    """Opaque provider configuration selected at composition time."""

    provider: str
    location: str
    credential_env: str | None = None
