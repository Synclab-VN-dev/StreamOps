from __future__ import annotations

from collections.abc import Iterable

from ..decision import Resolution
from .ambiguous import AmbiguousResolver
from .base import BaseResolver, ResolverRequest
from .candidate import CandidateResolver
from .empty_slot import EmptySlotResolver
from .equipped import EquippedResolver


class ResolverPipeline:
    """Ordered chain of Template Method resolvers."""

    def __init__(self, resolvers: Iterable[BaseResolver]):
        self.resolvers = tuple(resolvers)

    def resolve(self, request: ResolverRequest) -> Resolution | None:
        for resolver in self.resolvers:
            decision = resolver.resolve(request)
            if decision is not None:
                return decision
        return None


def item_resolver_pipeline() -> ResolverPipeline:
    # Strong resolver first, fail-closed fallback last.
    return ResolverPipeline(
        (
            EquippedResolver(),
            CandidateResolver(),
            AmbiguousResolver(),
        )
    )


def empty_slot_resolver_pipeline() -> ResolverPipeline:
    return ResolverPipeline((EmptySlotResolver(),))
