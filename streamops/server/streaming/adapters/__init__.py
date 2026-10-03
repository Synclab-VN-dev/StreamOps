"""Destination adapter registry."""

from .base import DestinationAdapter
from .custom_rtmp import CustomRtmpAdapter

_ADAPTERS: dict[str, DestinationAdapter] = {
    "custom_rtmp": CustomRtmpAdapter(),
}


def get_destination_adapter(destination_type: str) -> DestinationAdapter:
    from ...errors import StreamingError

    try:
        return _ADAPTERS[destination_type]
    except KeyError as exc:
        raise StreamingError(
            "destination_invalid",
            f"Unsupported streaming destination type: {destination_type}",
            422,
        ) from exc


def destination_type_catalog() -> list[dict]:
    return [adapter.descriptor() for adapter in _ADAPTERS.values()]


__all__ = [
    "DestinationAdapter",
    "CustomRtmpAdapter",
    "destination_type_catalog",
    "get_destination_adapter",
]
