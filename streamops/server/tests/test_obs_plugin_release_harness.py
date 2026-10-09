"""The release harness must package *custom built* bytes, not an upstream ZIP."""
from __future__ import annotations

import json
from pathlib import Path
import runpy
import zipfile

import pytest


HARNESS = runpy.run_path(
    str(Path(__file__).resolve().parents[3] / "scripts" / "release" / "obs_plugin_package.py")
)


@pytest.fixture()
def harness_source(tmp_path):
    source = tmp_path / "util" / "obs-multi-rtmp-websocket"
    source.mkdir(parents=True)
    (source / "buildspec.json").write_text(json.dumps({
        "name": "obs-multi-rtmp", "version": "0.7.4.3",
        "dependencies": {"obs-studio": {"version": "32.2.1"}}
    }), encoding="utf-8")
    (source / "LICENSE").write_text(
        "GNU GENERAL PUBLIC LICENSE\nVersion 2, June 1991\n", encoding="utf-8"
    )
    root = source / "release" / "RelWithDebInfo" / "obs-multi-rtmp"
    dll = root / "bin" / "64bit" / "obs-multi-rtmp.dll"
    pdb = dll.with_suffix(".pdb")
    locale = root / "data" / "locale" / "en-US.ini"
    dll.parent.mkdir(parents=True, exist_ok=True)
    locale.parent.mkdir(parents=True, exist_ok=True)
    dll.write_bytes(b"MZ CUSTOM SOURCE DLL v0.7.4.3")
    pdb.write_bytes(b"CUSTOM SOURCE PDB v0.7.4.3")
    locale.write_bytes(b"[text]\nTitle=OBS Custom Plugin\n")
    return source, root


def package(tmp_path, harness_source, *, approved=False):
    source, root = harness_source
    output = tmp_path / "artifacts"
    manifest = HARNESS["build_package"](
        output, source, "a" * 40, "RelWithDebInfo", approved=approved
    )
    return manifest, output


def test_harness_deterministic_custom_zip_and_manifest(tmp_path, harness_source):
    manifest, out = package(tmp_path, harness_source)
    assert manifest["version"] == "0.7.4.3"
    assert manifest["source_commit"] == "a" * 40
    assert manifest["obs_version"] == "32.2.1"
    assert manifest["vendor"] == "sorayuki.multi_rtmp"
    assert manifest["metadata"]["approved"] is False
    assert manifest["metadata"]["redistribution_approved"] is False
    assert manifest["metadata"]["file_count"] == 3
    assert HARNESS["verify_package"](out)["artifact_sha256"] == manifest["artifact_sha256"]
    zip_path = out / manifest["artifact_name"]
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert names == [
            "obs-plugins/64bit/obs-multi-rtmp.dll",
            "obs-plugins/64bit/obs-multi-rtmp.pdb",
            "data/obs-plugins/obs-multi-rtmp/locale/en-US.ini",
        ]
        assert zf.read("obs-plugins/64bit/obs-multi-rtmp.dll") == b"MZ CUSTOM SOURCE DLL v0.7.4.3"
    original = zip_path.read_bytes()
    HARNESS["build_package"](
        out, harness_source[0], "a" * 40, "RelWithDebInfo",
    )
    assert zip_path.read_bytes() == original, "Release artifact must be deterministic"
    assert (out / "obs-multi-rtmp.provenance.json").is_file()
    assert (out / "LICENSE-GPL-2.0.txt").is_file()


def test_harness_requires_reviewed_redistribution_before_release(tmp_path, harness_source):
    manifest, out = package(tmp_path, harness_source)
    with pytest.raises(ValueError, match="not approved"):
        HARNESS["verify_package"](out, must_approve=True)
    approved = HARNESS["build_package"](
        out, harness_source[0], "a" * 40, "RelWithDebInfo", approved=True,
    )
    assert approved["metadata"]["approved"] is True
    assert HARNESS["verify_package"](
        out, must_approve=True, expected_version="0.7.4.3",
        expected_commit="a" * 40,
    )["source_commit"] == "a" * 40


def test_harness_rejects_fake_version_and_wrong_obs_dependency(tmp_path, harness_source):
    src, _ = harness_source
    manifest, out = package(tmp_path, harness_source)
    with pytest.raises(ValueError, match="requested version"):
        HARNESS["verify_package"](out, expected_version="0.7.4.4")
    with pytest.raises(ValueError, match="workflow checkout"):
        HARNESS["verify_package"](out, expected_commit="b" * 40)
    spec = json.loads((src / "buildspec.json").read_text())
    spec["dependencies"]["obs-studio"]["version"] = "31.0.0"
    (src / "buildspec.json").write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="supported OBS"):
        HARNESS["build_package"](out, src, "a" * 40, "RelWithDebInfo")
    spec["dependencies"]["obs-studio"]["version"] = "32.2.1"
    (src / "buildspec.json").write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="Source commit"):
        HARNESS["build_package"](out, src, "short", "RelWithDebInfo")


def test_harness_rejects_missing_pdb_locale_and_unexpected_files(tmp_path, harness_source):
    src, root = harness_source
    out = tmp_path / "pkg"
    p = root / "bin" / "64bit" / "obs-multi-rtmp.pdb"
    p.unlink()
    with pytest.raises(ValueError, match="Required custom-built binary"):
        HARNESS["build_package"](out, src, "a" * 40, "RelWithDebInfo")
    p.write_bytes(b"symbols")
    l = root / "data" / "locale" / "en-US.ini"
    l.unlink()
    with pytest.raises(ValueError, match="en-US.ini"):
        HARNESS["build_package"](out, src, "a" * 40, "RelWithDebInfo")
    l.write_bytes(b"text")
    extra = root / "config.json"
    extra.write_bytes(b"unapproved")
    with pytest.raises(ValueError, match="Unexpected file"):
        HARNESS["build_package"](out, src, "a" * 40, "RelWithDebInfo")


def test_harness_detects_modified_zip_manifest_and_provenance(tmp_path, harness_source):
    manifest, out = package(tmp_path, harness_source, approved=True)
    z = out / manifest["artifact_name"]
    z.write_bytes(z.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="ZIP SHA"):
        HARNESS["verify_package"](out, must_approve=True)
    HARNESS["build_package"](out, harness_source[0], "a" * 40, "RelWithDebInfo", approved=True)
    f = out / "obs-multi-rtmp.release.json"
    md = json.loads(f.read_text())
    md["metadata"]["tree_sha256"] = "0" * 64
    f.write_text(json.dumps(md))
    with pytest.raises(ValueError, match="tree SHA"):
        HARNESS["verify_package"](out)
    HARNESS["build_package"](out, harness_source[0], "a" * 40, "RelWithDebInfo", approved=True)
    proof = out / "obs-multi-rtmp.provenance.json"
    obj = json.loads(proof.read_text())
    obj["dll_sha256"] = "f" * 64
    proof.write_text(json.dumps(obj))
    with pytest.raises(ValueError, match="Provenance"):
        HARNESS["verify_package"](out)



def test_harness_generated_zip_is_accepted_by_windows_plugin_installer(tmp_path, harness_source):
    """End-to-end package format agreement: CMake tree → manifest/ZIP → real installer."""
    import shutil

    from streamops.server.platform.windows.obs_plugin.installer import (
        WindowsObsMultiRtmpInstaller, _file_records,
    )
    from streamops.server.services.obs_plugin_release_source import (
        DirectoryPluginReleaseSource, ManagedPluginReleaseSource,
    )

    manifest, out = package(tmp_path, harness_source, approved=True)
    repo_root = tmp_path / "managed" / "obs-multi-rtmp"
    repo_root.mkdir(parents=True)
    shutil.copy2(out / "obs-multi-rtmp.release.json", repo_root / "release.json")
    shutil.copy2(out / manifest["artifact_name"], repo_root / manifest["artifact_name"])
    provider = ManagedPluginReleaseSource(DirectoryPluginReleaseSource(repo_root.parent))
    destination = tmp_path / "installed-plugin"
    installer = WindowsObsMultiRtmpInstaller(
        tmp_path / "state", plugin_root=destination, appdata=tmp_path / "appdata",
        obs_executable=tmp_path / "obs64.exe", release_source=provider,
        process_probe=lambda: [], version_probe=lambda _: "32.2.1",
    )
    assert installer.install().result == "installed"
    assert installer.status().installed_version == "0.7.4.3"
    actual_records = _file_records(destination)
    assert len(actual_records) == 3
    assert (destination / "bin" / "64bit" / "obs-multi-rtmp.dll").read_bytes().startswith(b"MZ CUSTOM")
    assert installer.rollback().result == "rolled_back"
    assert not _file_records(destination)
