"""Explicit, conservative storage migration; never invoked at application startup.

Unknown metadata, live writers, WAL and destination conflicts are blocked. Source
bytes are the rollback backup and are never removed. A publish journal blocks
new runtimes until the complete manifest has been verified.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import uuid

from .storage import StorageError, canonical, check_owner
from .store import atomic_write_json

TREES = {"state", "sessions", "runtime", "targets", "rulekit", "logs", "cache"}


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def quiescence() -> None:
    """Fail closed if process/task discovery cannot establish an offline window.

    Conservatively blocks *all* Python/Node/FE/NVDA processes, even unrelated
    ones. The migration's own process is excluded. Never stops a process/task.
    """
    if os.name != "nt":
        raise StorageError("BLOCKED: production migration requires Windows process/task/ACL preflight")
    script = f'''$ErrorActionPreference='Stop'
$names=@('D4Planner.exe','d4planner-fe.exe','nvda.exe','nvda_noUIAccess.exe','node.exe','python.exe','pythonw.exe')
$p=@(Get-CimInstance Win32_Process | Where-Object {{$_.ProcessId -ne {os.getpid()} -and $_.Name -in $names}})
$t=@(Get-ScheduledTask | Where-Object {{$_.TaskName -match 'D4Planner' -and $_.State -ne 'Disabled'}})
if($p.Count -or $t.Count) {{throw 'BUSY: close writers and disable D4Planner tasks explicitly'}}
'''
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, timeout=30, text=True)
    if result.returncode:
        raise StorageError("BUSY: writer/task discovery failed or writers remain")




@contextmanager
def writer_exclusion(paths, *, delete=False):
    """Windows share-read handles deny concurrent write/delete while copying.

    Portable fixture tests use a process probe supplied by their test harness;
    production migration is gated on Windows by quiescence().
    """
    handles = []
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        kernel.SetFileInformationByHandle.restype = wintypes.BOOL
        kernel.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        kernel.ReadFile.restype = wintypes.BOOL
    try:
        for path in paths:
            if os.name == "nt":
                handle = kernel.CreateFileW(str(path), 0x80000000 | (0x10000 if delete else 0), 1, None, 3, 0x80, None)
                if handle == ctypes.c_void_p(-1).value:
                    raise StorageError(f"BUSY: cannot exclude writers: {path}")
                handles.append((path, handle))
        def remove(path):
            if os.name == "nt":
                handle = dict(handles).get(path)
                if handle is None:
                    if path.exists():
                        raise StorageError("BLOCKED: unleased recovery path")
                    return
                disposition = wintypes.BOOL(True)
                if not kernel.SetFileInformationByHandle(handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
                    raise StorageError("BLOCKED: cannot remove leased recovery file")
            else:
                path.unlink(missing_ok=True)
        def digest(path):
            if os.name != "nt":
                return sha(path)
            handle = dict(handles).get(path)
            if handle is None:
                raise StorageError("BLOCKED: unleased recovery path")
            # Read the owned DELETE-capable handle directly. A second CRT open
            # does not share DELETE on Windows and would conflict with our lease.
            result = hashlib.sha256()
            buffer = ctypes.create_string_buffer(65536)
            count = wintypes.DWORD()
            while True:
                if not kernel.ReadFile(handle, buffer, len(buffer), ctypes.byref(count), None):
                    raise StorageError("BLOCKED: cannot hash leased recovery file")
                if not count.value:
                    break
                result.update(buffer.raw[:count.value])
            return result.hexdigest()
        yield remove, digest
    finally:
        for _, handle in handles:
            kernel.CloseHandle(handle)

def database_check(path: Path) -> dict:
    # Refuse WAL rather than lose committed frames or checkpoint the source.
    for suffix in ("-wal", "-journal"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists() and sidecar.stat().st_size:
            raise StorageError(f"BLOCKED: SQLite recovery/checkpoint required: {sidecar}")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            raise StorageError(f"BLOCKED: SQLite integrity: {path}")
        schema = [list(row) for row in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")]
        counts = {}
        for kind, name, _, _ in schema:
            if kind == "table":
                counts[name] = db.execute('SELECT count(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0]
        return {"integrity": "ok", "schema": schema, "rowCounts": counts,
                "userVersion": db.execute("PRAGMA user_version").fetchone()[0]}



def mapped_bytes(path: Path, source: Path, target: Path) -> tuple[bytes | None, list[dict]]:
    relative = path.relative_to(source)
    # Session evidence is historical, immutable, and not a live path consumer.
    if relative.parts[0] in {"sessions", "logs"} or path.suffix.lower() not in {".json", ".jsonl", ".ps1", ".cmd"}:
        return None, []
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    variants = (str(source), str(source).replace(chr(92), chr(92) * 2))
    if not any(v.casefold() in text.casefold() for v in variants):
        return raw, []
    known = {"state/runtime.json": (("sessionDir",),),
             "state/capture.json": (("rawSpeechPath",), ("diagnosticsPath",)),
             "launcher.json": (("equipmentRepository", "path"),)}
    if relative.as_posix() not in known:
        raise StorageError(f"PATH_INCOMPATIBLE: unknown legacy metadata path: {relative}")
    value = json.loads(text)
    rewrites = []
    for keys in known[relative.as_posix()]:
        node = value
        for key in keys[:-1]:
            node = node.get(key, {})
        old = node.get(keys[-1])
        if not isinstance(old, str):
            continue
        old_path = Path(old)
        if not old_path.is_absolute():
            raise StorageError(f"PATH_INCOMPATIBLE: nonabsolute metadata: {relative}")
        if old_path.is_relative_to(source):
            if not old_path.exists():
                raise StorageError(f"PATH_INCOMPATIBLE: missing metadata referent: {old_path}")
            canonical(old_path if old_path.is_dir() else old_path.parent)
            new = str(target / old_path.relative_to(source))
            node[keys[-1]] = new
            rewrites.append({"field": ".".join(keys), "before": old, "after": new})
    mapped = json.dumps(value, ensure_ascii=False, indent=2)
    if any(v.casefold() in mapped.casefold() for v in variants):
        raise StorageError(f"PATH_INCOMPATIBLE: unknown legacy field: {relative}")
    return mapped.encode("utf-8"), rewrites

def inventory(source: Path, target: Path, *, verified=None) -> list[dict]:
    files = []
    for path in sorted(source.rglob("*")):
        canonical(path.parent)
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise StorageError(f"BLOCKED: linked source: {path}")
        if path.is_dir():
            continue
        relative = path.relative_to(source)
        if relative.as_posix() in {".storage-migration-active.json", ".storage-migrated.json"}:
            continue
        if relative.parts[0] not in TREES and relative.as_posix() not in {"launcher.json", "nvdaControllerClient64.dll"}:
            raise StorageError(f"BLOCKED: unclassified source: {relative}")
        if not path.is_file() or path.stat().st_nlink != 1:
            raise StorageError(f"BLOCKED: special/hardlinked source: {relative}")
        if path.name.endswith((".lock", ".lck")) and relative.parts[0] != "logs":
            raise StorageError(f"BLOCKED: lock/log-owner requires subsystem review: {relative}")
        if relative.parent.as_posix() == "runtime/bin" and relative.name in {
            "start-nvda.ps1", "restart-nvda.ps1", "stop-nvda.ps1", "start-d4.ps1", "probe-tolk.ps1"
        }:
            digest = sha(path)
            files.append({"path": relative.as_posix(), "sourcePath": relative.as_posix(),
                          "sourceSha256": digest, "sha256": digest, "bytes": path.stat().st_size,
                          "rewrites": [], "sqlite": None, "action": "SKIP_RUNTIME_GENERATED",
                          "reason": "preserve original; canonical runtime regenerates helper commands"})
            continue
        content, rewrites = mapped_bytes(path, source, target)
        if relative.as_posix() in {"state/runtime.json", "state/capture.json"}:
            value = json.loads(path.read_text())
            if value.get("enabled") or value.get("captureActive") or (relative.name == "runtime.json" and value.get("state") not in {None, "STOPPED"}):
                raise StorageError(f"BUSY: active capture metadata: {relative}")
        mapped = relative
        if relative.parts[0] == "cache":
            mapped = Path("runtime/nvda-controller") / relative
        elif relative.as_posix() == "nvdaControllerClient64.dll":
            mapped = Path("runtime/nvda-controller") / relative
        elif relative.as_posix() == "logs/event-migration.jsonl":
            mapped = Path("state/event-migration.jsonl")
        if any(item["path"] == mapped.as_posix() for item in files):
            raise StorageError(f"CONFLICT: multiple source paths map to {mapped}")
        destination = target / mapped
        canonical(destination.parent)
        if destination.is_symlink():
            raise StorageError(f"BLOCKED: linked destination: {relative}")
        check_owner(path)
        if destination.exists():
            check_owner(destination)
        source_digest = sha(path)
        digest = hashlib.sha256(content).hexdigest() if content is not None else source_digest
        if destination.exists() and (not destination.is_file() or sha(destination) != digest):
            raise StorageError(f"CONFLICT: different destination bytes: {relative}")
        checks = None
        if path.suffix.lower() in {".db", ".sqlite3", ".sqlite"}:
            previous = (verified or {}).get(relative.as_posix())
            if previous is not None and previous["sourceSha256"] == source_digest:
                # Same bytes as the preflight integrity/schema check. Windows
                # SQLite cannot reopen a file under our no-write sharing lease.
                checks = previous["sqlite"]
            else:
                checks = database_check(path)
        files.append({"path": mapped.as_posix(), "sourcePath": relative.as_posix(), "sha256": digest, "sourceSha256": source_digest, "rewrites": rewrites, "bytes": len(content) if content is not None else path.stat().st_size,
                      "action": "SKIP_IDENTICAL" if destination.exists() else "COPY", "sqlite": checks})
    return files



def external_references(source: Path) -> list[dict]:
    references = set()
    override = os.environ.get("D4PLANNER_EQUIPMENT_REPOSITORY_DB")
    if override:
        references.add(override)
    launcher = source / "launcher.json"
    if launcher.exists():
        value = json.loads(launcher.read_text(encoding="utf-8-sig"))
        repository = value.get("equipmentRepository", {})
        if repository.get("enabled"):
            references.add(repository["path"])
    result = []
    for value in sorted(references):
        path = Path(value)
        canonical(path.parent)
        if path.is_relative_to(source):
            continue
        if not path.is_file() or path.is_symlink():
            raise StorageError(f"PATH_INCOMPATIBLE: external repository cannot be verified: {path}")
        result.append({"path": str(path), "ownership": "EXTERNAL_READ_ONLY_PRESERVED",
                       "sha256": sha(path), "sqlite": database_check(path)})
    return result

def plan(source: Path, target: Path, *, _probe=quiescence) -> dict:
    source, target = canonical(source), canonical(target)
    if source == target or source.is_relative_to(target) or target.is_relative_to(source):
        raise StorageError("PATH_CONFLICT: source and destination must be disjoint")
    if not source.is_dir():
        raise StorageError("BLOCKED: source does not exist")
    if (source / ".storage-migration-active.json").exists() or (target / "private/storage-migration.json").exists():
        raise StorageError("BLOCKED: unfinished migration requires recovery")
    completed = source / ".storage-migrated.json"
    if completed.exists() and json.loads(completed.read_text()).get("target") != str(target):
        raise StorageError("PATH_CONFLICT: source already migrated to another root")
    _probe()
    check_owner(source)
    if target.exists():
        check_owner(target)
    files = inventory(source, target)
    ancestor = target
    while not ancestor.exists():
        ancestor = ancestor.parent
    if shutil.disk_usage(ancestor).free < sum(f["bytes"] for f in files) * 2 + 1024 * 1024:
        raise StorageError("BLOCKED: insufficient staging space")
    return {"schema": "d4planner-storage-migration/v1", "id": uuid.uuid4().hex,
            "timestamp": datetime.now(timezone.utc).isoformat(), "status": "PLANNED",
            "source": str(source), "target": str(target), "files": files,
            "backup": str(source), "published": [], "errors": [],
            "externalReferences": external_references(source)}


def verify(report: dict, *, leased=False) -> None:
    source, target = Path(report["source"]), Path(report["target"])
    for item in report["files"]:
        for root in ((source,) if item["action"] == "SKIP_RUNTIME_GENERATED" else (source, target)):
            path = root / (item["sourcePath"] if root == source else item["path"])
            canonical(path.parent)
            expected = item["sourceSha256"] if root == source else item["sha256"]
            if path.is_symlink() or sha(path) != expected:
                raise StorageError(f"BLOCKED: changed bytes: {path}")
            if item["sqlite"] and not leased:
                actual = database_check(path)
                if json.dumps(actual, sort_keys=True) != json.dumps(item["sqlite"], sort_keys=True):
                    raise StorageError(f"BLOCKED: SQLite mismatch: {path}")


def apply(report: dict, *, _probe=quiescence) -> dict:
    source, target = Path(report["source"]), Path(report["target"])
    fresh = plan(source, target, _probe=_probe)
    if fresh["files"] != report["files"] or fresh["externalReferences"] != report["externalReferences"]:
        raise StorageError("BLOCKED: inventory changed since plan")
    files = [source / item["sourcePath"] for item in report["files"]]
    files += [target / item["path"] for item in report["files"] if item["action"] == "SKIP_IDENTICAL"]
    with writer_exclusion(files):
        return _apply_locked(report, _probe=_probe)


def _apply_locked(report: dict, *, _probe=quiescence) -> dict:
    source, target = Path(report["source"]), Path(report["target"])
    verified = {item["sourcePath"]: item for item in report["files"]}
    if inventory(source, target, verified=verified) != report["files"]:
        raise StorageError("BLOCKED: inventory changed before acquiring leases")
    private = canonical(target / "private")
    receipt_path = private / "storage-origin.json"
    if all(item["action"] != "COPY" for item in report["files"]) and receipt_path.exists():
        if receipt_path.is_symlink():
            raise StorageError("BLOCKED: linked migration receipt")
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("status") != "VERIFIED" or receipt.get("source") != str(source):
            raise StorageError("BLOCKED: different migration receipt owner")
        verify(report, leased=True)
        return {**report, "status": "VERIFIED", "noOp": True, "receiptId": receipt["id"]}
    private.mkdir(parents=True, exist_ok=True)
    journal = private / "storage-migration.json"
    # Exclusive creation prevents a second migrator from publishing concurrently.
    with journal.open("x", encoding="utf-8") as stream:
        json.dump(report, stream)
    source_journal = source / ".storage-migration-active.json"
    try:
        with source_journal.open("x", encoding="utf-8") as stream:
            json.dump({"id": report["id"], "target": str(target)}, stream)
    except Exception:
        journal.unlink()
        raise
    staging = private / ("storage-staging-" + report["id"])
    staging.mkdir()
    report["staging"] = str(staging)
    report["status"] = "STAGING"
    atomic_write_json(journal, report)
    try:
        for item in report["files"]:
            if item["action"] != "COPY":
                continue
            staged = staging / item["path"]
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / item["sourcePath"], staged)
            if item["rewrites"]:
                staged.write_bytes(mapped_bytes(source / item["sourcePath"], source, target)[0])
            if sha(staged) != item["sha256"]:
                raise StorageError("BLOCKED: staging hash mismatch")
            if item["sqlite"] and database_check(staged) != item["sqlite"]:
                raise StorageError("BLOCKED: staging SQLite mismatch")
        _probe()
        if inventory(source, target, verified=verified) != report["files"]:
            raise StorageError("BLOCKED: source changed during staging")
        report["status"] = "PUBLISHING"
        atomic_write_json(journal, report)
        for item in report["files"]:
            if item["action"] != "COPY":
                continue
            destination = target / item["path"]
            canonical(destination.parent)
            destination.parent.mkdir(parents=True, exist_ok=True)
            canonical(destination.parent)
            # Checkpoint intent before publication, so interruption is recoverable.
            report["published"].append(item["path"])
            atomic_write_json(journal, report)
            os.link(staging / item["path"], destination)  # atomic no-overwrite
        verify(report, leased=True)
        report["status"] = "VERIFIED"
        atomic_write_json(private / ("storage-migration-" + report["id"] + ".json"), report)
        atomic_write_json(private / "storage-origin.json", report)
        atomic_write_json(source / ".storage-migrated.json", {"id": report["id"], "target": str(target)})
        journal.unlink()
        source_journal.unlink()
        # Retain staging + source for explicit recovery. Never cleanup user data.
        return report
    except Exception as exc:
        report["status"] = "RECOVERY_REQUIRED"
        report["errors"].append(str(exc))
        atomic_write_json(journal, report)
        raise


def rollback(report: dict, *, _probe=quiescence) -> dict:
    if report.get("noOp"):
        return {**report, "status": "ROLLED_BACK"}
    target = canonical(report["target"])
    journal = target / "private/storage-migration.json"
    if not journal.exists():
        journal = target / "private" / ("storage-migration-" + report["id"] + ".json")
    canonical(journal.parent)
    if journal.is_symlink() or not journal.is_file():
        raise StorageError("BLOCKED: recovery requires an owned persisted journal")
    recorded = json.loads(journal.read_text())
    if any(recorded.get(key) != report.get(key) for key in ("id", "source", "target", "files", "published")):
        raise StorageError("BLOCKED: recovery manifest differs from owned journal")
    completed = Path(report["source"]) / ".storage-migrated.json"
    if completed.exists() and json.loads(completed.read_text()).get("id") != report["id"]:
        raise StorageError("BLOCKED: different source migration owner")
    for name in ("storage-origin.json", "storage-migration.json"):
        marker = target / "private" / name
        if marker.exists() and (marker.is_symlink() or json.loads(marker.read_text()).get("id") != report["id"]):
            raise StorageError("BLOCKED: different target migration owner")
    paths = []
    entries = {item["path"]: item for item in report["files"]}
    for relative in report["published"]:
        if Path(relative).is_absolute() or ".." in Path(relative).parts or relative not in entries or entries[relative]["action"] != "COPY":
            raise StorageError("BLOCKED: invalid recovery manifest")
        path = target / relative
        canonical(path.parent)
        if path.exists():
            paths.append(path)
    with writer_exclusion(paths, delete=True) as (remove, digest):
        return _rollback_locked(report, remove, digest, _probe=_probe)


def _rollback_locked(report: dict, remove, digest, *, _probe=quiescence) -> dict:
    _probe()
    target = canonical(report["target"])
    entries = {f["path"]: f for f in report["files"]}
    source_journal = Path(report["source"]) / ".storage-migration-active.json"
    if source_journal.exists():
        marker = json.loads(source_journal.read_text())
        if marker.get("id") != report["id"]:
            raise StorageError("BLOCKED: different source migration owner")

    # Validate every candidate before removing any; never overwrite newer writes.
    for relative in report["published"]:
        path = target / relative
        canonical(path.parent)
        if Path(relative).is_absolute() or ".." in Path(relative).parts or relative not in entries or entries[relative]["action"] != "COPY":
            raise StorageError("BLOCKED: invalid recovery manifest")
        if path.exists() and (path.is_symlink() or digest(path) != entries[relative]["sha256"]):
            raise StorageError("BLOCKED: post-switch writes require manual recovery")
        for suffix in ("-wal", "-journal"):
            if Path(str(path) + suffix).exists():
                raise StorageError("BLOCKED: SQLite sidecar requires manual recovery")
    for relative in report["published"]:
        remove(target / relative)
    source_journal.unlink(missing_ok=True)
    (Path(report["source"]) / ".storage-migrated.json").unlink(missing_ok=True)
    report["status"] = "ROLLED_BACK"
    atomic_write_json(target / "private" / ("storage-migration-" + report["id"] + ".json"), report)
    (target / "private/storage-migration.json").unlink(missing_ok=True)
    (target / "private/storage-origin.json").unlink(missing_ok=True)
    return report


def run_cli(args) -> int:
    report = {"status": "BLOCKED", "action": args.action, "errors": []}
    try:
        if args.action == "dry-run":
            if args.source is None or args.target is None:
                raise StorageError("--source and --target are required")
            source, target = canonical(args.source), canonical(args.target)
        else:
            if args.manifest is None:
                raise StorageError("--manifest is required")
            parsed = json.loads(args.manifest.read_text(encoding="utf-8"))
            if not isinstance(parsed, dict):
                raise StorageError("Migration manifest must be an object")
            report = parsed
            source, target = canonical(report["source"]), canonical(report["target"])
            if report.get("schema") != "d4planner-storage-migration/v1":
                raise StorageError("Unsupported migration manifest")
            if len(report.get("id", "")) != 32 or any(c not in "0123456789abcdef" for c in report["id"]):
                raise StorageError("Invalid migration id")
            for entry in report["files"]:
                relative = Path(entry["path"])
                original = Path(entry["sourcePath"])
                if relative.is_absolute() or ".." in relative.parts or not relative.parts or original.is_absolute() or ".." in original.parts or not original.parts:
                    raise StorageError("Invalid manifest path")
        output = args.report.absolute()
        canonical(output.parent)
        if output.is_relative_to(source) or output.is_relative_to(target) or output.exists():
            raise StorageError("Report must be a new file outside both roots")
        if args.action == "dry-run":
            report.update(source=str(source), target=str(target),
                          timestamp=datetime.now(timezone.utc).isoformat(),
                          inventory=[{"path": str(p.relative_to(source)),
                                      "kind": "link" if p.is_symlink() else "directory" if p.is_dir() else "file"}
                                     for p in source.rglob("*")])
            report = plan(source, target)
        elif args.action == "apply":
            report = apply(report)
        elif args.action == "verify":
            quiescence()
            verify(report)
            report["status"] = "VERIFIED"
        else:
            report = rollback(report)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, subprocess.SubprocessError) as exc:
        report["status"] = "BLOCKED"
        errors = report.get("errors")
        report["errors"] = (errors if isinstance(errors, list) else []) + [str(exc)]
    # Explicit report is the only dry-run write; roots are never changed.
    print(json.dumps(report, indent=2))
    import sys
    print(f"Storage migration: {report['status']}; {len(report.get('files', []))} planned files; "
          f"{len(report.get('errors', []))} errors", file=sys.stderr)
    if 'output' in locals() and not output.exists() and not output.is_relative_to(source) and not output.is_relative_to(target):
        with output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
    return 4 if report["status"] == "BLOCKED" else 0
