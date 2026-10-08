from __future__ import annotations

import asyncio

import pytest

from streamops.server.errors import ObsPluginError, ObsStartError
from streamops.server.obs.manager import ObsRuntimeStatus
from streamops.server.services.obs_plugin import (
    ObsPluginService,
    PluginHostResult,
    PluginHostStatus,
)


def runtime(state="READY", *, streaming=False, recording=False, version="32.2.1"):
    return ObsRuntimeStatus(
        state=state,
        process={"running": state != "STOPPED"},
        websocket={"connected": state == "READY", "obs_version": version},
        output={"streaming": streaming, "recording": recording},
        last_operation=None,
        error=None,
    )


class FakeManager:
    def __init__(self, value=None):
        self.value = value or runtime()
        self.calls = []
        self.start_error = None

    def status(self):
        self.calls.append("status")
        return self.value

    def stop(self):
        self.calls.append("stop")
        self.value = runtime("STOPPED")
        return self.value

    def start(self):
        self.calls.append("start")
        if self.start_error:
            raise self.start_error
        self.value = runtime()
        return self.value

    def restart(self):
        self.calls.append("restart")
        self.value = runtime()
        return self.value


class FakeHost:
    def __init__(self, installation="absent", *, loaded=False, compatible=True):
        self.installation = installation
        self.loaded = loaded
        self.compatible = compatible
        self.calls = []
        self.failures = {}

    def _fail(self, action):
        failure = self.failures.get(action)
        if failure:
            raise failure

    def status(self):
        self.calls.append("status")
        self._fail("status")
        return PluginHostStatus(
            self.installation,
            self.compatible,
            self.loaded,
            "0.7.4.0" if self.loaded else None,
        )

    def install(self):
        self.calls.append("install")
        self._fail("install")
        result = "already_installed" if self.installation == "exact" else "installed"
        self.installation = "exact"
        return PluginHostResult(result)

    def verify(self):
        self.calls.append("verify")
        self._fail("verify")
        self.loaded = True
        return self.status()

    def rollback(self):
        self.calls.append("rollback")
        self._fail("rollback")
        self.installation = "absent"
        self.loaded = False
        return PluginHostResult("rolled_back")


def run(awaitable):
    return asyncio.run(awaitable)


@pytest.mark.parametrize(
    ("host", "manager", "state"),
    [
        (FakeHost(), FakeManager(runtime("STOPPED")), "NOT_INSTALLED"),
        (FakeHost("exact"), FakeManager(), "INSTALLED"),
        (FakeHost("exact", loaded=True), FakeManager(), "VERIFIED"),
        (FakeHost("exact", compatible=False), FakeManager(), "INCOMPATIBLE"),
        (FakeHost("conflict"), FakeManager(), "FAILED"),
    ],
)
def test_status_state_model(host, manager, state):
    assert run(ObsPluginService(manager, host).status("obs-multi-rtmp")).state == state


def test_fresh_install_stops_installs_starts_and_verifies():
    host, manager = FakeHost(), FakeManager()
    result = run(ObsPluginService(manager, host).install("obs-multi-rtmp"))
    assert result.result == "installed"
    assert result.status.state == "VERIFIED"
    assert manager.calls.count("stop") == 1
    assert manager.calls.count("start") == 1
    assert host.calls.count("install") == 1
    assert host.calls.count("verify") == 1


def test_idempotent_loaded_install_does_not_restart():
    host, manager = FakeHost("exact", loaded=True), FakeManager()
    result = run(ObsPluginService(manager, host).install("obs-multi-rtmp"))
    assert result.result == "already_installed"
    assert "stop" not in manager.calls and "restart" not in manager.calls


def test_exact_files_not_loaded_are_restarted_and_verified():
    host, manager = FakeHost("exact"), FakeManager()
    result = run(ObsPluginService(manager, host).install("obs-multi-rtmp"))
    assert result.result == "already_installed"
    assert result.status.state == "VERIFIED"
    assert manager.calls.count("restart") == 1


@pytest.mark.parametrize(
    ("streaming", "recording", "code"),
    [(True, False, "obs_busy_streaming"), (False, True, "obs_busy_recording")],
)
def test_install_and_rollback_block_active_outputs(streaming, recording, code):
    for action in ("install", "rollback"):
        service = ObsPluginService(
            FakeManager(runtime(streaming=streaming, recording=recording)), FakeHost("exact", loaded=True)
        )
        with pytest.raises(ObsPluginError) as error:
            run(getattr(service, action)("obs-multi-rtmp"))
        assert error.value.code == code


def test_verify_fails_when_obs_stopped_or_module_missing():
    stopped = ObsPluginService(FakeManager(runtime("STOPPED")), FakeHost("exact"))
    with pytest.raises(ObsPluginError) as error:
        run(stopped.verify("obs-multi-rtmp"))
    assert error.value.code == "plugin_verify_failed"

    missing = FakeHost("exact")
    missing.failures["verify"] = ObsPluginError("plugin_verify_failed", "missing", 409)
    with pytest.raises(ObsPluginError) as error:
        run(ObsPluginService(FakeManager(), missing).verify("obs-multi-rtmp"))
    assert error.value.code == "plugin_verify_failed"


def test_rollback_restarts_obs_and_refuses_modified_files():
    host, manager = FakeHost("exact", loaded=True), FakeManager()
    result = run(ObsPluginService(manager, host).rollback("obs-multi-rtmp"))
    assert result.result == "rolled_back"
    assert result.status.state == "NOT_INSTALLED"
    assert manager.calls.count("stop") == 1 and manager.calls.count("start") == 1

    conflict = ObsPluginService(FakeManager(), FakeHost("conflict"))
    with pytest.raises(ObsPluginError) as error:
        run(conflict.rollback("obs-multi-rtmp"))
    assert error.value.code == "plugin_state_conflict"


def test_permission_and_incompatible_failures_are_typed():
    host = FakeHost()
    host.failures["install"] = PermissionError("secret path")
    with pytest.raises(ObsPluginError) as error:
        run(ObsPluginService(FakeManager(), host).install("obs-multi-rtmp"))
    assert error.value.code == "plugin_install_permission_denied"
    assert "secret path" not in str(error.value)

    with pytest.raises(ObsPluginError) as error:
        run(ObsPluginService(FakeManager(), FakeHost(compatible=False)).install("obs-multi-rtmp"))
    assert error.value.code == "plugin_incompatible"


def test_restart_failure_is_typed_and_attempts_safe_rollback():
    host, manager = FakeHost(), FakeManager()
    manager.start_error = ObsStartError("OBS did not become ready")
    with pytest.raises(ObsPluginError) as error:
        run(ObsPluginService(manager, host).install("obs-multi-rtmp"))
    assert error.value.code == "obs_restart_failed"
    assert "rollback" in host.calls


def test_unknown_plugin_is_never_sent_to_host():
    host = FakeHost()
    with pytest.raises(ObsPluginError) as error:
        run(ObsPluginService(FakeManager(), host).status("arbitrary.dll"))
    assert error.value.code == "plugin_not_supported"
    assert host.calls == []


@pytest.mark.parametrize(
    ("streaming", "recording", "code"),
    [(True, False, "obs_busy_streaming"), (False, True, "obs_busy_recording")],
)
def test_update_rejects_active_outputs_without_mutating_host(streaming, recording, code):
    host = FakeHost("exact", loaded=True)
    manager = FakeManager(runtime(streaming=streaming, recording=recording))
    with pytest.raises(ObsPluginError) as caught:
        run(ObsPluginService(manager, host).update("obs-multi-rtmp"))
    assert caught.value.code == code
    assert "update" not in host.calls
    assert "stop" not in manager.calls
    assert "restart" not in manager.calls


def test_update_rejects_missing_plugin_before_mutation():
    host = FakeHost("absent")
    manager = FakeManager()
    with pytest.raises(ObsPluginError) as caught:
        run(ObsPluginService(manager, host).update("obs-multi-rtmp"))
    assert caught.value.code == "plugin_not_installed"
    assert "update" not in host.calls
    assert "stop" not in manager.calls


def test_update_calls_distinct_host_operation_not_install():
    class UpdatableHost(FakeHost):
        def update(self):
            self.calls.append("update")
            return PluginHostResult("updated")

    host = UpdatableHost("exact", loaded=True)
    result = run(ObsPluginService(FakeManager(), host).update("obs-multi-rtmp"))
    assert result.operation == "update"
    assert result.result == "updated"
    assert host.calls.count("update") == 1
    assert "install" not in host.calls


def test_update_failure_has_typed_sanitized_error():
    class BrokenHost(FakeHost):
        def update(self):
            raise RuntimeError("sensitive token=do-not-leak")

    with pytest.raises(ObsPluginError) as caught:
        run(ObsPluginService(FakeManager(), BrokenHost("exact")).update("obs-multi-rtmp"))
    assert caught.value.code == "plugin_update_failed"
    assert "do-not-leak" not in str(caught.value)


@pytest.mark.parametrize("action", ["install", "update", "rollback"])
def test_mutations_reject_transitional_obs_state_without_stopping(action):
    host = FakeHost("exact", loaded=True)
    manager = FakeManager(runtime("STARTING"))
    with pytest.raises(ObsPluginError) as caught:
        run(getattr(ObsPluginService(manager, host), action)("obs-multi-rtmp"))
    assert caught.value.code == "plugin_state_conflict"
    assert "stop" not in manager.calls


@pytest.mark.parametrize("action", ["install", "update", "verify", "rollback"])
def test_unknown_plugin_rejected_for_every_operation(action):
    host = FakeHost("exact", loaded=True)
    manager = FakeManager()
    with pytest.raises(ObsPluginError) as caught:
        run(getattr(ObsPluginService(manager, host), action)("unapproved-plugin"))
    assert caught.value.code == "plugin_not_supported"
    assert host.calls == []


def test_host_status_exception_is_sanitized_and_typed():
    host = FakeHost()
    host.failures["status"] = RuntimeError("private-path")
    with pytest.raises(ObsPluginError) as caught:
        run(ObsPluginService(FakeManager(), host).status("obs-multi-rtmp"))
    assert caught.value.code == "plugin_status_failed"
    assert "private-path" not in str(caught.value)


def test_install_from_stopped_state_does_not_stop_again():
    host, manager = FakeHost(), FakeManager(runtime("STOPPED"))
    result = run(ObsPluginService(manager, host).install("obs-multi-rtmp"))
    assert result.status.state == "VERIFIED"
    assert "stop" not in manager.calls
    assert manager.calls.count("start") == 1


def test_concurrent_mutations_reject_second_operation():
    import threading
    entered = threading.Event()
    release = threading.Event()
    class BlockingHost(FakeHost):
        def install(self):
            entered.set()
            assert release.wait(timeout=5)
            return super().install()
    host = BlockingHost()
    service = ObsPluginService(FakeManager(), host)
    async def scenario():
        first = asyncio.create_task(service.install("obs-multi-rtmp"))
        assert await asyncio.to_thread(entered.wait, 5)
        try:
            with pytest.raises(ObsPluginError) as caught:
                await service.rollback("obs-multi-rtmp")
            assert caught.value.code == "plugin_state_conflict"
        finally:
            release.set()
        await first
    run(scenario())
    assert host.calls.count("install") == 1
    assert "rollback" not in host.calls


def test_vendor_probe_requires_registered_handler_and_sanitizes_error():
    class VendorClient:
        def __init__(self, reply=None, failure=None):
            self.reply, self.failure, self.calls, self.closed = reply, failure, [], False
        def connect(self):
            self.calls.append("connect")
        def request(self, name, payload):
            self.calls.append((name, payload))
            if self.failure:
                raise self.failure
            return self.reply
        def close(self):
            self.closed = True

    for good in (True, False):
        client = VendorClient(
            {"vendorResponseData": {"targets": [], "count": 0}} if good
            else {"vendorResponseData": {}},
            None if good else RuntimeError("stream_key=must-never-leak"),
        )
        manager = FakeManager()
        manager.client_factory = lambda: client
        service = ObsPluginService(manager, FakeHost("exact", loaded=True))
        if good:
            assert run(service.verify("obs-multi-rtmp")).result == "verified"
        else:
            with pytest.raises(ObsPluginError) as caught:
                run(service.verify("obs-multi-rtmp"))
            assert caught.value.code == "plugin_verify_failed"
            assert "must-never-leak" not in str(caught.value)
        assert client.closed is True
        assert ("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "list_targets",
            "requestData": {},
        }) in client.calls


@pytest.mark.parametrize("installed,available,expected", [
    ("1.0.0", "2.0.0", "UPDATE_AVAILABLE"),
    ("1.0.0", "1.0.0", "VERIFIED"),
    ("2.0.0", "1.0.0", "VERIFIED"),
])
def test_version_status_transition(installed, available, expected):
    class Host(FakeHost):
        def status(self):
            return PluginHostStatus("exact", True, True, "0.7.4.0",
                                    installed_version=installed, available_version=available)
    value = run(ObsPluginService(FakeManager(), Host()).status("obs-multi-rtmp"))
    assert value.state == expected
    assert value.installed_version == installed
    assert value.available_version == available


def test_inventory_only_reports_registered_plugin():
    value = run(ObsPluginService(FakeManager(), FakeHost()).inventory())
    assert len(value) == 1
    assert value[0].plugin_id == "obs-multi-rtmp"
    assert value[0].state == "NOT_INSTALLED"
