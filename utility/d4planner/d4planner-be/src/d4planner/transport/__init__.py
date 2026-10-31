"""Release 1 loopback WebSocket transport.

The transport depends on domain ports. It never reads Target files or the
assessment database and never computes Equipment scores.
"""

from .core import (
    D4PlannerDomain,
    D4PlannerProtocolSession,
    HudHub,
    ProtocolViolation,
    TargetActivationError,
)
from .websocket import D4PlannerWebSocketServer, WebSocketServerConfig

__all__ = [
    "D4PlannerDomain",
    "D4PlannerProtocolSession",
    "D4PlannerWebSocketServer",
    "HudHub",
    "ProtocolViolation",
    "TargetActivationError",
    "WebSocketServerConfig",
]
