"""Shared exception types for StreamOps.

Legacy CLI modules reuse the standalone server's canonical exception hierarchy
so server-owned OBS code can be called without translating every failure.
"""

from .server.errors import (
    ObsWebSocketConnectionError,
    ObsWebSocketRequestError,
    SceneOperationError,
    ServerError,
)
from .server.scene_config import SceneConfigError


StreamOpsError = ServerError
ConfigError = SceneConfigError
ObsConnectionError = ObsWebSocketConnectionError
ObsRequestError = ObsWebSocketRequestError
VerificationError = SceneOperationError

__all__ = [
    "ConfigError",
    "ObsConnectionError",
    "ObsRequestError",
    "StreamOpsError",
    "VerificationError",
]
