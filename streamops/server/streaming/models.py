"""Validation helpers for livestream destinations."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

from ..errors import StreamingError


def normalize_destination(payload: dict[str, Any], *, destination_id: str | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise StreamingError("destination_invalid", "Destination must be an object.", 422)
    allowed = {"schema_version", "id", "name", "type", "enabled", "settings"}
    extras = sorted(set(payload) - allowed)
    if extras:
        raise StreamingError(
            "destination_invalid",
            f"Destination has unknown field(s): {', '.join(extras)}.",
            422,
        )

    requested_id = payload.get("id")
    if destination_id is not None and requested_id not in (None, destination_id):
        raise StreamingError("destination_invalid", "Destination id cannot be changed by PUT.", 422)
    value_id = destination_id or requested_id or str(uuid4())
    _require_uuid(value_id)

    schema_version = payload.get("schema_version", 1)
    if schema_version != 1:
        raise StreamingError("destination_invalid", "schema_version must be 1.", 422)

    name = payload.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        raise StreamingError("destination_invalid", "name must be a non-empty string of at most 120 characters.", 422)

    destination_type = payload.get("type", "custom_rtmp")
    if destination_type != "custom_rtmp":
        raise StreamingError("destination_invalid", "Only custom_rtmp destinations are supported.", 422)

    enabled = payload.get("enabled", True)
    if type(enabled) is not bool:
        raise StreamingError("destination_invalid", "enabled must be a boolean.", 422)

    settings = payload.get("settings")
    if not isinstance(settings, dict):
        raise StreamingError("destination_invalid", "settings must be an object.", 422)
    setting_extras = sorted(set(settings) - {"server_url"})
    if setting_extras:
        raise StreamingError(
            "destination_invalid",
            f"settings has unknown field(s): {', '.join(setting_extras)}.",
            422,
        )
    server_url = settings.get("server_url")
    if not isinstance(server_url, str) or not server_url.strip():
        raise StreamingError("destination_invalid", "settings.server_url is required.", 422)
    server_url = server_url.strip()
    parsed = urlparse(server_url)
    if parsed.scheme not in {"rtmp", "rtmps"} or not parsed.hostname:
        raise StreamingError(
            "destination_invalid",
            "settings.server_url must be a valid rtmp:// or rtmps:// URL.",
            422,
        )

    return {
        "schema_version": 1,
        "id": value_id,
        "name": name.strip(),
        "type": "custom_rtmp",
        "enabled": enabled,
        "settings": {"server_url": server_url},
    }


def require_destination_id(value: str) -> str:
    _require_uuid(value)
    return value


def _require_uuid(value: Any) -> None:
    try:
        parsed = UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise StreamingError("destination_not_found", f"Streaming destination not found: {value}", 404) from exc
    if parsed.version != 4:
        raise StreamingError("destination_not_found", f"Streaming destination not found: {value}", 404)
