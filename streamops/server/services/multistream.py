"""Shared multistream core used by both HTTP and WebSocket transports."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import threading
import time
from typing import Any
from urllib.parse import urlparse

from ..errors import StreamingError
from ..multistream import MultiRtmpAdapter, MultistreamEventBus, MultistreamRepository, MultistreamSecretStore


STATES = {"IDLE", "STARTING", "LIVE", "RECONNECTING", "STOPPING", "FAILED"}
ACTIVE_STATES = {"STARTING", "LIVE", "RECONNECTING", "STOPPING"}


class MultistreamService:
    def __init__(
        self,
        repository: MultistreamRepository,
        adapter: MultiRtmpAdapter,
        secrets: MultistreamSecretStore | None = None,
        *,
        poll_interval: float = 0.25,
        transition_timeout: float = 15.0,
    ) -> None:
        self.repository = repository
        self.adapter = adapter
        self.secrets = secrets or MultistreamSecretStore(repository.root.with_name("multistream-secrets"))
        self.events = MultistreamEventBus()
        self.poll_interval = poll_interval
        self.transition_timeout = transition_timeout
        self._states: dict[str, dict[str, Any]] = {}
        self._deadlines: dict[str, float] = {}
        self._lock = threading.RLock()
        self._monitor: asyncio.Task[None] | None = None
        self._available: bool | None = None

    async def start(self) -> None:
        if self._monitor is not None:
            return
        try:
            await asyncio.to_thread(self.reconcile)
            await asyncio.to_thread(self.refresh)
        except StreamingError:
            self._available = False
        self._monitor = asyncio.create_task(self._monitor_loop(), name="multistream-monitor")

    async def close(self) -> None:
        task, self._monitor = self._monitor, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def subscribe(self, listener: Callable[[dict[str, Any]], None]) -> None:
        self.events.subscribe(listener)

    def unsubscribe(self, listener: Callable[[dict[str, Any]], None]) -> None:
        self.events.unsubscribe(listener)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "destinations": [
                    self._public_runtime(item, self._cached(item)) for item in self.repository.list()
                ]
            }

    def list_destinations(self) -> dict[str, Any]:
        self.refresh(raise_unavailable=False)
        return self.snapshot()

    def get_destination(self, destination_id: str) -> dict[str, Any]:
        item = self.repository.get(destination_id)
        self.refresh_destination(item, raise_unavailable=False)
        return self._public_runtime(item, self._cached(item))

    def create_destination(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            item, credential = self._normalize_create(payload)
            destination_id = item["destination_id"]
            if self.repository.exists(destination_id):
                raise StreamingError("destination_conflict", "Multistream destination already exists.", 409)
            if any(existing["name"].casefold() == item["name"].casefold() for existing in self.repository.list()):
                raise StreamingError("destination_conflict", "Multistream destination name already exists.", 409)
            target_id: str | None = None
            try:
                self._vendor(self.adapter.add_target, item["name"])
                target = self._unique_target(item["name"])
                target_id = str(target["id"])
                item["plugin_target_id"] = target_id
                self._vendor(self.adapter.update_server, target_id, item["server_url"])
                self._vendor(self.adapter.update_stream_key, target_id, credential, secrets=(credential,))
                self.secrets.set(destination_id, credential)
                self.repository.save(item, create=True)
            except Exception:
                self.secrets.delete(destination_id)
                if target_id:
                    try:
                        self.adapter.delete_target(target_id)
                    except Exception:
                        pass
                raise
            runtime = {"state": "IDLE", "vendor_status": ""}
            self._states[destination_id] = runtime
            result = self._public_runtime(item, runtime)
            self._emit("destination.created", item, result)
            return result

    def update_destination(self, destination_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            old = self.repository.get(destination_id)
            runtime = self.refresh_destination(old, raise_unavailable=False)
            if runtime["state"] in ACTIVE_STATES:
                raise StreamingError("destination_active", "Stop the destination before updating it.", 409)
            item, credential = self._normalize_update(old, payload)
            if any(
                existing["destination_id"] != destination_id
                and existing["name"].casefold() == item["name"].casefold()
                for existing in self.repository.list()
            ):
                raise StreamingError("destination_conflict", "Multistream destination name already exists.", 409)
            target_id = item["plugin_target_id"]
            if item["name"] != old["name"]:
                self._vendor(self.adapter.update_name, target_id, item["name"])
            if item["server_url"] != old["server_url"]:
                self._vendor(self.adapter.update_server, target_id, item["server_url"])
            if credential is not None:
                self._vendor(self.adapter.update_stream_key, target_id, credential, secrets=(credential,))
                self.secrets.set(destination_id, credential)
            self.repository.save(item)
            result = self._public_runtime(item, runtime)
            self._emit("destination.updated", item, result)
            return result

    def delete_destination(self, destination_id: str) -> dict[str, bool]:
        with self._lock:
            item = self.repository.get(destination_id)
            runtime = self.refresh_destination(item, raise_unavailable=False)
            if runtime["state"] in ACTIVE_STATES:
                raise StreamingError("destination_active", "Stop the destination before deleting it.", 409)
            self._vendor(self.adapter.delete_target, item["plugin_target_id"])
            self.repository.delete(destination_id)
            self.secrets.delete(destination_id)
            self._states.pop(destination_id, None)
            self._deadlines.pop(destination_id, None)
            self._emit("destination.deleted", item, {"deleted": True})
            return {"deleted": True}

    def start_destination(self, destination_id: str) -> dict[str, Any]:
        with self._lock:
            item = self.repository.get(destination_id)
            if not item["enabled"]:
                raise StreamingError("destination_disabled", "Destination is disabled.", 409)
            current = self.refresh_destination(item)
            if current["state"] in {"STARTING", "LIVE", "RECONNECTING"}:
                return self._public_runtime(item, current)
            self._set_state(item, {"state": "STARTING", "vendor_status": "start_requested"})
            self._deadlines[destination_id] = time.monotonic() + self.transition_timeout
            try:
                self._vendor(self.adapter.start, item["plugin_target_id"])
            except StreamingError as exc:
                self._set_state(item, {"state": "FAILED", "vendor_status": exc.code})
                self._emit("destination.error", item, {"code": exc.code, "message": str(exc)})
                raise
            return self._public_runtime(item, self._cached(item))

    def stop_destination(self, destination_id: str) -> dict[str, Any]:
        with self._lock:
            item = self.repository.get(destination_id)
            current = self.refresh_destination(item)
            if current["state"] == "IDLE":
                return self._public_runtime(item, current)
            if current["state"] == "STOPPING":
                return self._public_runtime(item, current)
            self._set_state(item, {"state": "STOPPING", "vendor_status": "stop_requested"})
            self._deadlines[destination_id] = time.monotonic() + self.transition_timeout
            try:
                self._vendor(self.adapter.stop, item["plugin_target_id"])
            except StreamingError as exc:
                self._set_state(item, {"state": "FAILED", "vendor_status": exc.code})
                self._emit("destination.error", item, {"code": exc.code, "message": str(exc)})
                raise
            return self._public_runtime(item, self._cached(item))

    def status(self, destination_id: str) -> dict[str, Any]:
        item = self.repository.get(destination_id)
        return self._public_runtime(item, self.refresh_destination(item))

    def stats(self, destination_id: str) -> dict[str, Any]:
        item = self.repository.get(destination_id)
        raw = self._vendor(self.adapter.stats, item["plugin_target_id"])
        metrics = {
            "total_bytes": self._number(raw.get("totalBytes", raw.get("bytesSent", 0))),
            "total_frames": self._number(raw.get("totalFrames", raw.get("frames", 0))),
            "bitrate_bps": self._number(raw.get("bitrateValue", raw.get("bitrate_bps", 0))),
            "fps": self._number(raw.get("fpsValue", raw.get("fps", 0))),
        }
        result = {
            "destination_id": item["destination_id"],
            "state": self._normalize_runtime(raw)["state"],
            "stats": metrics,
        }
        self._emit("destination.stats_updated", item, result)
        return result

    def reconcile(self) -> dict[str, Any]:
        with self._lock:
            targets = self._vendor(self.adapter.list_targets)
            by_id = {str(target.get("id")): target for target in targets if target.get("id") is not None}
            changed: list[str] = []
            for item in self.repository.list():
                if item.get("plugin_target_id") in by_id:
                    continue
                matches = [target for target in targets if target.get("name") == item["name"]]
                if len(matches) > 1:
                    raise StreamingError("vendor_identity_ambiguous", "Plugin target identity is ambiguous.", 409)
                if not matches:
                    self._vendor(self.adapter.add_target, item["name"])
                    targets = self._vendor(self.adapter.list_targets)
                    matches = [target for target in targets if target.get("name") == item["name"]]
                if len(matches) != 1:
                    raise StreamingError("vendor_reconcile_failed", "Could not reconcile plugin target.", 503)
                target_id = str(matches[0]["id"])
                self._vendor(self.adapter.update_server, target_id, item["server_url"])
                credential = self.secrets.get(item["destination_id"])
                self._vendor(self.adapter.update_stream_key, target_id, credential, secrets=(credential,))
                item["plugin_target_id"] = target_id
                self.repository.save(item)
                changed.append(item["destination_id"])
            self._available = True
            return {"reconciled": changed}

    def refresh(self, *, raise_unavailable: bool = True) -> None:
        for item in self.repository.list():
            try:
                self.refresh_destination(item)
            except StreamingError:
                if raise_unavailable:
                    raise

    def refresh_destination(self, item: dict[str, Any], *, raise_unavailable: bool = True) -> dict[str, Any]:
        try:
            raw = self._vendor(self.adapter.state, item["plugin_target_id"])
            runtime = self._normalize_runtime(raw)
            self._available = True
        except StreamingError:
            self._available = False
            if raise_unavailable:
                raise
            return self._cached(item)
        destination_id = item["destination_id"]
        cached = self._cached(item)
        deadline = self._deadlines.get(destination_id)
        stale_during_transition = (
            cached["state"] == "STARTING" and runtime["state"] in {"IDLE", "STARTING"}
        ) or (
            cached["state"] == "STOPPING"
            and runtime["state"] in {"STARTING", "LIVE", "RECONNECTING", "STOPPING"}
        )
        if stale_during_transition:
            if deadline is not None and time.monotonic() >= deadline:
                runtime = {"state": "FAILED", "vendor_status": "transition_timeout"}
            else:
                # The Vendor operation is asynchronous. Immediately after its ACK the
                # status endpoint can still return the pre-command state; retaining the
                # Core-owned transition prevents STARTING/STOPPING from bouncing back.
                runtime = cached
        self._set_state(item, runtime)
        if runtime["state"] not in {"STARTING", "STOPPING"}:
            self._deadlines.pop(destination_id, None)
        return runtime

    async def _monitor_loop(self) -> None:
        while True:
            await asyncio.sleep(self.poll_interval)
            was_available = self._available
            try:
                if was_available is False:
                    await asyncio.to_thread(self.reconcile)
                await asyncio.to_thread(self.refresh)
            except StreamingError:
                self._available = False

    def _set_state(self, item: dict[str, Any], runtime: dict[str, Any]) -> None:
        destination_id = item["destination_id"]
        previous = self._states.get(destination_id, {"state": "IDLE", "vendor_status": ""})
        self._states[destination_id] = runtime
        if previous["state"] != runtime["state"]:
            self._emit(
                "destination.state_changed",
                item,
                {"previous_state": previous["state"], "state": runtime["state"]},
            )

    def _emit(self, event: str, item: dict[str, Any], data: dict[str, Any]) -> None:
        self.events.publish(event, item["destination_id"], self._sanitize(data))

    def _cached(self, item: dict[str, Any]) -> dict[str, Any]:
        return self._states.get(item["destination_id"], {"state": "IDLE", "vendor_status": ""})

    def _unique_target(self, name: str) -> dict[str, Any]:
        matches = [target for target in self._vendor(self.adapter.list_targets) if target.get("name") == name]
        if len(matches) != 1:
            raise StreamingError("vendor_identity_ambiguous", "Expected exactly one plugin target for destination.", 409)
        return matches[0]

    def _normalize_create(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        self._reject_extras(payload, {"destination_id", "name", "server_url", "enabled", "credential"})
        credential = payload.get("credential")
        if not isinstance(credential, str) or not credential.strip() or len(credential) > 4096 or "\x00" in credential:
            raise StreamingError("credential_invalid", "credential must be a non-empty string of at most 4096 characters.", 422)
        return self._normalize_public(payload), credential.strip()

    def _normalize_update(self, old: dict[str, Any], payload: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        self._reject_extras(payload, {"name", "server_url", "enabled", "credential"})
        credential = payload.get("credential")
        if "credential" in payload and (
            not isinstance(credential, str) or not credential.strip() or len(credential) > 4096 or "\x00" in credential
        ):
            raise StreamingError("credential_invalid", "credential must be a non-empty string of at most 4096 characters.", 422)
        public = {**self._public(old), **{key: value for key, value in payload.items() if key != "credential"}}
        item = self._normalize_public(public)
        item["plugin_target_id"] = old["plugin_target_id"]
        return item, credential.strip() if isinstance(credential, str) else None

    def _normalize_public(self, payload: dict[str, Any]) -> dict[str, Any]:
        destination_id = payload.get("destination_id")
        name = payload.get("name")
        server_url = payload.get("server_url")
        enabled = payload.get("enabled", True)
        if not isinstance(destination_id, str):
            raise StreamingError("destination_invalid", "destination_id is required.", 422)
        self.repository._path(destination_id)
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 128:
            raise StreamingError("destination_invalid", "name must be a non-empty string of at most 128 characters.", 422)
        parsed = urlparse(server_url) if isinstance(server_url, str) else None
        if parsed is None or parsed.scheme not in {"rtmp", "rtmps"} or not parsed.hostname or parsed.username or parsed.password:
            raise StreamingError("destination_invalid", "server_url must be an rtmp/rtmps URL without user credentials.", 422)
        if type(enabled) is not bool:
            raise StreamingError("destination_invalid", "enabled must be boolean.", 422)
        return {"destination_id": destination_id, "name": name.strip(), "server_url": server_url, "enabled": enabled}

    @staticmethod
    def _reject_extras(payload: dict[str, Any], allowed: set[str]) -> None:
        extras = set(payload) - allowed
        if extras:
            raise StreamingError("destination_invalid", f"Unknown field(s): {', '.join(sorted(extras))}", 422)

    @staticmethod
    def _normalize_runtime(raw: dict[str, Any]) -> dict[str, Any]:
        runtime_state = str(raw.get("runtimeState") or "").upper()
        if runtime_state in STATES:
            state = runtime_state
        else:
            status = str(raw.get("status") or raw.get("rawStatus") or "")
            failed = bool(raw.get("runtimeError")) or any(word in status.casefold() for word in ("fail", "error"))
            state = "FAILED" if failed else ("LIVE" if bool(raw.get("isRunning", raw.get("streaming", False))) else "IDLE")
        return {"state": state, "vendor_status": str(raw.get("status") or raw.get("rawStatus") or runtime_state)}

    @staticmethod
    def _public(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "destination_id": item["destination_id"],
            "name": item["name"],
            "server_url": item["server_url"],
            "enabled": item["enabled"],
        }

    def _public_runtime(self, item: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
        return {**self._public(item), "state": runtime["state"]}

    @staticmethod
    def _number(value: Any) -> int | float:
        if isinstance(value, bool):
            return 0
        if isinstance(value, int | float):
            return value
        try:
            return float(str(value).split()[0])
        except (ValueError, IndexError):
            return 0

    @staticmethod
    def _sanitize(value: Any, secrets: tuple[str, ...] = ()) -> Any:
        sensitive = {"key", "token", "password", "credential", "streamkey", "stream_key", "newstreamkey"}
        if isinstance(value, dict):
            return {
                key: "[REDACTED]" if key.replace("-", "_").casefold() in sensitive else MultistreamService._sanitize(item, secrets)
                for key, item in value.items()
                if key != "plugin_target_id"
            }
        if isinstance(value, list):
            return [MultistreamService._sanitize(item, secrets) for item in value]
        if isinstance(value, str):
            for secret in secrets:
                if secret:
                    value = value.replace(secret, "[REDACTED]")
        return value

    def _vendor(self, operation: Callable[..., Any], *args: Any, secrets: tuple[str, ...] = ()) -> Any:
        try:
            return operation(*args)
        except StreamingError as exc:
            message = str(self._sanitize(str(exc), secrets))
            raise StreamingError(exc.code, message, exc.status_code) from None
        except Exception:
            raise StreamingError("multistream_service_unavailable", "OBS multistream service is unavailable.", 503) from None
