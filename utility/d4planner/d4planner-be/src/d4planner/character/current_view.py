"""Display-only equipment projection. Never infer scoring IDs or character ownership."""
from typing import Any


def display_lines(values: list[Any]) -> list[str]:
    result = []
    for value in values:
        if isinstance(value, str):
            result.append(value)
        elif isinstance(value, dict):
            # Capture parsers retain text; typed entities may have a label instead.
            text = value.get('text') or value.get('raw') or value.get('label')
            if isinstance(text, str):
                result.append(text)
    return result


def current_view(rows, revision):
    return {'sourceState': 'READY', 'identity': 'UNVERIFIED', 'revision': revision,
        'items': [{
            'fingerprint': row['itemFingerprint'], 'slotFamily': row['slotFamily'],
            'slotIndex': row['slotIndex'], 'name': row['name'], 'itemType': row['itemType'],
            'itemPower': row['itemPower'], 'rarity': row['rarity'],
            'baseStats': display_lines(row['baseStats']), 'affixes': display_lines(row['affixes']),
            'effects': display_lines(row['effectsRaw']), 'observedAt': row['observedAt'],
            'confidence': row['confidence'],
        } for row in rows]}
