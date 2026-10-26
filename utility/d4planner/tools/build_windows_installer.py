"""Build the single custom NSIS Setup around a verified production ZIP.

Tauri's default NSIS upgrade removes resources in place. This custom template
delegates payload activation to windows_install.py instead, retaining one
installer/registration/uninstaller and the existing FE lifecycle unchanged.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release1_delivery as delivery
from windows_install import APP_ID, version


def build(package: Path, python_root: Path, output: Path, makensis: Path) -> dict:
    manifest = delivery.verify_package(package)
    if manifest.get("applicationId") != APP_ID:
        raise ValueError("PACKAGE_APPLICATION_MISMATCH")
    version(manifest["version"])
    if not (python_root / "python.exe").is_file():
        raise ValueError("PRIVATE_PYTHON_REQUIRED")
    output.mkdir(parents=True, exist_ok=True)
    maintenance = output / "maintenance-delete.nsh"
    files = [(path.relative_to(python_root).as_posix(), path) for path in python_root.rglob("*") if path.is_file()]
    if any(path.is_symlink() for _, path in files): raise ValueError("SYMLINK_RUNTIME")
    deletes = ['Delete "$INSTDIR\\maintenance\\windows_install.py"', 'Delete "$INSTDIR\\maintenance\\release1_delivery.py"']
    deletes += ['Delete "$INSTDIR\\maintenance\\python\\' + relative.replace('/', '\\') + '"' for relative, _ in files]
    directories = {"maintenance", "maintenance/python"}
    for relative, _ in files:
        directories.update("maintenance/python/" + str(parent).replace("\\", "/") for parent in Path(relative).parents if str(parent) != ".")
    deletes += ['RMDir "$INSTDIR\\' + name.replace('/', '\\') + '"' for name in sorted(directories, key=lambda item: (-item.count('/'), item))]
    maintenance.write_text("\n".join(deletes) + "\n", encoding="utf-8")
    repository = Path(__file__).resolve().parents[3]
    installer = output / f"D4Planner-Setup-{manifest['version']}.exe"
    arguments = [str(makensis), "-V2"]
    for key, value in {
        "VERSION": manifest["version"], "OUTPUT": installer.resolve(),
        "PACKAGE": package.resolve(), "PACKAGE_SHA256": delivery.sha256_file(package),
        "PYTHON_ROOT": python_root.resolve(), "ENGINE": Path(__file__).with_name("windows_install.py").resolve(),
        "DELIVERY": Path(delivery.__file__).resolve(), "MAINTENANCE_DELETE": maintenance.resolve(),
    }.items(): arguments.append(f"-D{key}={value}")
    arguments.append(str(repository / "utility/d4planner/release1/installer.nsi"))
    subprocess.run(arguments, check=True, timeout=600)
    result = {"schemaVersion":"d4planner-setup-build/v1", "version":manifest["version"],
              "artifact":str(installer), "sha256":delivery.sha256_file(installer),
              "bytes":installer.stat().st_size, "packageSha256":delivery.sha256_file(package),
              "sourceHead":subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()}
    (output / "setup-build.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("package", "python-root", "output", "makensis"): parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.package, args.python_root, args.output, args.makensis), sort_keys=True))
