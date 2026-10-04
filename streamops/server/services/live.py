"""Livestream orchestration shared by REST and WebSocket transports."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import math
import threading
from typing import Any
from uuid import uuid4

from ..errors import StreamingError
from ..obs.client import ObsClient
from ..scene_profiles import SOURCE_CATALOG
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
                        self._restore_runtime_overrides(client)
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


    def set_source_visibility(self, source_id: str, visible: bool) -> dict[str, Any]:
        if not isinstance(visible, bool):
            raise StreamingError("invalid_request", "visible must be a boolean.", 422)
        with self._lock:
            self._require_obs_ready()
            client = self._client()
            try:
                self._require_runtime_mutable(client)
                source, scene_name, item_id = self._runtime_source(client, source_id)
                before = self._runtime_source_snapshot(client, source, scene_name, item_id)
                client.set_scene_item_enabled(scene_name, item_id, visible)
                override = self._runtime_override(source_id)
                if visible == bool(source.get("enabled", True)):
                    override.pop("visibility", None)
                else:
                    override["visibility"] = visible
                self._prune_runtime_override(source_id)
                self._record_runtime_activity(
                    "visibility",
                    source,
                    {"visible": before["actual"]["visible"]},
                    {"visible": visible},
                )
                self._persist_session()
                return self._runtime_source_snapshot(client, source, scene_name, item_id)
            finally:
                client.close()

    def set_source_position(
        self,
        source_id: str,
        *,
        x: float | int | None = None,
        y: float | int | None = None,
    ) -> dict[str, Any]:
        if x is None and y is None:
            raise StreamingError("invalid_request", "At least one of x or y is required.", 422)
        if x is not None:
            x = _coordinate(x, "x")
        if y is not None:
            y = _coordinate(y, "y")
        with self._lock:
            self._require_obs_ready()
            client = self._client()
            try:
                self._require_runtime_mutable(client)
                source, scene_name, item_id = self._runtime_source(
                    client, source_id, require_position=True
                )
                before = self._runtime_source_snapshot(client, source, scene_name, item_id)
                current = client.get_scene_item_transform(scene_name, item_id)
                target_x = float(current.get("positionX") or 0.0) if x is None else float(x)
                target_y = float(current.get("positionY") or 0.0) if y is None else float(y)
                client.set_scene_item_transform(
                    scene_name,
                    item_id,
                    {"positionX": target_x, "positionY": target_y},
                )
                self._set_position_override(source_id, source, target_x, target_y)
                self._record_runtime_activity(
                    "position",
                    source,
                    before["actual"].get("position"),
                    {"x": target_x, "y": target_y},
                )
                self._persist_session()
                return self._runtime_source_snapshot(client, source, scene_name, item_id)
            finally:
                client.close()

    def move_source(self, source_id: str, *, dx: float | int, dy: float | int) -> dict[str, Any]:
        dx = _coordinate(dx, "dx")
        dy = _coordinate(dy, "dy")
        with self._lock:
            self._require_obs_ready()
            client = self._client()
            try:
                self._require_runtime_mutable(client)
                source, scene_name, item_id = self._runtime_source(
                    client, source_id, require_position=True
                )
                before = self._runtime_source_snapshot(client, source, scene_name, item_id)
                current = client.get_scene_item_transform(scene_name, item_id)
                target_x = float(current.get("positionX") or 0.0) + float(dx)
                target_y = float(current.get("positionY") or 0.0) + float(dy)
                client.set_scene_item_transform(
                    scene_name,
                    item_id,
                    {"positionX": target_x, "positionY": target_y},
                )
                self._set_position_override(source_id, source, target_x, target_y)
                self._record_runtime_activity(
                    "move",
                    source,
                    before["actual"].get("position"),
                    {"x": target_x, "y": target_y, "dx": float(dx), "dy": float(dy)},
                )
                self._persist_session()
                return self._runtime_source_snapshot(client, source, scene_name, item_id)
            finally:
                client.close()

    def reset_source_overrides(self, source_id: str) -> dict[str, Any]:
        with self._lock:
            self._require_obs_ready()
            client = self._client()
            try:
                self._require_runtime_mutable(client)
                source, scene_name, item_id = self._runtime_source(client, source_id)
                self._restore_source_override(client, source, scene_name, item_id)
                self._record_runtime_activity("reset", source, None, self._baseline_for_source(source))
                self._persist_session()
                return self._runtime_source_snapshot(client, source, scene_name, item_id)
            finally:
                client.close()

    def reset_runtime_overrides(self) -> dict[str, Any]:
        with self._lock:
            self._require_obs_ready()
            client = self._client()
            try:
                self._require_runtime_mutable(client)
                self._restore_runtime_overrides(client)
                self._persist_session()
                return self._runtime_scene_status(client)
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
                    self._restore_runtime_overrides(client)
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
                "session_id": self._session.get("session_id") if self._session else None,
                "profile": self._session_profile(),
                "destination": self._session_destination(),
                "output": {"active": False},
                "started_at": self._session.get("started_at") if self._session else None,
                "runtime_scene": {
                    "status": "UNAVAILABLE",
                    "sources": [],
                    "overrides": deepcopy(self._runtime_overrides()),
                } if self._session else None,
                "runtime_activity": deepcopy(self._session.get("runtime_activity", []))
                if self._session else [],
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
            "session_id": self._session.get("session_id") if self._session else None,
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
            "runtime_scene": self._runtime_scene_status(client),
            "runtime_activity": deepcopy(self._session.get("runtime_activity", [])) if self._session else [],
        }


    def _require_runtime_mutable(self, client: Any) -> None:
        if not self._session:
            raise StreamingError(
                "live_runtime_unavailable",
                "Runtime scene control requires a managed live session.",
                409,
            )
        if self._transition is not None or self._session.get("state") != "LIVE":
            raise StreamingError(
                "live_runtime_unavailable",
                "Runtime scene control is available only while the managed session is LIVE.",
                409,
            )
        stream = client.get_stream_status()
        if not bool(stream.get("outputActive")):
            raise StreamingError(
                "live_runtime_unavailable",
                "OBS streaming output is not active.",
                409,
            )

    def _runtime_source(
        self,
        client: Any,
        source_id: str,
        *,
        require_position: bool = False,
    ) -> tuple[dict[str, Any], str, int]:
        if not isinstance(source_id, str) or not source_id.strip():
            raise StreamingError("invalid_request", "source_id must be a non-empty string.", 422)
        if not self._session:
            raise StreamingError("live_runtime_unavailable", "No managed live session.", 409)
        profile = self.scene_service.get_profile(self._session["profile_id"])
        source = next(
            (item for item in profile.get("sources", []) if item.get("id") == source_id),
            None,
        )
        if source is None:
            raise StreamingError(
                "runtime_source_not_owned",
                "Source does not belong to the active managed Scene Profile.",
                404,
            )
        capability = SOURCE_CATALOG.get(source.get("type"), {})
        if not capability.get("video"):
            raise StreamingError(
                "runtime_source_unsupported",
                "Runtime scene control is limited to visual sources in this phase.",
                409,
            )
        if require_position and not isinstance(source.get("transform"), dict):
            raise StreamingError(
                "runtime_position_unsupported",
                "Source has no managed position baseline.",
                409,
            )
        scene_name = str(profile["obs_scene_name"])
        source_name = self._source_input_name(source)
        matches = [
            item
            for item in client.get_scene_item_list(scene_name)
            if item.get("sourceName") == source_name
        ]
        if len(matches) != 1:
            raise StreamingError(
                "runtime_scene_item_unavailable",
                "Expected exactly one matching OBS scene item for the managed source.",
                409,
            )
        return source, scene_name, int(matches[0]["sceneItemId"])

    @staticmethod
    def _source_input_name(source: dict[str, Any]) -> str:
        capability = SOURCE_CATALOG.get(source.get("type"), {})
        if capability.get("existing"):
            return str(source.get("settings", {}).get("source_name") or "")
        return str(source.get("obs_name") or "")

    def _runtime_overrides(self) -> dict[str, dict[str, Any]]:
        if not self._session:
            return {}
        overrides = self._session.setdefault("runtime_overrides", {})
        if not isinstance(overrides, dict):
            overrides = {}
            self._session["runtime_overrides"] = overrides
        return overrides

    def _runtime_override(self, source_id: str) -> dict[str, Any]:
        overrides = self._runtime_overrides()
        current = overrides.setdefault(source_id, {})
        if not isinstance(current, dict):
            current = {}
            overrides[source_id] = current
        return current

    def _prune_runtime_override(self, source_id: str) -> None:
        overrides = self._runtime_overrides()
        current = overrides.get(source_id)
        if isinstance(current, dict) and not current:
            overrides.pop(source_id, None)

    def _set_position_override(
        self,
        source_id: str,
        source: dict[str, Any],
        x: float,
        y: float,
    ) -> None:
        baseline = self._baseline_for_source(source).get("position")
        override = self._runtime_override(source_id)
        if (
            baseline
            and _same_number(x, baseline["x"])
            and _same_number(y, baseline["y"])
        ):
            override.pop("position", None)
        else:
            override["position"] = {"x": x, "y": y}
        self._prune_runtime_override(source_id)

    def _baseline_for_source(self, source: dict[str, Any]) -> dict[str, Any]:
        baseline: dict[str, Any] = {"visible": bool(source.get("enabled", True))}
        transform = source.get("transform")
        if isinstance(transform, dict):
            baseline["position"] = {
                "x": float(transform.get("x") or 0.0),
                "y": float(transform.get("y") or 0.0),
            }
        return baseline

    def _expected_for_source(self, source: dict[str, Any]) -> dict[str, Any]:
        expected = deepcopy(self._baseline_for_source(source))
        override = self._runtime_overrides().get(str(source.get("id")), {})
        if isinstance(override, dict):
            if "visibility" in override:
                expected["visible"] = bool(override["visibility"])
            position = override.get("position")
            if isinstance(position, dict):
                expected["position"] = {
                    "x": float(position.get("x") or 0.0),
                    "y": float(position.get("y") or 0.0),
                }
        return expected

    def _runtime_source_snapshot(
        self,
        client: Any,
        source: dict[str, Any],
        scene_name: str,
        item_id: int,
    ) -> dict[str, Any]:
        items = {
            int(item["sceneItemId"]): item
            for item in client.get_scene_item_list(scene_name)
        }
        item = items.get(item_id)
        baseline = self._baseline_for_source(source)
        expected = self._expected_for_source(source)
        actual: dict[str, Any] = {
            "visible": bool(item.get("sceneItemEnabled")) if item is not None else None,
        }
        if "position" in baseline and item is not None:
            transform = client.get_scene_item_transform(scene_name, item_id)
            actual["position"] = {
                "x": float(transform.get("positionX") or 0.0),
                "y": float(transform.get("positionY") or 0.0),
            }
        drift: list[str] = []
        if item is None:
            drift.append("item_missing")
        else:
            if actual["visible"] != expected["visible"]:
                drift.append("visibility")
            if "position" in expected:
                position = actual.get("position")
                if (
                    not position
                    or not _same_number(position["x"], expected["position"]["x"])
                    or not _same_number(position["y"], expected["position"]["y"])
                ):
                    drift.append("position")
        override = deepcopy(self._runtime_overrides().get(str(source.get("id")), {}))
        return {
            "id": source.get("id"),
            "name": source.get("name"),
            "type": source.get("type"),
            "baseline": baseline,
            "override": override,
            "effective": expected,
            "actual": actual,
            "drift": drift,
        }

    def _runtime_scene_status(self, client: Any) -> dict[str, Any] | None:
        if not self._session:
            return None
        try:
            profile = self.scene_service.get_profile(self._session["profile_id"])
        except Exception:
            return {
                "status": "UNAVAILABLE",
                "sources": [],
                "overrides": deepcopy(self._runtime_overrides()),
            }
        scene_name = str(profile.get("obs_scene_name") or "")
        try:
            items = client.get_scene_item_list(scene_name)
        except Exception:
            return {
                "status": "UNAVAILABLE",
                "sources": [],
                "overrides": deepcopy(self._runtime_overrides()),
            }
        by_name: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            by_name.setdefault(str(item.get("sourceName") or ""), []).append(item)
        sources: list[dict[str, Any]] = []
        for source in profile.get("sources", []):
            capability = SOURCE_CATALOG.get(source.get("type"), {})
            if not capability.get("video"):
                continue
            matches = by_name.get(self._source_input_name(source), [])
            if len(matches) != 1:
                baseline = self._baseline_for_source(source)
                sources.append({
                    "id": source.get("id"),
                    "name": source.get("name"),
                    "type": source.get("type"),
                    "baseline": baseline,
                    "override": deepcopy(self._runtime_overrides().get(str(source.get("id")), {})),
                    "effective": self._expected_for_source(source),
                    "actual": {"visible": None},
                    "drift": ["item_missing"],
                })
                continue
            sources.append(
                self._runtime_source_snapshot(
                    client,
                    source,
                    scene_name,
                    int(matches[0]["sceneItemId"]),
                )
            )
        return {
            "status": "PASS" if all(not item["drift"] for item in sources) else "DRIFTED",
            "sources": sources,
            "overrides": deepcopy(self._runtime_overrides()),
        }

    def _restore_source_override(
        self,
        client: Any,
        source: dict[str, Any],
        scene_name: str,
        item_id: int,
    ) -> None:
        source_id = str(source["id"])
        override = deepcopy(self._runtime_overrides().get(source_id, {}))
        if not override:
            return
        baseline = self._baseline_for_source(source)
        try:
            if "visibility" in override:
                client.set_scene_item_enabled(scene_name, item_id, baseline["visible"])
            if "position" in override and "position" in baseline:
                client.set_scene_item_transform(
                    scene_name,
                    item_id,
                    {
                        "positionX": baseline["position"]["x"],
                        "positionY": baseline["position"]["y"],
                    },
                )
        except Exception as exc:
            raise StreamingError(
                "runtime_restore_failed",
                f"Could not restore runtime override for source {source.get('name') or source_id}.",
                409,
            ) from exc
        self._runtime_overrides().pop(source_id, None)

    def _restore_runtime_overrides(self, client: Any) -> None:
        if not self._session:
            return
        pending = list(self._runtime_overrides())
        if not pending:
            return
        profile = self.scene_service.get_profile(self._session["profile_id"])
        sources = {
            str(source.get("id")): source
            for source in profile.get("sources", [])
        }
        for source_id in pending:
            source = sources.get(source_id)
            if source is None:
                raise StreamingError(
                    "runtime_restore_failed",
                    f"Could not restore unknown runtime source {source_id}.",
                    409,
                )
            _, scene_name, item_id = self._runtime_source(client, source_id)
            self._restore_source_override(client, source, scene_name, item_id)
            self._record_runtime_activity(
                "restore",
                source,
                None,
                self._baseline_for_source(source),
            )
            self._persist_session()

    def _record_runtime_activity(
        self,
        action: str,
        source: dict[str, Any],
        before: Any,
        after: Any,
    ) -> None:
        if not self._session:
            return
        entries = self._session.setdefault("runtime_activity", [])
        if not isinstance(entries, list):
            entries = []
            self._session["runtime_activity"] = entries
        entries.append({
            "at": _now(),
            "action": action,
            "source_id": source.get("id"),
            "source_name": source.get("name"),
            "before": deepcopy(before),
            "after": deepcopy(after),
        })
        del entries[:-50]

    def _persist_session(self) -> None:
        if self._session:
            self.session_store.save_session(self._session)

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


def _coordinate(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StreamingError("invalid_request", f"{name} must be a finite number.", 422)
    number = float(value)
    if not math.isfinite(number):
        raise StreamingError("invalid_request", f"{name} must be a finite number.", 422)
    return number


def _same_number(left: Any, right: Any) -> bool:
    try:
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=0.01)
    except (TypeError, ValueError):
        return False
