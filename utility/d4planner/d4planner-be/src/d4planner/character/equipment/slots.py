from __future__ import annotations


SLOTS = {
    "Two-Handed": "unresolved_two_handed",
    "Head": "helm",
    "Torso": "chest",
    "Hands": "gloves",
    "Legs": "pants",
    "Feet": "boots",
    "Ranged": "ranged",
    "Main Hand": "main_hand",
    "Off-Hand": "off_hand",
    "Ring": "ring",
    "Neck": "amulet",
}

# Ring is deliberately excluded because two physical ring positions currently
# share slot_family=ring and slot_index=None.
SINGLE_INSTANCE_SLOTS = frozenset(SLOTS.values()) - {"ring", "unresolved_two_handed"}

# Type/physical-slot validation is capture semantics, not a provider ID mapping.
# Reject unsupported families instead of carrying a previous armour slot forward.
SLOT_TYPES = {
    'helm': {'Helm'}, 'chest': {'Chest Armor'}, 'gloves': {'Gloves'},
    'pants': {'Pants'}, 'boots': {'Boots'}, 'ring': {'Ring'}, 'amulet': {'Amulet'},
    'main_hand': {'Sword', 'Wand', 'Staff', 'Dagger'},
    'off_hand': {'Sword', 'Focus', 'Dagger'}, 'ranged': {'Bow', 'Crossbow'},
}
