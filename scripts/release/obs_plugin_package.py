"""Build a deterministic Synclab-managed OBS plugin release from local CMake output.

No network, no upstream binary; all version/compatibility metadata is derived
from the checked-out custom plugin source and exact installed file bytes.
Usage:
  python scripts/release/obs_plugin_package.py pack --source-root util/obs-multi-rtmp-websocket --source-commit <40-hex> --output-dir dist/obs-plugin
  python scripts/release/obs_plugin_package.py verify --output-dir dist/obs-plugin
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile

PLUGIN_ID = "obs-multi-rtmp"
NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*\.ini\Z", re.IGNORECASE)
VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+\.\d+\Z")
SHA_PATTERN = re.compile(r"[a-f0-9]{40}\Z")
REQUIRED = {
    "bin/64bit/obs-multi-rtmp.dll": "obs-plugins/64bit/obs-multi-rtmp.dll",
    "bin/64bit/obs-multi-rtmp.pdb": "obs-plugins/64bit/obs-multi-rtmp.pdb",
}
MANIFEST_FILE = f"{PLUGIN_ID}.release.json"
PROVENANCE_FILE = f"{PLUGIN_ID}.provenance.json"
LICENSE_FILE = "LICENSE-GPL-2.0.txt"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_sha256(files: dict[str, bytes]) -> str:
    rows = [
        f"{path}|{len(blob)}|{sha256(blob)}"
        for path, blob in sorted(files.items())
    ]
    return sha256("\n".join(rows).encode("utf-8"))


def _json(path: Path) -> dict:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return parsed


def _source_details(root: Path) -> tuple[str, str]:
    spec = _json(root / "buildspec.json")
    version = spec.get("version")
    obs_dep = spec.get("dependencies", {}).get("obs-studio", {})
    obs_version = obs_dep.get("version")
    if spec.get("name") != PLUGIN_ID or not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise ValueError("Invalid custom plugin name/version in buildspec.json.")
    if obs_version != "32.2.1":
        raise ValueError("Custom plugin must be built against supported OBS 32.2.1.")
    return version, obs_version


def collect_built_files(source_root: Path, configuration: str) -> dict[str, bytes]:
    release = source_root / "release" / configuration / PLUGIN_ID
    if not release.is_dir():
        raise ValueError(f"Custom source CMake install output missing: {release}")
    output: dict[str, bytes] = {}
    for name in REQUIRED:
        source = release / name
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"Required custom-built binary missing: {source}")
        output[name] = source.read_bytes()
        if not output[name]:
            raise ValueError(f"Empty custom-built file: {source}")
    if not output["bin/64bit/obs-multi-rtmp.dll"].startswith(b"MZ"):
        raise ValueError("Custom plugin DLL is not a Windows PE executable.")
    locales = release / "data" / "locale"
    if not locales.is_dir() or locales.is_symlink():
        raise ValueError(f"Built plugin locale directory missing: {locales}")
    for p in sorted(locales.iterdir()):
        if p.is_symlink() or not p.is_file() or not NAME_PATTERN.fullmatch(p.name):
            raise ValueError(f"Unexpected plugin locale payload: {p.name}")
        output["data/locale/" + p.name] = p.read_bytes()
    if "data/locale/en-US.ini" not in output:
        raise ValueError("Required en-US.ini locale missing from custom-built plugin.")
    for p in release.rglob("*"):
        if p.is_symlink():
            raise ValueError(f"Symlink in plugin CMake install output: {p}")
        if p.is_file() and p.relative_to(release).as_posix() not in output:
            raise ValueError(f"Unexpected file in plugin CMake install output: {p}")
    return output


def _zip_path(installed_path: str) -> str:
    if installed_path in REQUIRED:
        return REQUIRED[installed_path]
    if installed_path.startswith("data/locale/"):
        return "data/obs-plugins/obs-multi-rtmp/locale/" + installed_path.removeprefix("data/locale/")
    raise ValueError("Unexpected plugin target path")


def build_package(output_dir: Path, source_root: Path, source_commit: str,
                  configuration: str, *, approved: bool = False) -> dict:
    if not SHA_PATTERN.fullmatch(source_commit):
        raise ValueError("Source commit must be the exact 40-character checkout SHA.")
    version, obs_version = _source_details(source_root)
    files = collect_built_files(source_root, configuration)
    archive = f"{PLUGIN_ID}-{version}-windows-x64.zip"
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_file = output_dir / archive
    with zipfile.ZipFile(archive_file, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9, allowZip64=False) as zf:
        for name, blob in sorted(files.items()):
            # Stable metadata makes the generated archive independent of mtime.
            info = zipfile.ZipInfo(_zip_path(name), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            zf.writestr(info, blob, compress_type=zipfile.ZIP_DEFLATED,
                        compresslevel=9)
    artifact_sha = sha256(archive_file.read_bytes())
    relative_paths = sorted(files)
    metadata = {
        "approved": approved,
        "redistribution_approved": approved,
        "file_count": len(files),
        "relative_paths": relative_paths,
        "tree_sha256": tree_sha256(files),
        "origin": "Synclab-VN-dev/StreamOps/util/obs-multi-rtmp-websocket",
        "configuration": configuration,
    }
    manifest = {
        "plugin_id": PLUGIN_ID,
        "version": version,
        "source_commit": source_commit,
        "platform": "windows",
        "architecture": "x64",
        "obs_version": obs_version,
        "artifact_name": archive,
        "artifact_sha256": artifact_sha,
        "vendor": "sorayuki.multi_rtmp",
        "metadata": metadata,
    }
    (output_dir / MANIFEST_FILE).write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    license_path = source_root / "LICENSE"
    license_text = license_path.read_text(encoding="utf-8")
    if "GNU GENERAL PUBLIC LICENSE" not in license_text:
        raise ValueError("Plugin redistribution requires the upstream GPL license.")
    (output_dir / LICENSE_FILE).write_text(license_text, encoding="utf-8")
    provenance = {
        "source_repository": "Synclab-VN-dev/StreamOps",
        "source_path": "util/obs-multi-rtmp-websocket",
        "source_commit": source_commit,
        "source_url": f"https://github.com/Synclab-VN-dev/StreamOps/tree/{source_commit}/util/obs-multi-rtmp-websocket",
        "plugin_version": version,
        "obs_version": obs_version,
        "configuration": configuration,
        "dll_sha256": sha256(files["bin/64bit/obs-multi-rtmp.dll"]),
        "artifact_name": archive,
        "artifact_sha256": artifact_sha,
        "release_tag": f"{PLUGIN_ID}/v{version}",
        "license": "GPL-2.0",
    }
    (output_dir / PROVENANCE_FILE).write_text(
        json.dumps(provenance, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    verify_package(output_dir, must_approve=approved)
    return manifest


def verify_package(output_dir: Path, *, must_approve: bool = False,
                   expected_version: str | None = None,
                   expected_commit: str | None = None) -> dict:
    manifest = _json(output_dir / MANIFEST_FILE)
    metadata = manifest["metadata"]
    version = manifest["version"]
    artifact_name = manifest["artifact_name"]
    if (manifest["plugin_id"] != PLUGIN_ID or not VERSION_PATTERN.fullmatch(version)
            or manifest["platform"] != "windows" or manifest["architecture"] != "x64"
            or manifest["obs_version"] != "32.2.1"
            or manifest["vendor"] != "sorayuki.multi_rtmp"
            or not SHA_PATTERN.fullmatch(manifest["source_commit"])
            or artifact_name != f"{PLUGIN_ID}-{version}-windows-x64.zip"):
        raise ValueError("Invalid managed package identity/compatibility.")
    if expected_version is not None and version != expected_version:
        raise ValueError("Built version does not match requested version.")
    if expected_commit is not None and manifest["source_commit"] != expected_commit:
        raise ValueError("Built source commit differs from workflow checkout.")
    if must_approve and (metadata.get("approved") is not True or
                         metadata.get("redistribution_approved") is not True):
        raise ValueError("Managed release is not approved for publication.")
    with zipfile.ZipFile(output_dir / artifact_name, "r") as zf:
        members = zf.infolist()
        entries: dict[str, bytes] = {}
        for member in members:
            if member.is_dir():
                raise ValueError("Release ZIP must contain files only.")
            name = member.filename
            path = None
            for target, archive_name in REQUIRED.items():
                if name == archive_name:
                    path = target
            prefix = "data/obs-plugins/obs-multi-rtmp/locale/"
            if path is None and name.startswith(prefix) and NAME_PATTERN.fullmatch(name[len(prefix):]):
                path = "data/locale/" + name[len(prefix):]
            if path is None or path in entries:
                raise ValueError(f"Unexpected/duplicate release ZIP entry: {name}")
            if member.file_size > 64 * 1024 * 1024:
                raise ValueError("Oversized ZIP member.")
            entries[path] = zf.read(member)
    if not set(REQUIRED).issubset(entries) or "data/locale/en-US.ini" not in entries:
        raise ValueError("Required custom plugin payload missing.")
    if len(entries) != metadata["file_count"]:
        raise ValueError("File count differs from release manifest.")
    if sorted(entries) != metadata["relative_paths"]:
        raise ValueError("Unexpected release file paths.")
    if tree_sha256(entries) != metadata["tree_sha256"]:
        raise ValueError("Release tree SHA differs from release manifest.")
    if sha256((output_dir / artifact_name).read_bytes()) != manifest["artifact_sha256"]:
        raise ValueError("ZIP SHA differs from release manifest.")
    provenance = _json(output_dir / PROVENANCE_FILE)
    if (provenance["source_commit"] != manifest["source_commit"]
            or provenance["plugin_version"] != version
            or provenance["artifact_sha256"] != manifest["artifact_sha256"]
            or provenance["dll_sha256"] != sha256(entries["bin/64bit/obs-multi-rtmp.dll"])):
        raise ValueError("Provenance does not match the release bytes.")
    if "GNU GENERAL PUBLIC LICENSE" not in (output_dir / LICENSE_FILE).read_text(encoding="utf-8"):
        raise ValueError("Missing GPL-2.0 redistribution license.")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="action", required=True)
    pack = sub.add_parser("pack")
    pack.add_argument("--source-root", type=Path, required=True)
    pack.add_argument("--output-dir", type=Path, required=True)
    pack.add_argument("--source-commit", required=True)
    pack.add_argument("--configuration", default="RelWithDebInfo")
    pack.add_argument("--release-approved", action="store_true")
    verify = sub.add_parser("verify")
    verify.add_argument("--output-dir", type=Path, required=True)
    verify.add_argument("--require-approved", action="store_true")
    verify.add_argument("--expected-version")
    verify.add_argument("--expected-commit")
    args = ap.parse_args(argv)
    if args.action == "pack":
        record = build_package(args.output_dir, args.source_root, args.source_commit,
                               args.configuration, approved=args.release_approved)
    else:
        record = verify_package(args.output_dir, must_approve=args.require_approved,
                                expected_version=args.expected_version,
                                expected_commit=args.expected_commit)
    print(json.dumps({
        "plugin_id": record["plugin_id"], "version": record["version"],
        "artifact_sha256": record["artifact_sha256"],
        "source_commit": record["source_commit"],
        "approved": record["metadata"]["approved"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
