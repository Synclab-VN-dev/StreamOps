"""Backward-compatible OBS client import for legacy scene/CLI callers."""

from streamops.errors import ObsConnectionError, ObsRequestError
from streamops.server.errors import ObsWebSocketConnectionError, ObsWebSocketRequestError
from streamops.server.obs.client import ObsClient as _ServerObsClient


class ObsClient(_ServerObsClient):
    """Legacy facade preserving the historical StreamOps exception contract."""

    @classmethod
    def from_env(cls) -> "ObsClient":
        try:
            return super().from_env()
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


__all__ = ["ObsClient"]
