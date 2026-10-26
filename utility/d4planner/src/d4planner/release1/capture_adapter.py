"""Production Equipment evidence adapters.

The adapter accepts only producer-assigned stable entity IDs. Human labels from
legacy speech capture remain display metadata and never become verified identity.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from d4planner.character.repository import EquipmentRepository

from .assessment import EquipmentSnapshot, ObservedEntity, ObservedItem, ObservedValue


SLOT_IDS = {
    "helm": "helm", "chest": "chest", "gloves": "gloves", "pants": "pants",
    "boots": "boots", "main_hand": "main-hand", "off_hand": "off-hand",
    "amulet": "amulet",
}


class EquipmentEvidenceError(ValueError):
    pass


def _value(value: Any) -> ObservedValue | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"type", "value", "unit", "evidence"}:
        raise EquipmentEvidenceError("typed value fields are invalid")
    if value["evidence"] not in {"OBSERVED", "CONFIRMED"}:
        raise EquipmentEvidenceError("typed value evidence is invalid")
    return ObservedValue(str(value["type"]), value["value"], str(value["unit"]), str(value["evidence"]))


class EquipmentCaptureAdapter:
    """Convert the versioned capture boundary into the S4 scoring snapshot."""

    SCHEMA_VERSION = "d4planner-equipment-evidence/v1"

    def from_event(self, event: dict[str, Any]) -> EquipmentSnapshot:
        required = {
            "schemaVersion", "characterId", "characterDisplayName", "currentRevision",
            "capturedAt", "captureHealth", "slots",
        }
        if not isinstance(event, dict) or set(event) != required:
            raise EquipmentEvidenceError("equipment evidence envelope is invalid")
        if event["schemaVersion"] != self.SCHEMA_VERSION:
            raise EquipmentEvidenceError("equipment evidence version mismatch")
        if not isinstance(event["currentRevision"], int) or isinstance(event["currentRevision"], bool) or event["currentRevision"] < 1:
            raise EquipmentEvidenceError("currentRevision must be positive")
        items: list[ObservedItem] = []
        evidence: dict[str, frozenset[str]] = {}
        seen_slots: set[str] = set()
        for slot in event["slots"]:
            if not isinstance(slot, dict) or set(slot) != {"slotId", "presence", "evidence", "item"}:
                raise EquipmentEvidenceError("slot evidence is invalid")
            slot_id = str(slot["slotId"])
            if not slot_id or slot_id in seen_slots:
                raise EquipmentEvidenceError("slotId is empty or duplicated")
            seen_slots.add(slot_id)
            tokens = slot["evidence"]
            if not isinstance(tokens, list) or any(token not in {"PRESENT_VALUE", "COMPLETE_CATEGORY", "COMPLETE_SLOT"} for token in tokens):
                raise EquipmentEvidenceError("slot completeness evidence is invalid")
            evidence[slot_id] = frozenset(tokens)
            item = slot["item"]
            if slot["presence"] == "UNKNOWN":
                if item is not None:
                    raise EquipmentEvidenceError("unknown slot cannot carry an item")
                continue
            if slot["presence"] == "CONFIRMED_ABSENT":
                if item is not None or "COMPLETE_SLOT" not in tokens:
                    raise EquipmentEvidenceError("confirmed absence requires COMPLETE_SLOT")
                continue
            if slot["presence"] != "OBSERVED" or not isinstance(item, dict):
                raise EquipmentEvidenceError("observed slot requires an item")
            entities: list[ObservedEntity] = []
            for entity in item.get("entities", []):
                required_entity = {"kind", "group", "entityId", "occurrence", "label", "values"}
                if not isinstance(entity, dict) or set(entity) != required_entity:
                    raise EquipmentEvidenceError("entity binding is invalid")
                entity_id = entity["entityId"]
                if not isinstance(entity_id, str) or not entity_id:
                    raise EquipmentEvidenceError("producer stable entityId is required")
                entities.append(ObservedEntity(
                    str(entity["kind"]), str(entity["group"]), entity_id,
                    int(entity["occurrence"]), str(entity["label"]),
                    tuple(_value(value) for value in entity["values"]),
                ))
            items.append(ObservedItem(
                slot_id, str(item["itemId"]), str(item["displayName"]),
                str(item["observedAt"]), str(item.get("source", "CAPTURE")), tuple(entities),
            ))
        return EquipmentSnapshot(
            str(event["characterId"]), str(event["characterDisplayName"]),
            int(event["currentRevision"]), str(event["capturedAt"]), tuple(items),
            evidence, str(event["captureHealth"]),
        )


class RepositoryEquipmentCaptureAdapter:
    """Read the durable current-equipment projection without inventing IDs."""

    def __init__(self, repository: EquipmentRepository):
        self.repository = repository

    def snapshot(self, *, character_id: str, character_display_name: str, current_revision: int) -> EquipmentSnapshot:
        rows = self.repository.list_equipment()
        ring_index = 0
        items: list[ObservedItem] = []
        evidence: dict[str, frozenset[str]] = {}
        latest = datetime.now(timezone.utc).isoformat()
        for row in rows:
            family = row["slotFamily"]
            if family == "ring":
                ring_index += 1
                slot_id = f"ring-{ring_index}"
            else:
                slot_id = SLOT_IDS.get(family)
            if slot_id is None:
                continue
            latest = max(latest, str(row["observedAt"]))
            entities: list[ObservedEntity] = []
            # Only new capture producers that persist explicit stable IDs enter
            # scoring. Legacy human-readable affix/effect strings remain UNKNOWN.
            for group, kind in (("affixes", "AFFIX"), ("effectsRaw", "EFFECT")):
                for raw in row.get(group, []):
                    if not isinstance(raw, dict) or not raw.get("entityId"):
                        continue
                    entities.append(ObservedEntity(
                        kind, "AFFIXES" if kind == "AFFIX" else "ASPECTS",
                        str(raw["entityId"]), int(raw.get("occurrence", 0)),
                        str(raw.get("label", raw["entityId"])),
                        tuple(_value(value) for value in raw.get("values", [])),
                    ))
            items.append(ObservedItem(
                slot_id, str(row["itemFingerprint"]), str(row["name"]),
                str(row["observedAt"]), "CAPTURE_REPOSITORY", tuple(entities),
            ))
            evidence[slot_id] = frozenset({"PRESENT_VALUE"})
        return EquipmentSnapshot(
            character_id, character_display_name, current_revision, latest,
            tuple(items), evidence, "HEALTHY",
        )

