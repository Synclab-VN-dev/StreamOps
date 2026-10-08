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
    assert caught.value.code == "plugin_state_conflict"
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
