from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import threading
import zipfile

import pytest

from streamops.server.app import create_app
from streamops.server.errors import ObsPluginError
from streamops.server.obs.manager import ObsRuntimeStatus
from streamops.server.platform.windows.obs_plugin.installer import (
    PluginInstallerFailure,
    ProcessEvidence,
    WindowsObsMultiRtmpInstaller,
    _file_records,
    _tree_digest,
)
from streamops.server.services.obs_plugin import (
    ObsPluginOperationResult,
    ObsPluginService,
    ObsPluginStatus,
    PluginHostResult,
    PluginHostStatus,
)
from streamops.server.services.obs_plugin_release_source import PluginRelease


APPROVED_FILES = {
    "bin/64bit/obs-multi-rtmp.dll": b"approved-dll-v1",
    "bin/64bit/obs-multi-rtmp.pdb": b"approved-pdb-v1",
    "data/locale/en-US.ini": b"approved-locale",
}


def _archive(files: dict[str, bytes]) -> bytes:
    mapping = {
        "bin/64bit/obs-multi-rtmp.dll": "obs-plugins/64bit/obs-multi-rtmp.dll",
        "bin/64bit/obs-multi-rtmp.pdb": "obs-plugins/64bit/obs-multi-rtmp.pdb",
        "data/locale/en-US.ini": "data/obs-plugins/obs-multi-rtmp/locale/en-US.ini",
    }
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as package:
        for target, payload in files.items():
            package.writestr(mapping[target], payload)
    return output.getvalue()


def _records(files: dict[str, bytes]) -> list[dict[str, object]]:
    return sorted([
        {"relative_path": path, "length": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        for path, payload in files.items()
    ], key=lambda item: str(item["relative_path"]))


def _write_tree(root: Path, files: dict[str, bytes]) -> None:
    for relative, payload in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def _installer(tmp_path: Path, *, legacy: dict[str, bytes] | None = None, running: bool = False):
    archive = _archive(APPROVED_FILES)
    records = _records(APPROVED_FILES)
    plugin_root = tmp_path / "plugin"
    if legacy is not None:
        _write_tree(plugin_root, legacy)
    appdata = tmp_path / "appdata"
    config = appdata / "obs-studio/basic/profiles/User/obs-multi-rtmp.json"
    config.parent.mkdir(parents=True)
    config.write_bytes(b'{"targets":[{"stream_key":"fixture-secret"}]}')
    exe = tmp_path / "obs64.exe"
    exe.touch()
    processes = [ProcessEvidence(10, exe, datetime.now(timezone.utc))] if running else []
    manifest = {
        "plugin_id": "obs-multi-rtmp",
        "package_version": "1.0.0",
        "expected_obs_version": "32.2.1",
        "artifact_name": "approved.zip",
        "artifact_url": "https://managed.invalid/approved.zip",
        "artifact_sha256": hashlib.sha256(archive).hexdigest(),
        "file_count": len(records),
        "relative_paths": sorted(APPROVED_FILES),
        "tree_sha256": _tree_digest(records),
    }
    installer = WindowsObsMultiRtmpInstaller(
        tmp_path / "state", plugin_root=plugin_root, obs_executable=exe,
        manifest=manifest, downloader=lambda _url: BytesIO(archive),
        process_probe=lambda: list(processes), version_probe=lambda _path: "32.2.1",
        appdata=appdata,
    )
    return installer, config, processes


def _runtime(state="STOPPED", *, streaming=False, recording=False):
    return ObsRuntimeStatus(
        state=state, process={},
        websocket={"connected": state == "READY", "obs_version": "32.2.1"},
        output={"streaming": streaming, "recording": recording}, last_operation=None,
    )


class _Manager:
    def __init__(self, value=None):
        self.value = value or _runtime()
        self.calls: list[str] = []

    def status(self):
        return self.value

    def stop(self):
        self.calls.append("stop")
        self.value = _runtime("STOPPED")
        return self.value

    def start(self):
        self.calls.append("start")
        self.value = _runtime("READY")
        return self.value


class _Host:
    def __init__(self, installer: WindowsObsMultiRtmpInstaller):
        self.installer = installer
        self.calls: list[str] = []

    def status(self):
        return self.installer.status()

    def adopt(self):
        self.calls.append("adopt")
        return PluginHostResult(self.installer.adopt().result)

    def install(self):
        self.calls.append("install")
        return PluginHostResult(self.installer.install().result)

    def update(self):
        self.calls.append("update")
        return PluginHostResult(self.installer.update().result)

    def rollback(self):
        self.calls.append("rollback")
        return PluginHostResult(self.installer.rollback().result)

    def verify(self):
        self.calls.append("verify")
        value = self.installer.status()
        return replace(value, loaded=True, loaded_version=value.installed_version)


def test_ad01_detects_legacy_tree_without_journal(tmp_path):
    installer, _, _ = _installer(tmp_path, legacy=APPROVED_FILES)
    assert installer.status().installation == "unmanaged"


def test_ad02_adopt_creates_verified_snapshot_and_legacy_journal(tmp_path):
    legacy = {**APPROVED_FILES, "bin/64bit/obs-multi-rtmp.dll": b"legacy"}
    installer, config, _ = _installer(tmp_path, legacy=legacy)
    assert installer.adopt().result == "adopted"
    root, journal = installer._read_current_transaction()
    assert journal["state"] == "legacy_adopted"
    assert journal["installed_version"] is None
    assert journal.get("source_commit") is None
    assert journal["backup_verified"] is True
    assert _file_records(root / "backup/obs-multi-rtmp") == _file_records(installer.plugin_root)
    assert journal["baseline_plugin_configs"][0]["sha256"] == hashlib.sha256(config.read_bytes()).hexdigest()


def test_ad03_second_adopt_is_idempotent(tmp_path):
    installer, _, _ = _installer(tmp_path, legacy=APPROVED_FILES)
    installer.adopt()
    pointer = installer.pointer.read_bytes()
    count = len(list(installer.transactions_root.iterdir()))
    assert installer.adopt().result == "already_adopted"
    assert installer.pointer.read_bytes() == pointer
    assert len(list(installer.transactions_root.iterdir())) == count


def test_ad04_exact_approved_legacy_is_not_rewritten(tmp_path):
    installer, _, _ = _installer(tmp_path, legacy=APPROVED_FILES)
    installer.adopt()
    dll = installer.plugin_root / "bin/64bit/obs-multi-rtmp.dll"
    before = (dll.read_bytes(), dll.stat().st_mtime_ns)
    assert installer.install().result == "installed"
    assert (dll.read_bytes(), dll.stat().st_mtime_ns) == before
    _, journal = installer._read_current_transaction()
    assert journal["state"] == "approved_release_installed"
    assert journal["previous_transaction_id"] is not None


def test_ad05_mismatched_legacy_remains_unchanged_until_install(tmp_path):
    legacy = {**APPROVED_FILES, "bin/64bit/obs-multi-rtmp.dll": b"legacy-mismatch"}
    installer, _, _ = _installer(tmp_path, legacy=legacy)
    before = _file_records(installer.plugin_root)
    installer.adopt()
    assert _file_records(installer.plugin_root) == before
    installer.install()
    assert _file_records(installer.plugin_root) == _records(APPROVED_FILES)


def test_ad06_corrupt_backup_fails_without_changing_legacy(tmp_path, monkeypatch):
    legacy = {**APPROVED_FILES, "bin/64bit/obs-multi-rtmp.dll": b"legacy"}
    installer, _, _ = _installer(tmp_path, legacy=legacy)
    before = _file_records(installer.plugin_root)
    original = installer._snapshot_and_verify

    def corrupt(transaction_root, transaction, records):
        original(transaction_root, transaction, records)
        (transaction_root / "backup/obs-multi-rtmp/bin/64bit/obs-multi-rtmp.dll").write_bytes(b"corrupt")
        raise PluginInstallerFailure("backup_invalid", "injected backup corruption")

    monkeypatch.setattr(installer, "_snapshot_and_verify", corrupt)
    with pytest.raises(PluginInstallerFailure) as error:
        installer.adopt()
    assert error.value.code == "backup_invalid"
    assert _file_records(installer.plugin_root) == before
    assert not installer.pointer.exists()


def test_ad06_missing_config_backup_blocks_recovery_without_overwrite(tmp_path):
    legacy = {**APPROVED_FILES, "bin/64bit/obs-multi-rtmp.dll": b"legacy"}
    installer, config, _ = _installer(tmp_path, legacy=legacy)
    installer.adopt()
    installer.install()
    root, _ = installer._read_current_transaction()
    (root / "backup/configs/0000.bin").unlink()
    approved_before = _file_records(installer.plugin_root)
    config_before = config.read_bytes()
    with pytest.raises(PluginInstallerFailure) as error:
        installer.rollback()
    assert error.value.code == "backup_invalid"
    assert _file_records(installer.plugin_root) == approved_before
    assert config.read_bytes() == config_before


@pytest.mark.parametrize("streaming,recording,code", [
    (True, False, "obs_busy_streaming"), (False, True, "obs_busy_recording"),
])
def test_ad07_active_outputs_reject_adopt(streaming, recording, code):
    class Host:
        calls: list[str] = []
        def status(self):
            return PluginHostStatus("unmanaged", True, False)
        def adopt(self):
            self.calls.append("adopt")
            return PluginHostResult("adopted")
    host = Host()
    with pytest.raises(ObsPluginError) as error:
        asyncio.run(ObsPluginService(_Manager(_runtime("READY", streaming=streaming, recording=recording)), host).adopt("obs-multi-rtmp"))
    assert error.value.code == code
    assert host.calls == []


def test_ad08_installer_rejects_adopt_while_obs_holds_dll(tmp_path):
    installer, _, _ = _installer(tmp_path, legacy=APPROVED_FILES, running=True)
    with pytest.raises(PluginInstallerFailure) as error:
        installer.adopt()
    assert error.value.code == "obs_running"
    assert not installer.state_root.exists()


def test_ad09_legacy_to_approved_creates_real_transaction_chain(tmp_path):
    legacy = {**APPROVED_FILES, "bin/64bit/obs-multi-rtmp.dll": b"legacy"}
    installer, config, _ = _installer(tmp_path, legacy=legacy)
    config_before = config.read_bytes()
    installer.adopt()
    _, adopted = installer._read_current_transaction()
    installer.install()
    _, approved = installer._read_current_transaction()
    assert approved["previous_transaction_id"] == adopted["transaction_id"]
    assert approved["state"] == "approved_release_installed"
    assert config.read_bytes() == config_before


def test_ad09_service_stops_obs_before_legacy_to_approved_install(tmp_path):
    legacy = {**APPROVED_FILES, "bin/64bit/obs-multi-rtmp.dll": b"legacy"}
    installer, _, _ = _installer(tmp_path, legacy=legacy)
    installer.adopt()
    host, manager = _Host(installer), _Manager(_runtime("READY"))
    result = asyncio.run(ObsPluginService(manager, host).install("obs-multi-rtmp"))
    assert result.result == "installed"
    assert manager.calls == ["stop", "start"]
    assert installer.status().installation == "exact"


def test_ad10_verify_failure_restores_legacy_byte_for_byte(tmp_path):
    legacy = {**APPROVED_FILES, "bin/64bit/obs-multi-rtmp.dll": b"legacy"}
    installer, config, _ = _installer(tmp_path, legacy=legacy)
    before, config_before = _file_records(installer.plugin_root), config.read_bytes()
    installer.adopt()
    host, manager = _Host(installer), _Manager(_runtime("READY"))
    service = ObsPluginService(manager, host, defer_restart=True)
    asyncio.run(service.install("obs-multi-rtmp"))
    manager.value = _runtime("READY")
    host.verify = lambda: (_ for _ in ()).throw(ObsPluginError("plugin_verify_failed", "safe", 409))
    with pytest.raises(ObsPluginError):
        asyncio.run(service.verify("obs-multi-rtmp"))
    assert _file_records(installer.plugin_root) == before
    assert config.read_bytes() == config_before
    assert installer.status().installation == "legacy_adopted"


def test_ad11_manual_rollback_restores_legacy_and_config(tmp_path):
    legacy = {**APPROVED_FILES, "bin/64bit/obs-multi-rtmp.dll": b"legacy"}
    installer, config, _ = _installer(tmp_path, legacy=legacy)
    before, config_before = _file_records(installer.plugin_root), config.read_bytes()
    installer.adopt()
    installer.install()
    assert installer.rollback().result == "rolled_back"
    assert _file_records(installer.plugin_root) == before
    assert config.read_bytes() == config_before
    assert installer.status().installation == "legacy_adopted"


@pytest.mark.parametrize("state,mutation_started", [("preparing", False), ("backup_verified", False)])
def test_ad12_pending_without_mutation_is_detected_and_aborted_safely(tmp_path, state, mutation_started):
    installer, _, _ = _installer(tmp_path, legacy=APPROVED_FILES)
    baseline = _file_records(installer.plugin_root)
    root, journal = installer._begin_transaction(
        kind="legacy_adoption", baseline_records=baseline, expected_files=baseline,
        previous_transaction_id=None, installed_version=None,
    )
    journal["state"], journal["mutation_started"] = state, mutation_started
    installer._write_json(root / "transaction.json", journal)
    assert installer.status().installation == "recovery_required"
    assert installer.rollback().result == "recovered_no_mutation"
    assert _file_records(installer.plugin_root) == baseline


@pytest.mark.parametrize("pending_state", ["mutation_pending", "recovery_required"])
def test_ad12_mutation_pending_restores_only_verified_backup(tmp_path, pending_state):
    legacy = {**APPROVED_FILES, "bin/64bit/obs-multi-rtmp.dll": b"legacy"}
    installer, _, _ = _installer(tmp_path, legacy=legacy)
    baseline = _file_records(installer.plugin_root)
    root, journal = installer._begin_transaction(
        kind="approved_release_install", baseline_records=baseline,
        expected_files=_records(APPROVED_FILES), previous_transaction_id=None, installed_version="1.0.0",
    )
    installer._snapshot_and_verify(root, journal, baseline)
    journal["state"], journal["mutation_started"] = pending_state, True
    installer._write_json(root / "transaction.json", journal)
    installer._write_json(installer.pointer, {"transaction_id": journal["transaction_id"]})
    _write_tree(installer.plugin_root, APPROVED_FILES)
    assert installer.rollback().result == "recovered_rolled_back"
    assert _file_records(installer.plugin_root) == baseline
    assert not installer.pointer.exists()


def test_ad12_catalog_is_not_installable_while_recovery_is_required():
    class Host:
        def status(self):
            return PluginHostStatus("recovery_required", True, False)

    class Source:
        def catalog_release(self, plugin_id):
            return PluginRelease(
                plugin_id=plugin_id, version="1.0.0", source_commit="a" * 40,
                platform="windows", architecture="x64", obs_version="32.2.1",
                artifact_name="approved.zip", artifact_sha256="0" * 64,
                vendor="sorayuki.multi_rtmp", metadata={},
            )

    catalog = asyncio.run(ObsPluginService(_Manager(), Host(), release_source=Source()).available())
    assert catalog["plugins"][0]["installable"] is False
    assert catalog["plugins"][0]["reason"] == "recovery_required"


def test_ad12_invalid_current_pointer_fails_closed(tmp_path):
    installer, _, _ = _installer(tmp_path, legacy=APPROVED_FILES)
    installer.pointer.parent.mkdir(parents=True)
    installer.pointer.write_text('{"transaction_id":"unsafe"}', encoding="utf-8")
    assert installer.status().installation == "recovery_required"
    for operation in (installer.adopt, installer.install):
        with pytest.raises(PluginInstallerFailure) as error:
            operation()
        assert error.value.code == "recovery_required"


def test_ad13_concurrent_adopt_rejects_second_mutation():
    entered, release = threading.Event(), threading.Event()

    class Host:
        def status(self):
            return PluginHostStatus("unmanaged", True, False)
        def adopt(self):
            entered.set(); release.wait(5)
            return PluginHostResult("adopted")

    async def scenario():
        service = ObsPluginService(_Manager(), Host())
        first = asyncio.create_task(service.adopt("obs-multi-rtmp"))
        assert await asyncio.to_thread(entered.wait, 2)
        with pytest.raises(ObsPluginError) as error:
            await service.adopt("obs-multi-rtmp")
        assert error.value.code == "plugin_state_conflict"
        release.set()
        await first

    asyncio.run(scenario())


def test_ad14_vendor_failure_is_typed_and_restores_legacy(tmp_path):
    legacy = {**APPROVED_FILES, "bin/64bit/obs-multi-rtmp.dll": b"legacy"}
    installer, _, _ = _installer(tmp_path, legacy=legacy)
    before = _file_records(installer.plugin_root)
    installer.adopt()
    host, manager = _Host(installer), _Manager(_runtime("READY"))

    class Client:
        def connect(self): pass
        def request(self, *_args, **_kwargs): raise RuntimeError("stream_key=never-return")
        def close(self): pass

    manager.client_factory = Client
    service = ObsPluginService(manager, host, defer_restart=True)
    asyncio.run(service.install("obs-multi-rtmp"))
    manager.value = _runtime("READY")
    with pytest.raises(ObsPluginError) as error:
        asyncio.run(service.verify("obs-multi-rtmp"))
    assert error.value.code == "plugin_verify_failed"
    assert "stream_key" not in str(error.value)
    assert _file_records(installer.plugin_root) == before


def test_ad15_rest_and_websocket_adopt_contract(server_config, capture_service):
    stopped = ObsPluginStatus(
        "obs-multi-rtmp", "0.7.4.0", "LEGACY_ADOPTED", True, False, True,
        managed=True, adoptable=False,
    )

    class Service:
        async def adopt(self, plugin_id):
            assert plugin_id == "obs-multi-rtmp"
            return ObsPluginOperationResult(stopped, "adopt", "adopted")

    app = create_app(server_config, capture_service=capture_service, obs_plugin_service=Service(), manage_runtime=False)
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        rest = client.post("/api/v1/obs/plugins/obs-multi-rtmp/adopt")
        assert rest.status_code == 200
        assert rest.json()["operation"] == "adopt"
        with client.websocket_connect("/api/v1/obs/plugins/ws") as ws:
            ws.send_json({"type": "request", "request_id": "adopt-1", "operation": "obs_plugin.adopt", "payload": {"plugin_id": "obs-multi-rtmp"}})
            response = ws.receive_json()
        assert response["ok"] is True
        assert response["data"] == rest.json()
        rejected = client.post("/api/v1/obs/plugins/obs-multi-rtmp/adopt", json={"source": "secret"})
        assert rejected.status_code == 400
        assert "secret" not in rejected.text


# Rollback safety regressions: data retention, crash injection, and restart.
def _installed_legacy_for_rollback(tmp_path):
    legacy = {**APPROVED_FILES, "bin/64bit/obs-multi-rtmp.dll": b"legacy"}
    installer, config, processes = _installer(tmp_path, legacy=legacy)
    installer.adopt()
    installer.install()
    return installer, config, processes, _records(legacy)


def _reopen(installer, tmp_path, config, processes):
    return WindowsObsMultiRtmpInstaller(
        tmp_path / "state", plugin_root=installer.plugin_root,
        obs_executable=tmp_path / "obs64.exe", manifest=dict(installer.manifest),
        process_probe=lambda: list(processes), version_probe=lambda _p: "32.2.1",
        appdata=config.parents[4],
    )


@pytest.mark.parametrize("modified", [
    b'{"targets":[{"stream_key":"NEW-KEY-DO-NOT-LOSE"}]}',
    b'{"targets":[]}',
])
def test_rb02_rb03_manual_rollback_rejects_changed_config_before_touching_dll(tmp_path, modified):
    installer, config, _, _ = _installed_legacy_for_rollback(tmp_path)
    before_files = _file_records(installer.plugin_root)
    before_pointer = installer.pointer.read_bytes()
    config.write_bytes(modified)
    with pytest.raises(PluginInstallerFailure) as error:
        installer.rollback()
    assert error.value.code == "config_conflict"
    assert _file_records(installer.plugin_root) == before_files
    assert installer.pointer.read_bytes() == before_pointer
    assert config.read_bytes() == modified
    assert "NEW-KEY" not in str(error.value)
    assert installer.status().installation == "exact"


def test_rb04_manual_rollback_rejects_new_nonempty_profile(tmp_path):
    installer, config, _, _ = _installed_legacy_for_rollback(tmp_path)
    before = _file_records(installer.plugin_root)
    new_config = config.parents[1] / "SecondProfile" / config.name
    new_config.parent.mkdir(parents=True)
    new_config.write_bytes(b'{"targets":[{"stream_key":"fresh"}]}')
    with pytest.raises(PluginInstallerFailure) as error:
        installer.rollback()
    assert error.value.code == "config_conflict"
    assert _file_records(installer.plugin_root) == before
    assert new_config.read_bytes().endswith(b'fresh"}]}')


def test_rb05_empty_new_config_is_removable(tmp_path):
    installer, config, _, legacy_records = _installed_legacy_for_rollback(tmp_path)
    empty_config = config.parents[1] / "SecondProfile" / config.name
    empty_config.parent.mkdir(parents=True)
    empty_config.write_bytes(b'{"targets":[]}')
    assert installer.rollback().result == "rolled_back"
    assert not empty_config.exists()
    assert _file_records(installer.plugin_root) == legacy_records


def test_rb06_corrupted_config_backup_fails_before_dll_mutation(tmp_path):
    installer, config, _, _ = _installed_legacy_for_rollback(tmp_path)
    files_before = _file_records(installer.plugin_root)
    pointer_before = installer.pointer.read_bytes()
    root, _ = installer._read_current_transaction()
    (root / "backup/configs/0000.bin").write_bytes(b"broken")
    with pytest.raises(PluginInstallerFailure) as error:
        installer.rollback()
    assert error.value.code == "backup_invalid"
    assert _file_records(installer.plugin_root) == files_before
    assert installer.pointer.read_bytes() == pointer_before


@pytest.mark.parametrize("cut", ["before_files", "after_clear", "after_restore", "after_pointer"])
def test_cr01_cr02_cr05_cr06_recovery_after_simulated_process_death(tmp_path, monkeypatch, cut):
    installer, config, processes, legacy_records = _installed_legacy_for_rollback(tmp_path)
    original_clear = installer._clear_contents
    original_restore = installer._restore_backup_verified
    original_pointer = installer._restore_previous_pointer

    def kill_before_clear(path):
        if cut == "before_files":
            raise SystemExit("injected process death before file clear")
        original_clear(path)
        if cut == "after_clear":
            raise SystemExit("injected death just after file clear")

    def kill_after_restore(root, transaction, **kwargs):
        original_restore(root, transaction, **kwargs)
        if cut == "after_restore":
            raise SystemExit("injected death before pointer change")

    def kill_after_pointer(transaction):
        original_pointer(transaction)
        if cut == "after_pointer":
            raise SystemExit("injected death after pointer change")

    monkeypatch.setattr(installer, "_clear_contents", kill_before_clear)
    monkeypatch.setattr(installer, "_restore_backup_verified", kill_after_restore)
    monkeypatch.setattr(installer, "_restore_previous_pointer", kill_after_pointer)
    with pytest.raises(SystemExit):
        installer.rollback()

    reopened = _reopen(installer, tmp_path, config, processes)
    assert reopened.status().installation == "recovery_required"
    assert reopened.rollback().result == "recovered_rolled_back"
    assert _file_records(reopened.plugin_root) == legacy_records
    assert reopened.status().installation == "legacy_adopted"


def test_cr03_mid_file_copy_recovery(tmp_path, monkeypatch):
    installer, config, processes, legacy_records = _installed_legacy_for_rollback(tmp_path)
    real_copy = installer._copy_contents

    def interrupted_copy(source, destination):
        # Partial copy of one managed file followed by hard process termination.
        (destination / "bin/64bit").mkdir(parents=True, exist_ok=True)
        (destination / "bin/64bit/obs-multi-rtmp.dll").write_bytes(b"partial")
        raise SystemExit("killed while copying plugin tree")

    monkeypatch.setattr(installer, "_copy_contents", interrupted_copy)
    with pytest.raises(SystemExit):
        installer.rollback()
    reopened = _reopen(installer, tmp_path, config, processes)
    assert reopened.status().installation == "recovery_required"
    assert reopened.rollback().result == "recovered_rolled_back"
    assert _file_records(reopened.plugin_root) == legacy_records


def test_cr07_corrupt_backup_after_crash_never_overwrites_partial_plugin(tmp_path, monkeypatch):
    installer, config, processes, _ = _installed_legacy_for_rollback(tmp_path)
    original = installer._clear_contents

    def interrupted_clear(path):
        original(path)
        raise SystemExit("crash after deleting current plugin")
    monkeypatch.setattr(installer, "_clear_contents", interrupted_clear)
    with pytest.raises(SystemExit):
        installer.rollback()
    reopened = _reopen(installer, tmp_path, config, processes)
    backup_root, _ = reopened._pending_transactions()[0]
    (backup_root / "backup/obs-multi-rtmp/bin/64bit/obs-multi-rtmp.dll").write_bytes(b"tampered")
    before = _file_records(reopened.plugin_root)
    with pytest.raises(PluginInstallerFailure) as error:
        reopened.rollback()
    assert error.value.code == "backup_invalid"
    assert _file_records(reopened.plugin_root) == before
    assert reopened.status().installation == "recovery_required"


def test_cr08_modified_config_after_crash_fails_closed(tmp_path, monkeypatch):
    installer, config, processes, _ = _installed_legacy_for_rollback(tmp_path)
    original = installer._clear_contents

    def interrupted_clear(path):
        original(path)
        raise SystemExit("crash after clear")
    monkeypatch.setattr(installer, "_clear_contents", interrupted_clear)
    with pytest.raises(SystemExit):
        installer.rollback()
    new_content = b'{"targets":[{"stream_key":"changed-after-crash"}]}'
    config.write_bytes(new_content)
    reopened = _reopen(installer, tmp_path, config, processes)
    with pytest.raises(PluginInstallerFailure) as error:
        reopened.rollback()
    assert error.value.code == "config_conflict"
    assert config.read_bytes() == new_content
    assert reopened.status().installation == "recovery_required"


def test_cr09_recovered_rollback_is_idempotent(tmp_path, monkeypatch):
    installer, config, processes, legacy_records = _installed_legacy_for_rollback(tmp_path)
    original = installer._clear_contents

    def interrupted_clear(path):
        original(path)
        raise SystemExit("crash after clear")
    monkeypatch.setattr(installer, "_clear_contents", interrupted_clear)
    with pytest.raises(SystemExit):
        installer.rollback()
    reopened = _reopen(installer, tmp_path, config, processes)
    assert reopened.rollback().result == "recovered_rolled_back"
    assert _file_records(reopened.plugin_root) == legacy_records
    assert not reopened._pending_transactions()
    with pytest.raises(PluginInstallerFailure) as error:
        reopened.rollback()
    assert error.value.code == "plugin_state_conflict"


def test_cr10_pending_rollback_blocks_other_operations(tmp_path, monkeypatch):
    installer, config, processes, _ = _installed_legacy_for_rollback(tmp_path)
    original = installer._clear_contents

    def interrupted_clear(path):
        original(path)
        raise SystemExit("crash after clear")
    monkeypatch.setattr(installer, "_clear_contents", interrupted_clear)
    with pytest.raises(SystemExit):
        installer.rollback()
    reopened = _reopen(installer, tmp_path, config, processes)
    for method in (reopened.install, reopened.adopt, reopened.update):
        with pytest.raises(PluginInstallerFailure) as error:
            method()
        assert error.value.code == "recovery_required"


def test_cr11_service_requires_explicit_obs_stop_before_recovery(tmp_path, monkeypatch):
    installer, config, processes, _ = _installed_legacy_for_rollback(tmp_path)
    original = installer._clear_contents

    def interrupted_clear(path):
        original(path)
        raise SystemExit("crash after clear")
    monkeypatch.setattr(installer, "_clear_contents", interrupted_clear)
    with pytest.raises(SystemExit):
        installer.rollback()
    reopened = _reopen(installer, tmp_path, config, processes)
    host, manager = _Host(reopened), _Manager(_runtime("READY"))
    with pytest.raises(ObsPluginError) as error:
        asyncio.run(ObsPluginService(manager, host, defer_restart=True).rollback("obs-multi-rtmp"))
    assert error.value.code == "plugin_recovery_requires_obs_stopped"
    assert manager.calls == []
    assert reopened.status().installation == "recovery_required"


def test_cr12_recovery_preserves_config_and_pointer_snapshot(tmp_path, monkeypatch):
    installer, config, processes, legacy_records = _installed_legacy_for_rollback(tmp_path)
    baseline_config = config.read_bytes()
    original = installer._restore_previous_pointer

    def interrupted_pointer(transaction):
        original(transaction)
        raise SystemExit("crash after previous pointer was committed")
    monkeypatch.setattr(installer, "_restore_previous_pointer", interrupted_pointer)
    with pytest.raises(SystemExit):
        installer.rollback()
    reopened = _reopen(installer, tmp_path, config, processes)
    assert reopened.rollback().result == "recovered_rolled_back"
    assert _file_records(reopened.plugin_root) == legacy_records
    assert config.read_bytes() == baseline_config
    assert reopened.status().installation == "legacy_adopted"
    assert not reopened._pending_transactions()

def test_p1_host_uses_shared_obs_executable_identity(tmp_path, monkeypatch):
    from streamops.server.platform.windows.obs_plugin.host import WindowsObsMultiRtmpHost

    monkeypatch.setattr(
        "streamops.server.platform.windows.obs_plugin.host.configured_plugin_release_source",
        lambda: None,
    )
    custom_exe = tmp_path / "custom-obs" / "obs64.exe"
    custom_exe.parent.mkdir()
    custom_exe.touch()
    host = WindowsObsMultiRtmpHost(tmp_path / "state", obs_executable=custom_exe)
    assert host.installer.obs_executable == custom_exe
    legacy = {**APPROVED_FILES, "bin/64bit/obs-multi-rtmp.dll": b"legacy"}
    _write_tree(tmp_path / "isolated", legacy)
    host.installer.plugin_root = tmp_path / "isolated"
    host.installer.process_probe = lambda: [
        ProcessEvidence(123, custom_exe, datetime.now(timezone.utc)),
    ]
    with pytest.raises(PluginInstallerFailure) as error:
        host.installer.adopt()
    assert error.value.code == "obs_running"

