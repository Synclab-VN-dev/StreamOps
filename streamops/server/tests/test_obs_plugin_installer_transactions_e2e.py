"""Filesystem-backed lifecycle acceptance: no network, OBS process or real user files."""
from __future__ import annotations

from io import BytesIO
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from streamops.server.platform.windows.obs_plugin.installer import (
    PluginInstallerFailure,
    WindowsObsMultiRtmpInstaller,
    _file_records,
    _tree_digest,
)


@pytest.fixture
def package(tmp_path):
    payload = {
        "obs-plugins/64bit/obs-multi-rtmp.dll": b"plugin-dll-v1",
        "obs-plugins/64bit/obs-multi-rtmp.pdb": b"plugin-symbols-v1",
        "data/obs-plugins/obs-multi-rtmp/locale/en-US.ini": b"[text]\\nlabel=hello\\n",
    }
    target = {
        "obs-plugins/64bit/obs-multi-rtmp.dll": "bin/64bit/obs-multi-rtmp.dll",
        "obs-plugins/64bit/obs-multi-rtmp.pdb": "bin/64bit/obs-multi-rtmp.pdb",
        "data/obs-plugins/obs-multi-rtmp/locale/en-US.ini": "data/locale/en-US.ini",
    }
    artifact = BytesIO()
    with zipfile.ZipFile(artifact, "w") as archive:
        for path, value in payload.items():
            archive.writestr(path, value)
    artifact_bytes = artifact.getvalue()
    expected_root = tmp_path / "expected"
    for src, dest in target.items():
        path = expected_root / dest
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload[src])
    records = _file_records(expected_root)
    manifest = {
        "package_version": "0.7.4.0",
        "expected_obs_version": "32.2.1",
        "artifact_name": "plugin.zip",
        "artifact_url": "https://managed.example.invalid/plugin.zip",
        "artifact_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "file_count": len(records),
        "relative_paths": [r["relative_path"] for r in records],
        "tree_sha256": _tree_digest(records),
    }
    root = tmp_path / "installed"
    appdata = tmp_path / "appdata"
    calls = []
    def downloader(url):
        calls.append(url)
        return BytesIO(artifact_bytes)
    def build(**overrides):
        return WindowsObsMultiRtmpInstaller(
            tmp_path / "state", plugin_root=root, appdata=appdata,
            obs_executable=tmp_path / "obs64.exe",
            manifest={**manifest, **overrides}, downloader=downloader,
            process_probe=lambda: [], version_probe=lambda _: "32.2.1",
        )
    return build, root, appdata, calls, manifest, artifact_bytes


def test_install_writes_exact_files_and_journal_then_rollback_restores_baseline(package):
    build, root, _, calls, manifest, _ = package
    installer = build()
    assert installer.status().installation == "absent"
    assert installer.install().result == "installed"
    assert installer.status().installation == "exact"
    assert installer.install().result == "already_installed"
    assert calls == [manifest["artifact_url"]]
    assert installer.pointer.is_file()
    assert installer.rollback().result == "rolled_back"
    assert _file_records(root) == []


def test_bad_hash_fails_before_any_installed_file_mutation(package):
    build, root, _, _, _, _ = package
    installer = build(artifact_sha256="f" * 64)
    with pytest.raises(PluginInstallerFailure) as caught:
        installer.install()
    assert caught.value.code == "artifact_hash_mismatch"
    assert not root.exists()
    assert not installer.pointer.exists()


def test_bad_tree_manifest_fails_before_install(package):
    build, root, _, _, _, _ = package
    installer = build(tree_sha256="0" * 64)
    with pytest.raises(PluginInstallerFailure) as caught:
        installer.install()
    assert caught.value.code == "artifact_manifest_mismatch"
    assert not root.exists()
    assert not installer.pointer.exists()


def test_incompatible_obs_rejected_without_download(package):
    build, root, _, calls, _, _ = package
    installer = build(expected_obs_version="31.0.0")
    with pytest.raises(PluginInstallerFailure) as caught:
        installer.install()
    assert caught.value.code == "incompatible_obs"
    assert calls == []
    assert not root.exists()


def test_rollback_rejects_modified_dll_without_overwriting_user_changes(package):
    build, root, _, _, _, _ = package
    installer = build()
    installer.install()
    dll = root / "bin" / "64bit" / "obs-multi-rtmp.dll"
    dll.write_bytes(b"modified-by-another-actor")
    with pytest.raises(PluginInstallerFailure) as caught:
        installer.rollback()
    assert caught.value.code == "rollback_conflict"
    assert dll.read_bytes() == b"modified-by-another-actor"


def test_rollback_does_not_delete_nonempty_new_user_config(package):
    build, root, appdata, _, _, _ = package
    installer = build()
    installer.install()
    config = appdata / "obs-studio" / "basic" / "profiles" / "User" / "obs-multi-rtmp.json"
    config.parent.mkdir(parents=True)
    content = b'{"targets":[{"stream_key":"must-preserve"}]}'
    config.write_bytes(content)
    with pytest.raises(PluginInstallerFailure) as caught:
        installer.rollback()
    assert caught.value.code == "config_conflict"
    assert config.read_bytes() == content
    assert installer.status().installation == "exact"


def test_rollback_removes_only_empty_new_plugin_config(package):
    build, _, appdata, _, _, _ = package
    installer = build()
    installer.install()
    config = appdata / "obs-studio" / "basic" / "profiles" / "User" / "obs-multi-rtmp.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"targets": [], "audio_configs": [], "video_configs": []}))
    assert installer.rollback().result == "rolled_back"
    assert not config.exists()


def test_update_same_version_is_rejected_without_false_success(package):
    build, _, _, _, _, _ = package
    installer = build()
    installer.install()
    with pytest.raises(PluginInstallerFailure) as caught:
        installer.update()
    assert caught.value.code == "update_not_available"


def test_install_rejects_unexpected_archive_file_before_mutation(package):
    build, root, _, _, manifest, _ = package
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("unexpected.exe", b"untrusted")
    data = archive.getvalue()
    installer = build(artifact_sha256=hashlib.sha256(data).hexdigest())
    installer.downloader = lambda url: BytesIO(data)
    with pytest.raises(PluginInstallerFailure) as caught:
        installer.install()
    assert caught.value.code == "artifact_invalid"
    assert not root.exists()


def test_rollback_preserves_preexisting_config_byte_for_byte(package):
    build, _, appdata, _, _, _ = package
    config = appdata / "obs-studio" / "basic" / "profiles" / "User" / "obs-multi-rtmp.json"
    config.parent.mkdir(parents=True)
    original = b'{"targets":[{"name":"saved"}]}\\r\\n'
    config.write_bytes(original)
    installer = build()
    installer.install()
    assert installer.rollback().result == "rolled_back"
    assert config.read_bytes() == original


def test_installer_never_downloads_when_existing_tree_conflicts(package):
    build, root, _, calls, _, _ = package
    root.mkdir(parents=True)
    (root / "unknown.dll").write_bytes(b"keep")
    with pytest.raises(PluginInstallerFailure) as caught:
        build().install()
    assert caught.value.code == "adoption_required"
    assert calls == []
    assert (root / "unknown.dll").read_bytes() == b"keep"


def test_rollback_without_transaction_is_typed_and_non_destructive(package):
    build, root, _, _, _, _ = package
    root.mkdir(parents=True)
    original = root / "user.txt"
    original.write_bytes(b"untouched")
    with pytest.raises(PluginInstallerFailure) as caught:
        build().rollback()
    assert caught.value.code == "transaction_missing"
    assert original.read_bytes() == b"untouched"


def test_e2e_update_v1_to_v2_changes_bytes_and_preserves_config(package):
    build, root, appdata, _, manifest, archive_v1 = package
    config = appdata / "obs-studio" / "basic" / "profiles" / "User" / "obs-multi-rtmp.json"
    config.parent.mkdir(parents=True)
    original = b'{"targets":[{"name":"retained"}]}'
    config.write_bytes(original)
    v1 = build()
    assert v1.install().result == "installed"
    old_dll = (root / "bin/64bit/obs-multi-rtmp.dll").read_bytes()
    from io import BytesIO
    replacement = BytesIO()
    with zipfile.ZipFile(BytesIO(archive_v1)) as source, zipfile.ZipFile(replacement, "w") as dest:
        for entry in source.infolist():
            payload = source.read(entry.filename)
            if entry.filename.endswith(".dll"):
                payload = b"plugin-dll-v2"
            dest.writestr(entry.filename, payload)
    new_bytes = replacement.getvalue()
    expected = package[1].parent / "expected-v2"
    for path in (package[1].parent / "expected").rglob("*"):
        if path.is_file():
            destination = expected / path.relative_to(package[1].parent / "expected")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"plugin-dll-v2" if path.name.endswith(".dll") else path.read_bytes())
    next_manifest = dict(manifest)
    next_manifest.update(
        package_version="0.7.5.0",
        artifact_sha256=hashlib.sha256(new_bytes).hexdigest(),
        tree_sha256=_tree_digest(_file_records(expected)),
    )
    v2 = build(**next_manifest)
    v2.downloader = lambda url: BytesIO(new_bytes)
    assert v2.update().result == "updated"
    assert (root / "bin/64bit/obs-multi-rtmp.dll").read_bytes() != old_dll
    assert v2.status().installation == "exact"
    assert config.read_bytes() == original


def test_e2e_update_rollback_restores_v1_bytes(package):
    build, root, _, _, manifest, archive = package
    installer = build()
    installer.install()
    before = _file_records(root)
    from io import BytesIO
    replacement = BytesIO()
    with zipfile.ZipFile(BytesIO(archive)) as source, zipfile.ZipFile(replacement, "w") as dest:
        for entry in source.infolist():
            payload = source.read(entry.filename)
            if entry.filename.endswith(".dll"):
                payload = b"plugin-dll-v2"
            dest.writestr(entry.filename, payload)
    new_bytes = replacement.getvalue()
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as scratch:
        expected = Path(scratch)
        with zipfile.ZipFile(BytesIO(new_bytes)) as content:
            for entry in content.infolist():
                mapped = ("bin/64bit/" + Path(entry.filename).name) if entry.filename.startswith("obs-plugins/") else ("data/locale/" + Path(entry.filename).name)
                dest = expected / mapped
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content.read(entry.filename))
        v2 = build(package_version="0.7.5.0",
                   artifact_sha256=hashlib.sha256(new_bytes).hexdigest(),
                   tree_sha256=_tree_digest(_file_records(expected)))
    v2.downloader = lambda url: BytesIO(new_bytes)
    assert v2.update().result == "updated"
    assert v2.rollback().result == "rolled_back"
    assert _file_records(root) == before
    assert v2.status().installation == "exact"
    assert v2.status().installed_version == "0.7.4.0"


def test_e2e_managed_provider_switch_without_direct_url_download(package):
    build, root, _, calls, _, _ = package
    from streamops.server.services.obs_plugin_release_source import ManagedPluginReleaseSource
    class Provider:
        def latest(self, plugin_id):
            from streamops.server.services.obs_plugin_release_source import PluginRelease
            return PluginRelease(
                plugin_id=plugin_id, version="0.7.4.0", source_commit="abc123",
                platform="windows", architecture="x64", obs_version="32.2.1",
                artifact_name="plugin.zip", artifact_sha256="a" * 64,
                vendor="approved", metadata={},
            )
        def open_artifact(self, release):
            return BytesIO(b"fixture")
    installer = WindowsObsMultiRtmpInstaller(
        package[1].parent / "managed-state", plugin_root=root,
        process_probe=lambda: [], version_probe=lambda _: "32.2.1",
        release_source=ManagedPluginReleaseSource(Provider()),
    )
    assert installer.release_source is not None
    assert calls == []


def test_e2e_provider_artifact_is_consumed_from_approved_source_only(package):
    from streamops.server.services.obs_plugin_release_source import (
        ManagedPluginReleaseSource, PluginRelease,
    )
    build, root, appdata, untrusted_calls, manifest, archive = package

    class Provider:
        def __init__(self):
            self.calls = []
        def latest(self, plugin_id):
            self.calls.append(("latest", plugin_id))
            return PluginRelease(
                plugin_id=plugin_id,
                version=manifest["package_version"],
                source_commit="abcdef1234",
                platform="windows", architecture="x64",
                obs_version=manifest["expected_obs_version"],
                artifact_name=manifest["artifact_name"],
                artifact_sha256=manifest["artifact_sha256"],
                vendor="sorayuki.multi_rtmp",
                metadata={key: manifest[key] for key in
                          ("file_count", "relative_paths", "tree_sha256")},
            )
        def open_artifact(self, release):
            self.calls.append(("open", release.version))
            return BytesIO(archive)

    provider = Provider()
    installer = WindowsObsMultiRtmpInstaller(
        root.parent / "managed-state", plugin_root=root, appdata=appdata,
        process_probe=lambda: [], version_probe=lambda _: "32.2.1",
        release_source=ManagedPluginReleaseSource(provider),
    )
    assert installer.install().result == "installed"
    assert installer.status().installed_version == "0.7.4.0"
    assert provider.calls[:2] == [("latest", "obs-multi-rtmp"), ("open", "0.7.4.0")]
    assert untrusted_calls == []


def test_e2e_post_update_verify_failure_recovers_byte_exact_baseline(package):
    import asyncio
    from streamops.server.errors import ObsPluginError
    from streamops.server.services.obs_plugin import (
        ObsPluginService, PluginHostResult, PluginHostStatus,
    )
    from streamops.server.obs.manager import ObsRuntimeStatus

    build, root, appdata, _, manifest, archive = package
    installer = build()
    installer.install()
    baseline = _file_records(root)
    config = appdata / "obs-studio" / "basic" / "profiles" / "User" / "obs-multi-rtmp.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_bytes(b'{"targets":[{"stream_key":"must-preserve"}]}')
    config_baseline = config.read_bytes()

    # Produce a distinct v2 package and tree manifest.
    updated = BytesIO()
    with zipfile.ZipFile(BytesIO(archive)) as original, zipfile.ZipFile(updated, "w") as target:
        for item in original.infolist():
            data = original.read(item.filename)
            target.writestr(item.filename, b"plugin-dll-v2" if item.filename.endswith(".dll") else data)
    new_bytes = updated.getvalue()
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as scratch:
        expected = Path(scratch)
        with zipfile.ZipFile(BytesIO(new_bytes)) as content:
            for entry in content.infolist():
                path = expected / ("bin/64bit/" + Path(entry.filename).name
                                   if entry.filename.startswith("obs-plugins/")
                                   else "data/locale/" + Path(entry.filename).name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content.read(entry.filename))
        v2 = build(package_version="0.7.5.0",
                   artifact_sha256=hashlib.sha256(new_bytes).hexdigest(),
                   tree_sha256=_tree_digest(_file_records(expected)))
    v2.downloader = lambda url: BytesIO(new_bytes)

    class Manager:
        def __init__(self):
            self.state = "READY"
            self.calls = []
        def status(self):
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
            installed = v2.status()
            return PluginHostStatus(
                "exact", True, True, "0.7.4.0",
                installed_version=installed.installed_version,
                available_version="0.7.5.0",
            )
        def update(self):
            self.calls.append("update")
            return PluginHostResult(v2.update().result)
        def verify(self):
            self.calls.append("verify")
            raise ObsPluginError("plugin_verify_failed", "injected failure", 409)
        def rollback(self):
            self.calls.append("rollback")
            return PluginHostResult(v2.rollback().result)

    manager, host = Manager(), Host()
    with pytest.raises(ObsPluginError) as caught:
        asyncio.run(ObsPluginService(manager, host).update("obs-multi-rtmp"))
    assert caught.value.code == "plugin_verify_failed"
    assert host.calls == ["update", "verify", "rollback"]
    assert manager.state == "READY"
    assert _file_records(root) == baseline
    assert config.read_bytes() == config_baseline


def test_update_rejects_invalid_release_hash_before_touching_v1_or_config(package):
    build, root, appdata, _, _, _ = package
    base = build()
    assert base.install().result == "installed"
    files_before = _file_records(root)
    pointer_before = base.pointer.read_bytes()
    config = appdata / "obs-studio" / "basic" / "profiles" / "User" / "obs-multi-rtmp.json"
    config.parent.mkdir(parents=True)
    config_before = b'{"targets":[{"stream_key":"preserve-secret"}]}'
    config.write_bytes(config_before)
    broken = build(package_version="0.7.5.0", artifact_sha256="f" * 64)
    with pytest.raises(PluginInstallerFailure) as caught:
        broken.update()
    assert caught.value.code == "artifact_hash_mismatch"
    assert _file_records(root) == files_before
    assert config.read_bytes() == config_before
    assert base.pointer.read_bytes() == pointer_before


def test_e2e_v1_to_v2_update_through_service_then_vendor_verify_preserves_config(package, tmp_path):
    """True filesystem transaction + process lifecycle + vendor probe, no OBS hardware."""
    import asyncio
    import shutil

    from streamops.server.obs.manager import ObsRuntimeStatus
    from streamops.server.services.obs_plugin import (
        ObsPluginService, PluginHostResult, PluginHostStatus,
    )

    build, root, appdata, _, manifest, v1_artifact = package
    config = appdata / "obs-studio" / "basic" / "profiles" / "User" / "obs-multi-rtmp.json"
    config.parent.mkdir(parents=True)
    baseline_config = b'{"targets":[{"stream_key":"keep-original"}]}'
    config.write_bytes(baseline_config)
    v1 = build()
    assert v1.install().result == "installed"
    baseline_files = _file_records(root)

    artifact_v2 = BytesIO()
    with zipfile.ZipFile(BytesIO(v1_artifact)) as source, zipfile.ZipFile(artifact_v2, "w") as target:
        for entry in source.infolist():
            data = source.read(entry.filename)
            target.writestr(entry.filename, b"plugin-dll-v2" if entry.filename.endswith(".dll") else data)
    v2_bytes = artifact_v2.getvalue()
    expected_v2 = tmp_path / "expected-v2-e2e"
    shutil.copytree(root, expected_v2)
    (expected_v2 / "bin" / "64bit" / "obs-multi-rtmp.dll").write_bytes(b"plugin-dll-v2")
    v2 = build(
        package_version="0.7.5.0",
        artifact_sha256=hashlib.sha256(v2_bytes).hexdigest(),
        tree_sha256=_tree_digest(_file_records(expected_v2)),
    )
    v2.downloader = lambda _url: BytesIO(v2_bytes)

    class VendorClient:
        def connect(self):
            pass

        def request(self, request_type, payload):
            assert request_type == "CallVendorRequest"
            assert payload == {
                "vendorName": "sorayuki.multi_rtmp",
                "requestType": "list_targets",
                "requestData": {},
            }
            return {"responseData": {"targets": [], "count": 0}}

        def close(self):
            pass

    class Manager:
        def __init__(self):
            self.state = "READY"
            self.calls = []
            self.client_factory = VendorClient

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

    manager = Manager()

    class Host:
        def __init__(self):
            self.loaded_version = "0.7.4.0"
            self.calls = []

        def status(self):
            installed = v2.status()
            return PluginHostStatus(
                installation=installed.installation,
                compatible=installed.compatible,
                loaded=manager.state == "READY",
                loaded_version=self.loaded_version if manager.state == "READY" else None,
                installed_version=installed.installed_version,
                available_version="0.7.5.0",
            )

        def update(self):
            self.calls.append("update")
            result = v2.update()
            self.loaded_version = "0.7.5.0"
            return PluginHostResult(result.result)

        def verify(self):
            self.calls.append("verify")
            return self.status()

        def rollback(self):
            return PluginHostResult(v2.rollback().result)

    host = Host()
    service = ObsPluginService(manager, host, defer_restart=True)
    initial = asyncio.run(service.status("obs-multi-rtmp"))
    assert initial.state == "UPDATE_AVAILABLE"
    assert initial.installed_version == "0.7.4.0"
    assert initial.available_version == "0.7.5.0"

    updated = asyncio.run(service.update("obs-multi-rtmp"))
    assert updated.result == "updated"
    assert updated.previous_version == "0.7.4.0"
    assert updated.status.installed_version == "0.7.5.0"
    assert updated.status.state == "RESTART_REQUIRED"
    assert manager.calls == ["stop"]
    assert config.read_bytes() == baseline_config
    assert _file_records(root) != baseline_files

    manager.start()  # Existing OBS Process API operation.
    assert asyncio.run(service.status("obs-multi-rtmp")).state == "RESTART_REQUIRED"
    verified = asyncio.run(service.verify("obs-multi-rtmp"))
    assert verified.status.state == "VERIFIED"
    assert verified.status.restart_required is False
    assert verified.status.last_verification is not None
    assert manager.calls == ["stop", "start"]
    assert host.calls == ["update", "verify"]
    assert _file_records(root) == _file_records(expected_v2)
    assert config.read_bytes() == baseline_config
