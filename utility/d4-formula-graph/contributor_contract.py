"""Shared narrow immutable contributor contract (works for module and CLI)."""
from dataclasses import dataclass

@dataclass(frozen=True)
class SourceContribution:
    metric_id: str
    family: str
    value: float | int
    source_id: str
    provenance: str
