"""Safe orchestration boundary for allowlisted OBS plugins."""

from __future__ import annotations

import asyncio
import json
import uuid
import re
from dataclasses import asdict, dataclass, replace, field
from datetime import datetime, timezone
import threading
from typing import Any, Literal, Protocol
from .obs_plugin_release_source import ManagedPluginReleaseSource

from ..errors import (
    ObsOperationInProgressError,
    ObsPluginError,
    ObsProcessError,
    ObsWebSocketConnectionError,
    ObsWebSocketRequestError,
    WrongDesktopSessionError,
)


# TODO(tech-debt): Move plugin identity/version/OBS compatibility into one packaged
# plugin registry/manifest contract. These service constants intentionally mirror the Windows
# manifest today and can drift when the pinned plugin or supported OBS version is upgraded.
PLUGIN_ID = "obs-multi-rtmp"
EXPECTED_VERSION = "0.7.4.0"
EXPECTED_OBS_VERSION = "32.2.1"

PluginState = Literal["NOT_INSTALLED", "UNMANAGED", "LEGACY_ADOPTED", "RECOVERY_REQUIRED", "INSTALLED", "LOADED", "INCOMPATIBLE", "ERROR", "VERIFIED", "UPDATE_AVAILABLE", "RESTART_REQUIRED", "VERIFY_FAILED", "FAILED"]


@dataclass(frozen=True)
class PluginHostStatus:
    installation: Literal["absent", "unmanaged", "legacy_adopted", "approved_release_installed", "exact", "recovery_required", "conflict"]
    compatible: bool
    loaded: bool
    loaded_version: str | None = None
    installed_version: str | None = None
    available_version: str | None = None
    restart_required: bool = False


@dataclass(frozen=True)
class PluginHostResult:
    result: str


class ObsPluginHost(Protocol):
    def status(self) -> PluginHostStatus: ...
    def adopt(self) -> PluginHostResult: ...
    def install(self) -> PluginHostResult: ...
    def update(self) -> PluginHostResult: ...
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
    installed_version: str | None = None
    available_version: str | None = None
    restart_required: bool = False
    managed: bool = False
    adoptable: bool = False
    display_name: str = "OBS Multi RTMP"
    last_verification: str | None = None
    rollback: dict[str, object] = field(default_factory=lambda: {
        "available": False, "target_version": None, "reason": "baseline_unavailable",
    })
    revision: int = 0
    # Flat aliases keep the current #75 FE adapter backward compatible.
    rollback_available: bool = False
    rollback_reason: str | None = "baseline_unavailable"
    operation: dict[str, object] = field(default_factory=lambda: {"state": "IDLE", "operation_id": None})

    def api_payload(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ObsPluginOperationResult:
    status: ObsPluginStatus
    operation: Literal["adopt", "install", "update", "verify", "rollback"]
    result: str
    previous_version: str | None = None

    def api_payload(self) -> dict[str, object]:
        return {
            **self.status.api_payload(), "operation": self.operation,
            "result": self.result, "previous_version": self.previous_version,
        }


class ObsPluginService:
    def __init__(
        self, obs_manager: Any, host: ObsPluginHost, *,
        defer_restart: bool = False, operation_timeout: float = 120.0,
        release_source: ManagedPluginReleaseSource | None = None,
    ) -> None:
        self.obs_manager = obs_manager
        self.host = host
        self.release_source = release_source if release_source is not None else getattr(host, "release_source", None)
        self.defer_restart = defer_restart
        if operation_timeout <= 0:
            raise ValueError("operation_timeout must be positive")
        self.operation_timeout = operation_timeout
        self._pending_change: str | None = None
        self._verified_at: str | None = None
        self._verification_failed = False
        self._operation_lock = threading.Lock()
        self._change_lock = threading.Lock()
        self._revision = 0
        self._subscribers: dict[asyncio.Queue, asyncio.AbstractEventLoop] = {}
        self._active_operation: dict[str, object] | None = None
        self._last_operation: dict[str, object] | None = None
        self._observed: dict[str, str] = {}

    def subscribe_changes(self) -> tuple[asyncio.Queue, int]:
        """Opt-in notifications; old WebSocket consumers remain response-only."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=32)
        with self._change_lock:
            self._subscribers[queue] = loop
            return queue, self._revision

    def unsubscribe_changes(self, queue: asyncio.Queue) -> None:
        with self._change_lock:
            self._subscribers.pop(queue, None)

    @staticmethod
    def _enqueue_changed(queue: asyncio.Queue, event: dict[str, object]) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(event)

    def _changed(self, resource: str) -> None:
        with self._change_lock:
            self._revision += 1
            event: dict[str, object] = {
                "type": "event", "event": "obs_plugin.changed",
                "data": {
                    "plugin_id": PLUGIN_ID, "revision": self._revision,
                    "resources": [resource],
                },
            }
            subscribers = tuple(self._subscribers.items())
        for queue, loop in subscribers:
            try:
                loop.call_soon_threadsafe(self._enqueue_changed, queue, event)
            except RuntimeError:
                # Client loop is already closing; disconnect cleanup removes it.
                pass

    def _observe(self, resource: str, value: object) -> None:
        fingerprint = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        with self._change_lock:
            prior = self._observed.get(resource)
            self._observed[resource] = fingerprint
        if prior is not None and prior != fingerprint:
            self._changed(resource)

    def _operation_snapshot(self) -> dict[str, object]:
        with self._change_lock:
            active = self._active_operation
            last = self._last_operation
            revision = self._revision
            value = dict(active or last or {"state": "IDLE", "operation_id": None})
        value["revision"] = revision
        return value

    async def operation_status(self, plugin_id: str) -> dict[str, object]:
        self._require_supported(plugin_id)
        operation = self._operation_snapshot()
        # The durable journal is authoritative after a process restart. A
        # disconnected caller must reconcile both the operation and plugin state.
        status = await self.status(plugin_id)
        return {
            "plugin_id": plugin_id,
            "revision": max(int(operation["revision"]), status.revision),
            "operation": operation,
            "plugin_state": status.state,
            "recovery_required": status.state == "RECOVERY_REQUIRED",
            "rollback": status.rollback,
        }

    def _rollback_readiness(self, status: ObsPluginStatus, runtime: Any) -> dict[str, object]:
        unavailable = lambda reason: {"available": False, "target_version": None, "reason": reason}
        if status.state == "RECOVERY_REQUIRED":
            return unavailable("recovery_required")
        if status.state in {"UNMANAGED", "LEGACY_ADOPTED", "NOT_INSTALLED", "FAILED", "INCOMPATIBLE"}:
            return unavailable("no_approved_transaction")
        if runtime.output.get("streaming") is True:
            return unavailable("obs_busy_streaming")
        if runtime.output.get("recording") is True:
            return unavailable("obs_busy_recording")
        if self._operation_lock.locked():
            return unavailable("operation_in_progress")
        getter = getattr(self.host, "rollback_readiness", None)
        if not callable(getter):
            return unavailable("baseline_unavailable")
        try:
            result = getter()
            if (isinstance(result, dict) and isinstance(result.get("available"), bool)
                    and (result.get("reason") is None or isinstance(result.get("reason"), str))
                    and (result.get("target_version") is None or isinstance(result.get("target_version"), str))):
                return {k: result.get(k) for k in ("available", "target_version", "reason")}
        except Exception:
            pass
        return unavailable("baseline_unavailable")

    async def status(self, plugin_id: str) -> ObsPluginStatus:
        self._require_supported(plugin_id)
        status = await asyncio.to_thread(self._status_sync)
        observed = status.api_payload()
        observed.pop("revision", None)
        observed.pop("operation", None)
        self._observe("status", observed)
        return replace(status, revision=self._operation_snapshot()["revision"])

    async def inventory(self) -> list[ObsPluginStatus]:
        """Return only registry-approved plugin statuses for Plugin Manager."""
        return [await self.status(plugin_id) for plugin_id in (PLUGIN_ID,)]


    async def available(self) -> dict[str, object]:
        """Server-approved published plugin catalog (not the registry inventory)."""
        result = await asyncio.to_thread(self._available_sync)
        self._observe("catalog", result)
        return result

    def _available_sync(self) -> dict[str, object]:
        if self.release_source is None:
            return {"plugins": [], "source_state": "UNCONFIGURED"}
        try:
            # Catalog may show an approved but incompatible release; mutation
            # still resolves via latest(), which strictly enforces OBS version.
            release = self.release_source.catalog_release(PLUGIN_ID)
        except ObsPluginError as exc:
            if exc.code == "plugin_release_unavailable":
                return {"plugins": [], "source_state": "EMPTY"}
            raise
        current = self._status_sync()
        installed_version = current.installed_version
        def version_parts(version: str | None) -> tuple[int, ...]:
            if not version or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", version):
                return ()
            return tuple(int(v) for v in version.split("."))
        compatible = bool(
            release.platform == "windows" and release.architecture == "x64"
            and release.obs_version == EXPECTED_OBS_VERSION and current.compatible
        )
        unsafe_state = current.state in {"UNMANAGED", "RECOVERY_REQUIRED", "FAILED", "VERIFY_FAILED"}
        can_install = bool(
            compatible and not unsafe_state and
            (not current.installed or current.state == "LEGACY_ADOPTED" or
             version_parts(release.version) > version_parts(installed_version))
        )
        reason = None
        if not compatible:
            reason = "incompatible_obs"
        elif current.state == "UNMANAGED":
            reason = "adoption_required"
        elif current.state == "RECOVERY_REQUIRED":
            reason = "recovery_required"
        elif current.state in {"FAILED", "VERIFY_FAILED"}:
            reason = "state_conflict"
        elif current.installed and not can_install:
            reason = "already_installed"
        return {
            "plugins": [{
                "plugin_id": PLUGIN_ID, "display_name": current.display_name,
                "available_version": release.version,
                "installed_version": installed_version,
                "compatibility": "compatible" if compatible else "incompatible",
                "installable": can_install,
                "reason": reason,
                "source_commit": release.source_commit,
                "release_ref": f"{PLUGIN_ID}/v{release.version}",
            }],
            "source_state": "READY",
        }

    async def install(self, plugin_id: str) -> ObsPluginOperationResult:
        self._require_supported(plugin_id)
        return await self._mutation("install", self._install_sync)

    async def adopt(self, plugin_id: str) -> ObsPluginOperationResult:
        self._require_supported(plugin_id)
        return await self._mutation("adopt", self._adopt_sync)

    async def update(self, plugin_id: str) -> ObsPluginOperationResult:
        self._require_supported(plugin_id)
        return await self._mutation("update", self._update_sync)

    async def verify(self, plugin_id: str) -> ObsPluginOperationResult:
        self._require_supported(plugin_id)
        return await self._mutation("verify", self._verify_sync)

    async def rollback(self, plugin_id: str) -> ObsPluginOperationResult:
        self._require_supported(plugin_id)
        return await self._mutation("rollback", self._rollback_sync)

    async def _mutation(self, operation: str, callback: Any) -> ObsPluginOperationResult:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._run_guarded, operation, callback),
                timeout=self.operation_timeout,
            )
        except asyncio.TimeoutError as exc:
            # The timed-out worker may still own the mutation lock. Never
            # start a second operation until the original worker exits.
            raise ObsPluginError(
                "plugin_operation_timeout",
                "OBS plugin operation timed out; inspect status before retrying.",
                504,
            ) from exc

    def _require_supported(self, plugin_id: str) -> None:
        if plugin_id != PLUGIN_ID:
            raise ObsPluginError("plugin_not_supported", "The requested OBS plugin is not supported.", 404)

    def _run_guarded(self, operation: str, callback: Any) -> ObsPluginOperationResult:
        if not self._operation_lock.acquire(blocking=False):
            raise ObsPluginError(
                "plugin_state_conflict", "Another OBS plugin operation is already running.", 409
            )
        operation_id = uuid.uuid4().hex
        with self._change_lock:
            self._active_operation = {
                "state": "RUNNING", "operation": operation,
                "operation_id": operation_id,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        self._changed("operation")
        try:
            result = callback()
        except BaseException as exc:
            # Store a stable code, never raw exceptions (which can contain keys).
            with self._change_lock:
                self._last_operation = {
                    **self._active_operation, "state": "FAILED",
                    "error_code": exc.code if isinstance(exc, ObsPluginError) else "internal_error",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                }
                self._active_operation = None
            self._changed("operation")
            raise
        else:
            with self._change_lock:
                self._last_operation = {
                    **self._active_operation, "state": "SUCCEEDED",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                }
                self._active_operation = None
            self._changed("operation")
            return result
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
        status = self._combine(host, runtime)
        rollback = self._rollback_readiness(status, runtime)
        return replace(
            status, rollback=rollback,
            rollback_available=bool(rollback["available"]),
            rollback_reason=rollback["reason"],
            revision=int(self._operation_snapshot()["revision"]),
            operation=self._operation_snapshot(),
        )

    def _combine(self, host: PluginHostStatus, runtime: Any) -> ObsPluginStatus:
        runtime_version = runtime.websocket.get("obs_version") if runtime.websocket else None
        compatible = host.compatible and runtime_version in (None, EXPECTED_OBS_VERSION)
        installed = host.installation != "absent"
        managed = host.installation in {"legacy_adopted", "approved_release_installed", "exact"}
        adoptable = host.installation == "unmanaged"
        approved = host.installation in {"approved_release_installed", "exact"}
        loaded = bool(
            approved
            and host.loaded
            and host.loaded_version == (getattr(host, "installed_version", None) or EXPECTED_VERSION)
            and runtime.state == "READY"
            and runtime.websocket.get("connected") is True
        )
        installed_version = getattr(host, "installed_version", None) if approved else None
        available_version = getattr(host, "available_version", None)
        def as_version(value: str | None) -> tuple[int, ...]:
            if not value or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", value):
                return ()
            return tuple(map(int, value.split(".")))
        update_available = bool(
            installed_version and available_version
            and as_version(available_version) > as_version(installed_version)
        )
        if host.installation == "recovery_required":
            state: PluginState = "RECOVERY_REQUIRED"
        elif host.installation == "unmanaged":
            state = "UNMANAGED"
        elif host.installation == "legacy_adopted":
            state = "LEGACY_ADOPTED"
        elif not compatible:
            state = "INCOMPATIBLE"
        elif host.installation == "conflict":
            state = "FAILED"
        elif not installed:
            state = "NOT_INSTALLED"
        elif getattr(host, "restart_required", False) or self._pending_change:
            state = "RESTART_REQUIRED"
        elif self._verification_failed:
            state = "VERIFY_FAILED"
        elif update_available:
            state = "UPDATE_AVAILABLE"
        elif loaded:
            state = "VERIFIED"
        else:
            state = "INSTALLED"
        return ObsPluginStatus(
            PLUGIN_ID, EXPECTED_VERSION, state, installed, loaded, compatible,
            installed_version=installed_version,
            available_version=available_version,
            restart_required=bool(getattr(host, "restart_required", False) or self._pending_change),
            managed=managed, adoptable=adoptable,
            last_verification=self._verified_at if loaded else None,
        )

    def _adopt_sync(self) -> ObsPluginOperationResult:
        runtime = self._runtime_for_mutation()
        if runtime.state != "STOPPED":
            raise ObsPluginError(
                "plugin_adopt_requires_obs_stopped",
                "OBS must be stopped before adopting existing plugin files.", 409,
            )
        initial = self._combine(self.host.status(), runtime)
        if initial.state == "RECOVERY_REQUIRED":
            raise ObsPluginError("plugin_recovery_required", "An unfinished plugin transaction requires recovery.", 409)
        if not initial.installed:
            raise ObsPluginError("plugin_not_installed", "No existing OBS plugin is available to adopt.", 409)
        lower = self._host_call("adopt")
        status = self._status_sync()
        return ObsPluginOperationResult(status, "adopt", lower.result)

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
        if initial.state == "UNMANAGED":
            raise ObsPluginError("plugin_adoption_required", "Existing plugin files must be explicitly adopted first.", 409)
        if initial.state == "RECOVERY_REQUIRED":
            raise ObsPluginError("plugin_recovery_required", "An unfinished plugin transaction requires recovery.", 409)
        self._ensure_compatible(initial)
        if self.defer_restart:
            if initial.loaded:
                return ObsPluginOperationResult(initial, "install", "already_installed")
            stopped = False
            try:
                if runtime.state == "READY":
                    self.obs_manager.stop()
                    stopped = True
                lower = self._host_call("install")
            except Exception:
                if stopped:
                    self._best_effort_start(None)
                raise
            self._pending_change = "install"
            self._verified_at = None
            self._verification_failed = False
            return ObsPluginOperationResult(
                replace(self._status_sync(), state="RESTART_REQUIRED", restart_required=True),
                "install", lower.result,
            )

        # The lower layer checks the exact manifest before requiring OBS to stop.
        if initial.installed and initial.state != "LEGACY_ADOPTED":
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

    def _update_sync(self) -> ObsPluginOperationResult:
        runtime = self._runtime_for_mutation()
        initial = self._combine(self.host.status(), runtime)
        if initial.state == "UNMANAGED":
            raise ObsPluginError("plugin_adoption_required", "Existing plugin files must be explicitly adopted first.", 409)
        if initial.state == "LEGACY_ADOPTED":
            raise ObsPluginError("plugin_state_conflict", "Install the first approved release before updating.", 409)
        if initial.state == "RECOVERY_REQUIRED":
            raise ObsPluginError("plugin_recovery_required", "An unfinished plugin transaction requires recovery.", 409)
        if not initial.installed:
            raise ObsPluginError("plugin_not_installed", "The OBS plugin must be installed before it can be updated.", 409)
        self._ensure_compatible(initial)
        if self.defer_restart:
            stopped = False
            try:
                if runtime.state == "READY":
                    self.obs_manager.stop()
                    stopped = True
                lower = self._host_call("update")
            except Exception:
                if stopped:
                    self._best_effort_start(None)
                raise
            self._pending_change = "update"
            self._verified_at = None
            self._verification_failed = False
            return ObsPluginOperationResult(
                replace(self._status_sync(), state="RESTART_REQUIRED", restart_required=True),
                "update", lower.result, previous_version=initial.installed_version,
            )
        stopped = False
        updated = False
        try:
            if runtime.state == "READY":
                self.obs_manager.stop()
                stopped = True
            lower = self._host_call("update")
            updated = lower.result == "updated"
            self._start_obs()
            verified = self._verify_loaded()
            return ObsPluginOperationResult(
                verified, "update", lower.result, previous_version=initial.installed_version
            )
        except Exception:
            if updated:
                self._recover_failed_install()
            elif stopped:
                self._best_effort_start(None)
            raise

    def _verify_sync(self) -> ObsPluginOperationResult:
        try:
            status = self._verify_loaded()
        except ObsPluginError:
            self._verification_failed = True
            if self.defer_restart and self._pending_change in {"install", "update"}:
                self._recover_failed_install()
                self._pending_change = None
            raise
        # _verify_loaded() builds its snapshot while the prior pending/failure
        # markers are still set. Clear them before recomputing the public state,
        # otherwise a successful vendor probe still reports RESTART_REQUIRED or
        # VERIFY_FAILED.
        self._pending_change = None
        self._verification_failed = False
        self._verified_at = datetime.now(timezone.utc).isoformat()
        verified = self._status_sync()
        return ObsPluginOperationResult(
            replace(verified, last_verification=self._verified_at, restart_required=False),
            "verify", "verified",
        )

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
        if not status.loaded:
            raise ObsPluginError(
                "plugin_verify_failed", "The pinned plugin module is not loaded by the current OBS process.", 409
            )
        self._verify_vendor()
        return status

    @staticmethod
    def _vendor_probe_failure(reason: str) -> ObsPluginError:
        """Expose only a fixed diagnostic reason; never propagate vendor payloads.

        OBS may include RTMP URLs or stream keys in request errors and target
        objects. Do not log exceptions or serialize the vendor response.
        The existing plugin_verify_failed code preserves the FE/API contract.
        """
        allowed = {
            "connection_failed", "request_rejected", "request_failed",
            "response_invalid", "vendor_response_missing", "vendor_error",
            "targets_invalid",
        }
        safe_reason = reason if reason in allowed else "request_failed"
        return ObsPluginError(
            "plugin_verify_failed",
            f"OBS multi-RTMP vendor readiness probe failed ({safe_reason}).",
            409,
        )

    def _verify_vendor(self) -> None:
        """Probe OBS vendor readiness without logging targets, URLs or keys."""
        factory = getattr(self.obs_manager, "client_factory", None)
        if factory is None:
            # Test doubles have no OBS socket; real ObsManager always exposes one.
            return
        client = None
        phase = "connect"
        try:
            client = factory()
            client.connect()
            phase = "request"
            reply = client.request("CallVendorRequest", {
                "vendorName": "sorayuki.multi_rtmp",
                "requestType": "list_targets",
                "requestData": {},
            })
        except ObsWebSocketConnectionError:
            raise self._vendor_probe_failure("connection_failed") from None
        except ObsWebSocketRequestError:
            raise self._vendor_probe_failure("request_rejected") from None
        except Exception:
            reason = "connection_failed" if phase == "connect" else "request_failed"
            raise self._vendor_probe_failure(reason) from None
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    # Closing a diagnostic connection cannot invalidate a valid
                    # vendor response or leak arbitrary OBS exception text.
                    pass

        if not isinstance(reply, dict):
            raise self._vendor_probe_failure("response_invalid")
        vendor = reply.get("vendorResponseData")
        if not isinstance(vendor, dict):
            raise self._vendor_probe_failure("vendor_response_missing")
        if vendor.get("error"):
            # Never include the free-form plugin error in the public response.
            raise self._vendor_probe_failure("vendor_error")
        if not isinstance(vendor.get("targets"), list):
            raise self._vendor_probe_failure("targets_invalid")

    def _rollback_sync(self) -> ObsPluginOperationResult:
        runtime = self._runtime_for_mutation()
        current = self._combine(self.host.status(), runtime)
        if current.state in {"ERROR", "FAILED"}:
            raise ObsPluginError(
                "plugin_state_conflict", "Rollback refused because installed plugin files were modified.", 409
            )
        if current.state == "RECOVERY_REQUIRED" and runtime.state != "STOPPED":
            raise ObsPluginError(
                "plugin_recovery_requires_obs_stopped",
                "Stop OBS via the Process API before recovering an unfinished plugin transaction.", 409,
            )
        if self.defer_restart:
            stopped = False
            try:
                if runtime.state == "READY":
                    self.obs_manager.stop()
                    stopped = True
                lower = self._host_call("rollback")
            except Exception:
                if stopped:
                    self._best_effort_start(None)
                raise
            self._pending_change = "rollback"
            self._verified_at = None
            self._verification_failed = False
            return ObsPluginOperationResult(
                replace(self._status_sync(), restart_required=True),
                "rollback", lower.result,
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

    def _host_call(self, action: Literal["adopt", "install", "update", "rollback"]) -> PluginHostResult:
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
            code = {"adopt": "plugin_adopt_failed", "install": "plugin_install_failed", "update": "plugin_update_failed", "rollback": "plugin_rollback_failed"}[action]
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
