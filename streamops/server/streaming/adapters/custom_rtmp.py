"""Custom RTMP destination adapter."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from ...errors import StreamingError
from .base import DestinationAdapter


class CustomRtmpAdapter(DestinationAdapter):
    type = "custom_rtmp"

    def descriptor(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "label": "Custom RTMP",
            "settings": [
                {
                    "key": "server_url",
                    "label": "Server URL",
                    "type": "string",
                    "required": True,
                    "placeholder": "rtmp://127.0.0.1:1935/live",
                }
            ],
            "credential": {
                "label": "Stream Key",
                "type": "password",
                "required": True,
            },
        }

    def validate(self, destination: dict[str, Any]) -> None:
        if destination.get("type") != self.type:
            raise StreamingError("destination_invalid", "Destination is not Custom RTMP.", 422)
        settings = destination.get("settings")
        server_url = settings.get("server_url") if isinstance(settings, dict) else None
        if not isinstance(server_url, str) or not server_url.strip():
            raise StreamingError("destination_invalid", "Custom RTMP server_url is required.", 422)
        parsed = urlparse(server_url.strip())
        if parsed.scheme not in {"rtmp", "rtmps"} or not parsed.hostname:
            raise StreamingError(
                "destination_invalid",
                "Custom RTMP server_url must be a valid rtmp:// or rtmps:// URL.",
                422,
            )

    def preflight(self, destination: dict[str, Any], secret: str) -> None:
        self.validate(destination)
        if not isinstance(secret, str) or not secret:
            raise StreamingError("credential_missing", "Stream credential is not configured.", 409)

    def resolve(self, destination: dict[str, Any], secret: str) -> dict[str, Any]:
        self.preflight(destination, secret)
        return {
            "type": self.type,
            "service_type": "rtmp_custom",
            "settings": {
                "server": destination["settings"]["server_url"],
                "key": secret,
                "use_auth": False,
            },
        }
