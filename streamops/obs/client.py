"""Compatibility wrapper for the canonical server-owned OBS client."""

from ..server.obs.client import INPUT_VOLUME_METERS_SUBSCRIPTION, ObsClient

__all__ = ["INPUT_VOLUME_METERS_SUBSCRIPTION", "ObsClient"]
