"""Per-user transactional installation engine used by the sole NSIS installer.

Application payloads are immutable version directories. Persistent data lives
outside the installation and is never migrated, copied back or deleted here.
The journal makes activation recoverable after termination or power failure.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release1_delivery as delivery

APP_ID = "vn.synclab.d4planner"
STATE_VERSION = "d4planner-install/v1"


class InstallError(RuntimeError):
    pass


def version(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value):
        raise InstallError("INVALID_RELEASE_VERSION")
    return tuple(map(int, value.split(".")))


def check_owned_layout(root: Path) -> None:
    for name in ("versions", "transactions", ".setup.lock", "active.json", "upgrade-journal.json", "D4Planner.exe"):
        path = root / name
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise InstallError("REPARSE_POINT_IN_APPLICATION_LAYOUT:" + name)


def atomic_json(path: Path, value: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=path.parent,
                                     prefix=path.name+".",suffix=".writing",delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value,stream,ensure_ascii=False,sort_keys=True)
        stream.flush(); os.fsync(stream.fileno())
    try: os.replace(temporary,path)
    finally: temporary.unlink(missing_ok=True)


def read_state(root: Path) -> dict | None:
    path = root / "active.json"
    if not path.exists():
        return None
    state = delivery.load_json(path)
    if state.get("applicationId") != APP_ID or state.get("schemaVersion") != STATE_VERSION:
        raise InstallError("FOREIGN_INSTALLATION")
    owned_payload(root, state)
    version(state["version"])
    return state


def owned_payload(root: Path, state: dict) -> Path:
    relative = str(state.get("payload", ""))
    path = delivery._contained_destination(root, relative)
    if len(Path(relative).parts) != 2 or Path(relative).parts[0] != "versions":
        raise InstallError("INVALID_PAYLOAD_OWNERSHIP")
    return path


def verify_directory(root: Path) -> dict:
    manifest = delivery.load_json(root / "release-manifest.json")
    if manifest.get("applicationId") != APP_ID:
        raise InstallError("PACKAGE_APPLICATION_MISMATCH")
    for entry in manifest["files"]:
        path = delivery._contained_destination(root, entry["path"])
        if (path.is_symlink() or not path.is_file() or path.stat().st_size != entry["bytes"]
                or delivery.sha256_file(path) != entry["sha256"]):
            raise InstallError("INSTALLED_RESOURCE_INTEGRITY:" + entry["path"])
    return manifest


@contextmanager
def install_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    check_owned_layout(root)
    path = root / ".setup.lock"
    with path.open("a+b") as stream:
        stream.seek(0); stream.write(b"0"); stream.flush(); stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise InstallError("ANOTHER_SETUP_IS_RUNNING") from error
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def stop_owned(root: Path) -> None:
    launcher = root / "D4Planner.exe"
    if launcher.is_file():
        completed = subprocess.run([str(launcher), "--stop"], cwd=root, timeout=25, check=False)
        if completed.returncode:
            raise InstallError(f"OWNED_APPLICATION_STOP_FAILED:{completed.returncode}")


def schema_compatible(data: Path, manifest: dict) -> None:
    db = data / "state/hud.sqlite3"
    if not db.exists():
        return
    try:
        with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=2) as connection:
            row = connection.execute("SELECT version FROM schema_meta WHERE component='release1-hud'").fetchone()
    except sqlite3.Error as error:
        raise InstallError("DB_COMPATIBILITY_UNVERIFIED:" + type(error).__name__) from error
    compatibility = manifest.get("hudSchemaCompatibility", {})
    if row is None or not compatibility.get("minimum", 0) <= row[0] <= compatibility.get("maximum", -1):
        raise InstallError("DB_SCHEMA_INCOMPATIBLE")


def begin_transaction(root: Path, previous: dict | None, next_payload: str, *, operation: str = "INSTALL", next_state: dict | None = None) -> Path:
    transaction = root / "transactions" / str(uuid.uuid4())
    transaction.mkdir(parents=True)
    if previous:
        shutil.copyfile(root / "D4Planner.exe", transaction / "D4Planner.previous.exe")
        atomic_json(transaction / "previous.json", previous)
    journal = {"applicationId": APP_ID, "transaction": transaction.relative_to(root).as_posix(),
               "previous": previous, "nextPayload": next_payload, "operation": operation}
    if next_state is not None: journal["nextState"] = next_state
    atomic_json(root / "upgrade-journal.json", journal)
    return transaction


def finish_transaction(root: Path, transaction: Path) -> None:
    # Only files created by this transaction; keep any unknown/user-owned files.
    (root / "upgrade-journal.json").unlink()
    for name in ("D4Planner.previous.exe", "previous.json"):
        (transaction / name).unlink(missing_ok=True)
    try: transaction.rmdir()
    except OSError: pass


def recover(root: Path) -> dict:
    root = root.resolve()
    check_owned_layout(root)
    journal_path = root / "upgrade-journal.json"
    if not journal_path.exists():
        return {"recovery": "NOT_NEEDED"}
    journal = delivery.load_json(journal_path)
    if journal.get("applicationId") != APP_ID:
        raise InstallError("FOREIGN_UPGRADE_JOURNAL")
    old = journal.get("previous")
    # Root launcher backup is stored under a generated, owned transaction path.
    transaction = delivery._contained_destination(root, journal["transaction"])
    if transaction.parent != root / "transactions":
        raise InstallError("INVALID_TRANSACTION_PATH")
    if journal.get("operation") == "ROLLBACK":
        next_state = journal.get("nextState")
        if (not old or not isinstance(next_state, dict) or next_state != old.get("previous")
                or next_state.get("applicationId") != APP_ID or next_state.get("schemaVersion") != STATE_VERSION
                or Path(next_state["dataDir"]).resolve() != Path(old["dataDir"]).resolve()
                or next_state.get("payload") != journal.get("nextPayload")):
            raise InstallError("INVALID_ROLLBACK_JOURNAL")
        if read_state(root) not in (old, next_state):
            raise InstallError("ROLLBACK_STATE_OWNERSHIP_MISMATCH")
        owned_payload(root, next_state)
    if old:
        previous_payload = owned_payload(root, old)
        manifest = verify_directory(previous_payload)
        if manifest.get("version") != old.get("version"):
            raise InstallError("RECOVERY_VERSION_MISMATCH")
        schema_compatible(Path(old["dataDir"]), manifest)
        backup = transaction / "D4Planner.previous.exe"
        if not backup.is_file() or delivery.sha256_file(backup) != delivery.sha256_file(previous_payload / "D4Planner.exe"):
            raise InstallError("RECOVERY_LAUNCHER_INTEGRITY")
        if (not (root / "D4Planner.exe").is_file()
                or delivery.sha256_file(backup) != delivery.sha256_file(root / "D4Planner.exe")):
            shutil.copyfile(backup, root / "D4Planner.recovery.exe")
            os.replace(root / "D4Planner.recovery.exe", root / "D4Planner.exe")
        atomic_json(root / "active.json", old)
    else:
        (root / "active.json").unlink(missing_ok=True)
        (root / "D4Planner.exe").unlink(missing_ok=True)
    (root / "D4Planner.next.exe").unlink(missing_ok=True)
    finish_transaction(root, transaction)
    return {"recovery": "RESTORED_PREVIOUS" if old else "FIRST_INSTALL_REVERTED"}


def static_health(root: Path) -> None:
    subprocess.run([str(root / "D4Planner.exe"), "--installation-health"],
                   cwd=root, check=True, timeout=30)


def runtime_health(root: Path) -> dict:
    # The root launcher owns a kill-on-close Job and a 55s inner deadline.
    # Its probe uses a disposable DataDir, never the installed user's database.
    with tempfile.TemporaryDirectory(prefix="D4Planner-health-report-") as temporary:
        report = Path(temporary) / "health.json"
        subprocess.run([str(root / "D4Planner.exe"), "--runtime-health", "--health-report", str(report)],
                       cwd=root, check=True, timeout=75)
        evidence = delivery.load_json(report)
        if not all(evidence.get(key) is True for key in ("ok", "runtimeReady", "ownedCleanup")):
            raise InstallError("RUNTIME_HEALTH_EVIDENCE_INVALID")
        return evidence


def rulekit_upgrade_preflight(payload: Path, data: Path, previous_payload: Path | None) -> dict:
    """Invoke Rule Kit's decision; packaging never parses a registry/profile."""
    with tempfile.TemporaryDirectory(prefix="D4Planner-rulekit-preflight-") as temporary:
        report = Path(temporary) / "preflight.json"
        command = [str(payload / "runtime/node/node.exe"),
                   str(payload / "utility/d4-rulekit/snapshot-management/manage.js"),
                   "--operation", "upgradePreflight", "--data-root", str(data / "rulekit"),
                   "--installation-root", str(payload), "--report", str(report)]
        if previous_payload is not None:
            command.extend(["--previous-installation-root", str(previous_payload)])
        completed = subprocess.run(command, cwd=payload, check=False, timeout=30)
        evidence = delivery.load_json(report)
        if completed.returncode or evidence.get("ok") is not True or evidence.get("result", {}).get("compatible") is not True:
            raise InstallError("RULEKIT_UPGRADE_PREFLIGHT_REJECTED:" + str(evidence.get("error", {}).get("code", "INVALID_RESULT")))
        return evidence["result"]


def install(package: Path, root: Path, data: Path, expected_sha: str,
            *, health_check=None, checkpoint=None) -> dict:
    root = root.resolve(); data = data.resolve()
    if root == data or root in data.parents or data in root.parents:
        raise InstallError("APP_DATA_DIR_OVERLAP")
    if delivery.sha256_file(package) != expected_sha:
        raise InstallError("PACKAGE_SHA256_MISMATCH")
    manifest = delivery.verify_package(package)
    if manifest.get("applicationId") != APP_ID:
        raise InstallError("PACKAGE_APPLICATION_MISMATCH")
    new_version = version(manifest.get("version", ""))
    schema_compatible(data, manifest)
    with install_lock(root):
        recover(root)
        previous = read_state(root)
        if previous and Path(previous["dataDir"]).resolve() != data:
            raise InstallError("UPGRADE_DATA_DIR_CHANGE_NOT_SUPPORTED")
        if previous and new_version < version(previous["version"]):
            raise InstallError("DOWNGRADE_REJECTED")
        if not previous and any(path.name not in {".setup.lock", "versions", "transactions"} for path in root.iterdir()):
            raise InstallError("INSTALLATION_DIRECTORY_NOT_EMPTY")
        stop_owned(root)
        identifier = str(uuid.uuid4())
        payload_relative = f"versions/{manifest['version']}-{expected_sha[:12]}-{identifier[:8]}"
        destination = root / payload_relative
        destination.mkdir(parents=True)
        # Verification precedes extraction; every destination is checked again.
        with zipfile.ZipFile(package) as archive:
            for relative in archive.namelist():
                target = delivery._contained_destination(destination, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(relative) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        verify_directory(destination)
        (health_check or static_health)(destination)
        if health_check is None and (manifest.get("ruleKit") or {}).get("snapshotManagementContract") == "d4-rulekit-snapshots/v1":
            rulekit_upgrade_preflight(destination, data, owned_payload(root, previous) if previous else None)
        transaction = begin_transaction(root, previous, payload_relative)
        try:
            if checkpoint: checkpoint("JOURNALED")
            shutil.copyfile(destination / "D4Planner.exe", root / "D4Planner.next.exe")
            os.replace(root / "D4Planner.next.exe", root / "D4Planner.exe")
            state = {"schemaVersion":STATE_VERSION, "applicationId":APP_ID,
                     "version":manifest["version"], "payload":payload_relative,
                     "packageSha256":expected_sha, "dataDir":str(data), "previous":previous}
            atomic_json(root / "active.json", state)
            if checkpoint: checkpoint("ACTIVATED")
            health = health_check(root) if health_check else runtime_health(root)
            finish_transaction(root, transaction)
        except Exception:
            recover(root)
            raise
        return {"ok":True, "version":manifest["version"], "installRoot":str(root),
                "dataDir":str(data), "packageSha256":expected_sha, "previousVersion":previous["version"] if previous else None, "runtimeHealth":health}


def rollback(root: Path, *, checkpoint=None) -> dict:
    root = root.resolve()
    with install_lock(root):
        recover(root)
        state = read_state(root)
        if not state or not state.get("previous"):
            raise InstallError("ROLLBACK_NOT_AVAILABLE")
        previous = state["previous"]
        manifest = verify_directory(owned_payload(root, previous))
        schema_compatible(Path(state["dataDir"]), manifest)
        current_manifest = verify_directory(owned_payload(root, state))
        if (manifest.get("version") != previous.get("version")
                or current_manifest.get("version") != state.get("version")
                or previous.get("applicationId") != APP_ID or previous.get("schemaVersion") != STATE_VERSION
                or Path(previous["dataDir"]).resolve() != Path(state["dataDir"]).resolve()):
            raise InstallError("ROLLBACK_STATE_OWNERSHIP_MISMATCH")
        if delivery.sha256_file(root / "D4Planner.exe") != delivery.sha256_file(owned_payload(root, state) / "D4Planner.exe"):
            raise InstallError("ACTIVE_LAUNCHER_INTEGRITY")
        # The previous application's Rule Kit owns compatibility, just as the
        # candidate does during upgrade. Reject before changing launcher/state;
        # never restore an older database or interpret the Registry in packaging.
        if (manifest.get("ruleKit") or {}).get("snapshotManagementContract") == "d4-rulekit-snapshots/v1":
            rulekit_upgrade_preflight(owned_payload(root, previous), Path(state["dataDir"]), owned_payload(root, state))
        stop_owned(root)
        transaction = begin_transaction(root, state, previous["payload"], operation="ROLLBACK", next_state=previous)
        try:
            if checkpoint: checkpoint("JOURNALED")
            shutil.copyfile(owned_payload(root, previous) / "D4Planner.exe", root / "D4Planner.next.exe")
            os.replace(root / "D4Planner.next.exe", root / "D4Planner.exe")
            if checkpoint: checkpoint("LAUNCHER_REPLACED")
            atomic_json(root / "active.json", previous)
            if checkpoint: checkpoint("ACTIVATED")
            finish_transaction(root, transaction)
        except Exception:
            recover(root)
            raise
        return {"ok":True, "rollbackVersion":previous["version"], "dataRestored":False}


def uninstall(root: Path) -> dict:
    root = root.resolve()
    with install_lock(root):
        recover(root)
        state = read_state(root)
        if not state:
            raise InstallError("OWNED_INSTALLATION_REQUIRED")
        stop_owned(root)
        # Remove only manifest-declared application files. Unknown/user files
        # remain, even when placed inside a version directory.
        manifests = list((root / "versions").glob("*/release-manifest.json"))
        for manifest_path in manifests:
            manifest = delivery.load_json(manifest_path)
            if manifest.get("applicationId") != APP_ID:
                continue
            for entry in manifest["files"]:
                path = delivery._contained_destination(manifest_path.parent, entry["path"])
                if path.is_file() and not path.is_symlink(): path.unlink()
            manifest_path.unlink()
            for directory in sorted(manifest_path.parent.rglob("*"), reverse=True):
                if directory.is_dir() and not directory.is_symlink():
                    try: directory.rmdir()
                    except OSError: pass
            try: manifest_path.parent.rmdir()
            except OSError: pass
        (root / "D4Planner.exe").unlink(missing_ok=True)
        (root / "active.json").unlink(missing_ok=True)
        for transaction in (root / "transactions").glob("*"):
            if transaction.is_dir() and not transaction.is_symlink():
                for name in ("D4Planner.previous.exe", "previous.json"):
                    (transaction / name).unlink(missing_ok=True)
                try: transaction.rmdir()
                except OSError: pass
        try: (root / "transactions").rmdir()
        except OSError: pass
        return {"ok":True, "uninstalled":True, "dataPreserved":state["dataDir"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("install", "rollback", "recover", "uninstall"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            if not args.package or not args.data or not args.sha256:
                raise InstallError("INSTALL_INPUTS_REQUIRED")
            result = install(args.package, args.root, args.data, args.sha256)
        elif args.command == "rollback": result = rollback(args.root)
        elif args.command == "uninstall": result = uninstall(args.root)
        else:
            with install_lock(args.root): result = recover(args.root)
        code = 0
    except Exception as error:
        result = {"ok":False, "classification":"INSTALL_FAILURE", "error":str(error)}
        code = 1
    args.report.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.report, result)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
