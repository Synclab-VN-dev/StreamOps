"""Livestream orchestration shared by REST and WebSocket transports."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import threading
import time
from typing import Any
from uuid import uuid4

from ..errors import StreamingError
from ..obs.client import ObsClient
from ..streaming import DestinationStore, SecretStore


class LiveService:
    def __init__(
        self,
        manager: Any,
        scene_service: Any,
        destination_store: DestinationStore,
        secret_store: SecretStore,
        *,
        client_factory: type[ObsClient] | Any = ObsClient,
        start_timeout: float = 12.0,
        stop_timeout: float = 12.0,
        poll_interval: float = 0.25,
    ) -> None:
        self.manager = manager
        self.scene_service = scene_service
        self.destination_store = destination_store
        self.secret_store = secret_store
        self.client_factory = client_factory
        self.start_timeout = start_timeout
        self.stop_timeout = stop_timeout
        self.poll_interval = poll_interval
        self._lock = threading.RLock()
        self._session: dict[str, Any] | None = None
        self._previous_service: dict[str, Any] | None = None
        self._transition: str | None = None

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
        return self._public_destination(self.destination_store.create(payload))

    def update_destination(self, destination_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._public_destination(self.destination_store.update(destination_id, payload))

    def delete_destination(self, destination_id: str) -> None:
        self.destination_store.delete(destination_id)
        self.secret_store.delete(destination_id)

    def set_credential(self, destination_id: str, credential: str) -> dict[str, bool]:
        self.destination_store.get(destination_id)
        self.secret_store.set(destination_id, credential)
        return {"credential_configured": True}

    def delete_credential(self, destination_id: str) -> dict[str, bool]:
        self.destination_store.get(destination_id)
        self.secret_store.delete(destination_id)
        return {"credential_configured": False}

    def preflight(self, profile_id: str, destination_id: str) -> dict[str, Any]:
        checks: list[dict[str, str]] = []

        runtime = self.manager.status()
        obs_ready = getattr(runtime, "state", None) == "READY"
        checks.append(_check("obs_ready", obs_ready, "OBS is ready." if obs_ready else f"OBS runtime is {getattr(runtime, 'state', 'UNKNOWN')}."))

        profile = None
        try:
            profile = self.scene_service.get_profile(profile_id)
            checks.append(_check("profile", True, f"Profile {profile.get('name', profile_id)} exists."))
        except Exception:
            checks.append(_check("profile", False, "Selected scene profile does not exist."))

        destination = None
        try:
            destination = self.destination_store.get(destination_id)
            checks.append(_check("destination", True, f"Destination {destination['name']} is valid."))
        except StreamingError:
            checks.append(_check("destination", False, "Selected stream destination is invalid or missing."))

        if destination is not None:
            checks.append(_check("destination_enabled", bool(destination["enabled"]), "Destination is enabled." if destination["enabled"] else "Destination is disabled."))
            configured = self.secret_store.exists(destination_id)
            checks.append(_check("credential", configured, "Credential is configured." if configured else "Stream credential is not configured."))

        if obs_ready and profile is not None:
            try:
                verify = self.scene_service.verify_profile(profile_id, runtime=True)
                passed = getattr(verify, "status", None) == "PASS"
                checks.append(_check("profile_verify", passed, "Runtime profile verification passed." if passed else "Runtime profile verification failed."))
            except Exception:
                checks.append(_check("profile_verify", False, "Runtime profile verification failed."))

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
            try:
                current = client.get_stream_status()
                if bool(current.get("outputActive")):
                    if self._session and self._session.get("profile_id") == profile_id and self._session.get("destination_id") == destination_id:
                        return self._status_with_client(client, current)
                    raise StreamingError("stream_already_live", "OBS is already streaming.", 409)

                destination = self.destination_store.get(destination_id)
                if not destination["enabled"]:
                    raise StreamingError("destination_disabled", "Streaming destination is disabled.", 409)
                credential = self.secret_store.get(destination_id)

                # Validate before mutation, then activate and verify once more before going live.
                verify = self.scene_service.verify_profile(profile_id, runtime=True)
                if getattr(verify, "status", None) != "PASS":
                    raise StreamingError("profile_verify_failed", "Runtime profile verification failed.", 409)
                self.scene_service.activate_profile(profile_id)
                verify = self.scene_service.verify_profile(profile_id, runtime=True)
                if getattr(verify, "status", None) != "PASS":
                    raise StreamingError("profile_verify_failed", "Runtime profile verification failed after activation.", 409)

                self._previous_service = deepcopy(client.get_stream_service_settings())
                self._transition = "STARTING"
                self._session = {
                    "session_id": str(uuid4()),
                    "profile_id": profile_id,
                    "destination_id": destination_id,
                    "started_at": _now(),
                }
                try:
                    client.set_stream_service_settings(
                        "rtmp_custom",
                        {
                            "server": destination["settings"]["server_url"],
                            "key": credential,
                            "use_auth": False,
                        },
                    )
                    client.start_stream()
                    status = self._wait_active(client, True, self.start_timeout)
                except StreamingError:
                    self._restore_previous_service(client)
                    self._session = None
                    self._transition = None
                    raise
                except Exception as exc:
                    self._restore_previous_service(client)
                    self._session = None
                    self._transition = None
                    raise StreamingError("stream_start_failed", "OBS failed to start streaming.", 503) from exc
                self._transition = None
                return self._status_with_client(client, status)
            finally:
                client.close()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._require_obs_ready()
            client = self._client()
            try:
                current = client.get_stream_status()
                if not bool(current.get("outputActive")):
                    self._restore_previous_service(client)
                    self._session = None
                    self._transition = None
                    return self._status_with_client(client, current)

                self._transition = "STOPPING"
                try:
                    client.stop_stream()
                    status = self._wait_active(client, False, self.stop_timeout)
                except StreamingError:
                    self._transition = None
                    raise
                except Exception as exc:
                    self._transition = None
                    raise StreamingError("stream_stop_failed", "OBS failed to stop streaming.", 503) from exc

                self._restore_previous_service(client)
                self._session = None
                self._transition = None
                return self._status_with_client(client, status)
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

    def _status_with_client(self, client: Any, stream: dict[str, Any]) -> dict[str, Any]:
        active = bool(stream.get("outputActive"))
        state = self._transition or ("LIVE" if active else "IDLE")
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
            raise StreamingError("obs_not_ready", f"OBS runtime is {getattr(runtime, 'state', 'UNKNOWN')}.", 409)

    def _wait_active(self, client: Any, expected: bool, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = client.get_stream_status()
            if bool(last.get("outputActive")) is expected:
                return last
            time.sleep(self.poll_interval)
        code = "stream_start_timeout" if expected else "stream_stop_timeout"
        message = "OBS did not become active before timeout." if expected else "OBS did not stop streaming before timeout."
        raise StreamingError(code, message, 504)

    def _restore_previous_service(self, client: Any) -> None:
        previous = self._previous_service
        self._previous_service = None
        if not previous:
            return
        service_type = previous.get("streamServiceType")
        settings = previous.get("streamServiceSettings")
        if isinstance(service_type, str) and isinstance(settings, dict):
            try:
                client.set_stream_service_settings(service_type, settings)
            except Exception:
                # The stream has already stopped; restoration failure must not expose
                # potentially sensitive service settings through an error message.
                pass

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

    def _session_destination(self) -> dict[str, Any] | None:
        if not self._session:
            return None
        try:
            destination = self.destination_store.get(self._session["destination_id"])
        except Exception:
            return {"id": self._session["destination_id"], "name": None, "type": None}
        return {"id": destination["id"], "name": destination["name"], "type": destination["type"]}

    def _client(self) -> Any:
        factory = self.client_factory
        if hasattr(factory, "from_env"):
            return factory.from_env()
        return factory()


def _check(identifier: str, passed: bool, message: str) -> dict[str, str]:
    return {"id": identifier, "status": "PASS" if passed else "FAIL", "message": message}


def _now() -> str:
    return datetime.now(UTC).isoformat()
