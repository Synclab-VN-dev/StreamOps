"""Backward-compatible OBS client import for legacy scene/CLI callers."""

from streamops.errors import ObsConnectionError, ObsRequestError
from streamops.server.errors import ObsWebSocketConnectionError, ObsWebSocketRequestError
from streamops.server.obs.client import INPUT_VOLUME_METERS_SUBSCRIPTION, ObsClient as _ServerObsClient


class ObsClient(_ServerObsClient):
    """Legacy facade preserving the historical StreamOps exception contract."""

    @classmethod
    def from_env(cls, *, event_subscriptions: int = 0) -> "ObsClient":
        try:
            return super().from_env(event_subscriptions=event_subscriptions)
        except ObsWebSocketConnectionError as exc:
            raise ObsConnectionError(str(exc)) from exc

    def connect(self) -> None:
        try:
            super().connect()
        except ObsWebSocketConnectionError as exc:
            raise ObsConnectionError(str(exc)) from exc

    def request(self, request_type: str, request_data: dict | None = None) -> dict:
        try:
            return super().request(request_type, request_data)
        except ObsWebSocketConnectionError as exc:
            raise ObsConnectionError(str(exc)) from exc
        except ObsWebSocketRequestError as exc:
            raise ObsRequestError(str(exc)) from exc


__all__ = ["INPUT_VOLUME_METERS_SUBSCRIPTION", "ObsClient"]
