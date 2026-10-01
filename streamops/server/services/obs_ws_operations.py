"""Allowlisted business operations exposed over the OBS dashboard WebSocket."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

from ..errors import (
    InvalidObsProcessRequestError,
    ObsExecutableNotAllowedError,
    ObsOperationInProgressError,
    ObsReadinessTimeoutError,
    ObsShutdownError,
    ObsShutdownTimeoutError,
    ObsStartError,
    ObsStartTimeoutError,
    ObsStatusError,
    ObsUnsafeOperationError,
    ObsWebSocketConnectionError,
    ObsWebSocketRequestError,
    SceneOperationError,
    SceneProfileConflictError,
    SceneProfileNotFoundError,
    SceneProfileStorageError,
    SceneProfileValidationError,
    SceneReviewArtifactNotFoundError,
    SceneReviewNotFoundError,
)
from ..scene_config import SceneConfigError


@dataclass(frozen=True)
class WsOperationError(Exception):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


class ObsWsOperations:
    """Dispatch dashboard operations to the same services used by REST routes."""

    def __init__(self, manager: Any, scene_service: Any, status_hub: Any) -> None:
        self.manager = manager
        self.scene_service = scene_service
        self.status_hub = status_hub
        self._operations: dict[str, Callable[[dict[str, Any]], Any]] = {
            "scene_profiles.list": self._profiles_list,
            "scene_profiles.get": self._profiles_get,
            "scene_profiles.create": self._profiles_create,
            "scene_profiles.update": self._profiles_update,
            "scene_profiles.delete": self._profiles_delete,
            "scene_profiles.duplicate": self._profiles_duplicate,
            "scene_profiles.apply": self._profiles_apply,
            "scene_profiles.verify": self._profiles_verify,
            "scene_profiles.activate": self._profiles_activate,
            "scene_profiles.review": self._profiles_review,
            "scene_reviews.get": self._reviews_get,
            "source_catalog.list": self._source_catalog,
            "inventory.get": self._inventory,
            "scene_profile_templates.list": self._templates_list,
            "scene_profile_templates.instantiate": self._templates_instantiate,
            "obs.lifecycle.start": self._obs_start,
            "obs.lifecycle.stop": self._obs_stop,
            "obs.lifecycle.restart": self._obs_restart,
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
    def _empty(cls, payload: dict[str, Any]) -> None:
        cls._fields(payload)

    @classmethod
    def _identifier(cls, payload: dict[str, Any], key: str, *extra: str) -> str:
        cls._fields(payload, key, *extra)
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise WsOperationError("invalid_request", f"{key} must be a non-empty string.")
        return value

    @staticmethod
    def _optional_name(payload: dict[str, Any]) -> str | None:
        name = payload.get("name")
        if name is not None and (not isinstance(name, str) or len(name) > 120):
            raise WsOperationError("invalid_request", "name must be a string of at most 120 characters.")
        return name

    def _require_ready(self) -> None:
        status = self.manager.status()
        if status.state != "READY":
            raise SceneOperationError(
                f"OBS runtime is {status.state}; Start OBS and wait for READY before using runtime scene operations."
            )

    def _profiles_list(self, payload: dict[str, Any]) -> Any:
        self._empty(payload)
        return self.scene_service.list_profiles()

    def _profiles_get(self, payload: dict[str, Any]) -> Any:
        return self.scene_service.get_profile(self._identifier(payload, "profile_id"))

    def _profiles_create(self, payload: dict[str, Any]) -> Any:
        self._fields(payload, "profile")
        profile = payload.get("profile")
        if not isinstance(profile, dict):
            raise WsOperationError("invalid_request", "profile must be an object.")
        return self.scene_service.create_profile(profile)

    def _profiles_update(self, payload: dict[str, Any]) -> Any:
        profile_id = self._identifier(payload, "profile_id", "profile")
        profile = payload.get("profile")
        if not isinstance(profile, dict):
            raise WsOperationError("invalid_request", "profile must be an object.")
        return self.scene_service.update_profile(profile_id, profile)

    def _profiles_delete(self, payload: dict[str, Any]) -> None:
        self.scene_service.delete_profile(self._identifier(payload, "profile_id"))

    def _profiles_duplicate(self, payload: dict[str, Any]) -> Any:
        profile_id = self._identifier(payload, "profile_id", "name")
        return self.scene_service.duplicate_profile(profile_id, name=self._optional_name(payload))

    def _profiles_apply(self, payload: dict[str, Any]) -> Any:
        profile_id = self._identifier(payload, "profile_id")
        self._require_ready()
        return self.scene_service.apply_profile(profile_id).to_dict()

    def _profiles_verify(self, payload: dict[str, Any]) -> Any:
        profile_id = self._identifier(payload, "profile_id")
        self._require_ready()
        return self.scene_service.verify_profile(profile_id, runtime=True).to_dict()

    def _profiles_activate(self, payload: dict[str, Any]) -> Any:
        profile_id = self._identifier(payload, "profile_id")
        self._require_ready()
        try:
            return self.scene_service.activate_profile(profile_id)
        finally:
            self.status_hub.trigger_refresh()

    def _profiles_review(self, payload: dict[str, Any]) -> Any:
        profile_id = self._identifier(payload, "profile_id", "seconds")
        seconds = payload.get("seconds", 30)
        if isinstance(seconds, bool) or not isinstance(seconds, int) or not 1 <= seconds <= 300:
            raise WsOperationError("invalid_request", "seconds must be an integer from 1 to 300.")
        self._require_ready()
        return self.scene_service.start_profile_review(profile_id, seconds=seconds).to_dict()

    def _reviews_get(self, payload: dict[str, Any]) -> Any:
        return self.scene_service.review_job(self._identifier(payload, "job_id")).to_dict()

    def _source_catalog(self, payload: dict[str, Any]) -> Any:
        self._empty(payload)
        return {"sources": self.scene_service.catalog()}

    def _inventory(self, payload: dict[str, Any]) -> Any:
        self._empty(payload)
        return self.scene_service.inventory()

    def _templates_list(self, payload: dict[str, Any]) -> Any:
        self._empty(payload)
        return {"templates": self.scene_service.list_templates()}

    def _templates_instantiate(self, payload: dict[str, Any]) -> Any:
        template_id = self._identifier(payload, "template_id", "name")
        return self.scene_service.instantiate_template(template_id, name=self._optional_name(payload))

    def _lifecycle(self, payload: dict[str, Any], method: str) -> Any:
        self._empty(payload)
        try:
            return getattr(self.manager, method)().api_payload()
        finally:
            self.status_hub.trigger_refresh()

    def _obs_start(self, payload: dict[str, Any]) -> Any:
        return self._lifecycle(payload, "start")

    def _obs_stop(self, payload: dict[str, Any]) -> Any:
        return self._lifecycle(payload, "stop")

    def _obs_restart(self, payload: dict[str, Any]) -> Any:
        return self._lifecycle(payload, "restart")


def public_ws_error(exc: Exception) -> tuple[str, str]:
    """Return the stable public code/message used by the REST exception handlers."""
    if isinstance(exc, WsOperationError):
        return exc.code, exc.message
    mappings: tuple[tuple[type[Exception], str], ...] = (
        (InvalidObsProcessRequestError, "invalid_obs_process_request"),
        (ObsOperationInProgressError, "obs_operation_in_progress"),
        (ObsUnsafeOperationError, "obs_unsafe_operation"),
        (ObsExecutableNotAllowedError, "obs_executable_unavailable"),
        (ObsStartTimeoutError, "obs_start_timeout"),
        (ObsReadinessTimeoutError, "obs_readiness_timeout"),
        (ObsShutdownTimeoutError, "obs_shutdown_timeout"),
        (ObsShutdownError, "obs_shutdown_failed"),
        (ObsStartError, "obs_start_failed"),
        (ObsStatusError, "obs_status_failed"),
        (SceneConfigError, "scene_config_invalid"),
        (SceneReviewNotFoundError, "scene_review_not_found"),
        (SceneReviewArtifactNotFoundError, "scene_review_artifact_not_found"),
        (SceneProfileNotFoundError, "scene_profile_not_found"),
        (SceneProfileValidationError, "scene_profile_invalid"),
        (SceneProfileConflictError, "scene_profile_conflict"),
        (SceneProfileStorageError, "scene_profile_storage_failed"),
        (ObsWebSocketConnectionError, "obs_unavailable"),
        (ObsWebSocketRequestError, "obs_request_failed"),
        (SceneOperationError, "scene_operation_failed"),
    )
    for error_type, code in mappings:
        if isinstance(exc, error_type):
            return code, str(exc)
    return "internal_error", "The operation failed unexpectedly."
