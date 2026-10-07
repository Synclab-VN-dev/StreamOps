from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..models import EquipmentObservation
from ..repository import EquipmentRepository
from .parser import fingerprint, is_item_anchor, normalize, parse_item

SLOTS = {
    "Head": "helm",
    "Torso": "chest",
    "Hands": "gloves",
    "Legs": "pants",
    "Feet": "boots",
    "Main Hand": "main_hand",
    "Off-Hand": "off_hand",
    "Ring": "ring",
    "Neck": "amulet",
}

# These slots have a single current occupant. Ring is intentionally excluded:
# Diablo IV has two ring slots while the current contract keeps slot_index=None,
# so "Ring ... Unequip -> Ring" can simply mean focus moved to the other ring.
SINGLE_INSTANCE_SLOTS = frozenset(SLOTS.values()) - {"ring"}


class _Diagnostics(Protocol):
    def emit(self, event: str, **fields: Any) -> bool: ...


@dataclass
class _Line:
    text: str
    seq: int
    timestamp: str
    session_id: str


class EquipmentProjector:
    def __init__(
        self,
        repository: EquipmentRepository,
        diagnostics: _Diagnostics | None = None,
    ):
        self.repository = repository
        self.diagnostics = diagnostics
        self.slot: str | None = None
        self.equipped_marker = False
        self.lookback: list[_Line] = []
        self.active: list[_Line] | None = None
        # An equipped item always ends on the action label "Unequip".
        # If the *very next* accessibility event rebounds to the same
        # single-instance slot, Real-A shows that the button was activated and
        # the slot is now empty. This marker deliberately survives one event.
        self._just_resolved_unequip_slot: str | None = None

    def set_diagnostics(self, diagnostics: _Diagnostics | None) -> None:
        self.diagnostics = diagnostics

    def _diag(self, event: str, line: _Line | None = None, **fields: Any) -> None:
        if self.diagnostics is None:
            return
        if line is not None:
            fields = {
                "sessionId": line.session_id,
                "sourceSeq": line.seq,
                "sourceTimestamp": line.timestamp,
                **fields,
            }
        try:
            self.diagnostics.emit(event, **fields)
        except Exception:
            # Diagnostics must never affect parser/projector/capture behavior.
            pass

    def record_error(self, event: dict[str, Any], exc: Exception) -> None:
        self._diag(
            "projector.error",
            _Line(
                normalize(str((event.get("data") or {}).get("text") or "")),
                int(event.get("eventSeq") or 0),
                str(event.get("timestamp") or ""),
                str(event.get("sessionId") or ""),
            ),
            errorType=type(exc).__name__,
            error=str(exc),
        )

    def consume(self, event: dict[str, Any]) -> None:
        if event.get("type") != "speech.raw":
            return

        seq = int(event.get("eventSeq") or 0)
        session = str(event.get("sessionId") or "")
        ts = str(event.get("timestamp") or "")
        checkpoint = self.repository.checkpoint()
        if checkpoint and checkpoint[0] == session and seq <= checkpoint[1]:
            return

        text = normalize(str((event.get("data") or {}).get("text") or ""))
        line = _Line(text, seq, ts, session)
        observation = None
        empty_slot_family = None

        # The current empty-slot signal is adjacency-sensitive. Diagnostics make
        # the decision visible so Real-A traces can refine the rule safely.
        previous_unequip_slot = self._just_resolved_unequip_slot
        self._just_resolved_unequip_slot = None

        if text in SLOTS:
            incoming_slot = SLOTS[text]
            if (
                previous_unequip_slot == incoming_slot
                and incoming_slot in SINGLE_INSTANCE_SLOTS
            ):
                empty_slot_family = incoming_slot
                self._diag(
                    "empty.confirmed",
                    line,
                    slot=incoming_slot,
                    reason="same_slot_immediate_rebound",
                )
            elif previous_unequip_slot:
                self._diag(
                    "empty.cancelled",
                    line,
                    slot=previous_unequip_slot,
                    reason=f"next_event_slot:{incoming_slot}",
                )
            self.slot = incoming_slot
            self.equipped_marker = False
            self.active = None
            self.lookback = []
        else:
            if previous_unequip_slot:
                self._diag(
                    "empty.cancelled",
                    line,
                    slot=previous_unequip_slot,
                    reason="next_event_not_same_slot",
                    nextText=text,
                )
            if text == "EQUIPPED":
                self.equipped_marker = True

        if self.active is not None:
            self.active.append(line)
            if text in {"Equip", "Unequip"}:
                raw = [x.text for x in self.active]
                item_name = self.active[0].text
                if text == "Unequip" and self.slot and self.equipped_marker:
                    try:
                        item = parse_item(raw)
                    except Exception as exc:
                        self._diag(
                            "parse.failed",
                            line,
                            slot=self.slot,
                            item=item_name,
                            action=text,
                            sourceSeqStart=self.active[0].seq,
                            errorType=type(exc).__name__,
                            error=str(exc),
                        )
                        raise
                    self._diag(
                        "parse.success",
                        line,
                        slot=self.slot,
                        item=item.name,
                        itemType=item.item_type,
                        itemPower=item.item_power,
                        action=text,
                        sourceSeqStart=self.active[0].seq,
                    )
                    observation = EquipmentObservation(
                        self.slot,
                        None,
                        item,
                        ts,
                        session,
                        self.active[0].seq,
                        seq,
                        "HIGH",
                        fingerprint(self.slot, item),
                    )
                    self._diag(
                        "observation.high",
                        line,
                        slot=self.slot,
                        item=item.name,
                        action=text,
                        sourceSeqStart=self.active[0].seq,
                        reason="slot+equipped+anchor+terminal_unequip",
                    )
                    self._just_resolved_unequip_slot = self.slot
                    if self.slot in SINGLE_INSTANCE_SLOTS:
                        self._diag(
                            "empty.pending",
                            line,
                            slot=self.slot,
                            reason="high_observation_terminal_unequip",
                        )
                    else:
                        self._diag(
                            "empty.excluded",
                            line,
                            slot=self.slot,
                            reason="multi_instance_slot",
                        )
                elif text == "Equip":
                    try:
                        candidate = parse_item(raw)
                        self._diag(
                            "parse.success",
                            line,
                            slot=self.slot,
                            item=candidate.name,
                            itemType=candidate.item_type,
                            itemPower=candidate.item_power,
                            action=text,
                            sourceSeqStart=self.active[0].seq,
                        )
                        item_name = candidate.name
                    except Exception as exc:
                        self._diag(
                            "parse.failed",
                            line,
                            slot=self.slot,
                            item=item_name,
                            action=text,
                            sourceSeqStart=self.active[0].seq,
                            errorType=type(exc).__name__,
                            error=str(exc),
                        )
                    self._diag(
                        "observation.not_equipped",
                        line,
                        slot=self.slot,
                        item=item_name,
                        action=text,
                        sourceSeqStart=self.active[0].seq,
                        reason="terminal_equip",
                    )
                elif text == "Unequip":
                    self._diag(
                        "observation.ambiguous",
                        line,
                        slot=self.slot,
                        item=item_name,
                        action=text,
                        sourceSeqStart=self.active[0].seq,
                        reason="missing_exact_equipped_marker",
                    )
                self.active = None
                self.equipped_marker = False
                self.lookback = []
        else:
            self.lookback.append(line)
            self.lookback = self.lookback[-3:]
            if len(self.lookback) == 3 and is_item_anchor(
                *(x.text for x in self.lookback)
            ):
                self.active = list(self.lookback)
                self.lookback = []
                self._diag(
                    "anchor.detected",
                    line,
                    slot=self.slot,
                    item=self.active[0].text,
                    itemType=self.active[1].text,
                    itemPowerText=self.active[2].text,
                    sourceSeqStart=self.active[0].seq,
                    equippedMarker=self.equipped_marker,
                )

        self.repository.commit_event(
            session_id=session,
            event_seq=seq,
            updated_at=ts,
            observation=observation,
            empty_slot_family=empty_slot_family,
        )

        if observation is not None:
            self._diag(
                "db.upsert",
                line,
                slot=observation.slot_family,
                item=observation.item.name,
                confidence=observation.confidence,
            )
        if empty_slot_family is not None:
            self._diag(
                "db.clear",
                line,
                slot=empty_slot_family,
                reason="empty_confirmed",
            )
