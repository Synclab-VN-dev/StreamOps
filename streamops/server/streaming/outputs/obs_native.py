"""OBS-native single-output engine."""

from __future__ import annotations

import time
from typing import Any

from ...errors import StreamingError
from ..session_store import LiveSessionStore
from .base import OutputEngine


class ObsNativeOutputEngine(OutputEngine):
    max_destinations = 1

    def __init__(
        self,
        client: Any,
        session_store: LiveSessionStore,
        *,
        start_timeout: float = 12.0,
        stop_timeout: float = 12.0,
        poll_interval: float = 0.25,
    ) -> None:
        self.client = client
        self.session_store = session_store
        self.start_timeout = start_timeout
        self.stop_timeout = stop_timeout
        self.poll_interval = poll_interval

    def prepare(self, destinations: list[dict[str, Any]]) -> None:
        if len(destinations) > self.max_destinations:
            raise StreamingError(
                "output_limit_exceeded",
                f"OBS native output supports at most {self.max_destinations} destination.",
                409,
            )
        if len(destinations) != 1:
            raise StreamingError("destination_invalid", "Exactly one streaming destination is required.", 422)

        destination = destinations[0]
        service_type = destination.get("service_type")
        settings = destination.get("settings")
        if not isinstance(service_type, str) or not isinstance(settings, dict):
            raise StreamingError("destination_invalid", "Resolved streaming destination is invalid.", 422)

        snapshot = self.client.get_stream_service_settings()
        self.session_store.save_restore(snapshot)
        try:
            self.client.set_stream_service_settings(service_type, settings)
        except Exception as exc:
            self._restore_after_prepare_failure()
            raise StreamingError("stream_start_failed", "OBS stream service could not be prepared.", 503) from exc

    def start(self) -> dict[str, Any]:
        try:
            self.client.start_stream()
            return self._wait_active(True, self.start_timeout)
        except StreamingError as exc:
            self._rollback_start_failure(exc)
            raise
        except Exception as exc:
            error = StreamingError("stream_start_failed", "OBS failed to start streaming.", 503)
            self._rollback_start_failure(error)
            raise error from exc

    def status(self) -> dict[str, Any]:
        return self.client.get_stream_status()

    def stop(self) -> dict[str, Any]:
        current = self.status()
        if not bool(current.get("outputActive")):
            return current
        try:
            self.client.stop_stream()
            return self._wait_active(False, self.stop_timeout)
        except StreamingError:
            raise
        except Exception as exc:
            raise StreamingError("stream_stop_failed", "OBS failed to stop streaming.", 503) from exc

    def restore_previous(self) -> None:
        previous = self.session_store.load_restore()
        if previous is None:
            return
        service_type = previous.get("streamServiceType")
        settings = previous.get("streamServiceSettings")
        if not isinstance(service_type, str) or not isinstance(settings, dict):
            raise StreamingError(
                "stream_restore_failed",
                "Persisted OBS stream service snapshot is invalid.",
                500,
            )
        try:
            self.client.set_stream_service_settings(service_type, settings)
        except Exception as exc:
            raise StreamingError(
                "stream_restore_failed",
                "Previous OBS stream service could not be restored.",
                503,
            ) from exc
        self.session_store.clear_restore()

    def _rollback_start_failure(self, original: StreamingError) -> None:
        try:
            current = self.status()
            if bool(current.get("outputActive")):
                self.client.stop_stream()
                self._wait_active(False, self.stop_timeout)
            self.restore_previous()
        except Exception as rollback_exc:
            raise StreamingError(
                "stream_recovery_required",
                "Stream start failed and automatic OBS recovery did not complete.",
                503,
            ) from rollback_exc

    def _restore_after_prepare_failure(self) -> None:
        try:
            self.restore_previous()
        except StreamingError:
            raise

    def _wait_active(self, expected: bool, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = self.status()
            if bool(current.get("outputActive")) is expected:
                return current
            time.sleep(self.poll_interval)
        code = "stream_start_timeout" if expected else "stream_stop_timeout"
        message = (
            "OBS did not become active before timeout."
            if expected
            else "OBS did not stop streaming before timeout."
        )
        raise StreamingError(code, message, 504)
