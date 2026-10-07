from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..models import EquipmentObservation, ParsedItem


class ResolutionKind(str, Enum):
    UPSERT = "UPSERT"
    NO_MUTATION = "NO_MUTATION"
    CLEAR_SLOT = "CLEAR_SLOT"
    DELETE_ITEM = "DELETE_ITEM"


@dataclass(slots=True)
class Resolution:
    """Pure resolver output; projector owns state/DB side effects."""

    resolver: str
    kind: ResolutionKind
    reason: str
    slot: str | None = None
    action: str | None = None
    item_name: str | None = None
    parsed_item: ParsedItem | None = None
    observation: EquipmentObservation | None = None
    source_seq_start: int | None = None
    source_seq_end: int | None = None
    start_empty_pending: bool = False
    keep_empty_pending: bool = False
    open_ring_probe: bool = False
    delete_fingerprint: str | None = None
    parse_error_type: str | None = None
    parse_error: str | None = None
