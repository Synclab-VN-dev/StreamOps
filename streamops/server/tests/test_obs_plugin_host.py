from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from importlib import resources
import io
import json
from pathlib import Path
import zipfile

import pytest

from streamops.server.errors import ObsPluginError
from streamops.server.platform.windows.obs_plugin import (
    PluginInstallerFailure,
    WindowsObsMultiRtmpHost,
    WindowsObsMultiRtmpInstaller,
)
from streamops.server.platform.windows.obs_plugin.installer import (
    ProcessEvidence,
    _tree_digest,
    _version_from_fixed_info,
)


FILES = {
    "bin/64bit/obs-multi-rtmp.dll": b"pinned dll",
    "bin/64bit/obs-multi-rtmp.pdb": b"pinned symbols",
    "data/locale/en-US.ini": b"locale",
}
ZIP_MAP = {
    "obs-plugins/64bit/obs-multi-rtmp.dll": "bin/64bit/obs-multi-rtmp.dll",
    "obs-plugins/64bit/obs-multi-rtmp.pdb": "bin/64bit/obs-multi-rtmp.pdb",
    "data/obs-plugins/obs-multi-rtmp/locale/en-US.ini": "data/locale/en-US.ini",
}


def make_installer(tmp_path: Path, *, bad_hash: bool = False, extra_entry: str | None = None):
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry, target in ZIP_MAP.items():
            archive.writestr(entry, FILES[target])
        if extra_entry:
            archive.writestr(extra_entry, b"unexpected")
    archive_bytes = archive_buffer.getvalue()
    records = [
        {"relative_path": name, "length": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in FILES.items()
    ]
    manifest = {
        "plugin_id": "obs-multi-rtmp",
        "package_version": "0.7.4.0",
        "expected_obs_version": "32.2.1",
        "artifact_name": "pinned.zip",
        "artifact_url": "https://upstream.invalid/pinned.zip",
        "artifact_sha256": "0" * 64 if bad_hash else hashlib.sha256(archive_bytes).hexdigest(),
        "file_count": len(records),
        "tree_sha256": _tree_digest(records),
        "relative_paths": sorted(FILES),
    }
    exe = tmp_path / "obs64.exe"
    exe.touch()
    evidence: list[ProcessEvidence] = []
    installer = WindowsObsMultiRtmpInstaller(
        tmp_path / "state",
        plugin_root=tmp_path / "ProgramData" / "obs-studio" / "plugins" / "obs-multi-rtmp",
        obs_executable=exe,
        manifest=manifest,
        downloader=lambda _url: io.BytesIO(archive_bytes),
        process_probe=lambda: evidence.copy(),
        version_probe=lambda _path: "32.2.1",
        appdata=tmp_path / "AppData",
    )
    return installer, evidence, archive_bytes


def test_manifest_is_loaded_from_package_resource():
    resource = resources.files("streamops.server.platform.windows.obs_plugin").joinpath("manifest.json")
    manifest = json.loads(resource.read_text(encoding="utf-8"))
    assert manifest["release_tag"] == "0.7.4.3"
    assert manifest["package_version"] == "0.7.4.0"
    assert manifest["file_count"] == 73


def test_obs_file_version_falls_back_when_product_version_is_unset():
    fixed = [0, 0, 0x00200002, 0x00010000, 0, 0] + [0] * 7
    assert _version_from_fixed_info(fixed) == "32.2.1"


def test_obs_file_version_prefers_product_version():
    fixed = [0, 0, 0x00200001, 0, 0x00200002, 0x00010000] + [0] * 7
    assert _version_from_fixed_info(fixed) == "32.2.1"


def test_install_is_exact_and_idempotent_even_with_obs_running(tmp_path):
    installer, evidence, _ = make_installer(tmp_path)
    assert installer.status().installation == "absent"
    assert installer.install().result == "installed"
    assert installer.status().installation == "exact"
    evidence.append(ProcessEvidence(123, installer.obs_executable, datetime.now(timezone.utc)))
    assert installer.install().result == "already_installed"


def test_rollback_then_fresh_install_repeats(tmp_path):
    installer, _, _ = make_installer(tmp_path)
    assert installer.install().result == "installed"
    assert installer.rollback().result == "rolled_back"
    assert installer.status().installation == "absent"
    assert installer.install().result == "installed"


def test_verify_requires_running_process_and_load_evidence(tmp_path):
    installer, evidence, _ = make_installer(tmp_path)
    installer.install()
    with pytest.raises(PluginInstallerFailure, match="not running"):
        installer.verify()
    evidence.append(ProcessEvidence(123, installer.obs_executable, datetime.now(timezone.utc)))
    with pytest.raises(PluginInstallerFailure, match="load evidence"):
        installer.verify()
    logs = installer.appdata / "obs-studio" / "logs"
    logs.mkdir(parents=True)
    (logs / "current.txt").write_text(
        "[obs-multi-rtmp] version: 0.7.4.0\n  C:/ProgramData/obs-studio/plugins/obs-multi-rtmp/bin/64bit/obs-multi-rtmp.dll",
        encoding="utf-8",
    )
    assert installer.verify().loaded is True


@pytest.mark.parametrize("bad_hash,extra_entry", [(True, None), (False, "unexpected/payload.bin")])
def test_artifact_hash_or_allowlist_mismatch_fails_closed(tmp_path, bad_hash, extra_entry):
    installer, _, _ = make_installer(tmp_path, bad_hash=bad_hash, extra_entry=extra_entry)
    with pytest.raises(PluginInstallerFailure):
        installer.install()
    assert installer.status().installation == "absent"


def test_rollback_refuses_modified_or_unmanaged_files(tmp_path):
    installer, _, _ = make_installer(tmp_path)
    installer.install()
    (installer.plugin_root / "unmanaged.txt").write_text("do not remove", encoding="utf-8")
    with pytest.raises(PluginInstallerFailure) as failure:
        installer.rollback()
    assert failure.value.code == "rollback_conflict"


@pytest.mark.parametrize(
    ("installer_error", "api_code", "http_status"),
    [
        (PermissionError("private path"), "plugin_install_permission_denied", 403),
        (PluginInstallerFailure("rollback_conflict"), "plugin_state_conflict", 409),
    ],
)
def test_host_maps_safe_typed_errors(tmp_path, installer_error, api_code, http_status):
    class FailingInstaller:
        def status(self):
            raise installer_error

        def rollback(self):
            raise installer_error

    host = WindowsObsMultiRtmpHost(tmp_path)
    host.installer = FailingInstaller()
    with pytest.raises(ObsPluginError) as failure:
        host.status()
    assert failure.value.code == "plugin_status_failed"

    with pytest.raises(ObsPluginError) as failure:
        host.rollback()
    assert failure.value.code == api_code
    assert failure.value.status_code == http_status
    assert "private path" not in str(failure.value)
