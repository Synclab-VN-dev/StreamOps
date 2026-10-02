"""Provider-neutral streaming destination adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DestinationAdapter(ABC):
    type: str

    @abstractmethod
    def descriptor(self) -> dict[str, Any]:
        """Return public metadata used by generic clients to render this destination type."""

    @abstractmethod
    def validate(self, destination: dict[str, Any]) -> None:
        """Validate provider-specific public configuration."""

    @abstractmethod
    def preflight(self, destination: dict[str, Any], secret: str) -> None:
        """Validate provider-specific readiness without mutating output state."""

    @abstractmethod
    def resolve(self, destination: dict[str, Any], secret: str) -> dict[str, Any]:
        """Resolve provider config into an output-engine-neutral in-memory target."""
