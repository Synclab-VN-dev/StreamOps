"""DataRoot contract. Dependency-free so the NVDA package uses this same resolver.

Resolution never creates directories. D4PLANNER_DATA_DIR always names state/.
Explicit roots are intentional standalone/isolation configuration, not a fallback.
"""
from __future__ import annotations

import os
import json
import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Mapping


class StorageError(ValueError):
    pass



def check_owner(path: Path) -> None:
    if sys.platform != "win32":
        if path.stat().st_uid != os.getuid():
            raise StorageError("PATH_INCOMPATIBLE: foreign owner")
        return
    system = os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR")
    if not system:
        raise StorageError("PATH_INCOMPATIBLE: Windows system directory unavailable")
    executable = Path(system) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = Path(__file__).with_name("storage_acl.ps1").read_text(encoding="utf-8")
    result = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-Command", script],
                            env={**os.environ, "D4PLANNER_ACL_PATH": str(path)},
                            capture_output=True, timeout=30, creationflags=0x08000000)
    if result.returncode:
        raise StorageError(f"PATH_INCOMPATIBLE: owner/ACL verification failed: {path}")

def canonical(path: str | Path) -> Path:
    value = path if isinstance(path, Path) else Path(path)
    if not value.is_absolute() or ".." in value.parts:
        raise StorageError(f"PATH_INCOMPATIBLE: absolute non-traversing path required: {value}")
    for part in (value, *value.parents):
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise StorageError(f"PATH_INCOMPATIBLE: linked path: {part}")
    result = value.resolve()
    ancestor = result
    while not ancestor.exists():
        ancestor = ancestor.parent
    if not ancestor.is_dir() or not os.access(ancestor, os.R_OK | os.W_OK | os.X_OK):
        raise StorageError(f"PATH_INCOMPATIBLE: inaccessible directory: {ancestor}")
    if os.name != "nt" and ancestor.stat().st_uid != os.getuid():
        # A new root below a shared temp directory is valid; an existing root
        # owned by somebody else is not.
        if result.exists():
            raise StorageError(f"PATH_INCOMPATIBLE: foreign owner: {result}")
    return result


def resolve_root(explicit: str | Path | None = None, *,
                 registered: str | Path | None = None,
                 environment: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environment is None else environment
    isolated = env.get("D4PLANNER_STORAGE_ISOLATED") == "1"
    if isolated and not env.get("D4PLANNER_DATA_ROOT"):
        raise StorageError("PATH_INCOMPATIBLE: explicit isolated DataRoot required")
    candidates = [v for v in (None if isolated else registered, explicit, env.get("D4PLANNER_DATA_ROOT"),
                              env.get("D4PLANNER_HOME")) if v is not None]
    roots = [canonical(v) for v in candidates]
    if roots and any(root != roots[0] for root in roots):
        raise StorageError("PATH_CONFLICT: DataRoot overrides/registration disagree")
    if env.get("LOCALAPPDATA"):
        local = Path(env["LOCALAPPDATA"])
    elif roots:
        local = None  # Managed children need no independent home-directory lookup.
    elif os.name == "nt":
        raise StorageError("PATH_INCOMPATIBLE: LOCALAPPDATA required for default DataRoot")
    else:
        local = Path.home() / ".local/share"
    root = roots[0] if roots else canonical(local / "StreamOps/D4Planner")
    if (root / ".storage-migrated.json").exists():
        raise StorageError("MIGRATION_REQUIRED: this legacy root was migrated; select the canonical target")
    if root.exists():
        check_owner(root)
    if isolated and registered:
        original = canonical(registered)
        if root.is_relative_to(original) or original.is_relative_to(root):
            raise StorageError("PATH_CONFLICT: isolated DataRoot must be disjoint from registered root")
    for key, expected in (("D4PLANNER_DATA_DIR", root / "state"),
                          ("D4_RULEKIT_DATA_ROOT", root / "rulekit")):
        if key in env and canonical(env[key]) != expected:
            raise StorageError(f"PATH_CONFLICT: {key} does not belong to DataRoot")
    if env.get("D4_LOG_DIR"):
        log = canonical(env["D4_LOG_DIR"])
        if log.parent != root / "logs" or log.name == ".control":
            raise StorageError("PATH_CONFLICT: D4_LOG_DIR does not belong to DataRoot")
    # Never silently present an empty account after changing the default.
    legacy = local / "d4planner" if local is not None else None  # LEGACY inventory only.
    if legacy is not None and (not roots or root == canonical(local / "StreamOps/D4Planner")) and legacy.exists() and any(legacy.iterdir()):
        try:
            receipt = json.loads((root / "private/storage-origin.json").read_text())
            valid = receipt["status"] == "VERIFIED" and canonical(receipt["source"]) == canonical(legacy)
            recorded = {entry["sourcePath"] for entry in receipt["files"]}
            actual = {p.relative_to(legacy).as_posix() for p in legacy.rglob("*") if p.is_file() and p.name not in {".storage-migrated.json", ".storage-migration-active.json"}}
            valid = valid and recorded == actual
            for entry in receipt["files"]:
                relative = Path(entry["sourcePath"])
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("invalid receipt")
                with (legacy / relative).open("rb") as stream:
                    valid = valid and hashlib.file_digest(stream, "sha256").hexdigest() == entry["sourceSha256"]
            if not valid:
                raise ValueError("changed legacy source")
        except (OSError, ValueError, KeyError, TypeError):
            raise StorageError("MIGRATION_REQUIRED: run d4planner storage migrate --help") from None
    if (root / "private/storage-migration.json").exists() or (root / ".storage-migration-active.json").exists():
        raise StorageError("MIGRATION_REQUIRED: unfinished storage migration; recover explicitly")
    return root


def child_environment(root: Path) -> dict[str, str]:
    root = canonical(root)
    return {"D4PLANNER_DATA_ROOT": str(root), "D4PLANNER_HOME": str(root),
            "D4PLANNER_DATA_DIR": str(root / "state"),
            "D4_RULEKIT_DATA_ROOT": str(root / "rulekit")}
