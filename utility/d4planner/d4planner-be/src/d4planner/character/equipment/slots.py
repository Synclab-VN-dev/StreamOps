from __future__ import annotations


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

# Ring is deliberately excluded because two physical ring positions currently
# share slot_family=ring and slot_index=None.
SINGLE_INSTANCE_SLOTS = frozenset(SLOTS.values()) - {"ring"}
