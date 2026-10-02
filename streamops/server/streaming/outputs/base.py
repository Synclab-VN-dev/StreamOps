"""Provider-neutral output engine contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class OutputEngine(ABC):
    max_destinations: int

    @abstractmethod
    def prepare(self, destinations: list[dict[str, Any]]) -> None:
        """Prepare one or more resolved destinations without starting output."""

    @abstractmethod
    def start(self) -> dict[str, Any]:
        """Start output and return converged runtime status."""

    @abstractmethod
    def status(self) -> dict[str, Any]:
        """Return current output runtime status."""

    @abstractmethod
    def stop(self) -> dict[str, Any]:
        """Stop output and return converged runtime status."""

    @abstractmethod
    def restore_previous(self) -> None:
        """Restore any previously snapshotted operator stream service."""
