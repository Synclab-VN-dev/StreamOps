"""Assemble reviewed Windows production inputs into an isolated package stage.

This tool performs no downloads.  Build automation must supply pinned, already
verified runtimes so the resulting release never depends on a global toolchain.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import public_package as public


class StageError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir() or source.is_symlink():
        raise StageError(f"INVALID_TREE:{source}")
    for member in sorted(source.rglob("*")):
        relative = member.relative_to(source)
        if ".bin" in relative.parts or "__pycache__" in relative.parts:
            continue
        target = destination / relative
        if member.is_symlink():
            raise StageError(f"SYMLINK_NOT_ALLOWED:{member}")
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif member.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(member, target)


def copy_public_tree(source: Path, destination: Path) -> None:
    for member in sorted(source.rglob("*")):
        relative = member.relative_to(source)
        if not public.included(relative):
            continue
        if member.is_symlink():
            raise StageError("SYMLINK_NOT_ALLOWED")
        if member.is_file():
            copy_file(member, destination / relative)


def copy_file(source: Path, destination: Path) -> None:
    if not source.is_file() or source.is_symlink():
        raise StageError(f"INVALID_FILE:{source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def assemble(args: argparse.Namespace) -> dict:
    root = args.output.resolve()
    if root.exists():
        raise StageError("OUTPUT_ALREADY_EXISTS")
    root.mkdir(parents=True)
    if getattr(args, "launcher_exe", None):
        copy_file(args.launcher_exe.resolve(), root / "D4Planner.exe")
    copy_file(args.frontend_exe.resolve(), root / "app/d4planner-fe.exe")
    public.validate_tree(args.python_root.resolve(), "runtime/python")
    copy_public_tree(args.python_root.resolve(), root / "runtime/python")
    copy_tree(args.python_site_packages.resolve(), root / "backend/site-packages")
    public.validate_tree(args.node_root.resolve(), "runtime/node")
    copy_public_tree(args.node_root.resolve(), root / "runtime/node")
    public.validate_tree(args.chromium_root.resolve(), "runtime/chromium")
    copy_public_tree(args.chromium_root.resolve(), root / "runtime/chromium")

    repository = Path(__file__).resolve().parents[3]
    # Dependency cache may contain an older editable/project wheel. Always
    # overlay production Backend sources from the exact checked-out revision.
    copy_tree(repository / "utility/d4planner/src/d4planner", root / "backend/site-packages/d4planner")
    copy_tree(repository / "utility/d4planner/contracts",
              root / "utility/d4planner/contracts")
    # Exact reviewed source allowlist; never copy a developer provider tree,
    # captured fixtures, encrypted packages or arbitrary untracked files.
    for relative in public.policy()["sourceAllowlist"]:
        copy_file(repository / relative, root / relative)
    for module in ("browser-infra", "providers/maxroll", "snapshot-management"):
        source = repository / "utility/d4-rulekit" / module / "node_modules"
        public.validate_tree(source, "dependencies/" + module, dependencies=True)
        for member in sorted(source.rglob("*")):
            relative = member.relative_to(source)
            if not public.included(relative) or relative.parts[:2] == ("@streamops", "browser-infrastructure"):
                continue
            if member.is_file():
                copy_file(member, root / "utility/d4-rulekit" / module / "node_modules" / relative)
        # Local package dependency comes from the same reviewed public source,
        # rather than an npm file-dependency cache containing development files.
        if (source / "@streamops/browser-infrastructure").exists():
            for relative in public.policy()["sourceAllowlist"]:
                prefix = "utility/d4-rulekit/browser-infra/"
                if relative.startswith(prefix):
                    copy_file(repository / relative, root / "utility/d4-rulekit" / module / "node_modules/@streamops/browser-infrastructure" / relative[len(prefix):])

    required = [
        root / "app/d4planner-fe.exe", root / "runtime/python/python.exe",
        root / "runtime/node/node.exe",
        root / "runtime/chromium/chrome-win64/chrome.exe",
        root / "utility/d4-rulekit/snapshot-management/manage.js",
        root / "backend/site-packages/d4planner/managed_backend.py",
        root / "backend/site-packages/d4planner/rulekit/worker.js",
        root / "utility/d4-rulekit/providers/maxroll/node_modules/playwright-core/package.json",
    ]
    missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
    if missing:
        raise StageError("MISSING_RUNTIME_FILES:" + ",".join(missing))
    report = {
        "schemaVersion": "d4planner-build-stage/v1",
        "output": str(root),
        "inputs": {
            "frontendSha256": sha256(root / "app/d4planner-fe.exe"),
            "pythonVersion": (root / "runtime/python/python312._pth").read_text(errors="replace").splitlines()[0],
            "nodeSha256": sha256(root / "runtime/node/node.exe"),
            "chromiumSha256": sha256(root / "runtime/chromium/chrome-win64/chrome.exe"),
            "snapshotIncluded": False,
        },
    }
    report["publicInspection"] = public.inspect_directory(root)
    (root / "build-stage.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--launcher-exe", type=Path, required=True)
    for name in ("frontend-exe", "python-root", "python-site-packages", "node-root",
                 "chromium-root", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(assemble(args), sort_keys=True))
        return 0
    except StageError as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
