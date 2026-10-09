"""Managed distribution source contract for OBS plugins.

Every installable plugin, regardless of ownership or origin, is resolved only
through the single managed distribution source selected by server composition.
The lifecycle core never falls back to an upstream repository, arbitrary URL,
or another release host.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import hashlib
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
import os
from pathlib import Path
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
            bool(re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", release.version))
            and bool(re.fullmatch(r"[A-Za-z0-9._-]{6,128}", release.source_commit))
            and release.platform == "windows"
            and release.architecture == "x64"
            and release.obs_version == "32.2.1"
            and isinstance(name, str) and name == PurePosixPath(name).name
            and bool(re.fullmatch(r"[A-Za-z0-9._-]+\.zip", name))
            and bool(re.fullmatch(r"[a-fA-F0-9]{64}", release.artifact_sha256))
            and isinstance(release.vendor, str) and bool(release.vendor)
            and isinstance(release.metadata, Mapping)
        )
        if not valid:
            raise ObsPluginError("plugin_release_invalid", "Approved plugin release metadata is invalid.", 409)
        return release

    def catalog_release(self, plugin_id: str) -> PluginRelease:
        """Read approved release metadata for display, even when OBS is incompatible.

        This does NOT authorize an install. Mutation must call latest(), which
        performs strict OBS-version and platform checks before artifact I/O.
        """
        try:
            release = self._source.latest(plugin_id)
        except ObsPluginError:
            raise
        except Exception as exc:
            raise ObsPluginError("plugin_release_source_error", "Managed plugin release metadata unavailable.", 503) from exc
        if (release.plugin_id != plugin_id or
                not isinstance(release.version, str) or
                not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", release.version) or
                not isinstance(release.source_commit, str) or
                not re.fullmatch(r"[A-Za-z0-9._-]{6,128}", release.source_commit) or
                release.platform != "windows" or release.architecture != "x64" or
                not isinstance(release.obs_version, str) or
                not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", release.obs_version) or
                not isinstance(release.artifact_name, str) or
                not re.fullmatch(r"[A-Za-z0-9._-]+\.zip", release.artifact_name) or
                not isinstance(release.artifact_sha256, str) or
                not re.fullmatch(r"[a-fA-F0-9]{64}", release.artifact_sha256) or
                not isinstance(release.metadata, Mapping) or
                release.metadata.get("approved") is not True or
                release.metadata.get("redistribution_approved") is not True):
            raise ObsPluginError("plugin_release_invalid", "Managed plugin release metadata invalid.", 409)
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


class DirectoryPluginReleaseSource:
    """Read approved artifacts only from server-controlled managed mirror."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve(strict=False)

    def _directory(self, plugin_id: str) -> Path:
        if not re.fullmatch(r"[a-z0-9-]{1,80}", plugin_id):
            raise ObsPluginError("plugin_release_invalid", "Invalid plugin ID.", 409)
        directory = (self.root / plugin_id).resolve(strict=False)
        if directory.parent != self.root:
            raise ObsPluginError("plugin_release_invalid", "Invalid plugin directory.", 409)
        return directory

    def latest(self, plugin_id: str) -> PluginRelease:
        try:
            data = json.loads((self._directory(plugin_id) / "release.json").read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Invalid release manifest")
            return PluginRelease(**data)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ObsPluginError("plugin_release_unavailable", "Managed release manifest unavailable.", 503) from exc

    def open_artifact(self, release: PluginRelease) -> BinaryIO:
        directory = self._directory(release.plugin_id)
        name = release.artifact_name
        if not isinstance(name, str) or name != Path(name).name:
            raise ObsPluginError("plugin_release_invalid", "Unsafe artifact name.", 409)
        artifact = directory / name
        if artifact.is_symlink() or artifact.resolve(strict=False).parent != directory:
            raise ObsPluginError("plugin_release_invalid", "Unsafe artifact path.", 409)
        try:
            return artifact.open("rb")
        except OSError as exc:
            raise ObsPluginError("plugin_release_unavailable", "Approved managed artifact unavailable.", 503) from exc



# GitHub Releases is the production managed source. The repository is selected
# exclusively by server configuration; no caller-supplied URLs are accepted.
DEFAULT_GITHUB_RELEASE_REPO = "Synclab-VN-dev/StreamOps-OBS-Plugins"
MAX_RELEASES_PAGES = 10
MAX_JSON_BYTES = 1024 * 1024
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024


def validate_github_download_url(url: str, repository: str) -> bool:
    """Explicit redirect policy; reject upstream, HTTP, credentials and lookalikes."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
        return False
    if parsed.port not in (None, 443):
        return False
    host = (parsed.hostname or "").lower()
    if host in {"objects.githubusercontent.com", "release-assets.githubusercontent.com"}:
        return bool(parsed.path.startswith("/")) and not parsed.path.startswith("//")
    if host == "github.com":
        return parsed.path.startswith(f"/{repository}/releases/download/")
    return False


class _SafeGitHubRedirect(HTTPRedirectHandler):
    def __init__(self, repository: str) -> None:
        self.repository = repository

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not validate_github_download_url(newurl, self.repository):
            raise ObsPluginError("plugin_release_invalid", "Untrusted managed release redirect rejected.", 409)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            # urllib normally forwards Authorization. NEVER forward GitHub
            # API tokens to the release-asset CDN even if that host is trusted.
            for field in ("Authorization", "Cookie"):
                redirected.headers.pop(field, None)
                redirected.unredirected_hdrs.pop(field, None)
        return redirected


class GitHubReleaseSource:
    """Approved releases/asset IDs from one server-owned GitHub repository.

    Tag convention: <plugin-id>/v<package-version>.
    Asset convention: <plugin-id>.release.json + <artifact_name>.
    Manifest includes PluginRelease fields; metadata must explicitly approve
    publication and redistribution, and carry exact filesystem file records.
    """

    def __init__(self, repository: str, *, token: str | None = None, transport=None) -> None:
        if not isinstance(repository, str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
        ):
            raise ValueError("Managed GitHub repository must be owner/name.")
        self.repository = repository
        self._api = f"https://api.github.com/repos/{repository}"
        self._token = token
        self._transport = transport or self._request
        self._pinned: dict[tuple[str, str, str, str], tuple[int, int]] = {}

    def _request(self, url: str, *, accept: str, token: str | None, max_bytes: int) -> bytes:
        if not url.startswith(self._api + "/"):
            raise ObsPluginError("plugin_release_invalid", "Unapproved release API origin.", 409)
        headers = {
            "Accept": accept,
            "User-Agent": "StreamOps-Managed-OBS-Plugins",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = "Bearer " + token
        opener = build_opener(_SafeGitHubRedirect(self.repository))
        with opener.open(Request(url, headers=headers), timeout=15) as response:
            # Reading one extra byte rejects oversized payloads without keeping
            # unbounded response bodies in memory.
            body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ObsPluginError("plugin_release_invalid", "Managed release response exceeds limit.", 409)
        return body

    def _fetch(self, url: str, *, accept: str, max_bytes: int) -> bytes:
        if not url.startswith(self._api + "/"):
            raise ObsPluginError("plugin_release_invalid", "Unapproved release API origin.", 409)
        try:
            body = self._transport(url, accept=accept, token=self._token, max_bytes=max_bytes)
        except ObsPluginError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise ObsPluginError(
                "plugin_release_source_error",
                "Managed GitHub release source unavailable.",
                503,
            ) from exc
        if not isinstance(body, bytes) or len(body) > max_bytes:
            raise ObsPluginError("plugin_release_invalid", "Invalid managed release payload.", 409)
        return body

    def _json(self, url: str):
        try:
            return json.loads(self._fetch(url, accept="application/vnd.github+json", max_bytes=MAX_JSON_BYTES))
        except (ValueError, UnicodeError) as exc:
            raise ObsPluginError("plugin_release_invalid", "Malformed managed release JSON.", 409) from exc

    def _releases(self) -> list[dict]:
        items = []
        for page in range(1, MAX_RELEASES_PAGES + 1):
            query = "?per_page=100" + (f"&page={page}" if page > 1 else "")
            batch = self._json(self._api + "/releases" + query)
            if not isinstance(batch, list):
                raise ObsPluginError("plugin_release_invalid", "Malformed GitHub release index.", 409)
            if any(not isinstance(item, dict) for item in batch):
                raise ObsPluginError("plugin_release_invalid", "Invalid GitHub release entry.", 409)
            items.extend(batch)
            if len(batch) < 100:
                return items
        raise ObsPluginError("plugin_release_source_error", "Managed release index pagination limit reached.", 503)

    @staticmethod
    def _key(release: PluginRelease) -> tuple[str, str, str, str]:
        return (release.plugin_id, release.version, release.artifact_name, release.artifact_sha256)

    def latest(self, plugin_id: str) -> PluginRelease:
        if not re.fullmatch(r"[a-z0-9-]{1,80}", plugin_id):
            raise ObsPluginError("plugin_release_invalid", "Invalid managed plugin ID.", 409)
        candidates = []
        for entry in self._releases():
            if entry.get("draft") or entry.get("prerelease"):
                continue
            tag = entry.get("tag_name")
            prefix = f"{plugin_id}/v"
            if not isinstance(tag, str) or not tag.startswith(prefix):
                continue
            version = tag[len(prefix):]
            if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", version):
                raise ObsPluginError("plugin_release_invalid", "Invalid managed version tag.", 409)
            candidates.append((tuple(int(part) for part in version.split(".")), version, entry))
        if not candidates:
            raise ObsPluginError("plugin_release_unavailable", "No approved managed plugin release available.", 503)
        _, version, entry = max(candidates, key=lambda item: item[0])
        assets = entry.get("assets")
        if not isinstance(assets, list) or not isinstance(entry.get("id"), int):
            raise ObsPluginError("plugin_release_invalid", "Malformed managed GitHub release.", 409)

        def asset_named(name: str) -> dict:
            matching = [a for a in assets if isinstance(a, dict) and a.get("name") == name]
            if len(matching) != 1 or not isinstance(matching[0].get("id"), int):
                raise ObsPluginError("plugin_release_invalid", "Required approved release asset missing.", 409)
            return matching[0]

        manifest_asset = asset_named(f"{plugin_id}.release.json")
        manifest = self._json_asset(int(manifest_asset["id"]))
        try:
            artifact = PluginRelease(**manifest)
        except (TypeError, ValueError, KeyError) as exc:
            raise ObsPluginError("plugin_release_invalid", "Invalid managed release manifest.", 409) from exc
        if artifact.plugin_id != plugin_id or artifact.version != version:
            raise ObsPluginError("plugin_release_invalid", "Manifest does not match its release tag.", 409)
        metadata = artifact.metadata
        if not isinstance(metadata, Mapping) or metadata.get("approved") is not True or metadata.get("redistribution_approved") is not True:
            raise ObsPluginError("plugin_release_invalid", "Managed release is not approved.", 409)
        if not (isinstance(artifact.source_commit, str) and
                re.fullmatch(r"[A-Za-z0-9._-]{6,128}", artifact.source_commit) and
                artifact.platform == "windows" and artifact.architecture == "x64" and
                re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", artifact.obs_version) and
                isinstance(artifact.artifact_sha256, str) and
                re.fullmatch(r"[a-fA-F0-9]{64}", artifact.artifact_sha256) and
                isinstance(artifact.artifact_name, str) and
                re.fullmatch(r"[A-Za-z0-9._-]+\.zip", artifact.artifact_name) and
                isinstance(metadata.get("file_count"), int) and
                isinstance(metadata.get("relative_paths"), list) and
                isinstance(metadata.get("tree_sha256"), str) and
                re.fullmatch(r"[a-fA-F0-9]{64}", metadata["tree_sha256"])):
            raise ObsPluginError("plugin_release_invalid", "Managed release metadata invalid.", 409)
        asset = asset_named(artifact.artifact_name)
        self._pinned[self._key(artifact)] = (int(entry["id"]), int(asset["id"]))
        return artifact

    def _json_asset(self, asset_id: int) -> dict:
        raw = self._fetch(self._api + f"/releases/assets/{asset_id}",
                          accept="application/octet-stream", max_bytes=MAX_JSON_BYTES)
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise ObsPluginError("plugin_release_invalid", "Malformed approved manifest.", 409) from exc
        if not isinstance(result, dict):
            raise ObsPluginError("plugin_release_invalid", "Approved manifest is not a JSON object.", 409)
        return result

    def open_artifact(self, release: PluginRelease) -> BinaryIO:
        identity = self._key(release)
        if identity not in self._pinned:
            raise ObsPluginError("plugin_release_invalid", "Artifact was not discovered and approved.", 409)
        _, asset_id = self._pinned[identity]
        raw = self._fetch(self._api + f"/releases/assets/{asset_id}",
                          accept="application/octet-stream", max_bytes=MAX_ARTIFACT_BYTES)
        if hashlib.sha256(raw).hexdigest().lower() != release.artifact_sha256.lower():
            raise ObsPluginError("plugin_release_invalid", "Approved release artifact SHA-256 mismatch.", 409)
        return BytesIO(raw)


def configured_plugin_release_source() -> ManagedPluginReleaseSource | None:
    """Production provider selected only by server-owned environment settings."""
    provider = os.environ.get("STREAMOPS_OBS_PLUGIN_SOURCE_PROVIDER", "").strip().lower()
    location = os.environ.get("STREAMOPS_OBS_PLUGIN_SOURCE_LOCATION", "").strip()
    legacy_path = os.environ.get("STREAMOPS_OBS_PLUGIN_RELEASE_DIR")
    if not provider and legacy_path:
        provider, location = "directory", legacy_path
    if not provider:
        return None  # fail closed until the managed source is configured
    if provider == "directory" and location:
        return ManagedPluginReleaseSource(DirectoryPluginReleaseSource(Path(location)))
    if provider == "github-release":
        repo = location or DEFAULT_GITHUB_RELEASE_REPO
        token_env = os.environ.get("STREAMOPS_OBS_PLUGIN_GITHUB_TOKEN_ENV", "").strip()
        if token_env and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token_env):
            raise ValueError("Invalid configured credential environment variable.")
        return ManagedPluginReleaseSource(
            GitHubReleaseSource(repo, token=os.environ.get(token_env) if token_env else None)
        )
    raise ValueError("Unknown or incomplete managed OBS plugin release provider configuration.")
