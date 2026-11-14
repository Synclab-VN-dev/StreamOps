"""Resolve new weapon contexts only from the Rule Kit's verified class layouts.

This is slot evidence, not character identity. All compatible classes must agree;
we never infer a character class from a unique item's name or the selected Target.
"""
from .parser import parse_type


def resolve_two_handed(layouts, segment) -> tuple[str, ...]:
    if not isinstance(layouts, dict) or layouts.get('status') != 'READY' or layouts.get('schemaVersion') != 'd4planner-equipment-layout/v1':
        return ()
    classes = layouts.get('classes')
    if not isinstance(classes, list) or not classes or len(segment) < 3:
        return ()
    parsed = parse_type(segment[1].text)
    if not parsed:
        return ()
    # Other weapon families need their own recorded regression, not guessed labels.
    if parsed[2] != 'Staff':
        return ()
    matches = []
    for entry in classes:
        if not isinstance(entry, dict) or not isinstance(entry.get('slots'), list):
            return ()
        slots = entry['slots']
        if any(not isinstance(s, dict) or not isinstance(s.get('itemTypes'), list) for s in slots):
            return ()
        accepted = [s for s in slots if parsed[2] in s['itemTypes']]
        if not accepted:
            continue
        # Provider slot identities are translated only by the Rule Kit adapter.
        if len(accepted) != 1 or accepted[0].get('slotFamily') != 'main_hand':
            return ()
        weapons = [s for s in slots if s.get('slotFamily') in {'main_hand','off_hand'}]
        if sorted(s['slotFamily'] for s in weapons) != ['main_hand','off_hand'] or any(s.get('slotFamily') == 'unsupported_weapon' for s in slots):
            return ()
        matches.append(('main_hand','off_hand'))
    return matches[0] if matches and all(m == matches[0] for m in matches) else ()
