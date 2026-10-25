"""Private BE↔Rule Kit IPC protocol constants and validation."""

from __future__ import annotations

from typing import Final

PROTOCOL_VERSION: Final = "d4-rulekit-ipc/v1"
APPLICATION_CONTRACT_VERSION: Final = "d4-rulekit-application/v1"
APPROVED_METHODS: Final = frozenset(
    {
        "listProviders",
        "createSession",
        "evaluate",
        "previewChanges",
        "commitChanges",
        "resetSession",
        "getSession",
        "closeSession",
    }
)


class ProtocolError(RuntimeError):
    """Worker violated the private protocol or returned malformed data."""


def validate_ready(message: object, *, instance_id: str, generation: int) -> dict:
    if not isinstance(message, dict):
        raise ProtocolError("READY must be a JSON object")
    expected = {
        "type": "READY",
        "protocolVersion": PROTOCOL_VERSION,
        "applicationContractVersion": APPLICATION_CONTRACT_VERSION,
        "workerInstanceId": instance_id,
        "workerGeneration": generation,
    }
    for key, value in expected.items():
        if message.get(key) != value:
            raise ProtocolError(f"READY {key} mismatch")
    if message.get("apis") != sorted(APPROVED_METHODS):
        raise ProtocolError("READY API surface mismatch")
    health = message.get("health")
    if not isinstance(health, dict) or health.get("ready") is not True:
        raise ProtocolError("worker reported unhealthy READY")
    return message
