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
        return {"vendorResponseData": {"targets": []}}
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
    release = managed(http).latest(PLUGIN)
    assert release.version == "1.2.0"
    with managed(http).open_artifact(release) as data:
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
