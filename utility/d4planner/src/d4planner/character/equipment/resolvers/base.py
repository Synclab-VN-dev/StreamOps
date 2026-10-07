from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..context import EquipmentContext, EquipmentLine
from ..decision import Resolution


@dataclass(slots=True)
class ResolverRequest:
    context: EquipmentContext
    line: EquipmentLine
    segment: list[EquipmentLine] | None = None
    action: str | None = None
    incoming_slot: str | None = None


class BaseResolver(ABC):
    """Template Method for equipment semantic resolvers."""

    name = "base"

    def resolve(self, request: ResolverRequest) -> Resolution | None:
        if not self.can_handle(request):
            return None

        rejection = self.validate(request)
        if rejection is not None:
            return self.on_rejected(request, rejection)

        return self.build_resolution(request)

    @abstractmethod
    def can_handle(self, request: ResolverRequest) -> bool:
        raise NotImplementedError

    def validate(self, request: ResolverRequest) -> str | None:
        return None

    def on_rejected(
        self,
        request: ResolverRequest,
        reason: str,
    ) -> Resolution | None:
        return None

    @abstractmethod
    def build_resolution(self, request: ResolverRequest) -> Resolution:
        raise NotImplementedError
