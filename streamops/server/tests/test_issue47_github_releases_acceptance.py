"""Issue #47 U17-U24 / E11-E17: executable GitHub-managed release acceptance.

These are deliberately *not* upstream-network tests. The GitHub REST transport
is replaced with a deterministic fake that preserves API URL/asset-ID semantics.
DEV-F must subsequently validate against actual Synclab GitHub Releases on A.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
from io import BytesIO
import json
from pathlib import Path
import zipfile

import pytest
from fastapi.testclient import TestClient

from streamops.server.app import create_app
from streamops.server.errors import ObsPluginError
from streamops.server.obs.manager import ObsRuntimeStatus
from streamops.server.platform.windows.obs_plugin.installer import (
    WindowsObsMultiRtmpInstaller, _file_records, _tree_digest,
)
from streamops.server.services.obs_plugin import (
    ObsPluginService, PluginHostResult, PluginHostStatus,
)
from streamops.server.services.obs_plugin_release_source import (
    GitHubReleaseSource, ManagedPluginReleaseSource,
    configured_plugin_release_source, validate_github_download_url,
)

REPO = "Synclab-VN-dev/StreamOps-OBS-Plugins"
PLUGIN = "obs-multi-rtmp"
API = "https://api.github.com/repos/" + REPO
PFX = "/api/v1/obs/plugins"


def artifact(version):
    contents = {
        "obs-plugins/64bit/obs-multi-rtmp.dll": ("dll " + version).encode(),
        "obs-plugins/64bit/obs-multi-rtmp.pdb": ("symbols " + version).encode(),
        "data/obs-plugins/obs-multi-rtmp/locale/en-US.ini": b"[text]\nname=Test\n",
    }
    data = BytesIO()
    with zipfile.ZipFile(data, "w") as zf:
        for name, value in contents.items():
            zf.writestr(name, value)
    return data.getvalue(), {
        "bin/64bit/obs-multi-rtmp.dll": contents["obs-plugins/64bit/obs-multi-rtmp.dll"],
        "bin/64bit/obs-multi-rtmp.pdb": contents["obs-plugins/64bit/obs-multi-rtmp.pdb"],
        "data/locale/en-US.ini": contents["data/obs-plugins/obs-multi-rtmp/locale/en-US.ini"],
    }


class GitHubFixture:
    """Mimics releases API + release asset API, with optional typed faults."""

    def __init__(self):
        self.releases = []
        self.assets = {}
        self.calls = []
        self.failure = None

    def add(self, version="1.0.0", plugin=PLUGIN, *, approved=True,
            draft=False, prerelease=False, compatible=True, sha_override=None,
            tag_override=None, omit_asset=False, metadata_override=None):
        payload, installed = artifact(version)
        rows = []
        for name, data in installed.items():
            rows.append({"relative_path": name, "length": len(data),
                         "sha256": hashlib.sha256(data).hexdigest()})
        tree = _tree_digest(rows)
        tag = tag_override or f"{plugin}/v{version}"
        archive = f"{plugin}-{version}-windows-x64.zip"
        metadata = {
            "approved": approved, "redistribution_approved": True,
            "file_count": len(rows),
            "relative_paths": sorted(installed),
            "tree_sha256": tree,
        }
        metadata.update(metadata_override or {})
        manifest = {
            "plugin_id": plugin, "version": version,
            "source_commit": "abcdef1234567890", "platform": "windows",
            "architecture": "x64",
            "obs_version": "32.2.1" if compatible else "31.0.0",
            "artifact_name": archive,
            "artifact_sha256": sha_override or hashlib.sha256(payload).hexdigest(),
            "vendor": "sorayuki.multi_rtmp",
            "metadata": metadata,
        }
        rid = 100 + len(self.releases)
        mid, aid = rid * 10 + 1, rid * 10 + 2
        assets = [{"id": mid, "name": f"{plugin}.release.json", "size": 900}]
        self.assets[mid] = json.dumps(manifest).encode()
        if not omit_asset:
            assets.append({"id": aid, "name": archive, "size": len(payload)})
            self.assets[aid] = payload
        self.releases.append({
            "id": rid, "tag_name": tag, "draft": draft, "prerelease": prerelease,
            "assets": assets, "published_at": "2026-10-09T00:00:00Z",
        })
        return manifest, aid

    def __call__(self, url, *, accept, token=None, max_bytes=None):
        assert url.startswith(API + "/"), "unexpected upstream or alternate repository"
        self.calls.append((url, accept, token))
        if self.failure:
            raise self.failure
        if url == API + "/releases?per_page=100":
            return json.dumps(self.releases).encode()
        prefix = API + "/releases/assets/"
        assert url.startswith(prefix), url
        assert accept == "application/octet-stream", accept
        result = self.assets[int(url[len(prefix):])]
        assert max_bytes is None or len(result) <= max_bytes
        return result


def source(http):
    return GitHubReleaseSource(REPO, transport=http)


def managed(http):
    return ManagedPluginReleaseSource(source(http))


def assert_clean(install_root, state_dir):
    assert not install_root.exists() or not _file_records(install_root)
    assert not (state_dir / "obs-plugins" / PLUGIN / "current-transaction.json").exists()


class Vendor:
    fail = False
    def connect(self): pass
    def request(self, name, payload):
        assert name == "CallVendorRequest"
        assert payload == {"vendorName": "sorayuki.multi_rtmp",
                           "requestType": "list_targets", "requestData": {}}
        if self.fail:
            raise ConnectionError("vendor missing")
        return {"responseData": {"targets": []}}
    def close(self): pass


class Process:
    def __init__(self):
        self.state, self.calls = "READY", []
        self.client_factory = Vendor
    def status(self):
        ready = self.state == "READY"
        return ObsRuntimeStatus(
            state=self.state, process={"running": ready},
            websocket={"connected": ready, "obs_version": "32.2.1"},
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
    def __init__(self, installer, manager):
        self.installer, self.manager = installer, manager
    def status(self):
        raw = self.installer.status()
        ready = self.manager.state == "READY"
        return PluginHostStatus(
            raw.installation, raw.compatible, raw.installation == "exact" and ready,
            raw.installed_version if ready else None,
            installed_version=raw.installed_version,
            available_version=raw.available_version,
        )
    def install(self):
        return PluginHostResult(self.installer.install().result)
    def update(self):
        return PluginHostResult(self.installer.update().result)
    def rollback(self):
        return PluginHostResult(self.installer.rollback().result)
    def verify(self):
        return self.status()


def environment(tmp_path, http):
    root = tmp_path / "installed"
    state = tmp_path / "runtime"
    manager = Process()
    installer = WindowsObsMultiRtmpInstaller(
        state, plugin_root=root, appdata=tmp_path / "AppData",
        obs_executable=tmp_path / "obs64.exe",
        release_source=managed(http), process_probe=lambda: [],
        version_probe=lambda _: "32.2.1",
    )
    service = ObsPluginService(manager, Host(installer, manager), defer_restart=True,
                               release_source=installer.release_source)
    return service, manager, installer, root, state


# UNIT: one discrete contract gate per test.


def test_u17_server_only_github_provider_configuration(monkeypatch):
    monkeypatch.setenv("STREAMOPS_OBS_PLUGIN_SOURCE_PROVIDER", "github-release")
    monkeypatch.setenv("STREAMOPS_OBS_PLUGIN_SOURCE_LOCATION", REPO)
    monkeypatch.delenv("STREAMOPS_OBS_PLUGIN_RELEASE_DIR", raising=False)
    selected = configured_plugin_release_source()
    assert isinstance(selected, ManagedPluginReleaseSource)
    assert isinstance(selected._source, GitHubReleaseSource)
    assert selected._source.repository == REPO
    assert not hasattr(selected._source, "fallback")


def test_u18_version_sort_draft_prerelease_policy():
    http = GitHubFixture()
    http.add("1.9.0")
    http.add("3.0.0", draft=True)
    http.add("2.1.0", prerelease=True)
    http.add("1.10.0")
    assert managed(http).latest(PLUGIN).version == "1.10.0"
    assert http.calls[0][0] == API + "/releases?per_page=100"


@pytest.mark.parametrize("change", [
    {"approved": False}, {"metadata_override": {"redistribution_approved": False}},
    {"metadata_override": {"tree_sha256": "bad"}},
    {"tag_override": f"{PLUGIN}/v9.9.9"},
    {"sha_override": "not-sha"},
])
def test_u19_release_identity_provenance_approval_validation(change):
    http = GitHubFixture()
    http.add(**change)
    with pytest.raises(ObsPluginError):
        managed(http).latest(PLUGIN)


def test_u20_catalog_intersects_registry_and_release(tmp_path):
    http = GitHubFixture()
    http.add("1.0.0")
    http.add("2.0.0", plugin="not-allowlisted")
    service, _, _, _, _ = environment(tmp_path, http)
    data = asyncio.run(service.available())
    assert data["source_state"] == "READY"
    assert len(data["plugins"]) == 1
    item = data["plugins"][0]
    assert item["plugin_id"] == PLUGIN
    assert item["available_version"] == "1.0.0"
    assert item["installed_version"] is None
    assert item["installable"] is True
    assert "not-allowlisted" not in repr(data)


@pytest.mark.parametrize("failure,code", [
    (ObsPluginError("plugin_release_source_error", "no access", 503), "plugin_release_source_error"),
    (ObsPluginError("plugin_release_source_error", "429", 503), "plugin_release_source_error"),
])
def test_u21_empty_is_distinct_from_source_failure(tmp_path, failure, code):
    empty = GitHubFixture()
    service, _, _, _, _ = environment(tmp_path, empty)
    assert asyncio.run(service.available()) == {"plugins": [], "source_state": "EMPTY"}
    service.release_source = None
    assert asyncio.run(service.available()) == {"plugins": [], "source_state": "UNCONFIGURED"}
    service.release_source = managed(empty)
    with pytest.raises(ObsPluginError) as caught:
        managed(empty).latest(PLUGIN)
    assert caught.value.code == "plugin_release_unavailable"
    empty.failure = failure
    with pytest.raises(ObsPluginError) as caught:
        asyncio.run(service.available())
    assert caught.value.code == code


@pytest.mark.parametrize("url,allowed", [
    ("https://release-assets.githubusercontent.com/foo", True),
    ("https://objects.githubusercontent.com/foo", True),
    ("https://github.com/Synclab-VN-dev/StreamOps-OBS-Plugins/releases/download/x/a.zip", True),
    ("https://github.com/sorayuki/obs-multi-rtmp/releases/download/x/a.zip", False),
    ("https://github.com.attacker.test/x", False),
    ("http://release-assets.githubusercontent.com/foo", False),
    ("https://evil.example/payload", False),
])
def test_u22_download_redirect_host_allowlist(url, allowed):
    assert validate_github_download_url(url, REPO) is allowed


def test_u22_redirect_denies_upstream_and_strips_api_credentials():
    from urllib.request import Request
    from streamops.server.services.obs_plugin_release_source import _SafeGitHubRedirect

    handler = _SafeGitHubRedirect(REPO)
    initial = Request(API + "/releases/assets/1002",
                      headers={"Authorization": "Bearer must-not-leak"})
    for denied in ("https://github.com/sorayuki/obs-multi-rtmp/releases/download/x/plugin.zip",
                   "https://release-assets.githubusercontent.com.evil.test/asset"):
        with pytest.raises(ObsPluginError):
            handler.redirect_request(initial, None, 302, "Found", {}, denied)

    redirect = handler.redirect_request(
        initial, None, 302, "Found", {},
        "https://release-assets.githubusercontent.com/approved-object",
    )
    assert redirect is not None
    assert redirect.get_header("Authorization") is None
    assert "must-not-leak" not in repr(redirect.headers)


def test_u23_static_available_route_and_reject_client_source(server_config, capture_service, tmp_path, caplog):
    http = GitHubFixture()
    http.add()
    service, manager, _, _, _ = environment(tmp_path, http)
    app = create_app(server_config, capture_service=capture_service,
                     obs_manager=manager, obs_plugin_service=service, manage_runtime=False)
    with TestClient(app) as api:
        good = api.get(PFX + "/available")
        assert good.status_code == 200
        assert good.json()["plugins"][0]["plugin_id"] == PLUGIN
        bad = api.get(PFX + "/available?repository=https://evil.example")
        assert bad.status_code == 400
        bad_post = api.post(PFX + f"/{PLUGIN}/install", json={"source": "upstream"})
        assert bad_post.status_code == 400
    assert "authorization" not in good.text.lower()
    assert "token" not in good.text.lower()
    assert "not_supported" not in good.text


def test_u24_mutated_approved_asset_fails_before_mutation(tmp_path):
    http = GitHubFixture()
    _, aid = http.add()
    service, _, installer, root, state = environment(tmp_path, http)
    selected = installer.release_source.latest(PLUGIN)
    http.assets[aid] = b"substituted after discovery"
    with pytest.raises(ObsPluginError) as caught:
        installer.release_source.open_artifact(selected)
    assert caught.value.code == "plugin_release_invalid"
    assert_clean(root, state)


# E2E: cross-boundary behavior, backed by GitHub REST/asset HTTP fixtures.


def test_e11_discovery_manifest_asset_from_expected_github_api():
    http = GitHubFixture()
    http.add("1.0.0")
    _, asset_id = http.add("1.2.0")
    # Discovery pins asset ID inside a specific provider instance. Reuse that
    # instance for download; recreating it must not bypass the approval pin.
    provider = managed(http)
    release = provider.latest(PLUGIN)
    assert release.version == "1.2.0"
    with provider.open_artifact(release) as data:
        assert data.read() == http.assets[asset_id]
    urls = [call[0] for call in http.calls]
    assert API + "/releases?per_page=100" in urls
    assert API + "/releases/assets/" + str(asset_id) in urls
    assert all(url.startswith(API + "/") for url in urls)


def test_e12_catalog_rest_inventory_allowlist_parity(server_config, capture_service, tmp_path):
    http = GitHubFixture()
    http.add()
    http.add(plugin="unregistered-plugin")
    service, manager, _, _, _ = environment(tmp_path, http)
    with TestClient(create_app(server_config, capture_service=capture_service,
                               obs_manager=manager, obs_plugin_service=service,
                               manage_runtime=False)) as api:
        catalog = api.get(PFX + "/available")
        inventory = api.get(PFX)
    assert catalog.status_code == inventory.status_code == 200
    assert catalog.headers["cache-control"] == "no-store"
    assert [p["plugin_id"] for p in catalog.json()["plugins"]] == [PLUGIN]
    assert [p["plugin_id"] for p in inventory.json()["plugins"]] == [PLUGIN]


def test_e13_catalog_empty_incompatible_installed_update(tmp_path):
    http = GitHubFixture()
    service, manager, installer, _, _ = environment(tmp_path, http)
    assert asyncio.run(service.available())["source_state"] == "EMPTY"
    http.add("1.0.0", compatible=False)
    invalid = asyncio.run(service.available())
    assert invalid["plugins"][0]["installable"] is False
    assert invalid["plugins"][0]["reason"]
    http.releases.clear()
    http.assets.clear()
    http.add("1.0.0")
    assert asyncio.run(service.install(PLUGIN)).status.state == "RESTART_REQUIRED"
    manager.start()
    assert asyncio.run(service.verify(PLUGIN)).status.state == "VERIFIED"
    installed = asyncio.run(service.available())["plugins"][0]
    assert installed["installed_version"] == "1.0.0"
    assert installed["installable"] is False
    http.add("1.1.0")
    updated = asyncio.run(service.available())["plugins"][0]
    assert updated["available_version"] == "1.1.0"
    assert updated["installable"] is True


def test_e14_github_provider_install_restart_verify_real_filesystem(tmp_path):
    http = GitHubFixture()
    http.add("1.0.0")
    service, manager, installer, root, _ = environment(tmp_path, http)
    pending = asyncio.run(service.install(PLUGIN))
    assert pending.status.restart_required is True
    assert manager.calls == ["stop"]
    assert (root / "bin/64bit/obs-multi-rtmp.dll").read_bytes() == b"dll 1.0.0"
    manager.start()
    result = asyncio.run(service.verify(PLUGIN))
    assert result.status.state == "VERIFIED"
    assert result.status.restart_required is False
    assert installer.status().installed_version == "1.0.0"


def test_e15_github_provider_v1_v2_update_verify_rollback(tmp_path):
    http = GitHubFixture()
    http.add("1.0.0")
    service, manager, installer, root, _ = environment(tmp_path, http)
    config = tmp_path / "AppData" / "obs-studio" / "basic" / "profiles" / "User" / "obs-multi-rtmp.json"
    config.parent.mkdir(parents=True)
    baseline = b'{"targets":[{"stream_key":"must-stay-private"}]}'
    config.write_bytes(baseline)
    asyncio.run(service.install(PLUGIN))
    manager.start()
    asyncio.run(service.verify(PLUGIN))
    digest_v1 = _file_records(root)
    http.add("1.1.0")
    assert asyncio.run(service.status(PLUGIN)).state == "UPDATE_AVAILABLE"
    changed = asyncio.run(service.update(PLUGIN))
    assert changed.status.state == "RESTART_REQUIRED"
    manager.start()
    assert asyncio.run(service.verify(PLUGIN)).status.state == "VERIFIED"
    assert _file_records(root) != digest_v1
    assert config.read_bytes() == baseline
    undone = asyncio.run(service.rollback(PLUGIN))
    assert undone.status.restart_required is True
    manager.start()
    verified_baseline = asyncio.run(service.verify(PLUGIN))
    # Baseline v1 is installed and verified, while Synclab still offers v2;
    # UPDATE_AVAILABLE is correct (not a false "VERIFIED" catalog state).
    assert verified_baseline.status.state == "UPDATE_AVAILABLE"
    assert verified_baseline.status.last_verification is not None
    assert verified_baseline.status.restart_required is False
    assert _file_records(root) == digest_v1
    assert config.read_bytes() == baseline
    assert installer.status().installed_version == "1.0.0"

    # Update again and force the *real vendor probe boundary* to fail.
    asyncio.run(service.update(PLUGIN))
    manager.start()
    Vendor.fail = True
    try:
        with pytest.raises(ObsPluginError) as failed:
            asyncio.run(service.verify(PLUGIN))
        assert failed.value.code == "plugin_verify_failed"
    finally:
        Vendor.fail = False
    assert manager.state == "READY"
    assert _file_records(root) == digest_v1
    assert config.read_bytes() == baseline
    assert installer.status().installed_version == "1.0.0"


@pytest.mark.parametrize("mode", [
    "invalid-sha", "bad-sha-format", "bad-tree", "missing-asset",
    "unapproved", "no-redistribution", "no-release",
    "http-401", "http-403", "http-404", "http-429", "timeout", "invalid-json",
])
def test_e16_github_release_failure_no_mutation_no_fallback(tmp_path, mode):
    from urllib.error import HTTPError, URLError
    http = GitHubFixture()
    kwargs = {
        "invalid-sha": {"sha_override": "0" * 64},
        "bad-sha-format": {"sha_override": "invalid"},
        "bad-tree": {"metadata_override": {"tree_sha256": "invalid"}},
        "missing-asset": {"omit_asset": True},
        "unapproved": {"approved": False},
        "no-redistribution": {"metadata_override": {"redistribution_approved": False}},
    }.get(mode, {})
    if mode != "no-release":
        http.add(**kwargs)
    status_codes = {"http-401": 401, "http-403": 403, "http-404": 404, "http-429": 429}
    if mode in status_codes:
        http.failure = HTTPError(API + "/releases", status_codes[mode], "status failure", {}, None)
    elif mode == "timeout":
        http.failure = URLError("offline / timed out")
    elif mode == "invalid-json":
        http.assets[next(iter(http.assets))] = b"{ invalid JSON"
    service, _, installer, root, state = environment(tmp_path, http)
    with pytest.raises(ObsPluginError) as caught:
        asyncio.run(service.install(PLUGIN))
    assert caught.value.code in {
        "plugin_install_failed", "plugin_release_source_error",
        "plugin_release_invalid", "plugin_release_unavailable",
    }
    assert_clean(root, state)
    assert all(call[0].startswith(API + "/") for call in http.calls)


def test_e17_provider_swap_does_not_change_rest_ws_api(server_config, capture_service, tmp_path):
    from streamops.server.services.obs_plugin_release_source import DirectoryPluginReleaseSource

    http = GitHubFixture()
    http.add("1.0.0")
    service, manager, installer, _, _ = environment(tmp_path, http)
    with TestClient(create_app(server_config, capture_service=capture_service,
                               obs_manager=manager, obs_plugin_service=service,
                               manage_runtime=False)) as api:
        before = api.get(PFX + "/available")
        inventory_before = api.get(PFX)
        with api.websocket_connect(PFX + "/ws") as ws:
            ws.send_json({"type": "request", "operation": "obs_plugin.status",
                          "request_id": "source-before", "payload": {"plugin_id": PLUGIN}})
            before_ws = ws.receive_json()
        assert before.status_code == inventory_before.status_code == 200
        assert before_ws["ok"] is True

        # Change solely the server-side configured provider. Routes, request
        # shape and lifecycle service are unchanged.
        root = tmp_path / "mirror" / PLUGIN
        root.mkdir(parents=True)
        metadata, aid = http.add("1.1.0")
        (root / "release.json").write_text(json.dumps(metadata), encoding="utf-8")
        (root / metadata["artifact_name"]).write_bytes(http.assets[aid])
        approved_dir = ManagedPluginReleaseSource(DirectoryPluginReleaseSource(root.parent))
        installer.release_source = approved_dir
        service.release_source = approved_dir
        after = api.get(PFX + "/available")
        inventory_after = api.get(PFX)
        with api.websocket_connect(PFX + "/ws") as ws:
            ws.send_json({"type": "request", "operation": "obs_plugin.status",
                          "request_id": "source-after", "payload": {"plugin_id": PLUGIN}})
            after_ws = ws.receive_json()
    assert after.status_code == inventory_after.status_code == 200
    assert before.json()["plugins"][0]["available_version"] == "1.0.0"
    assert after.json()["plugins"][0]["available_version"] == "1.1.0"
    assert set(before.json()["plugins"][0]) == set(after.json()["plugins"][0])
    assert before_ws["data"]["plugin_id"] == after_ws["data"]["plugin_id"] == PLUGIN
    assert before_ws["request_id"] == "source-before"
    assert after_ws["request_id"] == "source-after"



# Hardening of U18/U19/U21/U22/U23/U24/E16/E17. These tests cover
# adversarial provider behavior and preserve the installed baseline.


def test_u18_releases_pagination_and_duplicate_versions():
    fixture = GitHubFixture()
    # The first GitHub page is full of unrelated plugins. We MUST fetch page
    # two rather than incorrectly reporting a missing approved release.
    for n in range(100):
        fixture.add(f"1.{n}.0", plugin="other-plugin")
    fixture.add("2.0.0")
    calls = []

    def paged(url, *, accept, token=None, max_bytes=None):
        calls.append(url)
        if url == API + "/releases?per_page=100":
            return json.dumps(fixture.releases[:100]).encode()
        if url == API + "/releases?per_page=100&page=2":
            return json.dumps(fixture.releases[100:]).encode()
        return fixture(url, accept=accept, token=token, max_bytes=max_bytes)

    assert GitHubReleaseSource(REPO, transport=paged).latest(PLUGIN).version == "2.0.0"
    assert API + "/releases?per_page=100&page=2" in calls

    duplicate = GitHubFixture()
    duplicate.add("1.0.0")
    duplicate.add("1.0.0")
    with pytest.raises(ObsPluginError) as caught:
        managed(duplicate).latest(PLUGIN)
    assert caught.value.code == "plugin_release_invalid"

    ambiguous = GitHubFixture()
    ambiguous.add("1.9.0")
    ambiguous.add("1.09.0")
    with pytest.raises(ObsPluginError) as caught:
        managed(ambiguous).latest(PLUGIN)
    assert caught.value.code == "plugin_release_invalid"

    invalid_latest = GitHubFixture()
    invalid_latest.add("1.0.0")
    invalid_latest.add("2.0.0", approved=False)
    with pytest.raises(ObsPluginError) as caught:
        managed(invalid_latest).latest(PLUGIN)
    assert caught.value.code == "plugin_release_invalid"
    # Never silently install the older version when the latest has failed
    # security/approval validation.


@pytest.mark.parametrize("bad", [
    {"missing_field": "source_commit"},
    {"manifest_change": {"source_commit": "bad!"}},
    {"manifest_change": {"platform": "linux"}},
    {"manifest_change": {"architecture": "arm64"}},
    {"manifest_change": {"artifact_name": "../plugin.zip"}},
    {"metadata_change": {"file_count": 4}},
    {"metadata_change": {"file_count": -1}},
    {"metadata_change": {"relative_paths": ["same.dll", "same.dll", "other.dll"]}},
    {"metadata_change": {"relative_paths": ["../escape.dll", "a.dll", "b.dll"]}},
    {"duplicate_asset": True},
])
def test_u19_bad_manifest_and_duplicate_asset_fail_closed(bad):
    fixture = GitHubFixture()
    manifest, _ = fixture.add()
    metadata = manifest.get("metadata", {})
    manifest.update(bad.get("manifest_change", {}))
    metadata.update(bad.get("metadata_change", {}))
    manifest.pop(bad.get("missing_field", ""), None)
    manifest_asset_id = fixture.releases[0]["assets"][0]["id"]
    fixture.assets[manifest_asset_id] = json.dumps(manifest).encode()
    if bad.get("duplicate_asset"):
        fixture.releases[0]["assets"].append(dict(fixture.releases[0]["assets"][1]))
    with pytest.raises(ObsPluginError) as caught:
        managed(fixture).latest(PLUGIN)
    assert caught.value.code == "plugin_release_invalid"


@pytest.mark.parametrize("http_status", [401, 403, 404, 429])
def test_u21_http_failure_is_exactly_typed(http_status):
    from urllib.error import HTTPError

    fixture = GitHubFixture()
    fixture.add()
    fixture.failure = HTTPError(API + "/releases", http_status, "HTTP failure", {}, None)
    with pytest.raises(ObsPluginError) as caught:
        managed(fixture).latest(PLUGIN)
    assert caught.value.code == "plugin_release_source_error"
    assert caught.value.status_code == 503
    assert str(http_status) not in str(caught.value)
    assert all(url.startswith(API + "/") for url, _, _ in fixture.calls)


def test_u22_max_download_size_rejects_before_install(tmp_path, monkeypatch):
    import streamops.server.services.obs_plugin_release_source as module

    class OversizedResponseFixture(GitHubFixture):
        def __call__(self, url, *, accept, token=None, max_bytes=None):
            # Intentionally ignore the requested limit so the actual HTTP
            # response-size enforcement (rather than the fixture) is tested.
            return super().__call__(url, accept=accept, token=token, max_bytes=None)

    fixture = OversizedResponseFixture()
    fixture.add()
    service, _, installer, root, state = environment(tmp_path, fixture)
    release = installer.release_source.latest(PLUGIN)
    monkeypatch.setattr(module, "MAX_ARTIFACT_BYTES", 8)
    with pytest.raises(ObsPluginError) as caught:
        installer.release_source.open_artifact(release)
    assert caught.value.code == "plugin_release_invalid"
    assert_clean(root, state)


def test_u22_multiple_redirects_never_forward_token():
    from urllib.request import Request
    from streamops.server.services.obs_plugin_release_source import _SafeGitHubRedirect

    handler = _SafeGitHubRedirect(REPO)
    token = "SECRET-MUST-NOT-LEAK"
    original = Request(API + "/releases/assets/1002",
                       headers={"Authorization": "Bearer " + token, "Cookie": token})
    first = handler.redirect_request(
        original, None, 302, "Found", {},
        "https://release-assets.githubusercontent.com/signed-asset",
    )
    assert first.get_header("Authorization") is None
    assert first.get_header("Cookie") is None
    second = handler.redirect_request(
        first, None, 302, "Found", {},
        "https://objects.githubusercontent.com/signed-asset",
    )
    assert second.get_header("Authorization") is None
    assert second.get_header("Cookie") is None
    assert token not in repr(first.headers) + repr(second.headers)
    with pytest.raises(ObsPluginError):
        handler.redirect_request(
            second, None, 302, "Found", {},
            "https://github.com/sorayuki/obs-multi-rtmp/releases/download/v1/unapproved.zip",
        )


def test_u22_local_http_release_server_exercises_real_http_transport():
    """Loopback HTTP reproduces GitHub JSON + octet asset endpoints without internet."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    fixture = GitHubFixture()
    fixture.add("1.0.0")
    payload, artifact_id = fixture.add("1.1.0")
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get("Accept")))
            if self.path == "/releases?per_page=100":
                content = json.dumps(fixture.releases).encode()
            elif self.path.startswith("/releases/assets/"):
                content = fixture.assets[int(self.path.rsplit("/", 1)[1])]
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            return  # Avoid test secrets and noisy server logs.

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = GitHubReleaseSource(REPO)
        # Test-only transport endpoint override, never a production config path.
        provider._api = f"http://127.0.0.1:{server.server_port}"
        release = provider.latest(PLUGIN)
        assert release.version == "1.1.0"
        with provider.open_artifact(release) as opened:
            assert opened.read() == fixture.assets[artifact_id]
        assert len(seen) == 3
        assert seen[0][0] == "/releases?per_page=100"
        assert seen[0][1] == "application/vnd.github+json"
        assert all(x[1] == "application/octet-stream" for x in seen[1:])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_u23_no_token_in_rest_or_websocket_errors(
    server_config, capture_service, tmp_path, caplog,
):
    from urllib.error import URLError
    import logging

    secret = "SECRET-GITHUB-PROVIDER-CANARY"
    fixture = GitHubFixture()
    fixture.add()
    fixture.failure = URLError("token=" + secret)
    service, manager, installer, _, _ = environment(tmp_path, fixture)
    # API errors must be sanitized even when transport exception has secrets.
    with caplog.at_level(logging.ERROR):
        with TestClient(create_app(
            server_config, capture_service=capture_service,
            obs_manager=manager, obs_plugin_service=service,
            manage_runtime=False,
        )) as api:
            available = api.get(PFX + "/available")
            assert available.status_code == 503
            assert available.json()["error"]["code"] == "plugin_release_source_error"
            with api.websocket_connect(PFX + "/ws") as ws:
                ws.send_json({
                    "type": "request", "request_id": "github-error",
                    "operation": "obs_plugin.install", "payload": {"plugin_id": PLUGIN},
                })
                response = ws.receive_json()
            assert response["ok"] is False
            assert response["request_id"] == "github-error"
            assert "error" in response
    assert secret not in available.text
    assert secret not in repr(response)
    assert secret not in caplog.text


@pytest.mark.parametrize("failure_mode", [
    "sha-mismatch", "invalid-tree", "asset-missing",
    "http-403", "http-429", "timeout",
])
def test_e16_failed_v2_update_preserves_v1_config_and_journal(tmp_path, failure_mode):
    from urllib.error import HTTPError, URLError

    fixture = GitHubFixture()
    fixture.add("1.0.0")
    service, manager, installer, root, state = environment(tmp_path, fixture)
    config = (tmp_path / "AppData" / "obs-studio" / "basic" /
              "profiles" / "User" / "obs-multi-rtmp.json")
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_bytes(b'{"targets":[{"stream_key":"keep-existing"}]}')
    assert asyncio.run(service.install(PLUGIN)).result == "installed"
    manager.start()
    assert asyncio.run(service.verify(PLUGIN)).status.state == "VERIFIED"
    before_records = _file_records(root)
    before_config = config.read_bytes()
    before_pointer = installer.pointer.read_bytes()
    before_journals = sorted(p.name for p in installer.transactions_root.iterdir())
    kwargs = {
        "sha-mismatch": {"sha_override": "0" * 64},
        "invalid-tree": {"metadata_override": {"tree_sha256": "0" * 64}},
        "asset-missing": {"omit_asset": True},
    }.get(failure_mode, {})
    fixture.add("1.1.0", **kwargs)
    if failure_mode == "http-403":
        fixture.failure = HTTPError(API + "/releases", 403, "Forbidden", {}, None)
    elif failure_mode == "http-429":
        fixture.failure = HTTPError(API + "/releases", 429, "Rate limit", {}, None)
    elif failure_mode == "timeout":
        fixture.failure = URLError("network timed out")

    with pytest.raises(ObsPluginError):
        asyncio.run(service.update(PLUGIN))
    assert _file_records(root) == before_records, "v1 DLL must remain byte-identical"
    assert config.read_bytes() == before_config
    assert installer.pointer.read_bytes() == before_pointer
    assert sorted(p.name for p in installer.transactions_root.iterdir()) == before_journals
    assert manager.state == "READY", "OBS must resume on update failure"
    if failure_mode in {"sha-mismatch", "invalid-tree"}:
        # Source was accessible and the replacement asset was fetched.
        assert any("/releases/assets/" in url for url, _, _ in fixture.calls)


def test_e17_provider_swap_then_real_rest_install_update_verify(
    server_config, capture_service, tmp_path,
):
    from streamops.server.services.obs_plugin_release_source import DirectoryPluginReleaseSource

    fixture = GitHubFixture()
    release_v1, asset_v1 = fixture.add("1.0.0")
    service, manager, installer, root, _ = environment(tmp_path, fixture)

    directory = tmp_path / "mirror" / PLUGIN
    directory.mkdir(parents=True)
    (directory / "release.json").write_text(json.dumps(release_v1), encoding="utf-8")
    (directory / release_v1["artifact_name"]).write_bytes(fixture.assets[asset_v1])
    first_provider = ManagedPluginReleaseSource(DirectoryPluginReleaseSource(directory.parent))
    installer.release_source = first_provider
    service.release_source = first_provider

    with TestClient(create_app(
        server_config, capture_service=capture_service,
        obs_manager=manager, obs_plugin_service=service, manage_runtime=False,
    )) as api:
        assert api.get(PFX + "/available").json()["plugins"][0]["available_version"] == "1.0.0"
        installed = api.post(PFX + "/" + PLUGIN + "/install")
        assert installed.status_code == 200
        assert installed.json()["state"] == "RESTART_REQUIRED"
        manager.start()
        verified = api.post(PFX + "/" + PLUGIN + "/verify")
        assert verified.status_code == 200
        assert verified.json()["state"] == "VERIFIED"
        before = _file_records(root)

        fixture.add("1.1.0")
        github_provider = managed(fixture)
        installer.release_source = github_provider
        service.release_source = github_provider
        assert api.get(PFX + "/available").json()["plugins"][0]["available_version"] == "1.1.0"
        updated = api.post(PFX + "/" + PLUGIN + "/update")
        assert updated.status_code == 200
        assert updated.json()["state"] == "RESTART_REQUIRED"
        manager.start()
        verified_v2 = api.post(PFX + "/" + PLUGIN + "/verify")
        assert verified_v2.status_code == 200
        assert verified_v2.json()["installed_version"] == "1.1.0"
        assert _file_records(root) != before
        assert (root / "bin/64bit/obs-multi-rtmp.dll").read_bytes() == b"dll 1.1.0"
