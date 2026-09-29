"""Backward-compatible OBS client import.

The streamops-node implementation is owned by streamops.server.obs.client.
Legacy scene/CLI callers can continue importing streamops.obs.client.
"""

from streamops.server.obs.client import ObsClient

__all__ = ["ObsClient"]
