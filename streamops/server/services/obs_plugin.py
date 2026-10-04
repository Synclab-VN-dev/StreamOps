"""Safe orchestration boundary for allowlisted OBS plugins."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import threading
from typing import Any, Literal, Protocol

from ..errors import (
    ObsOperationInProgressError,
    ObsPluginError,
    ObsProcessError,
    WrongDesktopSessionError,
)


PLUGIN_ID = "obs-multi-rtmp"
EXPECTED_VERSION = "0.7.4.0"
EXPECTED_OBS_VERSION = "32.2.1"

PluginState = Literal["NOT_INSTALLED", "INSTALLED", "LOADED", "INCOMPATIBLE", "ERROR"]


@dataclass(frozen=True)
class PluginHostStatus:
    installation: Literal["absent", "exact", "conflict"]
    compatible: bool
    loaded: bool
    loaded_version: str | None = None


@dataclass(frozen=True)
class PluginHostResult:
    result: str


class ObsPluginHost(Protocol):
    def status(self) -> PluginHostStatus: ...
    def install(self) -> PluginHostResult: ...
    def verify(self) -> PluginHostStatus: ...
    def rollback(self) -> PluginHostResult: ...


@dataclass(frozen=True)
class ObsPluginStatus:
    plugin_id: str
    expected_version: str
    state: PluginState
    installed: bool
    loaded: bool
    compatible: bool

    def api_payload(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ObsPluginOperationResult:
    status: ObsPluginStatus
    operation: Literal["install", "verify", "rollback"]
    result: str

    def api_payload(self) -> dict[str, object]:
        return {**self.status.api_payload(), "operation": self.operation, "result": self.result}


class ObsPluginService:
    def __init__(self, obs_manager: Any, host: ObsPluginHost) -> None:
        self.obs_manager = obs_manager
        self.host = host
        self._operation_lock = threading.Lock()

    async def status(self, plugin_id: str) -> ObsPluginStatus:
        self._require_supported(plugin_id)
        return await asyncio.to_thread(self._status_sync)

    async def install(self, plugin_id: str) -> ObsPluginOperationResult:
        self._require_supported(plugin_id)
        return await asyncio.to_thread(self._run_guarded, "install", self._install_sync)

    async def verify(self, plugin_id: str) -> ObsPluginOperationResult:
        self._require_supported(plugin_id)
        return await asyncio.to_thread(self._run_guarded, "verify", self._verify_sync)

    async def rollback(self, plugin_id: str) -> ObsPluginOperationResult:
        self._require_supported(plugin_id)
        return await asyncio.to_thread(self._run_guarded, "rollback", self._rollback_sync)

    def _require_supported(self, plugin_id: str) -> None:
        if plugin_id != PLUGIN_ID:
            raise ObsPluginError("plugin_not_supported", "The requested OBS plugin is not supported.", 404)

    def _run_guarded(self, operation: str, callback: Any) -> ObsPluginOperationResult:
        if not self._operation_lock.acquire(blocking=False):
            raise ObsPluginError(
                "plugin_state_conflict", "Another OBS plugin operation is already running.", 409
            )
        try:
            return callback()
        finally:
            self._operation_lock.release()

    def _status_sync(self) -> ObsPluginStatus:
        try:
            host = self.host.status()
            runtime = self.obs_manager.status()
        except ObsPluginError:
            raise
        except Exception as exc:
            raise ObsPluginError(
                "plugin_status_failed", "OBS plugin status could not be inspected.", 503
            ) from exc
        return self._combine(host, runtime)

    def _combine(self, host: PluginHostStatus, runtime: Any) -> ObsPluginStatus:
        runtime_version = runtime.websocket.get("obs_version") if runtime.websocket else None
        compatible = host.compatible and runtime_version in (None, EXPECTED_OBS_VERSION)
        installed = host.installation == "exact"
        loaded = bool(
            installed
            and host.loaded
            and host.loaded_version == EXPECTED_VERSION
            and runtime.state == "READY"
            and runtime.websocket.get("connected") is True
        )
        if not compatible:
            state: PluginState = "INCOMPATIBLE"
        elif host.installation == "conflict":
            state = "ERROR"
        elif not installed:
            state = "NOT_INSTALLED"
        elif loaded:
            state = "LOADED"
        else:
            state = "INSTALLED"
        return ObsPluginStatus(PLUGIN_ID, EXPECTED_VERSION, state, installed, loaded, compatible)

    def _runtime_for_mutation(self) -> Any:
        runtime = self.obs_manager.status()
        if runtime.output.get("streaming") is True:
            raise ObsPluginError("obs_busy_streaming", "OBS plugin changes are blocked while streaming.", 409)
        if runtime.output.get("recording") is True:
            raise ObsPluginError("obs_busy_recording", "OBS plugin changes are blocked while recording.", 409)
        if runtime.state not in {"READY", "STOPPED"}:
            raise ObsPluginError(
                "plugin_state_conflict", "OBS must be READY or STOPPED before changing plugins.", 409
            )
        return runtime

    def _ensure_compatible(self, status: ObsPluginStatus) -> None:
        if not status.compatible:
            raise ObsPluginError(
                "plugin_incompatible", f"This plugin is pinned to OBS {EXPECTED_OBS_VERSION}.", 409
            )

    def _install_sync(self) -> ObsPluginOperationResult:
        runtime = self._runtime_for_mutation()
        initial = self._combine(self.host.status(), runtime)
        self._ensure_compatible(initial)

        # The lower layer checks the exact manifest before requiring OBS to stop.
        if initial.installed:
            lower = self._host_call("install")
            if initial.loaded:
                return ObsPluginOperationResult(initial, "install", lower.result)
            self._restart_or_start(runtime)
            verified = self._verify_loaded()
            return ObsPluginOperationResult(verified, "install", lower.result)

        stopped_by_service = False
        installed = False
        try:
            if runtime.state == "READY":
                self.obs_manager.stop()
                stopped_by_service = True
            lower = self._host_call("install")
            installed = lower.result == "installed"
            self._start_obs()
            verified = self._verify_loaded()
            return ObsPluginOperationResult(verified, "install", lower.result)
        except ObsPluginError as exc:
            if installed:
                self._recover_failed_install()
            elif stopped_by_service:
                self._best_effort_start(exc)
            raise
        except (ObsProcessError, WrongDesktopSessionError) as exc:
            self._best_effort_start(exc)
            raise ObsPluginError("obs_restart_failed", "OBS did not return to READY after plugin install.", 503) from exc

    def _verify_sync(self) -> ObsPluginOperationResult:
        status = self._verify_loaded()
        return ObsPluginOperationResult(status, "verify", "verified")

    def _verify_loaded(self) -> ObsPluginStatus:
        runtime = self.obs_manager.status()
        if runtime.state != "READY" or runtime.websocket.get("connected") is not True:
            raise ObsPluginError(
                "plugin_verify_failed", "OBS must be running and READY to verify plugin load.", 409
            )
        try:
            host = self.host.verify()
        except ObsPluginError:
            raise
        except Exception as exc:
            raise ObsPluginError("plugin_verify_failed", "The plugin load could not be verified.", 409) from exc
        status = self._combine(host, runtime)
        self._ensure_compatible(status)
        if status.state != "LOADED":
            raise ObsPluginError(
                "plugin_verify_failed", "The pinned plugin module is not loaded by the current OBS process.", 409
            )
        return status

    def _rollback_sync(self) -> ObsPluginOperationResult:
        runtime = self._runtime_for_mutation()
        current = self._combine(self.host.status(), runtime)
        if current.state == "ERROR":
            raise ObsPluginError(
                "plugin_state_conflict", "Rollback refused because installed plugin files were modified.", 409
            )
        stopped_by_service = False
        try:
            if runtime.state == "READY":
                self.obs_manager.stop()
                stopped_by_service = True
            lower = self._host_call("rollback")
            self._start_obs()
            status = self._status_sync()
            return ObsPluginOperationResult(status, "rollback", lower.result)
        except ObsPluginError as exc:
            if stopped_by_service:
                self._best_effort_start(exc)
            raise
        except (ObsProcessError, WrongDesktopSessionError) as exc:
            self._best_effort_start(exc)
            raise ObsPluginError("obs_restart_failed", "OBS did not return to READY after plugin rollback.", 503) from exc

    def _host_call(self, action: Literal["install", "rollback"]) -> PluginHostResult:
        try:
            return getattr(self.host, action)()
        except ObsPluginError:
            raise
        except PermissionError as exc:
            raise ObsPluginError(
                "plugin_install_permission_denied",
                "StreamOps does not have permission to modify the OBS plugin directory.",
                403,
            ) from exc
        except Exception as exc:
            code = "plugin_install_failed" if action == "install" else "plugin_rollback_failed"
            raise ObsPluginError(code, f"OBS plugin {action} failed.", 503) from exc

    def _restart_or_start(self, runtime: Any) -> None:
        try:
            if runtime.state == "READY":
                self.obs_manager.restart()
            else:
                self.obs_manager.start()
        except (ObsProcessError, WrongDesktopSessionError) as exc:
            raise ObsPluginError("obs_restart_failed", "OBS did not return to READY.", 503) from exc

    def _start_obs(self) -> None:
        try:
            status = self.obs_manager.start()
        except (ObsProcessError, WrongDesktopSessionError) as exc:
            raise ObsPluginError("obs_restart_failed", "OBS did not return to READY.", 503) from exc
        if status.state != "READY" or status.websocket.get("connected") is not True:
            raise ObsPluginError("obs_restart_failed", "OBS did not return to READY.", 503)

    def _recover_failed_install(self) -> None:
        try:
            runtime = self.obs_manager.status()
            if runtime.state == "READY":
                self.obs_manager.stop()
            if self.obs_manager.status().state == "STOPPED":
                self.host.rollback()
            self.obs_manager.start()
        except Exception:
            # The original typed failure is retained; status will expose any remaining conflict.
            return

    def _best_effort_start(self, _original: Exception) -> None:
        try:
            if self.obs_manager.status().state == "STOPPED":
                self.obs_manager.start()
        except Exception:
            return
