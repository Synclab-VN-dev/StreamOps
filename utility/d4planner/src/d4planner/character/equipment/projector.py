from __future__ import annotations

from typing import Any, Protocol

from ..repository import EquipmentRepository
from .context import EquipmentContext, EquipmentLine
from .decision import Resolution, ResolutionKind
from .parser import is_item_anchor, normalize
from .resolvers import (
    ResolverRequest,
    empty_slot_resolver_pipeline,
    item_resolver_pipeline,
    ring_resolver_pipeline,
)
from .slots import SINGLE_INSTANCE_SLOTS, SLOTS


class _Diagnostics(Protocol):
    def emit(self, event: str, **fields: Any) -> bool: ...


class EquipmentProjector:
    """Orchestrate stream context -> resolver decisions -> repository commit.

    Item classification and empty-slot semantics live in dedicated resolvers.
    The projector owns mutable stream state, diagnostics, and DB side effects.
    """

    def __init__(
        self,
        repository: EquipmentRepository,
        diagnostics: _Diagnostics | None = None,
    ):
        self.repository = repository
        self.diagnostics = diagnostics
        self.context = EquipmentContext()
        self.item_resolvers = item_resolver_pipeline()
        self.empty_slot_resolvers = empty_slot_resolver_pipeline()
        self.ring_resolvers = ring_resolver_pipeline()

    def set_diagnostics(self, diagnostics: _Diagnostics | None) -> None:
        self.diagnostics = diagnostics

    def _diag(
        self,
        event: str,
        line: EquipmentLine | None = None,
        **fields: Any,
    ) -> None:
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
            EquipmentLine(
                normalize(str((event.get("data") or {}).get("text") or "")),
                int(event.get("eventSeq") or 0),
                str(event.get("timestamp") or ""),
                str(event.get("sessionId") or ""),
            ),
            errorType=type(exc).__name__,
            error=str(exc),
        )

    def _resolve_pending_ring(
        self,
        line: EquipmentLine,
        incoming_slot: str | None,
    ) -> Resolution | None:
        if self.context.ring_pending_fingerprint is None:
            return None

        decision = self.ring_resolvers.resolve(
            ResolverRequest(
                context=self.context,
                line=line,
                incoming_slot=incoming_slot,
            )
        )
        if decision is None:
            self.context.clear_ring_pending()
            return None

        if decision.open_ring_probe:
            self.context.open_ring_probe()
            self._diag(
                "ring.probe",
                line,
                resolver=decision.resolver,
                result=decision.kind.value,
                slot="ring",
                item=decision.item_name,
                reason=decision.reason,
            )
        elif decision.kind == ResolutionKind.DELETE_ITEM:
            self.context.clear_ring_pending()
            self._diag(
                "ring.confirmed_empty",
                line,
                resolver=decision.resolver,
                result=decision.kind.value,
                slot="ring",
                item=decision.item_name,
                reason=decision.reason,
            )
        else:
            self.context.clear_ring_pending()
            self._diag(
                "ring.cancelled",
                line,
                resolver=decision.resolver,
                result=decision.kind.value,
                slot="ring",
                item=decision.item_name,
                reason=decision.reason,
                nextText=line.text,
            )
        return decision

    def _resolve_pending_empty(
        self,
        line: EquipmentLine,
        incoming_slot: str | None,
    ) -> Resolution | None:
        if self.context.pending_empty_slot is None:
            return None

        decision = self.empty_slot_resolvers.resolve(
            ResolverRequest(
                context=self.context,
                line=line,
                incoming_slot=incoming_slot,
            )
        )
        if decision is None:
            self.context.clear_empty_pending()
            return None

        if decision.keep_empty_pending:
            self.context.keep_empty_pending()
            self._diag(
                "empty.pending_keep",
                line,
                resolver=decision.resolver,
                result=decision.kind.value,
                slot=decision.slot,
                reason=decision.reason,
                interstitialCount=self.context.pending_empty_interstitial_count,
                nextText=line.text,
            )
        elif decision.kind == ResolutionKind.CLEAR_SLOT:
            self.context.clear_empty_pending()
            self._diag(
                "empty.confirmed",
                line,
                resolver=decision.resolver,
                result=decision.kind.value,
                slot=decision.slot,
                reason=decision.reason,
            )
        else:
            self.context.clear_empty_pending()
            extra = {}
            if incoming_slot is None:
                extra["nextText"] = line.text
            self._diag(
                "empty.cancelled",
                line,
                resolver=decision.resolver,
                result=decision.kind.value,
                slot=decision.slot,
                reason=decision.reason,
                **extra,
            )
        return decision

    def _trace_item_resolution(
        self,
        decision: Resolution,
        line: EquipmentLine,
    ) -> None:
        if decision.parsed_item is not None:
            self._diag(
                "parse.success",
                line,
                resolver=decision.resolver,
                slot=decision.slot,
                item=decision.parsed_item.name,
                itemType=decision.parsed_item.item_type,
                itemPower=decision.parsed_item.item_power,
                action=decision.action,
                sourceSeqStart=decision.source_seq_start,
            )
        elif decision.parse_error:
            self._diag(
                "parse.failed",
                line,
                resolver=decision.resolver,
                slot=decision.slot,
                item=decision.item_name,
                action=decision.action,
                sourceSeqStart=decision.source_seq_start,
                errorType=decision.parse_error_type,
                error=decision.parse_error,
            )

        common = {
            "resolver": decision.resolver,
            "result": decision.kind.value,
            "slot": decision.slot,
            "item": decision.item_name,
            "action": decision.action,
            "sourceSeqStart": decision.source_seq_start,
            "reason": decision.reason,
        }
        if decision.resolver == "equipped":
            self._diag("observation.high", line, **common)
        elif decision.resolver == "candidate":
            self._diag("observation.not_equipped", line, **common)
        elif decision.resolver == "ambiguous":
            self._diag("observation.ambiguous", line, **common)

        if decision.start_empty_pending and decision.slot:
            if decision.slot == "ring" and decision.observation is not None:
                self.context.start_ring_pending(
                    decision.observation.fingerprint,
                    decision.observation.item.name,
                )
                self._diag(
                    "ring.pending",
                    line,
                    resolver="ring",
                    slot="ring",
                    item=decision.observation.item.name,
                    reason="high_observation_terminal_unequip",
                )
            elif decision.slot in SINGLE_INSTANCE_SLOTS:
                self.context.start_empty_pending(decision.slot)
                self._diag(
                    "empty.pending",
                    line,
                    resolver="empty_slot",
                    slot=decision.slot,
                    reason="high_observation_terminal_unequip",
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
        line = EquipmentLine(text, seq, ts, session)
        observation = None
        empty_slot_family = None
        remove_item_fingerprint = None
        incoming_slot = SLOTS.get(text)

        if incoming_slot is not None:
            self._diag(
                "slot.enter",
                line,
                slot=incoming_slot,
                previousSlot=self.context.slot,
            )

        ring_decision = self._resolve_pending_ring(line, incoming_slot)
        if ring_decision and ring_decision.kind == ResolutionKind.DELETE_ITEM:
            remove_item_fingerprint = ring_decision.delete_fingerprint

        empty_decision = self._resolve_pending_empty(line, incoming_slot)
        if empty_decision and empty_decision.kind == ResolutionKind.CLEAR_SLOT:
            empty_slot_family = empty_decision.slot

        if incoming_slot is not None:
            self.context.reset_for_slot(incoming_slot)
        elif text == "EQUIPPED":
            self.context.equipped_marker = True

        if self.context.active is not None:
            self.context.active.append(line)
            if text in {"Equip", "Unequip"}:
                segment = list(self.context.active)
                request = ResolverRequest(
                    context=self.context,
                    line=line,
                    segment=segment,
                    action=text,
                )
                try:
                    decision = self.item_resolvers.resolve(request)
                except Exception as exc:
                    self._diag(
                        "parse.failed",
                        line,
                        resolver="equipped",
                        slot=self.context.slot,
                        item=segment[0].text if segment else None,
                        action=text,
                        sourceSeqStart=segment[0].seq if segment else None,
                        errorType=type(exc).__name__,
                        error=str(exc),
                    )
                    raise

                if decision is not None:
                    self._trace_item_resolution(decision, line)
                    observation = decision.observation

                self.context.reset_segment()
        else:
            self.context.lookback.append(line)
            self.context.lookback = self.context.lookback[-3:]
            if len(self.context.lookback) == 3 and is_item_anchor(
                *(entry.text for entry in self.context.lookback)
            ):
                self.context.active = list(self.context.lookback)
                self.context.lookback = []
                self._diag(
                    "anchor.detected",
                    line,
                    slot=self.context.slot,
                    item=self.context.active[0].text,
                    itemType=self.context.active[1].text,
                    itemPowerText=self.context.active[2].text,
                    sourceSeqStart=self.context.active[0].seq,
                    equippedMarker=self.context.equipped_marker,
                )

        self.repository.commit_event(
            session_id=session,
            event_seq=seq,
            updated_at=ts,
            observation=observation,
            empty_slot_family=empty_slot_family,
            remove_item_fingerprint=remove_item_fingerprint,
        )

        if observation is not None:
            self._diag(
                "db.upsert",
                line,
                resolver="repository",
                result="UPSERT",
                slot=observation.slot_family,
                item=observation.item.name,
                confidence=observation.confidence,
            )
        if empty_slot_family is not None:
            self._diag(
                "db.clear",
                line,
                resolver="repository",
                result="CLEAR_SLOT",
                slot=empty_slot_family,
                reason="empty_confirmed",
            )
        if remove_item_fingerprint is not None:
            self._diag(
                "db.delete_item",
                line,
                resolver="repository",
                result="DELETE_ITEM",
                slot="ring",
                fingerprint=remove_item_fingerprint,
                reason="bare_ring_slot_confirmed",
            )
