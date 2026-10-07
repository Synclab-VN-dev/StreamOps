"""Allowlisted Stream Manage operations exposed over WebSocket."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from .obs_ws_operations import WsOperationError


class LiveWsOperations:
    def __init__(self, service: Any, status_hub: Any) -> None:
        self.service = service
        self.status_hub = status_hub
        self._operations: dict[str, Callable[[dict[str, Any]], Any]] = {
            "destinations.list": self._destinations_list,
            "destinations.get": self._destinations_get,
            "destinations.create": self._destinations_create,
            "destinations.update": self._destinations_update,
            "destinations.delete": self._destinations_delete,
            "destinations.set_credential": self._destinations_set_credential,
            "destinations.delete_credential": self._destinations_delete_credential,
            "live.preflight": self._live_preflight,
            "live.preflight.shared": self._live_preflight_shared,
            "live.start": self._live_start,
            "live.status": self._live_status,
            "live.source.visibility": self._live_source_visibility,
            "live.source.position": self._live_source_position,
            "live.source.move": self._live_source_move,
            "live.source.reset": self._live_source_reset,
            "live.scene.reset_overrides": self._live_scene_reset_overrides,
            "live.stop": self._live_stop,
        }

    async def execute(self, operation: str, payload: dict[str, Any]) -> Any:
        handler = self._operations.get(operation)
        if handler is None:
            raise WsOperationError("unknown_operation", f"Unsupported operation: {operation}")
        return await asyncio.to_thread(handler, payload)

    @staticmethod
    def _fields(payload: dict[str, Any], *allowed: str) -> None:
        extras = sorted(set(payload) - set(allowed))
        if extras:
            raise WsOperationError("invalid_request", f"Unexpected payload field(s): {', '.join(extras)}")

    @classmethod
    def _identifier(cls, payload: dict[str, Any], key: str, *extra: str) -> str:
        cls._fields(payload, key, *extra)
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise WsOperationError("invalid_request", f"{key} must be a non-empty string.")
        return value

    def _refresh(self, result: Any) -> Any:
        self.status_hub.trigger_refresh()
        return result

    def _destinations_list(self, payload: dict[str, Any]) -> Any:
        self._fields(payload)
        return self.service.list_destinations()

    def _destinations_get(self, payload: dict[str, Any]) -> Any:
        return self.service.get_destination(self._identifier(payload, "destination_id"))

    def _destinations_create(self, payload: dict[str, Any]) -> Any:
        self._fields(payload, "destination")
        destination = payload.get("destination")
        if not isinstance(destination, dict):
            raise WsOperationError("invalid_request", "destination must be an object.")
        return self._refresh(self.service.create_destination(destination))

    def _destinations_update(self, payload: dict[str, Any]) -> Any:
        destination_id = self._identifier(payload, "destination_id", "destination")
        destination = payload.get("destination")
        if not isinstance(destination, dict):
            raise WsOperationError("invalid_request", "destination must be an object.")
        return self._refresh(self.service.update_destination(destination_id, destination))

    def _destinations_delete(self, payload: dict[str, Any]) -> Any:
        destination_id = self._identifier(payload, "destination_id")
        self.service.delete_destination(destination_id)
        return self._refresh({"deleted": True})

    def _destinations_set_credential(self, payload: dict[str, Any]) -> Any:
        destination_id = self._identifier(payload, "destination_id", "credential")
        credential = payload.get("credential")
        if not isinstance(credential, str):
            raise WsOperationError("invalid_request", "credential must be a string.")
        return self._refresh(self.service.set_credential(destination_id, credential))

    def _destinations_delete_credential(self, payload: dict[str, Any]) -> Any:
        destination_id = self._identifier(payload, "destination_id")
        return self._refresh(self.service.delete_credential(destination_id))

    def _live_args(self, payload: dict[str, Any]) -> tuple[str, str]:
        self._fields(payload, "profile_id", "destination_id")
        profile_id = payload.get("profile_id")
        destination_id = payload.get("destination_id")
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise WsOperationError("invalid_request", "profile_id must be a non-empty string.")
        if not isinstance(destination_id, str) or not destination_id.strip():
            raise WsOperationError("invalid_request", "destination_id must be a non-empty string.")
        return profile_id, destination_id

    def _live_preflight(self, payload: dict[str, Any]) -> Any:
        profile_id, destination_id = self._live_args(payload)
        return self.service.preflight(profile_id, destination_id)

    def _live_preflight_shared(self, payload: dict[str, Any]) -> Any:
        profile_id = self._identifier(payload, "profile_id")
        return self.service.shared_preflight(profile_id)

    def _live_start(self, payload: dict[str, Any]) -> Any:
        profile_id, destination_id = self._live_args(payload)
        try:
            return self.service.start(profile_id, destination_id)
        finally:
            self.status_hub.trigger_refresh()

    def _live_status(self, payload: dict[str, Any]) -> Any:
        self._fields(payload)
        return self.service.status()


    def _live_source_visibility(self, payload: dict[str, Any]) -> Any:
        source_id = self._identifier(payload, "source_id", "visible")
        visible = payload.get("visible")
        if not isinstance(visible, bool):
            raise WsOperationError("invalid_request", "visible must be a boolean.")
        return self._refresh(self.service.set_source_visibility(source_id, visible))

    def _live_source_position(self, payload: dict[str, Any]) -> Any:
        source_id = self._identifier(payload, "source_id", "x", "y")
        if "x" not in payload and "y" not in payload:
            raise WsOperationError("invalid_request", "At least one of x or y is required.")
        return self._refresh(
            self.service.set_source_position(
                source_id,
                x=payload.get("x"),
                y=payload.get("y"),
            )
        )

    def _live_source_move(self, payload: dict[str, Any]) -> Any:
        source_id = self._identifier(payload, "source_id", "dx", "dy")
        if "dx" not in payload or "dy" not in payload:
            raise WsOperationError("invalid_request", "dx and dy are required.")
        return self._refresh(
            self.service.move_source(
                source_id,
                dx=payload.get("dx"),
                dy=payload.get("dy"),
            )
        )

    def _live_source_reset(self, payload: dict[str, Any]) -> Any:
        source_id = self._identifier(payload, "source_id")
        return self._refresh(self.service.reset_source_overrides(source_id))

    def _live_scene_reset_overrides(self, payload: dict[str, Any]) -> Any:
        self._fields(payload)
        return self._refresh(self.service.reset_runtime_overrides())

    def _live_stop(self, payload: dict[str, Any]) -> Any:
        self._fields(payload)
        try:
            return self.service.stop()
        finally:
            self.status_hub.trigger_refresh()
