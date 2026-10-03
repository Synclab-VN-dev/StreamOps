"""Livestream orchestration shared by REST and WebSocket transports."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import threading
from typing import Any
from uuid import uuid4

from ..errors import StreamingError
from ..obs.client import ObsClient
from ..streaming import DestinationStore, LiveSessionStore, SecretStore
from ..streaming.adapters import destination_type_catalog, get_destination_adapter
from ..streaming.outputs import ObsNativeOutputEngine


class LiveService:
    def __init__(
        self,
        manager: Any,
        scene_service: Any,
        destination_store: DestinationStore,
        secret_store: SecretStore,
        *,
        client_factory: type[ObsClient] | Any = ObsClient,
        output_engine_factory: type[ObsNativeOutputEngine] | Any = ObsNativeOutputEngine,
        session_store: LiveSessionStore | None = None,
        start_timeout: float = 12.0,
        stop_timeout: float = 12.0,
        poll_interval: float = 0.25,
    ) -> None:
        self.manager = manager
        self.scene_service = scene_service
        self.destination_store = destination_store
        self.secret_store = secret_store
        self.client_factory = client_factory
        self.output_engine_factory = output_engine_factory
        self.session_store = session_store or LiveSessionStore(
            destination_store.root.parent / "live-session"
        )
        self.start_timeout = start_timeout
        self.stop_timeout = stop_timeout
        self.poll_interval = poll_interval
        self._lock = threading.RLock()
        self._session = self.session_store.load_session()
        self._transition: str | None = None

    def destination_types(self) -> dict[str, Any]:
        return {"types": destination_type_catalog()}

    # Destination CRUD is intentionally owned here so REST and WS share behavior.
    def list_destinations(self) -> dict[str, Any]:
        result = self.destination_store.list()
        return {
            "destinations": [self._public_destination(item) for item in result["destinations"]],
            "errors": result["errors"],
        }

    def get_destination(self, destination_id: str) -> dict[str, Any]:
        return self._public_destination(self.destination_store.get(destination_id))

    def create_destination(self, payload: dict[str, Any]) -> dict[str, Any]:
        destination = self.destination_store.create(payload)
        get_destination_adapter(destination["type"]).validate(destination)
        return self._public_destination(destination)

    def update_destination(self, destination_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._require_destination_mutable(destination_id)
            destination = self.destination_store.update(destination_id, payload)
            get_destination_adapter(destination["type"]).validate(destination)
            return self._public_destination(destination)

    def delete_destination(self, destination_id: str) -> None:
        with self._lock:
            self._require_destination_mutable(destination_id)
            self.destination_store.delete(destination_id)
            self.secret_store.delete(destination_id)

    def set_credential(self, destination_id: str, credential: str) -> dict[str, bool]:
        with self._lock:
            self._require_destination_mutable(destination_id)
            self.destination_store.get(destination_id)
            self.secret_store.set(destination_id, credential)
            return {"credential_configured": True}

    def delete_credential(self, destination_id: str) -> dict[str, bool]:
        with self._lock:
            self._require_destination_mutable(destination_id)
            self.destination_store.get(destination_id)
            self.secret_store.delete(destination_id)
            return {"credential_configured": False}

    def preflight(self, profile_id: str, destination_id: str) -> dict[str, Any]:
        checks: list[dict[str, str]] = []

        runtime = self.manager.status()
        obs_ready = getattr(runtime, "state", None) == "READY"
        checks.append(
            _check(
                "obs_ready",
                obs_ready,
                "OBS is ready."
                if obs_ready
                else f"OBS runtime is {getattr(runtime, 'state', 'UNKNOWN')}.",
            )
        )

        profile = None
        try:
            profile = self.scene_service.get_profile(profile_id)
            checks.append(
                _check("profile", True, f"Profile {profile.get('name', profile_id)} exists.")
            )
        except Exception:
            checks.append(_check("profile", False, "Selected scene profile does not exist."))

        destination = None
        try:
            destination = self.destination_store.get(destination_id)
            get_destination_adapter(destination["type"]).validate(destination)
            checks.append(_check("destination", True, f"Destination {destination['name']} is valid."))
        except StreamingError:
            checks.append(
                _check("destination", False, "Selected stream destination is invalid or missing.")
            )

        if destination is not None:
            checks.append(
                _check(
                    "destination_enabled",
                    bool(destination["enabled"]),
                    "Destination is enabled."
                    if destination["enabled"]
                    else "Destination is disabled.",
                )
            )
            configured = self.secret_store.exists(destination_id)
            checks.append(
                _check(
                    "credential",
                    configured,
                    "Credential is configured."
                    if configured
                    else "Stream credential is not configured.",
                )
            )
            if configured:
                try:
                    secret = self.secret_store.get(destination_id)
                    get_destination_adapter(destination["type"]).preflight(destination, secret)
                    checks.append(_check("destination_adapter", True, "Destination adapter is ready."))
                except StreamingError:
                    checks.append(
                        _check("destination_adapter", False, "Destination adapter preflight failed.")
                    )

        max_destinations = int(getattr(self.output_engine_factory, "max_destinations", 1))
        checks.append(
            _check(
                "output_engine",
                max_destinations >= 1,
                f"Output engine supports up to {max_destinations} destination(s).",
            )
        )

        if obs_ready and profile is not None:
            try:
                verify = self.scene_service.verify_profile(profile_id, runtime=True)
                passed = getattr(verify, "status", None) == "PASS"
                checks.append(
                    _check(
                        "profile_verify",
                        passed,
                        "Runtime profile verification passed."
                        if passed
                        else "Runtime profile verification failed.",
                    )
                )
            except Exception:
                checks.append(
                    _check("profile_verify", False, "Runtime profile verification failed.")
                )

        return {
            "status": "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL",
            "profile_id": profile_id,
            "destination_id": destination_id,
            "checks": checks,
        }

    def start(self, profile_id: str, destination_id: str) -> dict[str, Any]:
        with self._lock:
            self._require_obs_ready()
            client = self._client()
            engine = self._engine(client)
            try:
                current = engine.status()
                if bool(current.get("outputActive")):
                    if (
                        self._session
                        and self._session.get("profile_id") == profile_id
                        and self._session_destination_id() == destination_id
                    ):
                        return self._status_with_client(client, current)
                    raise StreamingError("stream_already_live", "OBS is already streaming.", 409)

                # Recover a previously managed session that survived a node restart
                # but whose OBS output is already inactive.
                if self._session or self.session_store.has_restore():
                    try:
                        engine.restore_previous()
                    except StreamingError:
                        self._mark_session("RESTORE_FAILED")
                        raise
                    self.session_store.clear_session()
                    self._session = None

                destination = self.destination_store.get(destination_id)
                if not destination["enabled"]:
                    raise StreamingError(
                        "destination_disabled", "Streaming destination is disabled.", 409
                    )
                credential = self.secret_store.get(destination_id)
                adapter = get_destination_adapter(destination["type"])
                resolved = adapter.resolve(destination, credential)

                verify = self.scene_service.verify_profile(profile_id, runtime=True)
                if getattr(verify, "status", None) != "PASS":
                    raise StreamingError(
                        "profile_verify_failed", "Runtime profile verification failed.", 409
                    )
                self.scene_service.activate_profile(profile_id)
                verify = self.scene_service.verify_profile(profile_id, runtime=True)
                if getattr(verify, "status", None) != "PASS":
                    raise StreamingError(
                        "profile_verify_failed",
                        "Runtime profile verification failed after activation.",
                        409,
                    )

                self._session = {
                    "schema_version": 1,
                    "session_id": str(uuid4()),
                    "state": "STARTING",
                    "profile_id": profile_id,
                    "destination_ids": [destination_id],
                    "started_at": _now(),
                }
                self.session_store.save_session(self._session)
                self._transition = "STARTING"

                try:
                    engine.prepare([resolved])
                    status = engine.start()
                except StreamingError as exc:
                    self._transition = None
                    if self.session_store.has_restore():
                        self._mark_session("RECOVERY_REQUIRED")
                    else:
                        self.session_store.clear_session()
                        self._session = None
                    raise exc

                self._transition = None
                self._mark_session("LIVE")
                return self._status_with_client(client, status)
            finally:
                client.close()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._require_obs_ready()
            client = self._client()
            engine = self._engine(client)
            try:
                current = engine.status()
                if bool(current.get("outputActive")):
                    self._transition = "STOPPING"
                    self._mark_session("STOPPING")
                    try:
                        current = engine.stop()
                    except StreamingError:
                        self._transition = None
                        self._mark_session("RECOVERY_REQUIRED")
                        raise

                try:
                    engine.restore_previous()
                except StreamingError:
                    self._transition = None
                    self._mark_session("RESTORE_FAILED")
                    raise

                self.session_store.clear_all()
                self._session = None
                self._transition = None
                return self._status_with_client(client, current, state_override="IDLE")
            finally:
                client.close()

    def status(self) -> dict[str, Any]:
        runtime = self.manager.status()
        if getattr(runtime, "state", None) != "READY":
            return {
                "state": "OBS_NOT_READY",
                "managed": bool(self._session),
                "profile": self._session_profile(),
                "destination": self._session_destination(),
                "output": {"active": False},
                "started_at": self._session.get("started_at") if self._session else None,
            }
        client = self._client()
        try:
            return self._status_with_client(client, client.get_stream_status())
        finally:
            client.close()

    def snapshot(self) -> dict[str, Any]:
        result = self.status()
        destinations = self.list_destinations()
        result["destinations"] = destinations["destinations"]
        result["destination_errors"] = destinations["errors"]
        return result

    def _status_with_client(
        self,
        client: Any,
        stream: dict[str, Any],
        *,
        state_override: str | None = None,
    ) -> dict[str, Any]:
        active = bool(stream.get("outputActive"))
        if state_override is not None:
            state = state_override
        elif self._transition is not None:
            state = self._transition
        elif active:
            state = "LIVE"
        elif self._session and self.session_store.has_restore():
            stored_state = self._session.get("state")
            state = (
                stored_state
                if stored_state in {"RESTORE_FAILED", "RECOVERY_REQUIRED"}
                else "RECOVERY_REQUIRED"
            )
        else:
            state = "IDLE"

        stats: dict[str, Any] = {}
        try:
            stats = client.get_stats()
        except Exception:
            pass
        return {
            "state": state,
            "managed": bool(self._session),
            "profile": self._session_profile(),
            "destination": self._session_destination(),
            "output": {
                "active": active,
                "reconnecting": bool(stream.get("outputReconnecting")),
                "duration_ms": int(stream.get("outputDuration") or 0),
                "bytes_sent": int(stream.get("outputBytes") or 0),
                "congestion": float(stream.get("outputCongestion") or 0.0),
                "skipped_frames": int(stream.get("outputSkippedFrames") or 0),
                "total_frames": int(stream.get("outputTotalFrames") or 0),
                "active_fps": float(stats.get("activeFps") or 0.0),
                "cpu_usage": float(stats.get("cpuUsage") or 0.0),
            },
            "started_at": self._session.get("started_at") if self._session else None,
        }

    def _require_obs_ready(self) -> None:
        runtime = self.manager.status()
        if getattr(runtime, "state", None) != "READY":
            raise StreamingError(
                "obs_not_ready",
                f"OBS runtime is {getattr(runtime, 'state', 'UNKNOWN')}.",
                409,
            )

    def _require_destination_mutable(self, destination_id: str) -> None:
        if not self._session or self._session_destination_id() != destination_id:
            return
        # A managed session owns its destination until session/restore metadata is
        # fully cleaned up. Do not infer mutability from a transient state label.
        raise StreamingError(
            "destination_in_use",
            "Streaming destination is locked by the active or recovering managed session.",
            409,
        )

    def _mark_session(self, state: str) -> None:
        if not self._session:
            return
        self._session["state"] = state
        self.session_store.save_session(self._session)

    def _public_destination(self, destination: dict[str, Any]) -> dict[str, Any]:
        public = deepcopy(destination)
        public["credential_configured"] = self.secret_store.exists(destination["id"])
        return public

    def _session_profile(self) -> dict[str, Any] | None:
        if not self._session:
            return None
        try:
            profile = self.scene_service.get_profile(self._session["profile_id"])
        except Exception:
            return {"id": self._session["profile_id"], "name": None}
        return {"id": profile["id"], "name": profile.get("name")}

    def _session_destination_id(self) -> str | None:
        if not self._session:
            return None
        destination_ids = self._session.get("destination_ids")
        if isinstance(destination_ids, list) and destination_ids:
            return destination_ids[0]
        value = self._session.get("destination_id")
        return value if isinstance(value, str) else None

    def _session_destination(self) -> dict[str, Any] | None:
        destination_id = self._session_destination_id()
        if destination_id is None:
            return None
        try:
            destination = self.destination_store.get(destination_id)
        except Exception:
            return {"id": destination_id, "name": None, "type": None}
        return {
            "id": destination["id"],
            "name": destination["name"],
            "type": destination["type"],
        }

    def _client(self) -> Any:
        factory = self.client_factory
        if hasattr(factory, "from_env"):
            return factory.from_env()
        return factory()

    def _engine(self, client: Any) -> Any:
        return self.output_engine_factory(
            client,
            self.session_store,
            start_timeout=self.start_timeout,
            stop_timeout=self.stop_timeout,
            poll_interval=self.poll_interval,
        )


def _check(identifier: str, passed: bool, message: str) -> dict[str, str]:
    return {"id": identifier, "status": "PASS" if passed else "FAIL", "message": message}


def _now() -> str:
    return datetime.now(UTC).isoformat()
